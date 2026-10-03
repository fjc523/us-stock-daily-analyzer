from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import tradingagents.dataflows.date_window as date_window
import tradingagents.graph.trading_graph as trading_graph_module
import tradingagents.llm_clients.codex_exec.runner as codex_runner_module
import tradingagents.agents.tools as tools_module
import pytest

from daily_analyzer.analyzer import AnalyzerGraph, ToolTraceCallback, build_upstream_config, write_progress
from daily_analyzer.config import WatchlistItem, parse_settings
from daily_analyzer.context import ContextBlock


EASTERN = ZoneInfo("America/New_York")
LIVE_DATE = "2026-10-02"
REPLAY_DATE = "2026-10-01"
LIVE_CONTEXT_TIME = datetime(2026, 10, 2, 8, 31, tzinfo=EASTERN)
REPLAY_CONTEXT_TIME = datetime(2026, 10, 1, 8, 31, tzinfo=EASTERN)
MEMORY_SENTINEL = "REPLAY_MEMORY_SENTINEL"
MARKET_PROMPT_MARKER = "你是市场分析师。"
PORTFOLIO_PROMPT_MARKER = "你是组合经理，综合执行风险"


def test_actual_graph_node_callback_records_stage_and_preserves_start(tmp_path):
    from langgraph.graph import StateGraph, START, END
    path = tmp_path / "progress.json"
    clock = lambda: LIVE_CONTEXT_TIME
    write_progress(path, "获取行情与新闻", clock, started_at=LIVE_CONTEXT_TIME.isoformat())
    observed = []
    graph = StateGraph(dict)
    def capture(state):
        observed.append(json.loads(path.read_text())["stage"])
        return state
    graph.add_node("News Analyst", capture)
    graph.add_node("Trader", capture)
    graph.add_edge(START, "News Analyst")
    graph.add_edge("News Analyst", "Trader")
    graph.add_edge("Trader", END)
    graph.compile().invoke({"symbol": "NVDA"}, config={"callbacks": [ToolTraceCallback(clock, progress_path=path)]})
    assert observed == ["分析师报告", "交易员方案"]
    assert json.loads(path.read_text())["started_at"] == LIVE_CONTEXT_TIME.isoformat()


class FixtureClock:
    def __init__(self, initial: datetime) -> None:
        self.value = initial
        self._lock = threading.Lock()

    def __call__(self) -> datetime:
        with self._lock:
            current = self.value
            self.value += timedelta(seconds=1)
            return current


def _project_settings():
    return parse_settings(
        {
            "llm": {
                "provider": "codex_exec",
                "deep": {"model": "gpt-6.1-sol", "reasoning_effort": "xhigh"},
                "quick": {"model": "gpt-6-luna", "reasoning_effort": "medium"},
                "call_timeout_seconds": 1,
                "max_retries": 1,
                "max_concurrent_calls": 4,
            },
            "codex": {"binary": "unused-codex"},
            "tradingagents": {
                "output_language": "Chinese",
                "late_news_refresh": False,
                "max_debate_rounds": 1,
                "max_risk_discuss_rounds": 1,
            },
        }
    )


def _memory_seed() -> bytes:
    return (
        "[2026-09-25 | MSFT | Buy | +1.0% | +0.5% | 5d | resolved:2026-09-30]\n\n"
        "DECISION:\n**Rating**: Buy\n\n"
        f"REFLECTION:\n{MEMORY_SENTINEL}\n\n"
        "<!-- ENTRY_END -->\n\n"
    ).encode("utf-8")


def _home_tradingagents_metadata() -> dict[str, tuple[int, int, int]] | None:
    root = Path.home() / ".tradingagents"
    if not root.exists():
        return None
    entries = [root, *root.rglob("*")]
    return {
        str(path.relative_to(root.parent)): (
            path.lstat().st_mtime_ns,
            path.lstat().st_size,
            path.lstat().st_mode,
        )
        for path in entries
    }


def _context(ticker: str, as_of: datetime) -> dict[str, ContextBlock]:
    return {
        "market_regime": ContextBlock(
            title="离线标的上下文",
            markdown=f"CONTEXT_{ticker}_UNIQUE\n盘前 148.20；夜盘 148.10；新闻发布时间 08:31 ET；固定测试数据，不是实盘报价。",
            data={"symbol": ticker},
            as_of=as_of,
            sources=("固定测试样例",),
        )
    }


def _new_graph(
    ticker: str,
    mode: str,
    settings,
    root: Path,
    batch_dir: Path,
    *,
    trade_date: str,
    price_data_end_date: str,
    context_as_of: datetime,
    clock: FixtureClock,
) -> AnalyzerGraph:
    news_cutoff = (
        datetime(2026, 10, 1, 12, 31, tzinfo=ZoneInfo("UTC"))
        if mode == "backfill"
        else None
    )
    config = build_upstream_config(
        settings,
        trade_date=trade_date,
        price_data_end_date=price_data_end_date,
        mode=mode,
        news_cutoff_utc=news_cutoff,
        batch_dir=batch_dir,
        project_root=root,
        has_alpha_vantage=False,
    )
    item = WatchlistItem(symbol=ticker, type="stock", analysts=["market", "news"])
    return AnalyzerGraph(
        item=item,
        mode=mode,
        config=config,
        state_log_dir=root / "state_logs" / mode / ticker,
        context_blocks=_context(ticker, context_as_of),
        context_as_of=context_as_of,
        clock=clock,
    )


def _message_text(prompt: str) -> str:
    payload = json.loads(prompt)
    return "\n".join(
        str(message.get("content", "")) for message in payload.get("messages", [])
    )


def test_real_analyzer_graph_runs_offline_in_parallel_and_backfill_preserves_memory(
    monkeypatch, tmp_path: Path
) -> None:
    fixed_today = lambda: LIVE_DATE
    from daily_analyzer.data_sources.futu import FutuDataSource
    monkeypatch.setattr(FutuDataSource, "identity", lambda *args: {})
    from tradingagents.dataflows.errors import VendorUnavailableError
    def no_futu_daily(*args, **kwargs):
        raise VendorUnavailableError("离线测试不连接OpenD")
    monkeypatch.setattr(FutuDataSource, "daily_bars", no_futu_daily)
    monkeypatch.setattr(FutuDataSource, "_call", no_futu_daily)
    monkeypatch.setattr(date_window, "get_current_date", fixed_today)
    monkeypatch.setattr(trading_graph_module, "get_current_date", fixed_today)
    monkeypatch.setattr(
        trading_graph_module,
        "resolve_instrument_identity",
        lambda ticker: {"company_name": f"测试企业 {ticker}"},
    )

    data_calls = []
    calls_lock = threading.Lock()

    def fake_route_to_vendor(name, *args, **kwargs):
        with calls_lock:
            data_calls.append((name, *args, kwargs))
        if name == "get_news":
            return f"固定新闻样例：{args[0]}"
        raise AssertionError(f"未打桩的数据工具被调用：{name}")

    monkeypatch.setattr(tools_module, "route_to_vendor", fake_route_to_vendor)

    llm_calls = []
    llm_calls_lock = threading.Lock()

    def fake_codex_run(runner, prompt: str, schema: dict):
        payload = json.loads(prompt)
        messages = payload.get("messages", [])
        properties = schema.get("properties", {})
        tool_specs = payload.get("tools", [])
        news_tool_available = any(
            tool.get("function", {}).get("name") == "get_news"
            for tool in tool_specs
        )
        news_tool_returned = any(
            message.get("role") == "tool" and message.get("name") == "get_news"
            for message in messages
        )
        with llm_calls_lock:
            llm_calls.append(
                {
                    "model": runner.model,
                    "effort": runner.reasoning_effort,
                    "role": getattr(runner, "role", None),
                    "prompt": prompt,
                    "text": _message_text(prompt),
                    "stage": "研究经理" if "recommendation" in properties else "交易员" if "action" in properties else "组合经理" if "rating" in properties else "分析师/辩论",
                }
            )

        if "kind" in properties:
            if news_tool_available and not news_tool_returned:
                output = {
                    "kind": "tool_calls",
                    "content": "",
                    "tool_calls": [
                        {
                            "name": "get_news",
                            "arguments_json": json.dumps(
                                {"start_date": "2026-09-25", "end_date": "2026-10-02"}
                            ),
                        }
                    ],
                }
            else:
                output = {
                    "kind": "final",
                    "content": "离线分析报告：只使用固定测试样例。",
                    "tool_calls": [],
                }
        elif "recommendation" in properties:
            output = {
                "recommendation": "Hold",
                "rationale": "固定样例证据有限。",
                "strategic_actions": "继续观察。",
            }
        elif "action" in properties:
            output = {
                "action": "Hold",
                "direction_change": "否",
                "reasoning": "按固定样例保持观察。",
                "entry_price": None,
                "stop_loss": None,
                "position_sizing": None,
                "reference_price": "148.20 USD，2026-10-02 08:31 ET，固定测试样例",
                "entry_plan": "148.0–148.2；仅固定测试条件；跌破148失效；依据测试盘前价",
                "add_plan": "不适用；等待仓位与信号确认",
            }
        elif "rating" in properties:
            output = {
                "rating": "Hold",
                "direction_change": "否",
                "executive_summary": "固定离线样例建议保持观察。",
                "investment_thesis": "本次输出仅用于验证图集成。",
                "price_target": None,
                "time_horizon": None,
                "reference_price": "148.20 USD，2026-10-02 08:31 ET，固定测试样例",
                "entry_plan": "暂不建仓；等待固定样例证据补齐",
                "add_plan": "暂不加仓；等待固定样例证据补齐",
            }
        elif "content" in properties:
            output = {"content": "离线辩论样例。"}
        else:
            raise AssertionError(f"测试未覆盖的模型输出 Schema：{schema}")
        return SimpleNamespace(output=output, events={})

    monkeypatch.setattr(codex_runner_module.CodexExecRunner, "run", fake_codex_run)

    settings = _project_settings()
    project_root = tmp_path / "project"
    batch_dir = tmp_path / "runs" / "live-batch"
    memory_path = project_root / "data" / "tradingagents" / "memory" / "trading_memory.md"
    memory_path.parent.mkdir(parents=True)
    seed = _memory_seed()
    memory_path.write_bytes(seed)
    home_before = _home_tradingagents_metadata()

    live_clock = FixtureClock(LIVE_CONTEXT_TIME)
    graphs = {
        ticker: _new_graph(
            ticker,
            "live",
            settings,
            project_root,
            batch_dir,
            trade_date=LIVE_DATE,
            price_data_end_date="2026-10-01",
            context_as_of=LIVE_CONTEXT_TIME,
            clock=live_clock,
        )
        for ticker in ("NVDA", "AAPL")
    }

    assert graphs["NVDA"].deep_thinking_llm.model_name == "gpt-6.1-sol"
    assert graphs["NVDA"].deep_thinking_llm.reasoning_effort == "xhigh"
    assert graphs["NVDA"].quick_thinking_llm.model_name == "gpt-6-luna"
    assert graphs["NVDA"].quick_thinking_llm.reasoning_effort == "medium"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(graph.propagate, graph.analysis_symbol, LIVE_DATE, "stock"): ticker
            for ticker, graph in graphs.items()
        }
        results = {futures[future]: future.result() for future in futures}

    live_memory = memory_path.read_bytes()
    live_entries = [
        line for line in live_memory.decode("utf-8").splitlines()
        if line.startswith(f"[{LIVE_DATE} | ")
    ]
    assert len(live_entries) == 2
    assert {line.split("|")[1].strip() for line in live_entries} == {"NVDA", "AAPL"}
    assert live_memory.startswith(seed)

    for ticker, graph in graphs.items():
        state, rating = results[ticker]
        assert rating == "Hold"
        assert state["company_of_interest"] == ticker
        assert state["market_report"] == "离线分析报告：只使用固定测试样例。"
        queries = graph.tool_trace.snapshot()
        news_queries = [query for query in queries if query["name"] == "get_news"]
        assert len(news_queries) == 1
        assert news_queries[0]["started_at"] <= news_queries[0]["finished_at"]

    assert {call[0] for call in data_calls} == {"get_news"}
    assert {call[1] for call in data_calls} == {"NVDA", "AAPL"}

    live_prompts = [call for call in llm_calls if MARKET_PROMPT_MARKER in call["text"]]
    news_prompts = [call for call in llm_calls if '"name": "get_news"' in call["prompt"]]
    pm_prompts = [call for call in llm_calls if PORTFOLIO_PROMPT_MARKER in call["text"]]
    for ticker, other in (("NVDA", "AAPL"), ("AAPL", "NVDA")):
        marker = f"CONTEXT_{ticker}_UNIQUE"
        market_prompt = next(call for call in live_prompts if marker in call["text"])
        news_prompt = next(call for call in news_prompts if marker in call["text"])
        portfolio_prompt = next(call for call in pm_prompts if marker in call["text"])
        assert f"CONTEXT_{other}_UNIQUE" not in market_prompt["text"]
        assert f"CONTEXT_{other}_UNIQUE" not in news_prompt["text"]
        assert f"CONTEXT_{other}_UNIQUE" not in portfolio_prompt["text"]
        assert market_prompt["model"] == "gpt-6-luna"
        assert market_prompt["effort"] == "medium"
        assert portfolio_prompt["model"] == "gpt-6.1-sol"
        assert portfolio_prompt["effort"] == "xhigh"
        ticker_calls = [call for call in llm_calls if marker in call["text"]]
        assert {call["stage"] for call in ticker_calls} >= {"研究经理", "交易员", "组合经理", "分析师/辩论"}
        for call in ticker_calls:
            assert all(text in call["text"] for text in ("盘前 148.20", "夜盘 148.10", "新闻发布时间"))
            if call["stage"] in {"研究经理", "交易员", "组合经理"}:
                assert (call["role"], call["model"], call["effort"]) == ("deep", "gpt-6.1-sol", "xhigh")
        assert "建仓点位" in results[ticker][0]["final_trade_decision"]
        assert "加仓点位" in results[ticker][0]["final_trade_decision"]
        assert "148.20 USD" in results[ticker][0]["final_trade_decision"]

    memory_before_replay = memory_path.read_bytes()
    replay_graph = _new_graph(
        "NVDA",
        "backfill",
        settings,
        project_root,
        tmp_path / "runs" / "replay-batch",
        trade_date=REPLAY_DATE,
        price_data_end_date="2026-09-30",
        context_as_of=REPLAY_CONTEXT_TIME,
        clock=FixtureClock(REPLAY_CONTEXT_TIME),
    )
    replay_state, replay_rating = replay_graph.propagate(
        replay_graph.analysis_symbol, REPLAY_DATE, "stock"
    )

    assert replay_rating == "Hold"
    assert replay_state["past_context"].find(MEMORY_SENTINEL) >= 0
    replay_pm_prompt = next(
        call for call in llm_calls
        if PORTFOLIO_PROMPT_MARKER in call["text"]
        and "CONTEXT_NVDA_UNIQUE" in call["text"]
        and MEMORY_SENTINEL in call["text"]
    )
    assert replay_pm_prompt["role"] == "deep"
    assert memory_path.read_bytes() == memory_before_replay
    assert _home_tradingagents_metadata() == home_before

    # 在同一离线 LLM 环境中运行完整批次，模拟查看器追加第二只股票。
    from daily_analyzer.runner import run_analysis
    from daily_analyzer.manual_analysis import AnalysisLauncher
    import daily_analyzer.runner as runner_module
    from daily_analyzer.storage import read_json
    root = tmp_path / 'append-project'
    (root / 'config').mkdir(parents=True)
    (root / 'config/settings.yaml').write_text('context_providers: []\nrun:\n  max_parallel_tickers: 2\n')
    (root / 'config/watchlist.yaml').write_text('items:\n  - symbol: NVDA\n    type: stock\n    analysts: [market, news]\n  - symbol: AAPL\n    type: stock\n    analysts: [market, news]\n')
    first, second = threading.Event(), threading.Event()
    append_clock = FixtureClock(LIVE_CONTEXT_TIME)
    news_counts = {}
    def refresh_route(name, *args, **kwargs):
        assert name == 'get_news'
        ticker = args[0]
        news_counts[ticker] = news_counts.get(ticker, 0) + 1
        published = (append_clock.value - timedelta(seconds=1)).isoformat()
        return f"### {ticker}交付消息{news_counts[ticker]} (source: fixture, created_at: {published})\n季度交付数据\nLink: https://example.test/{ticker}/{news_counts[ticker]}"
    monkeypatch.setattr(tools_module, 'route_to_vendor', refresh_route)
    class BlockingGraph(AnalyzerGraph):
        def propagate(self, *args, **kwargs):
            if self.analysis_symbol == 'NVDA':
                first.set()
                assert second.wait(5)
            else:
                second.set()
            return super().propagate(*args, **kwargs)
    macro_counts = {}
    class Manager:
        def prepare(self, batch): return {}
        def extend(self, items): pass
        def build(self, item, cutoff):
            blocks = dict(_context(item.symbol, cutoff))
            blocks['macro_releases'] = ContextBlock('macro_releases', '截至开始时刻未见当日经济数据标题。',
                {'releases': [], 'prior_revised': [], 'unparsed_economic_titles': []}, cutoff, ['fixture'])
            return blocks
        def refresh_macro_releases(self, item, as_of):
            # 每进入一个决策节点补抓一次：模拟数据源在开始后才收录的 08:30 标题
            count = macro_counts[item.symbol] = macro_counts.get(item.symbol, 0) + 1
            return [{'title': f'USA {item.symbol}宏观指标{index} 1{index}K Vs 9K Est.', 'name': f'{item.symbol}宏观指标{index}',
                     'actual': f'1{index}K', 'estimate': '9K', 'prior': None, 'created_at': '2026-10-02T12:30:12Z'}
                    for index in range(1, count + 1)]
        def close(self): pass
    main_thread = threading.get_ident()
    writes = []
    original_write = runner_module.atomic_write_json
    def write(path, payload):
        if '/current/' in str(path): writes.append(threading.get_ident())
        original_write(path, payload)
    monkeypatch.setattr(runner_module, 'atomic_write_json', write)
    monkeypatch.setattr(runner_module, '_codex_version', lambda _: 'fixture')
    def append():
        assert first.wait(5)
        AnalysisLauncher(root, clock=lambda: LIVE_CONTEXT_TIME).start('AAPL')
    thread = threading.Thread(target=append)
    thread.start()
    site_threads = []
    def build(root, **kwargs):
        from daily_analyzer.site import build_site
        site_threads.append(threading.get_ident())
        return build_site(root, **kwargs)
    outcome = run_analysis(root, tickers='NVDA', force=True, clock=append_clock,
                           context_manager_factory=lambda *args: Manager(), analyzer_factory=BlockingGraph,
                           site_builder=build)
    thread.join(5)
    assert outcome.exit_code == 0
    directory = root / 'data/runs/2026-10-02'
    assert read_json(directory / 'current/AAPL.json')['appended'] is True
    assert read_json(directory / 'current/NVDA.json')['status'] == 'success'
    assert writes == [main_thread, main_thread]
    assert site_threads and set(site_threads) == {main_thread}
    assert 'AAPL' in (root / 'site/index.html').read_text()
    for ticker in ('NVDA','AAPL'):
        result = read_json(directory / f'current/{ticker}.json')
        assert len(result['late_news']) == 2
        assert [row['stage'] for row in result['late_news']] == ['research','portfolio']
        assert len([row for row in result['data_queries'] if row['name'] == 'get_news']) == 3
        assert result['information_through'] >= result['late_news'][-1]['fetched_at']
        prompts = [row['text'] for row in llm_calls if f'CONTEXT_{ticker}_UNIQUE' in row['text']]
        trader = next(row['text'] for row in llm_calls if row['stage'] == '交易员' and f'{ticker}交付消息2' in row['text'])
        assert f'{ticker}交付消息2' in trader and f'{ticker}交付消息3' not in trader
        assert any(f'{ticker}交付消息3' in text and '上游未评估' in text for text in prompts)
        # 经济数据补抓：按标题去重，研究阶段一条、组合经理阶段新增一条
        assert [row['stage'] for row in result['late_macro']] == ['research', 'portfolio']
        assert result['late_macro_errors'] == []
        assert result['information_through'] >= result['late_macro'][-1]['fetched_at']
        assert f'{ticker}宏观指标1：实际 11K' in trader and f'{ticker}宏观指标2' not in trader
        assert any(f'{ticker}宏观指标2：实际 12K' in text and '上游未评估的经济数据' in text for text in prompts)



def test_upstream_config_carries_custom_decision_and_price_rules(tmp_path):
    settings = parse_settings({"decision": {"horizon_trading_days": [7, 15], "plan_validity_trading_days": 3},
                               "price_plan": {"min_reward_risk": 2.0}})
    config = build_upstream_config(settings, trade_date="2026-10-02", price_data_end_date="2026-10-01",
                                  mode="live", news_cutoff_utc=None, batch_dir=tmp_path / "batch",
                                  project_root=tmp_path, has_alpha_vantage=False)
    assert config["decision_horizon_trading_days"] == [7, 15]
    assert config["decision_plan_validity_trading_days"] == 3
    assert config["price_plan_min_reward_risk"] == 2.0
    assert config["price_plan_stop_atr_normal"] == (1.5, 2.0)


def test_upstream_config_carries_stocktwits_toggle_and_macro_chain(tmp_path):
    def build(settings):
        return build_upstream_config(settings, trade_date="2026-10-02", price_data_end_date="2026-10-01",
                                     mode="live", news_cutoff_utc=None, batch_dir=tmp_path / "batch",
                                     project_root=tmp_path, has_alpha_vantage=False)
    config = build(parse_settings({}))
    assert config["stocktwits_enabled"] is False
    assert config["tool_vendors"]["get_macro_indicators"] == "fred_public,futu,fred"
    assert build(parse_settings({"tradingagents": {"stocktwits_enabled": True}}))["stocktwits_enabled"] is True

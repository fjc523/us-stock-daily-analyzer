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

from daily_analyzer.analyzer import AnalyzerGraph, build_upstream_config
from daily_analyzer.config import WatchlistItem, parse_settings
from daily_analyzer.context import ContextBlock


EASTERN = ZoneInfo("America/New_York")
LIVE_DATE = "2026-10-02"
REPLAY_DATE = "2026-10-01"
LIVE_CONTEXT_TIME = datetime(2026, 10, 2, 8, 31, tzinfo=EASTERN)
REPLAY_CONTEXT_TIME = datetime(2026, 10, 1, 8, 31, tzinfo=EASTERN)
MEMORY_SENTINEL = "REPLAY_MEMORY_SENTINEL"
MARKET_PROMPT_MARKER = "You are a trading assistant tasked with analyzing financial markets."
PORTFOLIO_PROMPT_MARKER = "As the Portfolio Manager, synthesize"


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
        "fixture": ContextBlock(
            title="离线标的上下文",
            markdown=f"CONTEXT_{ticker}_UNIQUE",
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
                "reasoning": "按固定样例保持观察。",
                "entry_price": None,
                "stop_loss": None,
                "position_sizing": None,
            }
        elif "rating" in properties:
            output = {
                "rating": "Hold",
                "executive_summary": "固定离线样例建议保持观察。",
                "investment_thesis": "本次输出仅用于验证图集成。",
                "price_target": None,
                "time_horizon": None,
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

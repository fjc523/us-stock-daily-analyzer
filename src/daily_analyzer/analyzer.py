"""将项目上下文与自选标的接入 TradingAgents 图。"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from langchain_core.callbacks import BaseCallbackHandler
from tradingagents.graph.trading_graph import TradingAgentsGraph

from daily_analyzer.context import ContextBlock, render_context
from daily_analyzer.storage import atomic_write_json, read_json


_NEW_YORK = ZoneInfo("America/New_York")
_STAGES = {
    "Market Analyst": "分析师报告", "Sentiment Analyst": "分析师报告",
    "News Analyst": "分析师报告", "Fundamentals Analyst": "分析师报告",
    "Bull Researcher": "多方研究", "Bear Researcher": "空方研究",
    "Research Manager": "研究经理结论", "Trader": "交易员方案",
    "Aggressive Analyst": "风险辩论·积极", "Neutral Analyst": "风险辩论·中性",
    "Conservative Analyst": "风险辩论·保守", "Portfolio Manager": "组合经理最终决策",
}


def _timestamp(clock: Callable[[], datetime]) -> str:
    value = clock()
    if value.tzinfo is None:
        value = value.replace(tzinfo=_NEW_YORK)
    return value.isoformat(timespec="seconds")


def write_progress(path: Path, stage: str, clock, *, started_at: str | None = None) -> None:
    """仅写当前标的的可选阶段诊断，不改结果或批次汇总。"""
    previous = read_json(path, {})
    if previous.get("stage") == stage:
        return
    atomic_write_json(path, {
        "stage": stage, "updated_at": _timestamp(clock),
        "started_at": started_at or previous.get("started_at"),
    })


class ToolTraceCallback(BaseCallbackHandler):
    """按图上的工具回调记录调用起止时刻。"""

    def __init__(self, clock: Callable[[], datetime] = datetime.now, *, progress_path: Path | None = None) -> None:
        self.clock = clock
        self.progress_path = progress_path
        self._lock = threading.Lock()
        self._started: dict[str, tuple[str, str]] = {}
        self._queries: list[dict[str, Any]] = []

    def on_chain_start(self, serialized, inputs, *, metadata=None, **kwargs) -> None:
        node = (metadata or {}).get("langgraph_node")
        if self.progress_path is not None and node in _STAGES:
            with self._lock:
                write_progress(self.progress_path, _STAGES[node], self.clock)

    def on_tool_start(
        self,
        serialized: Mapping[str, Any],
        input_str: str,
        *,
        run_id: Any,
        **kwargs: Any,
    ) -> None:
        del input_str, kwargs
        name = str(serialized.get("name") or "未知工具")
        with self._lock:
            self._started[str(run_id)] = (name, _timestamp(self.clock))

    def on_tool_end(self, output: Any, *, run_id: Any, **kwargs: Any) -> None:
        del kwargs
        self._finish(str(run_id), output)

    def on_tool_error(self, error: BaseException, *, run_id: Any, **kwargs: Any) -> None:
        del error, kwargs
        self._finish(str(run_id))

    def _finish(self, key: str, output: Any = None) -> None:
        finished = _timestamp(self.clock)
        with self._lock:
            previous = self._started.pop(key, None)
            if previous is None:
                return
            name, started = previous
            row: dict[str, Any] = {
                "name": name,
                "started_at": started,
                "finished_at": finished,
            }
            text = str(output or "").casefold()
            if "结果已截断" in text or "truncated" in text:
                row["truncated"] = "news" in name.casefold() or "新闻" in name
            self._queries.append(row)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return sorted(self._queries, key=lambda row: row["started_at"])


class AnalyzerGraph(TradingAgentsGraph):
    """绑定单只标的上下文并覆盖回放记忆写入与状态日志路径。"""

    def __init__(
        self,
        *,
        item: Any,
        mode: str,
        config: dict[str, Any],
        state_log_dir: str | Path,
        context_blocks: Mapping[str, ContextBlock],
        context_as_of: datetime,
        portfolio: Any = None,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.item = item
        self.mode = mode
        self.state_log_dir = Path(state_log_dir)
        self.context_blocks = dict(context_blocks)
        self.context_as_of = context_as_of
        horizon = config.get("decision_horizon_trading_days", (5, 20))
        validity = config.get("decision_plan_validity_trading_days", 5)
        cutoff = config.get("news_cutoff_utc") or "实时工具数据以各次查询记录为准，未冻结"
        framework = (
            "## 决策框架\n"
            f"运行时点：{_timestamp(clock)}；附加上下文截至：{context_as_of.isoformat()}；信息截止：{cutoff}。\n"
            f"最新完整日线日期P：{config.get('price_data_end_date') or '未提供'}。\n"
            f"方向与目标配置周期：未来{horizon[0]}–{horizon[1]}个交易日；"
            f"点位方案有效期：分析当日起{validity}个交易日。\n"
            "单标的标准仓位=100%，是该标的计划持仓量，不是账户总资产比例或现有持仓买卖比例。"
        )
        if mode == "live":
            framework += f"\n分析请求美东自然日：{context_as_of.astimezone(_NEW_YORK).date().isoformat()}（不表示当天开市）。"
            from daily_analyzer.live_information import install_live_information_adapter
            from daily_analyzer.context.analysis_quote import recent_after_window
            install_live_information_adapter()
            # 配置会被上游deepcopy；闭包保留带锁Callable，不复制其内部锁。
            config = {**config, '_daily_live_information_clock': lambda: clock()}
            if recent_after_window(context_as_of) is not None:
                framework += "\n当前为休市/收盘后分析；最近盘后报价日期与年龄见原after上下文，不能称实时可成交价。新闻按本次实际查询取得，日线与盘后价各有独立历史截止。"
        if item.type == "index":
            framework += f"\n订阅为指数{item.symbol}，以代理ETF {item.analysis_symbol}的价格给出点位。"
        self.context_compaction = config.get('context_compaction', True)
        self.context_profiles = dict(config.get('context_profiles') or {})
        if self.context_compaction:
            from daily_analyzer.context.compaction import render_compacted_context
            self.injected_context = framework + "\n\n" + render_compacted_context(
                self.context_blocks, context_as_of, validity=validity)
            self.brief_injected_context = framework + "\n\n" + render_compacted_context(
                self.context_blocks, context_as_of, profile='brief', validity=validity)
        else:
            self.injected_context = framework + "\n\n" + render_context(self.context_blocks, context_as_of)
            self.brief_injected_context = self.injected_context
        self.tool_trace = ToolTraceCallback(clock, progress_path=self.state_log_dir.parent / "progress.json")
        self._clock = clock
        self._portfolio = portfolio
        callback_list = [self.tool_trace]
        if config.get('late_news_refresh'):
            config = {**config, '_late_news_clock': lambda: clock(),
                      '_late_news_initial_as_of': context_as_of.isoformat()}
        super().__init__(
            selected_analysts=list(item.analysts),
            config=config,
            callbacks=callback_list,
        )
        original_get_args = self.propagator.get_graph_args
        self.propagator.get_graph_args = lambda: original_get_args(callbacks=callback_list)

    def propagate(self, *args, **kwargs):
        if self.mode != "live":
            return super().propagate(*args, **kwargs)
        from daily_analyzer.live_information import live_information_scope
        # 上游构造会更新进程默认配置；独立作用域防止默认私有clock污染其他调用。
        with live_information_scope(self._clock):
            return super().propagate(*args, **kwargs)

    @property
    def analysis_symbol(self) -> str:
        return str(self.item.analysis_symbol)

    def resolve_instrument_context(
        self,
        ticker: str,
        asset_type: str = "stock",
        trade_date: str | None = None,
    ) -> str:
        from tradingagents.agents.context import build_instrument_context
        from daily_analyzer.data_sources.futu import get_shared_data_source
        identity = {"company_name": self.item.name} if self.item.name else {}
        try:
            details = get_shared_data_source().identity(ticker)
            identity = {**details, **identity}
        except Exception:
            pass
        if identity.get("company_name"):
            base = build_instrument_context(ticker, asset_type, identity, trade_date)
            from tradingagents.dataflows.date_window import is_historical
            if asset_type == "stock" and identity.get("business") and not is_historical(trade_date):
                base += "\n富途公司简介（当前资料）：" + identity["business"][:240]
        else:
            base = super().resolve_instrument_context(ticker, asset_type, trade_date)
        return f"{base}\n\n{self.injected_context}" if self.injected_context else base

    def create_run_state(
        self, company_name: str, trade_date: str, asset_type: str = "stock", portfolio=None
    ):
        self.settle_pending(company_name)
        memory_ticker = str(self.item.symbol)
        initial = self.propagator.create_initial_state(
            company_name,
            trade_date,
            asset_type=asset_type,
            past_context=self.memory_log.get_past_context(
                memory_ticker, as_of=self._memory_as_of(trade_date)
            ),
            instrument_context=self.resolve_instrument_context(
                company_name, asset_type, trade_date
            ),
            portfolio_context=portfolio.render(company_name) if portfolio is not None else "",
        )
        full = initial['instrument_context']
        brief = full.removesuffix(self.injected_context) + self.brief_injected_context
        initial.update(instrument_context_full=full, instrument_context_brief=brief,
                       context_compaction=self.context_compaction, context_profiles=self.context_profiles)
        return initial

    def settle_pending(self, company_name: str) -> None:
        if self.mode == "backfill":
            return
        super().settle_pending(str(self.item.symbol))

    def record_decision(self, company_name: str, trade_date: str, final_state: dict) -> None:
        self._log_state(trade_date, final_state)
        if self.mode == "backfill":
            return
        decision = final_state.get("final_trade_decision")
        if not decision:
            return
        from tradingagents.agents.rating import run_rating

        self.memory_log.store_decision(
            ticker=str(self.item.symbol),
            trade_date=trade_date,
            final_trade_decision=decision,
            rating=run_rating(final_state),
        )

    def _log_state(self, trade_date: str, final_state: dict) -> None:
        from tradingagents.agents.rating import run_rating

        debate = final_state["investment_debate_state"]
        risk = final_state["risk_debate_state"]
        entry = {
            "company_of_interest": final_state["company_of_interest"],
            "trade_date": final_state["trade_date"],
            "market_report": final_state["market_report"],
            "sentiment_report": final_state["sentiment_report"],
            "news_report": final_state["news_report"],
            "fundamentals_report": final_state["fundamentals_report"],
            "investment_debate_state": {
                key: debate[key]
                for key in ("bull_history", "bear_history", "history", "current_response")
            },
            "trader_investment_plan": final_state["trader_investment_plan"],
            "risk_debate_state": {
                key: risk[key]
                for key in (
                    "aggressive_history", "conservative_history", "neutral_history", "history"
                )
            },
            "investment_plan": final_state["investment_plan"],
            "final_trade_decision": final_state["final_trade_decision"],
            "final_rating": run_rating(final_state),
            "run_settings": self.run_settings(),
        }
        path = self.state_log_dir / f"full_states_log_{trade_date}.json"
        atomic_write_json(path, entry)


def build_upstream_config(
    settings: Any,
    *,
    trade_date: str,
    price_data_end_date: str,
    mode: str,
    news_cutoff_utc: datetime | None,
    batch_dir: str | Path,
    project_root: str | Path,
    has_alpha_vantage: bool,
) -> dict[str, Any]:
    """从项目设置构造批次共享的上游配置。"""
    from copy import deepcopy

    from tradingagents.default_config import DEFAULT_CONFIG

    root = Path(project_root).resolve()
    batch = Path(batch_dir).resolve()
    config = deepcopy(DEFAULT_CONFIG)
    config.update(
        {
            "llm_provider": settings.llm.provider,
            "deep_think_llm": settings.llm.deep.model,
            "quick_think_llm": settings.llm.quick.model,
            "codex_deep_reasoning_effort": settings.llm.deep.reasoning_effort,
            "codex_quick_reasoning_effort": settings.llm.quick.reasoning_effort,
            "codex_binary": settings.codex.binary or "codex",
            "codex_timeout": settings.llm.call_timeout_seconds,
            "codex_retries": settings.llm.max_retries,
            "codex_max_concurrency": settings.llm.max_concurrent_calls,
            "codex_usage_log_path": str(batch / "llm_calls.jsonl"),
            "codex_prompt_log_dir": str(batch / "prompts") if settings.llm.log_prompts else None,
            "market_timezone": "America/New_York",
            "futu_enabled": settings.futu.enabled,
            "trade_date": trade_date,
            "price_data_end_date": price_data_end_date,
            "news_cutoff_utc": news_cutoff_utc.isoformat() if news_cutoff_utc else None,
            "alpaca_requests_per_minute": settings.alpaca.requests_per_minute,
            "results_dir": str(root / "data" / "tradingagents" / "results"),
            "data_cache_dir": str(root / "data" / "tradingagents" / "cache"),
            "memory_log_path": str(root / "data" / "tradingagents" / "memory" / "trading_memory.md"),
            "output_language": settings.tradingagents.output_language,
            "max_debate_rounds": settings.tradingagents.max_debate_rounds,
            "max_risk_discuss_rounds": settings.tradingagents.max_risk_discuss_rounds,
            "stocktwits_enabled": settings.tradingagents.stocktwits_enabled,
            "late_news_refresh": settings.tradingagents.late_news_refresh,
            "context_compaction": settings.tradingagents.context_compaction,
            "context_profiles": settings.tradingagents.context_profiles,
            "checkpoint_enabled": False,
            "decision_horizon_trading_days": list(settings.decision.horizon_trading_days),
            "decision_plan_validity_trading_days": settings.decision.plan_validity_trading_days,
        }
    )
    for key, value in settings.price_plan.model_dump().items():
        config[f"price_plan_{key}"] = value
    from daily_analyzer.data_sources.futu import get_shared_data_source
    from tradingagents.dataflows.ohlcv_sources import register_ohlcv_source
    source = get_shared_data_source()
    source.host, source.port = settings.futu.host, settings.futu.port
    register_ohlcv_source("futu", source.daily_bars)
    from tradingagents.dataflows.router import register_vendor_method
    from functools import partial
    for method, impl in {"get_fundamentals": source.fundamentals, "get_insider_transactions": source.insiders,
                         "get_news": source.news, "get_macro_indicators": source.macro,
                         "get_balance_sheet": partial(source.statements, 2),
                         "get_income_statement": partial(source.statements, 1),
                         "get_cashflow": partial(source.statements, 3)}.items():
        register_vendor_method(method, "futu", impl)
    from daily_analyzer.data_sources.treasury import TREASURY_SOURCE
    register_vendor_method('get_macro_indicators', 'fred_public', TREASURY_SOURCE.macro)
    config["tool_vendors"].update({"get_fundamentals":"futu,yfinance", "get_insider_transactions":"futu,yfinance",
         "get_news":"alpaca,futu,yfinance", "get_macro_indicators":"fred_public,futu,fred",
         **{key:"sec_edgar,futu,yfinance" for key in ("get_balance_sheet", "get_income_statement", "get_cashflow")}})
    config.setdefault("data_vendors", {})["news_data"] = "alpaca,yfinance"
    config["data_vendors"]["core_stock_apis"] = (
        "alpaca,futu,yfinance,alpha_vantage" if has_alpha_vantage else "alpaca,futu,yfinance"
    )
    config["data_vendors"]["technical_indicators"] = config["data_vendors"]["core_stock_apis"]
    return config

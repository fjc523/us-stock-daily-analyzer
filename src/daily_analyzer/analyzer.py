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
        self.injected_context = render_context(self.context_blocks, context_as_of)
        self.tool_trace = ToolTraceCallback(clock, progress_path=self.state_log_dir.parent / "progress.json")
        self._clock = clock
        self._portfolio = portfolio
        callback_list = [self.tool_trace]
        super().__init__(
            selected_analysts=list(item.analysts),
            config=config,
            callbacks=callback_list,
        )
        original_get_args = self.propagator.get_graph_args
        self.propagator.get_graph_args = lambda: original_get_args(callbacks=callback_list)

    @property
    def analysis_symbol(self) -> str:
        return str(self.item.analysis_symbol)

    def resolve_instrument_context(
        self,
        ticker: str,
        asset_type: str = "stock",
        trade_date: str | None = None,
    ) -> str:
        base = super().resolve_instrument_context(ticker, asset_type, trade_date)
        return f"{base}\n\n{self.injected_context}" if self.injected_context else base

    def create_run_state(
        self, company_name: str, trade_date: str, asset_type: str = "stock", portfolio=None
    ):
        self.settle_pending(company_name)
        memory_ticker = str(self.item.symbol)
        return self.propagator.create_initial_state(
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
            "checkpoint_enabled": False,
        }
    )
    config.setdefault("data_vendors", {})["news_data"] = "alpaca,yfinance"
    config["data_vendors"]["core_stock_apis"] = (
        "yfinance,alpha_vantage" if has_alpha_vantage else "yfinance"
    )
    return config

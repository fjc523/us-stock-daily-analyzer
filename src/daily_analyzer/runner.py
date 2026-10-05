"""批次编排、结果落盘与 CLI 运行入口。"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from unittest.mock import patch
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from daily_analyzer.append_requests import append_lock, read_requests, STOP_MESSAGES
from daily_analyzer.analyzer import AnalyzerGraph, build_upstream_config, write_progress
from daily_analyzer.config import (
    ConfigurationError,
    ProjectConfig,
    Settings,
    apply_llm_overrides,
    load_project_config,
    load_watchlist,
    to_tradingagents_portfolio,
)
from daily_analyzer.context import ProviderServices, create_context_manager, serialize_blocks
from daily_analyzer.data_sources import AlpacaDataSource, FutuQuoteManager
from daily_analyzer.site import build_site, symbol_slug
from daily_analyzer.storage import (
    RunAlreadyRunningError,
    append_log,
    atomic_write_json,
    jsonable,
    read_json,
    run_lock,
)
from daily_analyzer.time_utils import (
    NEW_YORK,
    NoTradingSessionError,
    RunWindow,
    as_new_york,
    is_trading_day,
    scheduled_decision,
    select_run_window,
    session_bounds,
)


@dataclass
class RunOutcome:
    exit_code: int
    message: str
    run_id: str | None = None
    status: str | None = None


@dataclass
class AttemptOutcome:
    item: Any
    result: dict[str, Any]
    category: str | None
    succeeded: bool


def _clock_now(clock: Callable[[], datetime]) -> datetime:
    return as_new_york(clock())


def _date_text(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _wait_until_first_start(
    settings: Settings,
    window: RunWindow,
    clock: Callable[[], datetime],
    sleeper: Callable[[float], None],
) -> None:
    if window.mode != "live":
        return
    anchor_text, zone_name = settings.schedule.anchor.split(maxsplit=1)
    hour, minute = (int(part) for part in anchor_text.split(":"))
    anchor = datetime.combine(
        window.trade_date, datetime_time(hour, minute), ZoneInfo(zone_name)
    ).astimezone(NEW_YORK)
    earliest = anchor + timedelta(
        seconds=settings.run.min_start_after_anchor_seconds
    )
    delay = (earliest - _clock_now(clock)).total_seconds()
    if delay > 0:
        sleeper(delay)


def _write_status(
    root: Path,
    *,
    last_run: Mapping[str, Any] | None = None,
    last_schedule_event: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    path = root / "data" / "status.json"
    status = read_json(path, {})
    if not isinstance(status, dict):
        status = {}
    if last_run is not None:
        status["last_run"] = dict(last_run)
    if last_schedule_event is not None:
        status["last_schedule_event"] = dict(last_schedule_event)
    atomic_write_json(path, status)
    return status


def _pid_alive(pid: int | None) -> bool:
    if pid is None or pid < 1:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _mark_interrupted(root: Path, trade_day: date, now: datetime) -> list[dict[str, Any]]:
    batches_dir = root / "data" / "runs" / trade_day.isoformat() / "batches"
    interrupted = []
    if not batches_dir.is_dir():
        return interrupted
    for batch_path in sorted(batches_dir.glob("*/batch.json")):
        batch = read_json(batch_path, {})
        if not isinstance(batch, dict) or batch.get("status") != "running":
            continue
        try:
            pid = int(batch.get("pid"))
        except (TypeError, ValueError):
            pid = None
        if _pid_alive(pid):
            continue
        batch["status"] = "interrupted"
        batch["finished_at"] = now.isoformat(timespec="seconds")
        batch["last_error"] = "运行进程已退出，批次已标记为中断"
        for item in batch.get("items", {}).values():
            if item.get("status") in {"pending", "running"}:
                item.update(
                    {
                        "status": "interrupted",
                        "error": "运行进程已退出，标的未完成",
                    }
                )
        atomic_write_json(batch_path, batch)
        interrupted.append(batch)
    return interrupted


def _batch_records(root: Path, trade_day: date) -> list[dict[str, Any]]:
    directory = root / "data" / "runs" / trade_day.isoformat() / "batches"
    records = []
    if not directory.is_dir():
        return records
    for path in sorted(directory.glob("*/batch.json")):
        value = read_json(path, {})
        if isinstance(value, dict):
            records.append(value)
    return records


def _schedule_flags(root: Path, trade_day: date) -> tuple[bool, bool]:
    scheduled = [batch for batch in _batch_records(root, trade_day) if batch.get("scheduled")]
    already_completed = any(
        batch.get("status") in {"completed", "partial", "failed"} for batch in scheduled
    )
    recover_interrupted = any(batch.get("status") == "interrupted" for batch in scheduled)
    return already_completed, recover_interrupted


def _record_schedule_event(
    root: Path,
    now: datetime,
    trade_day: date,
    result: str,
    reason: str,
    *,
    site_builder: Callable[..., Mapping[str, Any]],
) -> None:
    event = {
        "at": now.isoformat(timespec="seconds"),
        "trade_date": trade_day.isoformat(),
        "result": result,
        "reason": reason,
    }
    _write_status(root, last_schedule_event=event)
    _build_site_and_log(root, now, trade_day, site_builder)
    append_log(root, trade_day, now, f"定时调度：{result}；{reason}")


def _build_site_and_log(
    root: Path,
    now: datetime,
    trade_day: date,
    site_builder: Callable[..., Mapping[str, Any]],
) -> None:
    try:
        result = site_builder(root, now=now)
        if not result.get("ok"):
            append_log(root, trade_day, now, f"站点构建失败：{result.get('error') or '未知错误'}")
    except Exception as exc:
        append_log(root, trade_day, now, f"站点构建失败：{type(exc).__name__}: {exc}")


def _filter_items(project: ProjectConfig, tickers: str | None) -> list[Any]:
    active = list(project.watchlist.active_items)
    if not tickers:
        return active
    requested = list(dict.fromkeys(value.strip().upper() for value in tickers.split(",") if value.strip()))
    if not requested:
        raise ConfigurationError("--tickers 至少需要一个标的代码")
    active_by_symbol = {item.symbol: item for item in active}
    disabled = {item.symbol for item in project.watchlist.items if not item.enabled}
    unknown = [symbol for symbol in requested if symbol not in active_by_symbol]
    if unknown:
        if any(symbol in disabled for symbol in unknown):
            raise ConfigurationError(
                f"自选标的已停用：{', '.join(symbol for symbol in unknown if symbol in disabled)}"
            )
        raise ConfigurationError(
            f"标的不在启用的自选清单中：{', '.join(unknown)}；请先加入 config/watchlist.yaml"
        )
    return [active_by_symbol[symbol] for symbol in requested]


def _priority_items(items: Sequence[Any], portfolio: Any) -> list[Any]:
    held = {str(position.ticker).strip().upper() for position in getattr(portfolio, "positions", [])}
    return sorted(
        items,
        key=lambda item: 0
        if str(item.symbol).upper() in held or str(item.analysis_symbol).upper() in held
        else 1,
    )


def _current_results(root: Path, trade_day: date) -> dict[str, dict[str, Any]]:
    directory = root / "data" / "runs" / trade_day.isoformat() / "current"
    values = {}
    if not directory.is_dir():
        return values
    for path in directory.glob("*.json"):
        value = read_json(path, {})
        if isinstance(value, dict):
            values[path.stem] = value
    return values


def _is_success(result: Mapping[str, Any] | None) -> bool:
    return bool(result and result.get("status") in {"success", "completed"})


def _exception_chain(error: BaseException):
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _error_category(error: BaseException) -> str:
    names = {type(item).__name__ for item in _exception_chain(error)}
    if "CodexQuotaError" in names:
        return "quota"
    if "CodexFatalConfigError" in names:
        return "fatal_config"
    if "CodexAbortedError" in names:
        return "aborted"
    if "TimeoutError" in names or "TimeoutExpired" in names:
        return "timeout"
    if "CodexTransientExhaustedError" in names:
        return "transient"
    return "error"


def _safe_error(error: BaseException, secrets: Sequence[str]) -> str:
    message = f"{type(error).__name__}: {error}"
    for secret in secrets:
        if secret:
            message = message.replace(secret, "[已隐藏]")
    return message[:600]


def _context_timestamp(blocks: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    return {
        name: {"as_of": block.get("as_of"), "source": block.get("sources", [])}
        for name, block in blocks.items()
    }


def _target_session(mode: str, started_at: datetime, trade_day: date) -> str:
    if mode == "backfill":
        return "回放"
    if not is_trading_day(trade_day):
        return "休市日（最近盘后）"
    opened, closed = session_bounds(trade_day)
    if started_at < opened:
        return "盘前"
    if started_at < closed:
        return "盘中"
    return "盘后"


def _usage_for_ticker(path: Path, ticker: str | None = None) -> dict[str, Any]:
    totals = {
        "calls": 0,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
    }
    if not path.is_file():
        return totals
    keys = {
        "input_tokens": ("input_tokens", "prompt_tokens"),
        "cached_input_tokens": ("cached_input_tokens", "cache_read_input_tokens"),
        "output_tokens": ("output_tokens", "completion_tokens"),
        "reasoning_output_tokens": ("reasoning_output_tokens", "reasoning_tokens"),
    }
    selected_rows = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if ticker is not None and row.get("ticker") != ticker:
                continue
            selected_rows.append(row)
            totals["calls"] += 1
            usage = row.get("tokens") if isinstance(row.get("tokens"), Mapping) else {}
            for target, names in keys.items():
                for name in names:
                    value = usage.get(name)
                    if isinstance(value, (int, float)):
                        totals[target] += int(value)
                        break
    if any(row.get('provider')=='claude_exec' for row in selected_rows):
        from daily_analyzer.model_usage import mixed_usage
        return mixed_usage(selected_rows)
    return totals


def _failed_result(
    *,
    item: Any,
    run_id: str,
    mode: str,
    trade_day: date,
    price_end: date,
    news_cutoff: datetime | None,
    status: str,
    error: str | None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    duration_seconds: float | None = None,
    blocks: Mapping[str, Mapping[str, Any]] | None = None,
    injected_context: str = "",
    portfolio_context: str | None = None,
) -> dict[str, Any]:
    blocks = blocks or {}
    return {
        "schema_version": 1,
        "run_id": run_id,
        "mode": mode,
        "symbol": item.symbol,
        "name": item.name,
        "analyzed_symbol": item.analysis_symbol,
        "type": item.type,
        "target_session": _target_session(mode, started_at, trade_day) if started_at and mode == "live" else mode,
        "upstream_trade_date": trade_day.isoformat(),
        "status": status,
        "error": error,
        "failure_category": None,
        "final_rating": None,
        "rating_cn": None,
        "final_trade_decision": None,
        "trader_investment_plan": None,
        "investment_plan": None,
        "reports": {},
        "investment_debate": None,
        "risk_debate": None,
        "injected_context": injected_context,
        "context_blocks": dict(blocks),
        "started_at": started_at.isoformat(timespec="seconds") if started_at else None,
        "context_as_of": started_at.isoformat(timespec="seconds") if started_at else None,
        "price_data_end_date": price_end.isoformat(),
        "news_cutoff_utc": news_cutoff.isoformat() if news_cutoff else None,
        "data_queries": [],
        "last_data_query_at": None,
        "information_through": (
            news_cutoff.isoformat()
            if mode == "backfill" and news_cutoff
            else None
        ),
        "finished_at": finished_at.isoformat(timespec="seconds") if finished_at else None,
        "started_after_open": False,
        "finished_after_open": False,
        "source_timestamps": _context_timestamp(blocks),
        "news_truncated": any(
            bool((block.get("data") or {}).get("truncated"))
            for name, block in blocks.items()
            if name == "macro_releases" and isinstance(block.get("data"), Mapping)
        ),
        "portfolio_context": portfolio_context,
        "llm": {},
        "duration_seconds": duration_seconds,
        "llm_usage": {
            "calls": 0,
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_output_tokens": 0,
        },
    }


def _rating_cn(rating: Any) -> str:
    values = {
        "BUY": "买入",
        "OVERWEIGHT": "增持",
        "HOLD": "持有",
        "UNDERWEIGHT": "减持",
        "SELL": "卖出",
        "REVIEW": "待复核",
    }
    return values.get(str(rating or "").upper(), "待复核")


def _default_context_manager(settings: Settings, root: Path, mode: str, clock):
    futu = FutuQuoteManager(
        host=settings.futu.host,
        port=settings.futu.port,
        max_subscriptions=settings.futu.max_subscriptions,
    )
    services = ProviderServices(
        alpaca=AlpacaDataSource(),
        futu=futu,
        futu_enabled=settings.futu.enabled and mode == "live",
        analysis_mode=mode,
        project_root=str(root),
        clock=clock,
    )
    names = list(settings.context_providers)
    if settings.tradingagents.position_structure_enabled and "position_structure" not in names:
        names.append("position_structure")
    if not settings.tradingagents.position_structure_enabled:
        names = [name for name in names if name != "position_structure"]
    return create_context_manager(names, services=services)


def _analyze_item(
    *,
    item: Any,
    run_id: str,
    root: Path,
    batch_dir: Path,
    window: RunWindow,
    shared_config: dict[str, Any],
    context_manager: Any,
    context_build_lock: threading.Lock,
    portfolio: Any,
    clock: Callable[[], datetime],
    monotonic: Callable[[], float],
    secrets: Sequence[str],
    analyzer_factory: Callable[..., Any],
    source_seed: Sequence[Mapping[str, Any]] = (),
    appended: bool = False,
) -> AttemptOutcome:
    from daily_analyzer.source_status import SourceStatusCollector
    from tradingagents.dataflows.vendor_observer import set_vendor_observer, reset_vendor_observer
    source_collector = SourceStatusCollector(secrets, source_seed)
    source_token = set_vendor_observer(source_collector.observe)
    started_at: datetime | None = None
    ticker_blocks: dict[str, Mapping[str, Any]] = {}
    injected = ""
    graph = None
    timer: float | None = None
    progress_path = batch_dir / "results" / symbol_slug(item.symbol) / "progress.json"
    try:
        write_progress(progress_path, "等待数据准备", clock)
        with context_build_lock:
            started_at = _clock_now(clock)
            timer = monotonic()
            write_progress(progress_path, "获取行情与新闻", clock, started_at=started_at.isoformat())
            cutoff = window.news_cutoff_utc or started_at
            typed_blocks = context_manager.build(item, cutoff)
            ticker_blocks = serialize_blocks(typed_blocks)
            from daily_analyzer.context import render_context

            injected = render_context(typed_blocks, cutoff)
        write_progress(progress_path, "准备分析与决策记忆", clock)
        graph_config = shared_config
        macro_block = typed_blocks.get("macro_releases")
        macro_initial = getattr(macro_block, "data", None)
        if window.mode == "live" and isinstance(macro_initial, Mapping) and "releases" in macro_initial:
            # 数据源存在收录延迟，决策节点前按标题去重补抓当日经济数据
            from daily_analyzer.context.providers import macro_seen_titles

            graph_config = {
                **shared_config,
                "_late_macro_refresher": lambda: context_manager.refresh_macro_releases(item, _clock_now(clock)),
                "_late_macro_seen": macro_seen_titles(macro_initial),
            }
        graph = analyzer_factory(
            item=item,
            mode=window.mode,
            config=graph_config,
            state_log_dir=batch_dir / "results" / symbol_slug(item.symbol) / "state",
            context_blocks=typed_blocks,
            context_as_of=cutoff,
            portfolio=portfolio,
            clock=clock,
        )
        injected = getattr(graph, "injected_context", injected)
        from tradingagents.llm_clients.codex_exec.runner import codex_usage_context

        with codex_usage_context(ticker=item.symbol):
            final_state, rating = graph.propagate(
                graph.analysis_symbol,
                window.trade_date.isoformat(),
                asset_type="stock" if item.type == "stock" else "etf",
                portfolio=portfolio,
            )
        reports_path = batch_dir / "reports" / symbol_slug(item.symbol)
        write_progress(progress_path, "保存报告", clock)
        graph.save_reports(final_state, ticker=graph.analysis_symbol, save_path=reports_path)
        finished_at = _clock_now(clock)
        tool_queries = graph.tool_trace.snapshot()
        last_query = max(
            (row["finished_at"] for row in tool_queries), default=None
        )
        information_through = (
            window.news_cutoff_utc.isoformat()
            if window.mode == "backfill" and window.news_cutoff_utc
            else max(started_at.isoformat(timespec="seconds"), last_query or "",
                     *(row.get("fetched_at", "") for row in final_state.get("late_news", [])),
                     *(row.get("fetched_at", "") for row in final_state.get("late_macro", [])))
        )
        open_time = session_bounds(window.trade_date)[0] if is_trading_day(window.trade_date) else None
        started_after_open = bool(window.mode == "live" and open_time and started_at > open_time)
        finished_after_open = bool(window.mode == "live" and open_time and finished_at > open_time)
        final_state = jsonable(final_state)
        reports = {
            name: final_state.get(name)
            for name in (
                "market_report", "sentiment_report", "news_report", "fundamentals_report"
            )
            if final_state.get(name)
        }
        macro = ticker_blocks.get("macro_releases", {})
        macro_data = macro.get("data") if isinstance(macro, Mapping) else {}
        calls = _usage_for_ticker(batch_dir / "llm_calls.jsonl", item.symbol)
        result = {
            **_failed_result(
                item=item,
                run_id=run_id,
                mode=window.mode,
                trade_day=window.trade_date,
                price_end=window.price_data_end_date,
                news_cutoff=window.news_cutoff_utc,
                status="success",
                error=None,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=max(0.0, monotonic() - timer) if timer is not None else 0.0,
                blocks=ticker_blocks,
                injected_context=injected,
                portfolio_context=portfolio.render(graph.analysis_symbol) if portfolio else None,
            ),
            "target_session": _target_session(window.mode, started_at, window.trade_date),
            "final_rating": str(rating),
            "rating_cn": _rating_cn(rating),
            "final_trade_decision": final_state.get("final_trade_decision"),
            "decision_plan_validity_trading_days": shared_config.get("decision_plan_validity_trading_days", 5),
            "decision_flags": final_state.get("decision_flags") or {},
            "structured": {key: final_state.get("structured_" + key) for key in ("research_plan", "trader_proposal", "pm_decision")},
            "late_news": final_state.get("late_news", []),
            "late_news_errors": final_state.get("late_news_errors", []),
            "late_macro": final_state.get("late_macro", []),
            "late_macro_errors": final_state.get("late_macro_errors", []),
            "trader_investment_plan": final_state.get("trader_investment_plan"),
            "investment_plan": final_state.get("investment_plan"),
            "reports": reports,
            "investment_debate": final_state.get("investment_debate_state"),
            "risk_debate": final_state.get("risk_debate_state"),
            "data_queries": tool_queries,
            "last_data_query_at": last_query,
            "information_through": information_through,
            "started_after_open": started_after_open,
            "finished_after_open": finished_after_open,
            "news_truncated": (
                bool(macro_data.get("truncated"))
                if isinstance(macro_data, Mapping)
                else False
            ) or any(row.get("truncated") is True for row in tool_queries),
            "llm": {
                "provider": shared_config.get("llm_provider"),
                "deep": {
                    "model": shared_config.get("deep_think_llm"),
                    "reasoning_effort": shared_config.get("codex_deep_reasoning_effort"),
                },
                "quick": {
                    "model": shared_config.get("quick_think_llm"),
                    "reasoning_effort": shared_config.get("codex_quick_reasoning_effort"),
                },
            },
            "llm_usage": calls,
        }
        from daily_analyzer.evaluation.plan_checks import decision_plan_checks
        result['decision_flags'] = decision_plan_checks(result, shared_config)
        result['allocation_tolerance_pct'] = shared_config.get('allocation_tolerance_pct', 10)
        if getattr(graph, 'role_llm_metadata', None):
            from daily_analyzer.model_usage import role_execution_evidence
            result['llm']['roles'] = role_execution_evidence(graph.role_llm_metadata, _read_usage_rows(batch_dir/'llm_calls.jsonl'), item.symbol)
        from daily_analyzer.model_usage import apply_execution_labels
        apply_execution_labels(result, shared_config)
        snapshot = getattr(graph, 'consistency_snapshot', None)
        if callable(snapshot):
            result['consistency_input'] = snapshot(final_state)
        result["data_source_status"] = source_collector.snapshot(ticker_blocks, shared_config, fred_configured=bool(os.environ.get("FRED_API_KEY")))
        if appended:
            result["appended"] = True
        result_path = batch_dir / "results" / f"{symbol_slug(item.symbol)}.json"
        atomic_write_json(result_path, result)
        return AttemptOutcome(item, result, None, True)
    except BaseException as exc:
        finished_at = _clock_now(clock)
        category = _error_category(exc)
        error_text = _safe_error(exc, secrets)
        result = _failed_result(
            item=item,
            run_id=run_id,
            mode=window.mode,
            trade_day=window.trade_date,
            price_end=window.price_data_end_date,
            news_cutoff=window.news_cutoff_utc,
            status="failed",
            error=error_text,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=max(0.0, monotonic() - timer) if timer is not None else 0.0,
            blocks=ticker_blocks,
            injected_context=injected,
            portfolio_context=portfolio.render(item.analysis_symbol) if portfolio else None,
        )
        result["failure_category"] = category
        result["llm"] = {
            "provider": shared_config.get("llm_provider"),
            "deep": {"model": shared_config.get("deep_think_llm"), "reasoning_effort": shared_config.get("codex_deep_reasoning_effort")},
            "quick": {"model": shared_config.get("quick_think_llm"), "reasoning_effort": shared_config.get("codex_quick_reasoning_effort")},
        }
        if graph is not None and getattr(graph, 'role_llm_metadata', None):
            from daily_analyzer.model_usage import role_execution_evidence
            result['llm']['roles'] = role_execution_evidence(graph.role_llm_metadata, _read_usage_rows(batch_dir/'llm_calls.jsonl'), item.symbol, auth_failed_role=getattr(exc,'role',None) if getattr(exc,'stage',None)=='auth_preflight' and getattr(exc,'model_requests',None)==0 else None)
        from daily_analyzer.model_usage import apply_execution_labels
        apply_execution_labels(result, shared_config)
        result["llm_usage"] = _usage_for_ticker(
            batch_dir / "llm_calls.jsonl", item.symbol
        )
        if started_at is not None and finished_at is not None:
            open_time = session_bounds(window.trade_date)[0] if is_trading_day(window.trade_date) else None
            result["started_after_open"] = bool(window.mode == "live" and open_time and started_at > open_time)
            result["finished_after_open"] = bool(window.mode == "live" and open_time and finished_at > open_time)
        if graph is not None:
            try:
                result["data_queries"] = graph.tool_trace.snapshot()
                result["last_data_query_at"] = max(
                    (row["finished_at"] for row in result["data_queries"]), default=None
                )
                result["news_truncated"] = result["news_truncated"] or any(
                    row.get("truncated") is True for row in result["data_queries"]
                )
                result["information_through"] = (
                    window.news_cutoff_utc.isoformat()
                    if window.mode == "backfill" and window.news_cutoff_utc
                    else max(started_at.isoformat(timespec="seconds"), result["last_data_query_at"] or "")
                )
            except Exception:
                pass
        result["data_source_status"] = source_collector.snapshot(ticker_blocks, shared_config, fred_configured=bool(os.environ.get("FRED_API_KEY")))
        if appended:
            result["appended"] = True
        atomic_write_json(
            batch_dir / "results" / f"{symbol_slug(item.symbol)}.json", result
        )
        return AttemptOutcome(item, result, category, False)
    finally:
        reset_vendor_observer(source_token)


def _write_skipped_result(
    *, item: Any, run_id: str, window: RunWindow, status: str, reason: str, batch_dir: Path
) -> dict[str, Any]:
    result = _failed_result(
        item=item,
        run_id=run_id,
        mode=window.mode,
        trade_day=window.trade_date,
        price_end=window.price_data_end_date,
        news_cutoff=window.news_cutoff_utc,
        status=status,
        error=reason,
    )
    atomic_write_json(batch_dir / "results" / f"{symbol_slug(item.symbol)}.json", result)
    return result


def _manifest_usage(root: Path, trade_day: date) -> dict[str, Any]:
    totals = {
        "calls": 0,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
    }
    rows=[]
    for batch in _batch_records(root, trade_day):
        path=root/'data/runs'/trade_day.isoformat()/'batches'/str(batch.get('run_id'))/'llm_calls.jsonl'
        usage=_usage_for_ticker(path)
        rows.extend(_read_usage_rows(path))
        for key in ('calls','input_tokens','cached_input_tokens','output_tokens','reasoning_output_tokens'):
            totals[key]=None if totals[key] is None or usage[key] is None else totals[key]+usage[key]
    if any(row.get('provider')=='claude_exec' for row in rows):
        from daily_analyzer.model_usage import mixed_usage
        return mixed_usage(rows)
    return totals


def _recompute_manifest(root: Path, trade_day: date, now: datetime) -> dict[str, Any]:
    current = _current_results(root, trade_day)
    histories: dict[str, list[dict[str, Any]]] = {}
    for batch in _batch_records(root, trade_day):
        for slug, item in (batch.get("items") or {}).items():
            histories.setdefault(slug, []).append(
                {
                    "run_id": batch.get("run_id"),
                    "status": item.get("status"),
                    "error": item.get("error"),
                    "duration_seconds": item.get("duration_seconds"),
                }
            )
    manifest_items = {}
    for slug, result in current.items():
        attempts = histories.get(slug, [])
        latest = attempts[-1] if attempts else None
        retry_failure = None
        if latest and latest.get("status") not in {
            "success", "completed", "skipped_already_done"
        } and _is_success(result):
            retry_failure = {
                "run_id": latest.get("run_id"),
                "status": latest.get("status"),
                "error": latest.get("error"),
            }
        manifest_items[slug] = {
            "symbol": result.get("symbol"),
            "status": result.get("status"),
            "run_id": result.get("run_id"),
            "recent_retry_failure": retry_failure,
            "attempts": attempts,
        }
    payload = {
        "trade_date": trade_day.isoformat(),
        "updated_at": now.isoformat(timespec="seconds"),
        "items": manifest_items,
        "llm_usage": _manifest_usage(root, trade_day),
    }
    atomic_write_json(root / "data" / "runs" / trade_day.isoformat() / "manifest.json", payload)
    return payload


def _record_attempt(
    *,
    root: Path,
    trade_day: date,
    batch_dir: Path,
    batch: dict[str, Any],
    outcome: AttemptOutcome,
    current: dict[str, dict[str, Any]],
    now: datetime,
) -> None:
    slug = symbol_slug(outcome.item.symbol)
    result = outcome.result
    current_dir = root / "data" / "runs" / trade_day.isoformat() / "current"
    current_dir.mkdir(parents=True, exist_ok=True)
    previous = current.get(slug)
    if outcome.succeeded or not _is_success(previous):
        atomic_write_json(current_dir / f"{slug}.json", result)
        current[slug] = result
        # 报告、查询快照及批次结果已成功，且current已原子落盘，才提交成功live决策记忆。
        if (outcome.succeeded and result.get("mode") == "live" and _is_success(result)
                and result.get("final_rating") in {"Buy", "Overweight", "Hold", "Underweight", "Sell"}
                and str(result.get("final_trade_decision") or "").strip()):
            from tradingagents.memory.log import TradingMemoryLog
            TradingMemoryLog({"memory_log_path": str(root / "data/tradingagents/memory/trading_memory.md")}).store_decision(
                ticker=outcome.item.symbol, trade_date=trade_day.isoformat(),
                final_trade_decision=result["final_trade_decision"], rating=result["final_rating"], replace_pending=True,
            )
    batch["items"].setdefault(slug, {}).update(
        {
            "symbol": outcome.item.symbol,
            "status": result.get("status"),
            "error": result.get("error"),
            "failure_category": outcome.category,
            "duration_seconds": result.get("duration_seconds"),
            "result_path": f"results/{slug}.json",
            "finished_at": result.get("finished_at"),
        }
    )
    atomic_write_json(batch_dir / "batch.json", batch)
    _recompute_manifest(root, trade_day, now)


def _finalize_exception_batch(
    *,
    root: Path,
    window: RunWindow,
    batch_dir: Path | None,
    batch: dict[str, Any] | None,
    items: Sequence[Any],
    current: dict[str, dict[str, Any]],
    error: BaseException,
    secrets: Sequence[str],
    site_builder: Callable[..., Mapping[str, Any]],
    clock: Callable[[], datetime],
) -> str | None:
    if batch is None or batch_dir is None or batch.get("status") != "running":
        return None
    now = _clock_now(clock)
    safe_error = _safe_error(error, secrets)
    category = _error_category(error)
    for item in items:
        slug = symbol_slug(item.symbol)
        record = batch["items"].get(slug, {})
        if record.get("status") not in {"pending", "running"}:
            continue
        result = _failed_result(
            item=item,
            run_id=str(batch["run_id"]),
            mode=window.mode,
            trade_day=window.trade_date,
            price_end=window.price_data_end_date,
            news_cutoff=window.news_cutoff_utc,
            status="failed",
            error=safe_error,
            finished_at=now,
            duration_seconds=0.0,
        )
        result["failure_category"] = category
        result_path = batch_dir / "results" / f"{slug}.json"
        atomic_write_json(result_path, result)
        _record_attempt(
            root=root,
            trade_day=window.trade_date,
            batch_dir=batch_dir,
            batch=batch,
            outcome=AttemptOutcome(item, result, category, False),
            current=current,
            now=now,
        )
    batch["status"] = "failed"
    batch["finished_at"] = now.isoformat(timespec="seconds")
    batch["last_error"] = safe_error
    usage_path = batch_dir / "llm_calls.jsonl"
    batch["llm_usage"] = _usage_for_ticker(usage_path)
    batch["warning_count"] = sum(
        len(row.get("warnings", [])) + len(row.get("agent_actions", []))
        for row in _read_usage_rows(usage_path)
    )
    _refresh_state(
        root=root,
        trade_day=window.trade_date,
        batch_dir=batch_dir,
        batch=batch,
        now=now,
        site_builder=site_builder,
        finished=True,
    )
    append_log(root, window.trade_date, now, f"批次异常：{safe_error}")
    return safe_error


def _progress_value(batch: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    items = list((batch.get("items") or {}).values())
    total = len(items)
    terminal = {
        "success", "completed", "failed", "interrupted", "skipped",
        "skipped_already_done", "skipped_quota", "skipped_fatal",
        "skipped_timeout",
    }
    completed = sum(item.get("status") in terminal for item in items)
    durations = [
        float(item["duration_seconds"])
        for item in items
        if item.get("duration_seconds") is not None
    ]
    average = sum(durations) / len(durations) if durations else None
    workers = max(1, int(batch.get("parallelism") or 1))
    remaining = max(0, total - completed)
    estimated = now + timedelta(seconds=average * remaining / workers) if average is not None else None
    errors = [item.get("error") for item in items if item.get("error")]
    return {
        "completed": completed,
        "total": total,
        "average_duration_seconds": average,
        "estimated_finish_at": estimated.isoformat(timespec="seconds") if estimated else None,
        "last_error": errors[-1] if errors else None,
    }


def _last_run_state(batch: Mapping[str, Any], now: datetime, finished: bool = False) -> dict[str, Any]:
    progress = _progress_value(batch, now)
    state = {
        "run_id": batch.get("run_id"),
        "trade_date": batch.get("trade_date"),
        "mode": batch.get("mode"),
        "status": batch.get("status"),
        "started_at": batch.get("started_at"),
        "finished_at": batch.get("finished_at") if finished else None,
        "progress": {"completed": progress["completed"], "total": progress["total"]},
        "average_duration_seconds": progress["average_duration_seconds"],
        "estimated_finish_at": progress["estimated_finish_at"],
        "last_error": batch.get("last_error") or progress["last_error"],
    }
    return state


def _refresh_state(
    *, root: Path, trade_day: date, batch_dir: Path, batch: dict[str, Any], now: datetime,
    site_builder: Callable[..., Mapping[str, Any]], finished: bool = False,
) -> None:
    atomic_write_json(batch_dir / "batch.json", batch)
    _recompute_manifest(root, trade_day, now)
    _write_status(root, last_run=_last_run_state(batch, now, finished=finished))
    _build_site_and_log(root, now, trade_day, site_builder)


def _fork_state(root: Path) -> dict[str, Any]:
    submodule = root / "TradingAgents"
    try:
        commit = subprocess.run(
            ["git", "-C", str(submodule), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "-C", str(submodule), "status", "--porcelain"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        )
        return {"tradingagents_commit": commit, "tradingagents_dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"tradingagents_commit": None, "tradingagents_dirty": None}


def _codex_version(settings: Settings) -> str | None:
    if settings.llm.provider != "codex_exec":
        return None
    binary = settings.codex.binary or "codex"
    try:
        result = subprocess.run(
            [binary, "--version"], capture_output=True, text=True, check=False, timeout=3
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = (result.stdout or result.stderr or "").strip()
    return output[:120] if result.returncode == 0 and output else None


def _secret_values(project: ProjectConfig) -> list[str]:
    values = []
    for secret in (
        project.credentials.alpaca_key_id,
        project.credentials.alpaca_secret_key,
        project.credentials.alpha_vantage_api_key,
        project.credentials.fred_api_key,
    ):
        if secret is not None:
            values.append(secret.get_secret_value())
    return values


def _environment_credentials(project: ProjectConfig) -> dict[str, str]:
    values: dict[str, str] = {}
    for secret, name in (
        (project.credentials.alpaca_key_id, "APCA_API_KEY_ID"),
        (project.credentials.alpaca_secret_key, "APCA_API_SECRET_KEY"),
        (project.credentials.alpha_vantage_api_key, "ALPHA_VANTAGE_API_KEY"),
        (project.credentials.fred_api_key, "FRED_API_KEY"),
    ):
        if secret is not None:
            values[name] = secret.get_secret_value()
    return values


def _settle_completed(root: Path, now: datetime) -> None:
    """结算失败仅记日志，不改变已完成分析。"""
    from daily_analyzer.evaluation import settle

    try:
        result = settle(root, now=now)
        append_log(root, now.date(), now, f"独立评估结算：记录{result['records']}，新增成熟窗口{result['newly_settled']}")
    except Exception as exc:
        append_log(root, now.date(), now, f"独立评估结算失败：{type(exc).__name__}")


def run_analysis(
    project_root: str | Path,
    *,
    date_value: str | None = None,
    tickers: str | None = None,
    force: bool = False,
    scheduled: bool = False,
    model: str | None = None,
    effort: str | None = None,
    now: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    context_manager_factory: Callable[..., Any] | None = None,
    analyzer_factory: Callable[..., Any] | None = None,
    site_builder: Callable[..., Mapping[str, Any]] | None = None,
    settler: Callable[[Path, datetime], None] | None = None,
) -> RunOutcome:
    """执行一个受锁保护的日分析批次。"""
    root = Path(project_root).expanduser().resolve()
    clock = clock or (lambda: now if now is not None else datetime.now(NEW_YORK))
    site_builder = site_builder or build_site
    analyzer_factory = analyzer_factory or AnalyzerGraph
    context_manager_factory = context_manager_factory or _default_context_manager
    try:
        project = load_project_config(root)
        settings = apply_llm_overrides(project.settings, model=model, effort=effort)
        if settings is not project.settings:
            project = ProjectConfig(settings, project.watchlist, project.portfolio, project.credentials)
    except ConfigurationError as exc:
        return RunOutcome(2, str(exc))

    try:
        window = select_run_window(date_value, as_new_york(now or _clock_now(clock)))
    except NoTradingSessionError as exc:
        if not scheduled:
            return RunOutcome(3, str(exc))
        current_time = _clock_now(clock)
        event_day = current_time.date()
        try:
            with run_lock(root):
                interrupted = _mark_interrupted(root, event_day, current_time)
                decision = scheduled_decision(
                    settings.schedule.anchor,
                    current_time,
                    already_completed=_schedule_flags(root, event_day)[0],
                    recover_interrupted=bool(interrupted) or _schedule_flags(root, event_day)[1],
                )
                result, reason = decision or ("skipped_after_close", str(exc))
                _record_schedule_event(root, current_time, event_day, result, reason, site_builder=site_builder)
            return RunOutcome(0, reason)
        except RunAlreadyRunningError as lock_error:
            return RunOutcome(1, str(lock_error))
    except ValueError as exc:
        return RunOutcome(2, str(exc))

    schedule_result = None
    schedule_reason = ""

    try:
        project = ProjectConfig(settings, project.watchlist, project.portfolio, project.credentials)
        items = _filter_items(project, tickers)
        portfolio = to_tradingagents_portfolio(project.portfolio)
        items = _priority_items(items, portfolio)
    except (ConfigurationError, ValueError) as exc:
        return RunOutcome(2, str(exc))

    try:
        lock_context = run_lock(root)
        lock_context.__enter__()
    except RunAlreadyRunningError as exc:
        return RunOutcome(1, str(exc))

    batch_dir: Path | None = None
    batch: dict[str, Any] | None = None
    current: dict[str, dict[str, Any]] = {}
    append_offset = 0
    try:
        current_now = _clock_now(clock)
        run_started_mono = monotonic()
        interrupted = _mark_interrupted(root, window.trade_date, current_now)
        if scheduled:
            completed, recover = _schedule_flags(root, current_now.date())
            decision = scheduled_decision(
                settings.schedule.anchor,
                current_now,
                already_completed=completed,
                recover_interrupted=bool(interrupted) or recover,
            )
            if decision and decision[0] != "recovery_started":
                result, reason = decision
                _record_schedule_event(
                    root, current_now, current_now.date(), result, reason,
                    site_builder=site_builder,
                )
                return RunOutcome(0, reason)
            schedule_result = (
                "recovery_started"
                if decision and decision[0] == "recovery_started"
                else "started"
            )
            schedule_reason = (
                "恢复当天未成功的标的"
                if schedule_result == "recovery_started"
                else "到达锚点，开始分析"
            )
        current = _current_results(root, window.trade_date)
        if scheduled and schedule_result == "recovery_started":
            items = [item for item in items if not _is_success(current.get(symbol_slug(item.symbol)))]
        elif not force:
            items = [item for item in items if not _is_success(current.get(symbol_slug(item.symbol)))]

        if scheduled and not items:
            _record_schedule_event(
                root,
                current_now,
                window.trade_date,
                "skipped_already_done",
                "当天所有标的已有成功结果",
                site_builder=site_builder,
            )
            return RunOutcome(0, "当天所有标的已有成功结果")

        run_id = f"{current_now.strftime('%Y%m%dT%H%M%S')}-{os.getpid()}"
        batch_dir = root / "data" / "runs" / window.trade_date.isoformat() / "batches" / run_id
        batch_dir.mkdir(parents=True, exist_ok=False)
        (batch_dir / "results").mkdir()
        (batch_dir / "reports").mkdir()
        from tradingagents.dataflows.yahoo_breaker import reset_yahoo_breaker
        from daily_analyzer.data_sources.futu import get_shared_data_source
        reset_yahoo_breaker()
        get_shared_data_source().clear_cache()
        from daily_analyzer.data_sources.treasury import TREASURY_SOURCE
        TREASURY_SOURCE.clear_cache()
        shared_config = build_upstream_config(
            settings,
            trade_date=window.trade_date.isoformat(),
            price_data_end_date=window.price_data_end_date.isoformat(),
            mode=window.mode,
            news_cutoff_utc=window.news_cutoff_utc,
            batch_dir=batch_dir,
            project_root=root,
            has_alpha_vantage=project.credentials.alpha_vantage_api_key is not None,
        )
        from tradingagents.graph.role_fallback import RoleBatchBreaker
        shared_config["_role_llm_breaker"] = RoleBatchBreaker()
        fork = _fork_state(root)
        batch = {
            "schema_version": 1,
            "run_id": run_id,
            "pid": os.getpid(),
            "trade_date": window.trade_date.isoformat(),
            "price_data_end_date": window.price_data_end_date.isoformat(),
            "news_cutoff_utc": window.news_cutoff_utc.isoformat() if window.news_cutoff_utc else None,
            "mode": window.mode,
            "scheduled": scheduled,
            "force": force,
            "requested_tickers": tickers,
            "accepting_appends": window.mode == "live",
            "append_rejections": [],
            "status": "running",
            "started_at": current_now.isoformat(timespec="seconds"),
            "finished_at": None,
            "parallelism": settings.run.max_parallel_tickers,
            "effective_config": {
                "llm_provider": settings.llm.provider,
                "deep": settings.llm.deep.model_dump(mode="json"),
                "quick": settings.llm.quick.model_dump(mode="json"),
                "output_language": settings.tradingagents.output_language,
                "context_providers": settings.context_providers,
                "alpaca_requests_per_minute": settings.alpaca.requests_per_minute,
            },
            "codex_version": _codex_version(settings),
            **fork,
            "items": {
                symbol_slug(item.symbol): {"symbol": item.symbol, "status": "pending"}
                for item in items
            },
            "llm_usage": {},
            "warning_count": 0,
            "last_error": None,
        }
        atomic_write_json(batch_dir / "batch.json", batch)
        if scheduled:
            _write_status(
                root,
                last_schedule_event={
                    "at": current_now.isoformat(timespec="seconds"),
                    "trade_date": window.trade_date.isoformat(),
                    "result": schedule_result,
                    "reason": schedule_reason,
                },
            )

        _recompute_manifest(root, window.trade_date, current_now)
        _write_status(root, last_run=_last_run_state(batch, current_now))
        _build_site_and_log(root, current_now, window.trade_date, site_builder)
        append_log(root, window.trade_date, current_now, f"批次 {run_id} 开始，模式 {window.mode}，标的 {len(items)} 只")

        env_values = _environment_credentials(project)
        environment_context = patch.dict(os.environ, env_values, clear=False)
        environment_context.__enter__()
        context_manager = None
        try:
            context_manager = context_manager_factory(settings, root, window.mode, clock)
            batch_context = {
                "items": list(items),
                "trade_date": window.trade_date,
                "price_data_end_date": window.price_data_end_date,
                "mode": window.mode,
                "decision_horizon_trading_days": list(settings.decision.horizon_trading_days),
                "context_as_of": current_now,
            }
            from daily_analyzer.source_status import SourceStatusCollector
            from tradingagents.dataflows.vendor_observer import set_vendor_observer, reset_vendor_observer
            batch_source_collector = SourceStatusCollector(_secret_values(project))
            batch_source_token = set_vendor_observer(batch_source_collector.observe)
            try:
                batch_blocks = context_manager.prepare(batch_context)
            finally:
                reset_vendor_observer(batch_source_token)
            atomic_write_json(batch_dir / "context.json", serialize_blocks(batch_blocks))
            if scheduled:
                _wait_until_first_start(settings, window, clock, sleeper)

            build_lock = threading.Lock()
            pending = deque(items)
            futures: dict[Future, Any] = {}
            stop_reason: str | None = None
            fatal_seen = False
            outcomes: dict[str, AttemptOutcome] = {}
            secret_values = _secret_values(project)

            append_seeds = {}

            def receive_appends():
                nonlocal append_offset
                accepted = []
                with append_lock(batch_dir):
                    requests, append_offset = read_requests(batch_dir, append_offset)
                    enabled = {item.symbol: item for item in load_watchlist(root).active_items} if requests else {}
                    for request in requests:
                        symbol = request.get("symbol")
                        slug = symbol_slug(symbol)
                        reason = STOP_MESSAGES.get(stop_reason)
                        if reason is None and monotonic() - run_started_mono >= settings.run.max_duration_minutes * 60:
                            reason = STOP_MESSAGES["skipped_timeout"]
                        if reason is None and request.get("trade_date") != batch["trade_date"]:
                            reason = "点击日期与当前批次交易日不同，请等待本批结束"
                        if reason is None and symbol not in enabled:
                            reason = "该标的已停用或不在订阅列表"
                        if reason is None and slug in batch["items"]:
                            reason = "本批已包含该标的"
                        if reason:
                            batch["append_rejections"].append({**request, "reason": reason})
                            continue
                        item = enabled[symbol]
                        batch["items"][slug] = {"symbol": symbol, "status": "pending", "source": "append",
                            "appended_at": _clock_now(clock).isoformat(), "request_id": request["request_id"]}
                        items.append(item)
                        pending.append(item)
                        accepted.append(item)
                    if requests:
                        batch["requested_tickers"] = ",".join(row["symbol"] for row in batch["items"].values())
                        atomic_write_json(batch_dir / "batch.json", batch)
                if requests:
                    _write_status(root, last_run=_last_run_state(batch, _clock_now(clock)))
                for item in accepted:
                    collector = SourceStatusCollector(secret_values, batch_source_collector.events)
                    token = set_vendor_observer(collector.observe)
                    try:
                        with build_lock:
                            context_manager.extend([item])
                    finally:
                        reset_vendor_observer(token)
                    append_seeds[item.symbol] = collector.events


            try:
                from tradingagents.llm_clients.codex_exec.runner import reset_abort

                reset_abort()
            except ImportError:
                reset_abort = None

            with ThreadPoolExecutor(
                max_workers=settings.run.max_parallel_tickers,
                thread_name_prefix="daily-analyzer",
            ) as executor:
                while True:
                    receive_appends()
                    while pending and len(futures) < settings.run.max_parallel_tickers and stop_reason is None:
                        if monotonic() - run_started_mono >= settings.run.max_duration_minutes * 60:
                            stop_reason = "skipped_timeout"
                            break
                        item = pending.popleft()
                        batch["items"][symbol_slug(item.symbol)]["status"] = "running"
                        atomic_write_json(batch_dir / "batch.json", batch)
                        future = executor.submit(
                            _analyze_item,
                            item=item,
                            run_id=run_id,
                            root=root,
                            batch_dir=batch_dir,
                            window=window,
                            shared_config=shared_config,
                            context_manager=context_manager,
                            context_build_lock=build_lock,
                            portfolio=portfolio,
                            clock=clock,
                            monotonic=monotonic,
                            secrets=secret_values,
                            analyzer_factory=analyzer_factory,
                            source_seed=append_seeds.get(item.symbol, batch_source_collector.events),
                            appended=batch["items"][symbol_slug(item.symbol)].get("source") == "append",
                        )
                        futures[future] = item
                    if not futures:
                        append_offset = _close_appends(batch_dir, batch, append_offset)
                        break
                    done, _ = wait(futures, timeout=0.5, return_when=FIRST_COMPLETED)
                    if not done:
                        continue
                    completed = [
                        (future, futures.pop(future), future.result())
                        for future in done
                    ]
                    if any(
                        outcome.category in {"fatal_config", "aborted"}
                        for _, _, outcome in completed
                    ):
                        fatal_seen = True
                        stop_reason = "skipped_fatal"
                        try:
                            from tradingagents.llm_clients.codex_exec.runner import abort_all_calls

                            abort_all_calls()
                        except ImportError:
                            pass
                    for _, item, outcome in completed:
                        category = outcome.category
                        if fatal_seen and category == "aborted":
                            outcome.result["status"] = "skipped_fatal"
                            outcome.result["error"] = outcome.result.get("error") or "Codex 子进程因致命错误中止"
                            outcome.succeeded = False
                        if category == "quota" and stop_reason is None:
                            stop_reason = "skipped_quota"
                        slug = symbol_slug(item.symbol)
                        if outcome.result.get("status") == "skipped_fatal":
                            atomic_write_json(
                                batch_dir / "results" / f"{slug}.json", outcome.result
                            )
                        if stop_reason:
                            batch["append_stop_reason"] = stop_reason
                        outcomes[slug] = outcome
                        current_now = _clock_now(clock)
                        _record_attempt(
                            root=root,
                            trade_day=window.trade_date,
                            batch_dir=batch_dir,
                            batch=batch,
                            outcome=outcome,
                            current=current,
                            now=current_now,
                        )
                        batch["items"][slug]["status"] = outcome.result.get("status")
                        batch["items"][slug]["error"] = outcome.result.get("error")
                        progress = _last_run_state(batch, current_now)
                        _write_status(root, last_run=progress)
                        _build_site_and_log(root, current_now, window.trade_date, site_builder)
                        append_log(
                            root,
                            window.trade_date,
                            current_now,
                            f"标的 {item.symbol}：{outcome.result.get('status')}"
                            + (f"；{outcome.result.get('error')}" if outcome.result.get("error") else ""),
                        )

            for item in list(pending):
                reason = {
                    "skipped_quota": "Codex 额度已达到上限，未派发此标的",
                    "skipped_fatal": "Codex 配置错误后停止派发",
                    "skipped_timeout": "批次达到最长运行时间，未派发此标的",
                }.get(stop_reason or "", "未派发")
                result = _write_skipped_result(
                    item=item,
                    run_id=run_id,
                    window=window,
                    status=stop_reason or "skipped",
                    reason=reason,
                    batch_dir=batch_dir,
                )
                outcome = AttemptOutcome(item, result, stop_reason, False)
                current_now = _clock_now(clock)
                _record_attempt(
                    root=root,
                    trade_day=window.trade_date,
                    batch_dir=batch_dir,
                    batch=batch,
                    outcome=outcome,
                    current=current,
                    now=current_now,
                )
                batch["items"][symbol_slug(item.symbol)]["status"] = result["status"]
                progress_now = _clock_now(clock)
                _write_status(
                    root, last_run=_last_run_state(batch, progress_now)
                )
                _build_site_and_log(
                    root, progress_now, window.trade_date, site_builder
                )
                append_log(
                    root,
                    window.trade_date,
                    progress_now,
                    f"标的 {item.symbol}：{result['status']}；{reason}",
                )

            current_now = _clock_now(clock)
            statuses = [item.get("status") for item in batch["items"].values()]
            successes = sum(status == "success" for status in statuses)
            failures = sum(status == "failed" for status in statuses)
            if fatal_seen or (failures and not successes):
                final_status = "failed"
            elif failures or any(str(status).startswith("skipped_") for status in statuses):
                final_status = "partial"
            else:
                final_status = "completed"
            batch["status"] = final_status
            batch["finished_at"] = current_now.isoformat(timespec="seconds")
            batch["llm_usage"] = _usage_for_ticker(
                batch_dir / "llm_calls.jsonl"
            )
            batch["warning_count"] = sum(
                len(row.get("warnings", [])) + len(row.get("agent_actions", []))
                for row in _read_usage_rows(batch_dir / "llm_calls.jsonl")
            )
            batch["last_error"] = next(
                (row.get("error") for row in reversed(list(batch["items"].values())) if row.get("error")),
                None,
            )
            _refresh_state(
                root=root,
                trade_day=window.trade_date,
                batch_dir=batch_dir,
                batch=batch,
                now=current_now,
                site_builder=site_builder,
                finished=True,
            )
            append_log(root, window.trade_date, current_now, f"批次 {run_id} 结束，状态 {final_status}")
            if window.mode == "live":
                (settler or _settle_completed)(root, current_now)
            exit_code = 0 if final_status == "completed" else 1
            return RunOutcome(exit_code, f"批次 {run_id}：{final_status}", run_id, final_status)
        finally:
            if context_manager is not None:
                context_manager.close()
            environment_context.__exit__(None, None, None)
    except RunAlreadyRunningError as exc:
        return RunOutcome(1, str(exc))
    except (ConfigurationError, ValueError) as exc:
        message = _finalize_exception_batch(
            root=root,
            window=window,
            batch_dir=batch_dir,
            batch=batch,
            items=items,
            current=current,
            error=exc,
            secrets=_secret_values(project),
            site_builder=site_builder,
            clock=clock,
        ) or _safe_error(exc, _secret_values(project))
        return RunOutcome(2, message, batch.get("run_id") if batch else None, "failed" if batch else None)
    except BaseException as exc:
        now_value = _clock_now(clock)
        secrets = _secret_values(project)
        message = _finalize_exception_batch(
            root=root,
            window=window,
            batch_dir=batch_dir,
            batch=batch,
            items=items,
            current=current,
            error=exc,
            secrets=secrets,
            site_builder=site_builder,
            clock=clock,
        )
        if message is None:
            message = _safe_error(exc, secrets)
            append_log(root, window.trade_date, now_value, f"批次异常：{message}")
        return RunOutcome(1, f"批次异常：{message}", batch.get("run_id") if batch else None, "failed" if batch else None)
    finally:
        try:
            if batch_dir is not None:
                if batch is not None and batch.get("accepting_appends"):
                    _close_appends(batch_dir, batch, append_offset)
                from daily_analyzer.data_sources.futu import get_shared_data_source
                get_shared_data_source().close_batch()
        finally:
            lock_context.__exit__(None, None, None)


def _close_appends(batch_dir, batch, offset):
    """与查看器共享锁，先关入口，再拒绝尚未派发的请求。"""
    with append_lock(batch_dir):
        batch["accepting_appends"] = False
        requests, offset = read_requests(batch_dir, offset)
        batch["append_rejections"].extend({**request, "reason": "本批已结束，请重新点击"} for request in requests)
        atomic_write_json(batch_dir / "batch.json", batch)
    return offset


def _read_usage_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows

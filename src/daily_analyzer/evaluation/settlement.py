"""独立结算记录、完成时刻入场与无前视多窗口回填。"""

from __future__ import annotations

import fcntl
import json
import hashlib
import math
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import exchange_calendars as xcals
import pandas as pd

from daily_analyzer.config import EvaluationSettings, load_project_config
from daily_analyzer.context.market_data import DailyPriceService, calculate_window_metrics
from daily_analyzer.data_sources import AlpacaDataSource, YahooDataSource
from daily_analyzer.data_sources.index_metadata import IndexMetadataSource
from daily_analyzer.site import _decision_section
from daily_analyzer.storage import read_json
from daily_analyzer.time_utils import NEW_YORK, as_new_york, session_bounds

RATINGS = {name.upper(): name for name in ("Buy", "Overweight", "Hold", "Underweight", "Sell")}


def number(value: Any, *, positive: bool = False) -> float | None:
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return result if math.isfinite(result) and (not positive or result > 0) else None


def entry_plan(finished: datetime) -> dict[str, Any]:
    """开收盘边界均属于盘中；半日市采用实际收盘。"""
    finished = as_new_york(finished)
    calendar = xcals.get_calendar("XNYS")
    day = finished.date()
    if calendar.is_session(pd.Timestamp(day)):
        opened, closed = session_bounds(day)
        if finished < opened:
            return {"basis": "same_day_open", "date": day.isoformat()}
        if finished <= closed:
            return {"basis": "same_day_close", "date": day.isoformat()}
        session = calendar.next_session(pd.Timestamp(day))
    else:
        session = calendar.date_to_session(pd.Timestamp(day), direction="next")
    return {"basis": "next_open", "date": session.date().isoformat()}


def exit_date(entry: dict[str, Any], days: int) -> date:
    calendar = xcals.get_calendar("XNYS")
    basis = entry.get("planned_basis", entry["basis"])
    return calendar.session_offset(pd.Timestamp(entry["date"]), days if basis == "same_day_close" else days - 1).date()


def last_complete_session(now: datetime) -> date:
    now = as_new_york(now)
    calendar = xcals.get_calendar("XNYS")
    candidate = calendar.date_to_session(pd.Timestamp(now.date()), direction="previous")
    if candidate.date() == now.date() and now < session_bounds(now.date())[1]:
        candidate = calendar.previous_session(candidate)
    return candidate.date()


def bar_prices(rows: list[dict[str, Any]], cutoff: date) -> dict[date, dict[str, float | None]]:
    """仅认确切日期；不以前后交易日或close替代open。"""
    output = {}
    for row in rows:
        stamp = next((row.get(key) for key in ("t", "timestamp", "date", "Date", "Datetime", "time") if row.get(key) is not None), None)
        try:
            parsed = pd.Timestamp(stamp)
            if pd.isna(parsed):
                continue
            day = parsed.tz_convert(NEW_YORK).date() if parsed.tzinfo else parsed.date()
        except (ValueError, TypeError, OverflowError):
            continue
        if day > cutoff:
            continue
        def price(keys):
            return next((value for key in keys if (value := number(row.get(key), positive=True)) is not None), None)
        output[day] = {"open": price(("o", "open", "Open")), "close": price(("c", "close", "Close", "adjclose", "Adj Close"))}
    return output


def plan_rating(text: Any, title: str) -> str | None:
    if isinstance(text, dict):
        candidate = text.get("rating") or text.get("action") or text.get("recommendation")
    else:
        section = _decision_section(text, title)
        candidate = re.match(r"\s*\**(Buy|Overweight|Hold|Underweight|Sell)\b", section, flags=re.I)
        candidate = candidate.group(1) if candidate else None
    return RATINGS.get(str(candidate).strip().upper())


def allocation(text: Any) -> float | None:
    if isinstance(text, dict):
        return number(text.get("target_allocation"))
    fixed = _decision_section(text, "目标配置（标准仓位=100%）")
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*%\s*", fixed)
    if not fixed:
        match = re.search(r"标准(?:配置|仓位|敞口)\s*(?:的|为|=|：|:)\s*(\d+(?:\.\d+)?)\s*%", str(text or ""))
    return float(match.group(1)) if match else None


def block_data(result: dict[str, Any], name: str) -> dict[str, Any]:
    block = (result.get("context_blocks") or {}).get(name) or {}
    return block.get("data") or {} if isinstance(block, dict) else {}


class SettlementServices:
    """复用日线与板块映射来源，不创建富途订阅。"""

    def __init__(self, root: Path) -> None:
        self.yahoo = YahooDataSource(project_root=root)
        self.prices = DailyPriceService(AlpacaDataSource(), self.yahoo)
        self.metadata = IndexMetadataSource()

    def sector(self, symbol: str) -> str | None:
        try:
            info = self.metadata.lookup([symbol]).get(symbol, {})
            if info.get("benchmark_kind") == "sector":
                return info.get("benchmark_symbol")
        except Exception:
            pass
        try:
            return self.yahoo.sector_etf(symbol)
        except Exception:
            return None


def new_record(result: dict[str, Any], settings: EvaluationSettings, manual: dict[str, str], services: Any) -> dict[str, Any]:
    symbol = result["symbol"]
    finished = datetime.fromisoformat(result["finished_at"])
    if finished.tzinfo is None:
        raise ValueError(f"{symbol} finished_at缺少时区，无法核验入场")
    plan = entry_plan(finished)
    kind = result["type"]
    primary = "raw_return" if kind == "index" or (kind == "etf" and symbol in settings.broad_market_etfs) else "excess_vs_spy"
    sector = None
    if kind == "stock":
        data = block_data(result, "sector_strength")
        sector = manual.get(symbol)
        if sector is None and data.get("symbol") == symbol and data.get("sector_etf"):
            sector = data["sector_etf"]
        if sector is None:
            sector = services.sector(symbol)
    anchors = block_data(result, "price_anchors").get("anchors") or {}
    values = {key: number(row.get("value")) for key, row in anchors.items() if isinstance(row, dict)}
    momentum = None
    regime = block_data(result, "market_regime")
    for row in regime.get("indices", []):
        if row.get("symbol") == result.get("analyzed_symbol", symbol):
            momentum = number(row.get("return_20d"))
    plans = {"rm": result.get("investment_plan"), "trader": result.get("trader_investment_plan"), "pm": result.get("final_trade_decision")}
    return {
        "run_id": result["run_id"], "symbol": symbol,
        "analysis_symbol": result.get("analyzed_symbol") or symbol, "type": kind,
        "trade_date": result.get("upstream_trade_date") or finished.astimezone(NEW_YORK).date().isoformat(),
        "finished_at": result["finished_at"], "target_session": result.get("target_session"),
        "price_data_end_date": result.get("price_data_end_date"), "is_current": False,
        "ratings": {"rm": plan_rating(plans["rm"], "Recommendation"), "trader": plan_rating(plans["trader"], "Action"), "pm": RATINGS.get(str(result.get("final_rating")).upper())},
        "target_allocation": {layer: allocation(text) for layer, text in plans.items()},
        "entry": {**plan, "planned_basis": plan["basis"], "price": None, "source": None},
        "sector_benchmark": sector, "primary_metric": primary,
        "anchors": values, "momentum_20d": momentum, "market_regime": regime.get("label"),
        "windows": {str(days): {"status": "pending", "exit_date": exit_date(plan, days).isoformat(), "raw_return": None, "excess_vs_spy": None, "excess_vs_sector": None, "primary_return": None} for days in settings.settlement_windows},
        "settled_at": None,
    }


def load_outcomes(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    keys = [(row["run_id"], row["symbol"]) for row in rows]
    if len(set(keys)) != len(keys):
        raise ValueError("评估存储存在重复run_id+symbol，未覆盖历史")
    return rows


@contextmanager
def evaluation_lock(root: Path):
    directory = root / "data/evaluation"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "outcomes.lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def write_outcomes(path: Path, rows: list[dict[str, Any]]) -> bool:
    content = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n" for row in rows)
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    descriptor, temporary = tempfile.mkstemp(prefix=".outcomes-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return True


def _settle(root: Path, settings: EvaluationSettings, manual: dict[str, str], services: Any, now: datetime) -> dict[str, Any]:
    path = root / "data/evaluation/outcomes.jsonl"
    rows = load_outcomes(path)
    indexed = {(row["run_id"], row["symbol"]): row for row in rows}
    added = 0
    for source in sorted((root / "data/runs").glob("*/batches/*/results/*.json")):
        result = read_json(source)
        if result.get("status") != "success" or result.get("mode") != "live":
            continue
        key = (result["run_id"], result["symbol"])
        if key not in indexed:
            indexed[key] = new_record(result, settings, manual, services)
            added += 1
        indexed[key].setdefault('decision_fingerprint',hashlib.sha256(str(result.get('final_trade_decision') or '').encode('utf-8')).hexdigest())
    current = set()
    for source in (root / "data/runs").glob("*/current/*.json"):
        row = read_json(source)
        if row.get("status") == "success" and row.get("mode") == "live":
            current.add((row.get("run_id"), row.get("symbol")))
    end = last_complete_session(now)
    cache = {}
    def prices(symbol, cutoff):
        key = (symbol, cutoff)
        if key not in cache:
            try:
                raw, source = services.prices.bars(symbol, cutoff)
                cache[key] = (bar_prices(raw, cutoff), source, raw)
            except Exception:
                cache[key] = ({}, "不可用", [])
        return cache[key]
    settled = 0
    for key, row in sorted(indexed.items()):
        row["is_current"] = key in current
        entry = row["entry"]
        day = date.fromisoformat(entry["date"])
        basis = entry.get("planned_basis", entry["basis"])
        field = "close" if basis == "same_day_close" else "open"
        price_day = row.get("price_data_end_date")
        if row.get("momentum_20d") is None and price_day and date.fromisoformat(price_day) <= end:
            _, source, raw = prices(row["analysis_symbol"], date.fromisoformat(price_day))
            row["momentum_20d"] = calculate_window_metrics(raw, date.fromisoformat(price_day), (20,)).get("return_20d")
            row["momentum_source"] = source
        if day > end:
            continue
        # 已取到的入场价格与来源冻结，重试只补真实缺价。
        if entry["price"] is None:
            entry_rows, source, _ = prices(row["analysis_symbol"], end)
            entry["price"] = entry_rows.get(day, {}).get(field)
            entry["source"] = source
            entry["basis"] = basis if entry["price"] is not None else "unavailable"
        for outcome in row["windows"].values():
            if outcome["status"] == "settled":
                continue
            exit_day = date.fromisoformat(outcome["exit_date"])
            if exit_day > end:
                outcome["status"] = "pending"
                continue
            if entry["price"] is None:
                outcome["status"] = "unavailable"
                outcome["reason"] = "入场价缺失"
                continue
            # 每个窗口从同一来源及同次复权快照同时取入场/出场，
            # 顶层entry.price仅保留首次可得的展示观测，不混入后续复权收益。
            asset, asset_source, _ = prices(row["analysis_symbol"], exit_day)
            opening = asset.get(day, {}).get(field)
            closing = asset.get(exit_day, {}).get("close")
            if opening is None or closing is None:
                outcome["status"] = "unavailable"
                outcome["reason"] = "窗口同源入场或出场价缺失"
                continue
            raw_return = closing / opening - 1
            asset_pricing = {"entry_price": opening, "exit_price": closing, "source": asset_source, "snapshot_through": exit_day.isoformat()}
            def excess(symbol):
                data, source, _ = prices(symbol, exit_day)
                opening = data.get(day, {}).get(field)
                closing = data.get(exit_day, {}).get("close")
                value = raw_return - (closing / opening - 1) if opening is not None and closing is not None else None
                pricing = {"entry_price": opening, "exit_price": closing, "source": source, "snapshot_through": exit_day.isoformat()}
                return value, pricing
            spy, spy_pricing = (None, None) if row["analysis_symbol"] == "SPY" else excess("SPY")
            sector, sector_pricing = excess(row["sector_benchmark"]) if row["sector_benchmark"] else (None, None)
            primary = raw_return if row["primary_metric"] == "raw_return" else spy
            outcome.update(raw_return=raw_return, excess_vs_spy=spy, excess_vs_sector=sector, primary_return=primary,
                           sources={"asset": asset_source, "spy": spy_pricing["source"] if spy_pricing else None, "sector": sector_pricing["source"] if sector_pricing else None},
                           pricing={"asset": asset_pricing, "spy": spy_pricing, "sector": sector_pricing})
            if primary is None:
                outcome["status"] = "unavailable"
                outcome["reason"] = "主基准价格缺失"
            else:
                outcome["status"] = "settled"
                outcome.pop("reason", None)
                outcome["settled_at"] = as_new_york(now).isoformat(timespec="seconds")
                row["settled_at"] = outcome["settled_at"]
                settled += 1
    rows = [row for _, row in sorted(indexed.items())]
    changed = write_outcomes(path, rows)
    return {"ok": True, "path": str(path), "records": len(rows), "current": sum(row["is_current"] for row in rows), "added": added, "newly_settled": settled, "changed": changed,
            "windows": {status: sum(outcome["status"] == status for row in rows for outcome in row["windows"].values()) for status in ("pending", "settled", "unavailable")}}


def settle(root: str | Path, *, now: datetime | None = None, services: Any = None, settings: EvaluationSettings | None = None, manual: dict[str, str] | None = None) -> dict[str, Any]:
    """只读原结果和行情，独立评估存储是唯一写入面。"""
    root = Path(root)
    now = now or datetime.now(NEW_YORK)
    environment = {}
    if settings is None:
        project = load_project_config(root)
        settings = project.settings.evaluation
        manual = {item.symbol: item.sector_etf for item in project.watchlist.items if item.sector_etf}
        for secret, name in ((project.credentials.alpaca_key_id, "APCA_API_KEY_ID"), (project.credentials.alpaca_secret_key, "APCA_API_SECRET_KEY")):
            if secret is not None:
                environment[name] = secret.get_secret_value()
    with patch.dict(os.environ, environment), evaluation_lock(root):
        return _settle(root, settings, manual or {}, services or SettlementServices(root), now)

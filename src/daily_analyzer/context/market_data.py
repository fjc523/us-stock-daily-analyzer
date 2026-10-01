"""上一交易日收盘数据读取与确定性窗口计算。"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any


def as_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if hasattr(value, "date") and not isinstance(value, str):
        candidate = value.date()
        if isinstance(candidate, date):
            return candidate
    return date.fromisoformat(str(value)[:10])


def previous_trading_day(day: date | str) -> date:
    import pandas as pd
    import exchange_calendars as exchange_calendars

    trade_day = as_date(day)
    calendar = exchange_calendars.get_calendar("XNYS")
    candidate = calendar.date_to_session(pd.Timestamp(trade_day), direction="previous")
    if candidate.date() >= trade_day:
        candidate = calendar.previous_session(candidate)
    return candidate.date()


def _bar_date(row: Mapping[str, Any]) -> date | None:
    for key in ("t", "timestamp", "date", "Date", "Datetime", "time"):
        value = row.get(key)
        if value is None:
            continue
        try:
            return as_date(value)
        except (TypeError, ValueError, OverflowError):
            continue
    return None


def _close(row: Mapping[str, Any]) -> float | None:
    for key in ("c", "close", "Close", "adjclose", "Adj Close"):
        value = row.get(key)
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            return number
    return None


def normalize_closes(rows: Sequence[Mapping[str, Any]] | None, end: date) -> dict[date, float]:
    values: dict[date, float] = {}
    for row in rows or []:
        day = _bar_date(row)
        value = _close(row)
        if day is not None and day <= end and value is not None:
            values[day] = value
    return dict(sorted(values.items()))


def _expected_sessions(end: date, count: int) -> list[date]:
    import pandas as pd
    import exchange_calendars as exchange_calendars

    calendar = exchange_calendars.get_calendar("XNYS")
    sessions = calendar.sessions_in_range(
        pd.Timestamp(end - timedelta(days=max(500, count * 3))), pd.Timestamp(end)
    )
    return [session.date() for session in sessions if session.date() <= end][-count:]


def calculate_window_metrics(
    rows: Sequence[Mapping[str, Any]] | None,
    end: date,
    windows: Sequence[int] = (5, 20, 50, 60, 200),
) -> dict[str, Any]:
    """按 XNYS 交易日计算收益与均线，不补齐缺失价格。"""
    closes = normalize_closes(rows, end)
    if not closes:
        status = "数据不足"
        metrics: dict[str, Any] = {}
        for days in windows:
            metrics[f"return_{days}d"] = None
            metrics[f"sma_{days}d"] = None
            metrics[f"status_{days}d"] = status
        return {"as_of": end.isoformat(), "close": None, "status": status, **metrics}
    if max(closes) != end:
        metrics = {}
        for days in windows:
            metrics[f"return_{days}d"] = None
            metrics[f"sma_{days}d"] = None
            metrics[f"status_{days}d"] = "未更新"
        return {
            "as_of": end.isoformat(),
            "close": None,
            "last_bar_date": max(closes).isoformat(),
            "status": "未更新",
            **metrics,
        }

    latest = closes[end]
    output: dict[str, Any] = {
        "as_of": end.isoformat(),
        "close": latest,
        "last_bar_date": end.isoformat(),
        "status": "可用",
    }
    for days in windows:
        expected = _expected_sessions(end, days + 1)
        values = [closes.get(session) for session in expected]
        if len(expected) < days + 1 or any(value is None for value in values):
            output[f"return_{days}d"] = None
            output[f"sma_{days}d"] = None
            output[f"status_{days}d"] = "数据不足"
            continue
        numeric = [float(value) for value in values if value is not None]
        output[f"return_{days}d"] = numeric[-1] / numeric[0] - 1
        output[f"sma_{days}d"] = sum(numeric[-days:]) / days
        output[f"status_{days}d"] = "可用"
    return output


class DailyPriceService:
    """优先 Alpaca SIP 复权日线，失败时回退至 Yahoo auto_adjust。"""

    def __init__(self, alpaca: Any, yahoo: Any) -> None:
        self.alpaca = alpaca
        self.yahoo = yahoo
        self._cache: dict[tuple[str, date], tuple[list[dict[str, Any]], str]] = {}

    def bars(self, symbol: str, end: date) -> tuple[list[dict[str, Any]], str]:
        key = (symbol.upper(), end)
        if key in self._cache:
            return self._cache[key]
        start = end - timedelta(days=500)
        rows: list[dict[str, Any]] = []
        source = "不可用"
        if symbol.upper() == "^VIX":
            rows = self.yahoo.daily_bars(symbol, start, end) or []
            source = "yfinance auto_adjust=True" if rows else "不可用"
        else:
            try:
                response = self.alpaca.daily_bars([symbol], start, end)
                rows = list(response.get(symbol, []))
                if rows:
                    source = "Alpaca SIP adjustment=all"
            except Exception:
                rows = []
            if not rows:
                rows = self.yahoo.daily_bars(symbol, start, end) or []
                if rows:
                    source = "yfinance auto_adjust=True"
        result = (rows, source)
        self._cache[key] = result
        return result

    def metrics(
        self, symbols: Sequence[str], end: date, windows: Sequence[int]
    ) -> dict[str, dict[str, Any]]:
        output = {}
        for symbol in dict.fromkeys(symbols):
            rows, source = self.bars(symbol, end)
            output[symbol] = {
                **calculate_window_metrics(rows, end, windows),
                "source": source,
            }
        return output

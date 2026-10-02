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
    """日线来源按Alpaca、富途、Yahoo顺序降级。"""

    def __init__(self, alpaca: Any, yahoo: Any, futu: Any = None, vix: Any = None) -> None:
        self.alpaca = alpaca
        self.yahoo = yahoo
        self.futu = futu
        self.vix = vix
        self._cache: dict[tuple[str, date], tuple[list[dict[str, Any]], str]] = {}

    def bars(self, symbol: str, end: date) -> tuple[list[dict[str, Any]], str]:
        key = (symbol.upper(), end)
        if key in self._cache:
            return self._cache[key]
        from tradingagents.dataflows.vendor_observer import observed_call
        from tradingagents.dataflows.errors import NoMarketDataError
        start = end - timedelta(days=500)
        rows = []
        source = "不可用"
        if symbol.upper() == "^VIX":
            chain = [] if self.vix is None else [("CBOE VIX", lambda: self.vix.cboe(start, end)), ("FRED VIXCLS", lambda: self.vix.fred(start, end))]
            chain.append(("yfinance auto_adjust=True", lambda: self.yahoo.daily_bars(symbol, start, end)))
        else:
            chain = [("Alpaca SIP adjustment=all", lambda: list(self.alpaca.daily_bars([symbol], start, end).get(symbol, [])))]
            if self.futu is not None:
                chain.append(("Futu QFQ", lambda: self.futu.daily_bars(symbol, start, end).to_dict(orient="records")))
            chain.append(("yfinance auto_adjust=True", lambda: self.yahoo.daily_bars(symbol, start, end)))
        for name, loader in chain:
            def valid_rows():
                values = loader() or []
                if normalize_closes(values, end).get(end) is None:
                    raise NoMarketDataError(symbol, symbol, "没有P日完整日线")
                return values
            try:
                rows = observed_call("vix" if symbol.upper() == "^VIX" else "daily_bars", name, valid_rows, observation_symbol=symbol)
                source = name
                break
            except Exception:
                rows = []
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

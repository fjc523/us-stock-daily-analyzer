"""Yahoo Finance 兜底数据适配器。"""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable


SECTOR_TO_ETF = {
    "Technology": "XLK",
    "Financial Services": "XLF",
    "Energy": "XLE",
    "Healthcare": "XLV",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Industrials": "XLI",
    "Basic Materials": "XLB",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}


def _frame_records(frame: Any) -> list[dict[str, Any]]:
    if frame is None:
        return []
    if hasattr(frame, "empty") and frame.empty:
        return []
    if hasattr(frame, "reset_index"):
        frame = frame.reset_index()
    if hasattr(frame, "to_dict"):
        try:
            return [dict(row) for row in frame.to_dict(orient="records")]
        except (TypeError, ValueError):
            return []
    if isinstance(frame, list):
        return [dict(row) for row in frame if isinstance(row, Mapping)]
    return []


class YahooDataSource:
    """仅作为日线、板块与经济日历的兜底来源。"""

    def __init__(
        self,
        *,
        project_root: str | Path = ".",
        ticker_factory: Callable[[str], Any] | None = None,
        calendar_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.ticker_factory = ticker_factory
        self.calendar_factory = calendar_factory
        self._cache_lock = threading.Lock()

    def _ticker(self, symbol: str) -> Any:
        factory = self.ticker_factory
        if factory is None:
            import yfinance as yf

            factory = yf.Ticker
        return factory(symbol)

    def daily_bars(
        self, symbol: str, start: date | str, end: date | str
    ) -> list[dict[str, Any]] | None:
        try:
            end_date = date.fromisoformat(end) if isinstance(end, str) else end
            start_date = date.fromisoformat(start) if isinstance(start, str) else start
            history = self._ticker(symbol).history(
                start=start_date.isoformat(),
                end=(end_date + timedelta(days=1)).isoformat(),
                auto_adjust=True,
            )
            rows = _frame_records(history)
            return [row for row in rows if _row_date(row) <= end_date]
        except Exception:
            return None

    def sector_etf(self, symbol: str) -> str | None:
        normalized = symbol.strip().upper()
        cache_path = self.project_root / "data" / "cache" / "sector_map.json"
        with self._cache_lock:
            cache = self._read_sector_cache(cache_path)
            cached = cache.get(normalized)
            if isinstance(cached, str):
                return cached or None
            try:
                sector = self._ticker(normalized).info.get("sector")
            except Exception:
                return None
            etf = SECTOR_TO_ETF.get(str(sector)) if sector else None
            if etf is None:
                return None
            cache[normalized] = etf
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(
                    json.dumps(cache, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            except OSError:
                return etf
            return etf

    def economic_calendar(self, start: date | str, end: date | str) -> list[dict[str, Any]] | None:
        try:
            if self.calendar_factory is None:
                import yfinance as yf

                factory = yf.Calendars
            else:
                factory = self.calendar_factory
            calendar = factory(start=str(start), end=str(end))
            frame = calendar.get_economic_events_calendar()
            rows = _frame_records(frame)
            if not rows:
                return []
            country_column = next(
                (key for key in ("country", "countryCode", "country_code") if key in rows[0]),
                None,
            )
            if country_column:
                rows = [row for row in rows if str(row.get(country_column, "")).upper() in {"US", "USA", "UNITED STATES"}]
            return rows
        except Exception:
            return None

    @staticmethod
    def _read_sector_cache(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}


def _row_date(row: Mapping[str, Any]) -> date:
    for key in ("Date", "Datetime", "date", "timestamp", "time"):
        value = row.get(key)
        if value is None:
            continue
        if hasattr(value, "date"):
            return value.date()
        text = str(value)
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            continue
    return date.min

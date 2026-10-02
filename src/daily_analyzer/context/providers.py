"""市场环境、板块强弱、扩展时段与经济数据提供器。"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .base import ContextBlock, ContextManager, ProviderRegistry, ProviderServices
from .market_data import as_date, previous_trading_day, normalize_closes, _expected_sessions

EASTERN = ZoneInfo("America/New_York")
MARKET_SYMBOLS = ("SPY", "QQQ", "IWM", "DIA")
SECTOR_ETFS = ("XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC")
BENCHMARK_NAMES = {"XLK": "科技", "XLF": "金融", "XLE": "能源", "XLV": "医疗", "XLY": "消费可选",
                   "XLP": "必需消费", "XLI": "工业", "XLB": "原材料", "XLU": "公用事业", "XLRE": "房地产",
                   "XLC": "通信服务", "SMH": "半导体", "SOXX": "半导体", "QQQ": "纳斯达克100",
                   "SPY": "标普500", "DIA": "道琼斯"}
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
MACRO_TITLE_RE = re.compile(
    r"^USA (?P<name>.+?) (?P<actual>\S+) Vs (?P<est>\S+) Est\.(?:; (?P<prior>\S+) Prior)?"
)


def _value(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, Mapping) else getattr(obj, key, default)


def _items(batch: Any) -> list[Any]:
    value = _value(batch, "items", []) or []
    return list(value)


def _trade_date(batch: Any) -> date:
    value = _value(batch, "trade_date") or _value(batch, "date")
    if value is None:
        raise ValueError("上下文批次缺少 trade_date")
    return as_date(value)


def _price_end(batch: Any) -> date:
    value = _value(batch, "price_data_end_date") or _value(batch, "previous_session_date")
    return as_date(value) if value is not None else previous_trading_day(_trade_date(batch))


def _symbol(item: Any) -> str:
    value = _value(item, "analysis_symbol") or _value(item, "symbol") or ""
    return str(value).strip().upper()


def _item_type(item: Any) -> str:
    return str(_value(item, "type", "stock"))


def _cutoff_datetime(value: datetime | date | str) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, date):
        result = datetime.combine(value, time(8, 31), EASTERN)
    else:
        text = str(value)
        result = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if result.tzinfo is None:
            result = result.replace(tzinfo=EASTERN)
    return result.astimezone(EASTERN)


def _parse_datetime(value: Any, default_zone: ZoneInfo = EASTERN) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif value is None:
        return None
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=default_zone)
    return parsed.astimezone(EASTERN)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _pct_return(metric: Mapping[str, Any], days: int) -> float | None:
    value = metric.get(f"return_{days}d")
    return _number(value)


def _format_pct(value: Any) -> str:
    number = _number(value)
    return "—" if number is None else f"{number * 100:+.2f}%"


def _format_number(value: Any) -> str:
    number = _number(value)
    return "—" if number is None else f"{number:.2f}"


def _relative_label(value: bool | None) -> str:
    return "上方" if value is True else "下方" if value is False else "数据不足"


def _source_list(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value and value != "不可用"))


class MarketRegimeProvider:
    name = "market_regime"
    scope = "batch"

    def __init__(self, services: ProviderServices) -> None:
        self.services = services
        self.metrics: dict[str, dict[str, Any]] = {}
        self.end: date | None = None

    def prepare(self, batch: Any) -> None:
        self.end = _price_end(batch)
        self.metrics = self.services.prices.metrics(
            [*MARKET_SYMBOLS, "^VIX"], self.end, (5, 20, 50, 200)
        )

    def build(self, item: Any, cutoff: datetime | date | str) -> ContextBlock:
        del item, cutoff
        if self.end is None:
            raise ValueError("market_regime 尚未准备")
        table: list[dict[str, Any]] = []
        sources: list[str] = []
        for symbol in MARKET_SYMBOLS:
            metric = self.metrics.get(symbol, {})
            sources.append(str(metric.get("source", "")))
            close = _number(metric.get("close"))
            averages = {
                days: _number(metric.get(f"sma_{days}d"))
                for days in (20, 50, 200)
            }
            table.append(
                {
                    "symbol": symbol,
                    "close": close,
                    "above_sma_20d": close > averages[20] if close is not None and averages[20] is not None else None,
                    "above_sma_50d": close > averages[50] if close is not None and averages[50] is not None else None,
                    "above_sma_200d": close > averages[200] if close is not None and averages[200] is not None else None,
                    "sma_20d": averages[20],
                    "sma_50d": averages[50],
                    "sma_200d": averages[200],
                    "return_5d": _pct_return(metric, 5),
                    "return_20d": _pct_return(metric, 20),
                    "status": metric.get("status", "数据不足"),
                }
            )
        vix = self.metrics.get("^VIX", {})
        sources.append(str(vix.get("source", "")))
        trend_inputs = [
            (self.metrics.get("SPY", {}).get("close"), self.metrics.get("SPY", {}).get("sma_50d")),
            (self.metrics.get("SPY", {}).get("close"), self.metrics.get("SPY", {}).get("sma_200d")),
            (self.metrics.get("QQQ", {}).get("close"), self.metrics.get("QQQ", {}).get("sma_50d")),
            (self.metrics.get("QQQ", {}).get("close"), self.metrics.get("QQQ", {}).get("sma_200d")),
        ]
        vix_close = _number(vix.get("close"))
        vix_change = _pct_return(vix, 5)
        if any(_number(close) is None or _number(average) is None for close, average in trend_inputs) or vix_close is None or vix_change is None:
            label = "数据不足"
            trend_score = None
            vix_spike = None
        else:
            trend_score = sum(float(close) > float(average) for close, average in trend_inputs)
            vix_spike = vix_change > 0.20
            if trend_score >= 3 and vix_close < 20 and not vix_spike:
                label = "偏强"
            elif trend_score <= 1 or vix_close > 25 or (vix_spike and trend_score <= 2):
                label = "偏弱"
            else:
                label = "中性"
        markdown = [f"市场环境：**{label}**"]
        markdown.append("| 指数 | 收盘 | 相对20日线 | 相对50日线 | 相对200日线 | 5日收益 | 20日收益 |")
        markdown.append("|---|---:|---|---|---|---:|---:|")
        for row in table:
            markdown.append(
                f"| {row['symbol']} | {_format_number(row['close'])} | "
                f"{_relative_label(row['above_sma_20d'])} | {_relative_label(row['above_sma_50d'])} | "
                f"{_relative_label(row['above_sma_200d'])} | {_format_pct(row['return_5d'])} | "
                f"{_format_pct(row['return_20d'])} |"
            )
            if row["status"] != "可用":
                markdown.append(f"\n{row['symbol']}：{row['status']}。")
        markdown.append(
            f"\nVIX 收盘 {_format_number(vix_close)}；5日变化 {_format_pct(vix_change)}；"
            f"趋势分 {trend_score if trend_score is not None else '—'}；"
            f"VIX 急升 {'是' if vix_spike else '否' if vix_spike is not None else '—'}。"
        )
        data = {
            "as_of": self.end.isoformat(),
            "label": label,
            "trend_score": trend_score,
            "vix_close": vix_close,
            "vix_return_5d": vix_change,
            "vix_spike": vix_spike,
            "indices": table,
        }
        return ContextBlock(self.name, "\n".join(markdown), data, self.end, _source_list(sources))


class SectorStrengthProvider:
    name = "sector_strength"
    scope = "ticker"

    def __init__(self, services: ProviderServices) -> None:
        self.services = services
        self.end: date | None = None
        self.metrics: dict[str, dict[str, Any]] = {}
        self.stock_sector_etfs: dict[str, tuple[str | None, bool]] = {}
        self.benchmarks: dict[str, dict[str, Any]] = {}
        self.index_memberships: dict[str, dict[str, Any]] = {}
        self.ranking: list[dict[str, Any]] = []
        self.sources: tuple[str, ...] = ()
        self._sector_source_used = False

    def prepare(self, batch: Any) -> None:
        self.end = _price_end(batch)
        symbols = [*SECTOR_ETFS, "SPY"]
        unresolved = []
        stock_symbols = []
        for item in _items(batch):
            if _item_type(item) != "stock":
                continue
            symbol = _symbol(item)
            if not symbol:
                continue
            symbols.append(symbol)
            stock_symbols.append(symbol)
            override = _value(item, "sector_etf")
            if override:
                sector_etf = str(override).strip().upper()
                self.stock_sector_etfs[symbol] = (sector_etf, True)
                symbols.append(sector_etf)
            else:
                self._sector_source_used = True
                sector_etf = self.services.yahoo.sector_etf(symbol)
                self.stock_sector_etfs[symbol] = (sector_etf, False)
                if sector_etf:
                    symbols.append(sector_etf)
            sector_etf, manual = self.stock_sector_etfs[symbol]
            if sector_etf:
                self.benchmarks[symbol] = {"benchmark_symbol": sector_etf, "benchmark_kind": "sector",
                                           "benchmark_reason": "手工指定板块" if manual else "Yahoo板块映射"}
            else:
                unresolved.append(symbol)
        if stock_symbols:
            if str(_value(batch, "mode", "live")) == "backfill":
                self.index_memberships = {s: {"benchmark_symbol": "SPY", "benchmark_kind": "default", "index_symbol": None,
                                               "benchmark_reason": "回放未核验历史指数成员，默认SPY"} for s in stock_symbols}
            else:
                self.index_memberships = self.services.index_metadata.lookup(stock_symbols)
            symbols.extend(row.get("index_symbol") or "SPY" for row in self.index_memberships.values())
            for symbol in unresolved:
                self.benchmarks[symbol] = self.index_memberships[symbol]
                metadata = self.benchmarks[symbol]
                symbols.append(metadata["benchmark_symbol"])
                if metadata["benchmark_kind"] == "sector":
                    self.stock_sector_etfs[symbol] = (metadata["benchmark_symbol"], False)
        self.metrics = self.services.prices.metrics(list(dict.fromkeys(symbols)), self.end, (5, 20, 60))
        sources = [str(metric.get("source", "")) for metric in self.metrics.values()]
        if self._sector_source_used:
            sources.append("Yahoo Finance info.sector 映射")
        sources.extend(str(row.get("metadata_source", "")) for row in self.index_memberships.values())
        self.sources = _source_list(sources)
        self.ranking = self._build_ranking()

    def _build_ranking(self) -> list[dict[str, Any]]:
        spy = self.metrics.get("SPY", {})
        rows = []
        for symbol in SECTOR_ETFS:
            metric = self.metrics.get(symbol, {})
            excess = {
                days: (
                    _pct_return(metric, days) - _pct_return(spy, days)
                    if _pct_return(metric, days) is not None and _pct_return(spy, days) is not None
                    else None
                )
                for days in (5, 20, 60)
            }
            rows.append(
                {
                    "symbol": symbol,
                    "excess_return_5d": excess[5],
                    "excess_return_20d": excess[20],
                    "excess_return_60d": excess[60],
                    "status": metric.get("status", "数据不足"),
                    "rank": None,
                }
            )
        available = [row for row in rows if row["excess_return_20d"] is not None]
        unavailable = [row for row in rows if row["excess_return_20d"] is None]
        available.sort(
            key=lambda row: (
                -row["excess_return_20d"],
                -(row["excess_return_60d"] if row["excess_return_60d"] is not None else float("-inf")),
                row["symbol"],
            )
        )
        for index, row in enumerate(available, start=1):
            row["rank"] = index
        unavailable.sort(key=lambda row: row["symbol"])
        return available + unavailable

    def build(self, item: Any, cutoff: datetime | date | str) -> ContextBlock:
        del cutoff
        if self.end is None:
            raise ValueError("sector_strength 尚未准备")
        lines = ["| 名次 | 行业 ETF | 相对 SPY 5日 | 20日 | 60日 | 状态 |", "|---:|---|---:|---:|---:|---|"]
        for row in self.ranking:
            rank = row["rank"] if row["rank"] is not None else "—"
            lines.append(
                f"| {rank} | {row['symbol']} | {_format_pct(row['excess_return_5d'])} | "
                f"{_format_pct(row['excess_return_20d'])} | {_format_pct(row['excess_return_60d'])} | {row['status']} |"
            )
        data: dict[str, Any] = {"as_of": self.end.isoformat(), "ranking": self.ranking}
        if _item_type(item) == "stock":
            symbol = _symbol(item)
            sector_etf, manual = self.stock_sector_etfs.get(symbol, (None, False))
            metadata = self.benchmarks[symbol]
            benchmark_symbol = metadata["benchmark_symbol"]
            stock = self.metrics.get(symbol, {})
            benchmark = self.metrics.get(benchmark_symbol, {})
            spy = self.metrics.get("SPY", {})
            relative = {}
            for days in (5, 20, 60):
                stock_return = _pct_return(stock, days)
                for prefix, metric in (("benchmark", benchmark), ("spy", spy)):
                    benchmark_return = _pct_return(metric, days)
                    relative[f"{prefix}_excess_{days}d"] = (
                        stock_return - benchmark_return if stock_return is not None and benchmark_return is not None else None
                    )
                if sector_etf:
                    relative[f"sector_excess_{days}d"] = relative[f"benchmark_excess_{days}d"]
            sector_rank = next((row["rank"] for row in self.ranking if row["symbol"] == sector_etf), None) if sector_etf else None
            lines.extend([
                "", f"{symbol} 比较基准：{benchmark_symbol}（{metadata['benchmark_reason']}）。",
                "相对基准：" + "；".join(f"{days}日 {_format_pct(relative[f'benchmark_excess_{days}d'])}" for days in (5, 20, 60)),
                "相对 SPY：" + "；".join(f"{days}日 {_format_pct(relative[f'spy_excess_{days}d'])}" for days in (5, 20, 60)),
            ])
            if not sector_etf:
                lines.append("未能识别所属板块，以上为指数基准比较。")
            if metadata.get("membership_as_of"):
                lines.append(f"发行方持仓名单截至 {metadata['membership_as_of']}。")
            data.update({"symbol": symbol, "sector_etf": sector_etf, "manual_override": manual,
                         "sector_rank": sector_rank, **metadata, **relative})
            comparisons = []
            if sector_etf:
                comparisons.append(self._comparison(symbol, sector_etf, "sector", metadata["benchmark_reason"]))
            index = self.index_memberships[symbol]
            index_symbol = index.get("index_symbol") or "SPY"
            index_kind = "index" if index.get("index_symbol") else "default"
            index_reason = (f"指数成员已核验；名单截至{index.get('membership_as_of', '未知')}"
                            if index_kind == "index" else index["benchmark_reason"])
            if index_kind == "index" and index.get("index_warning"):
                index_reason += "；" + index["index_warning"]
            if sector_etf and index_kind == "default":
                index_reason = index_reason.removeprefix("行业未识别；")
            comparisons.append(self._comparison(symbol, index_symbol, index_kind, index_reason))
            data["comparisons"] = comparisons
            for comparison in comparisons:
                lines.append(f"{comparison['name']}（{comparison['symbol']}）：" + "；".join(
                    f"{days}日 {_format_pct(comparison[f'excess_{days}d'])}" for days in (5, 20, 60)))
        return ContextBlock(self.name, "\n".join(lines), data, self.end, self.sources)

    def _comparison(self, symbol: str, benchmark: str, kind: str, reason: str) -> dict[str, Any]:
        """图表复用批次缓存，共同首日归一为100，不补造行情。"""
        stock_metric, benchmark_metric = self.metrics.get(symbol, {}), self.metrics.get(benchmark, {})
        result = {"symbol": benchmark, "kind": kind, "name": BENCHMARK_NAMES.get(benchmark, benchmark), "reason": reason}
        for days in (5, 20, 60):
            stock_return, baseline_return = _pct_return(stock_metric, days), _pct_return(benchmark_metric, days)
            result[f"excess_{days}d"] = stock_return - baseline_return if stock_return is not None and baseline_return is not None else None
        stock_rows, stock_source = self.services.prices.bars(symbol, self.end)
        benchmark_rows, benchmark_source = self.services.prices.bars(benchmark, self.end)
        stock, baseline = normalize_closes(stock_rows, self.end), normalize_closes(benchmark_rows, self.end)
        dates = [d for d in _expected_sessions(self.end, 61) if stock.get(d, 0) > 0 and baseline.get(d, 0) > 0]
        result["chart"] = None
        if len(dates) >= 2 and dates[-1] == self.end:
            result["chart"] = {"dates": [d.isoformat() for d in dates],
                               "stock": [stock[d] / stock[dates[0]] * 100 for d in dates],
                               "benchmark": [baseline[d] / baseline[dates[0]] * 100 for d in dates],
                               "sources": [stock_source, benchmark_source]}
        return result


class ExtendedHoursProvider:
    name = "extended_hours"
    scope = "ticker"

    def __init__(self, services: ProviderServices) -> None:
        self.services = services
        self.batch: Any = None
        self.futu_prepared = False

    def prepare(self, batch: Any) -> None:
        self.batch = batch
        if str(_value(batch, "mode", "live")) == "backfill" or not self.services.futu_enabled:
            return
        symbols = [_symbol(item) for item in _items(batch)]
        symbols.extend(MARKET_SYMBOLS)
        symbols.extend(SECTOR_ETFS)
        self.services.futu.start_batch(symbols)
        self.futu_prepared = True

    def build(self, item: Any, cutoff: datetime | date | str) -> ContextBlock:
        if self.batch is None:
            raise ValueError("extended_hours 尚未准备")
        trade_day = _trade_date(self.batch)
        price_end = _price_end(self.batch)
        as_of = _cutoff_datetime(cutoff)
        symbols = list(dict.fromkeys([_symbol(item), *MARKET_SYMBOLS]))
        mode = str(_value(self.batch, "mode", "live"))
        if mode == "backfill":
            payload, sources = self._backfill(symbols, trade_day, as_of)
        else:
            payload, sources = self._live(symbols, trade_day, price_end, as_of)
        futu_warning = getattr(self.services.futu, "warning", None)
        if futu_warning:
            payload["warnings"] = [str(futu_warning)]
        spy_change = _number(payload.get("SPY", {}).get("pre", {}).get("change_pct"))
        target_symbol = _symbol(item)
        target_change = _number(payload.get(target_symbol, {}).get("pre", {}).get("change_pct"))
        relative = target_change - spy_change if target_change is not None and spy_change is not None else None
        payload["premarket_relative_to_spy_pct"] = relative
        lines = ["| 标的 | 时段 | 最新价 | 相对 P 收盘 | 成交量 | 最高 | 最低 | 报价时间 | 来源 | 状态 |", "|---|---|---:|---:|---:|---:|---:|---|---|---|"]
        for symbol in symbols:
            for session, label in (("after", "上一交易日盘后"), ("overnight", "夜盘"), ("pre", "盘前")):
                segment = payload.get(symbol, {}).get(session, {})
                status = segment.get("status") or "数据不可用"
                if segment.get("warning"):
                    status = f"{status}（{segment['warning']}）"
                lines.append(
                    f"| {symbol} | {label} | {_format_number(segment.get('price'))} | "
                    f"{_format_pct(_number(segment.get('change_pct')) / 100 if _number(segment.get('change_pct')) is not None else None)} | "
                    f"{segment.get('volume') if segment.get('volume') is not None else '—'} | "
                    f"{_format_number(segment.get('high'))} | {_format_number(segment.get('low'))} | "
                    f"{segment.get('quote_time') or '—'} | {segment.get('source') or '—'} | "
                    f"{status} |"
                )
        if futu_warning:
            lines.insert(0, f"数据源说明：{futu_warning}。")
        lines.append(f"\n{target_symbol} 相对 SPY 的盘前涨跌幅差：{_format_pct(relative / 100 if relative is not None else None)}。")
        return ContextBlock(self.name, "\n".join(lines), payload, as_of, _source_list(sources))

    def _live(
        self, symbols: list[str], trade_day: date, price_end: date, cutoff: datetime
    ) -> tuple[dict[str, Any], list[str]]:
        source_names: list[str] = []
        futu = self.services.futu
        subscribed = dict(futu.get_quotes(symbols) or {})
        candidates: dict[str, dict[str, list[dict[str, Any]]]] = {
            symbol: {segment: [] for segment in ("after", "overnight", "pre")}
            for symbol in symbols
        }

        def add_futu_rows(rows: Mapping[str, Mapping[str, Any]], source: str) -> None:
            for symbol in symbols:
                row = rows.get(futu_symbol(symbol))
                if row is None:
                    continue
                for segment in ("after", "overnight", "pre"):
                    parsed = _futu_segment(row, segment, trade_day, price_end, cutoff)
                    if parsed is not None:
                        parsed["source"] = source
                        candidates[symbol][segment].append(parsed)

        if futu.mode == "subscription":
            add_futu_rows(subscribed, "富途订阅报价")
            needs_snapshot = [
                symbol
                for symbol in symbols
                if any(
                    not any(entry["status"] == "可用" for entry in candidates[symbol][segment])
                    for segment in ("after", "overnight", "pre")
                )
            ]
            if needs_snapshot:
                add_futu_rows(futu.get_snapshots(needs_snapshot) or {}, "富途快照")
        elif futu.mode == "snapshot":
            add_futu_rows(subscribed, "富途快照")

        missing_overnight = [
            symbol
            for symbol in symbols
            if not any(entry["status"] == "可用" for entry in candidates[symbol]["overnight"])
        ]
        missing_premarket = [
            symbol
            for symbol in symbols
            if not any(entry["status"] == "可用" for entry in candidates[symbol]["pre"])
        ]
        try:
            overnight = _alpaca_snapshots(self.services.alpaca, missing_overnight, "overnight")
        except Exception:
            overnight = {}
        try:
            premarket = _alpaca_snapshots(self.services.alpaca, missing_premarket, "iex")
        except Exception:
            premarket = {}

        segments: dict[str, dict[str, Any]] = {symbol: {} for symbol in symbols}
        for symbol in symbols:
            close = self._previous_close(symbol, price_end)
            for segment in ("after", "overnight", "pre"):
                entries = candidates[symbol][segment]
                raw = next((entry for entry in entries if entry["status"] == "可用"), None)
                if raw is None and segment == "overnight":
                    raw = _alpaca_segment(overnight.get(symbol), "Alpaca feed=overnight", trade_day, price_end, cutoff)
                elif raw is None and segment == "pre":
                    raw = _alpaca_segment(premarket.get(symbol), "Alpaca feed=iex", trade_day, price_end, cutoff)
                    if raw is not None:
                        raw["warning"] = "IEX 覆盖不完整"
                if raw is None and entries:
                    raw = entries[0]
                if raw is None:
                    raw = _empty_segment("数据不可用")
                if close is None:
                    close = _number(raw.get("previous_close"))
                    if close is None:
                        close = next(
                            (
                                _number(candidate.get("previous_close"))
                                for entries in candidates[symbol].values()
                                for candidate in entries
                                if _number(candidate.get("previous_close")) is not None
                            ),
                            None,
                        )
                raw["change_pct"] = _change_pct(raw.get("price"), close) if raw.get("status") not in {"非本时段数据", "过期"} else None
                segments[symbol][segment] = raw
                if raw.get("source"):
                    source_names.append(raw["source"])
        return segments, source_names

    def _backfill(
        self, symbols: list[str], trade_day: date, cutoff: datetime
    ) -> tuple[dict[str, Any], list[str]]:
        start = datetime.combine(trade_day, time(4, 0), EASTERN)
        end = min(cutoff, datetime.combine(trade_day, time(8, 31), EASTERN))
        response = self.services.alpaca.iex_minute_bars(symbols, start, end)
        payload: dict[str, Any] = {}
        for symbol in symbols:
            rows = response.get(symbol, [])
            bars = []
            for row in rows:
                timestamp = _parse_datetime(_row_get(row, "t", "timestamp"), timezone.utc)
                if timestamp is None or timestamp.date() != trade_day:
                    continue
                if not (time(4, 0) <= timestamp.timetz().replace(tzinfo=None) < time(8, 31)):
                    continue
                bars.append((timestamp, row))
            bars.sort(key=lambda pair: pair[0])
            if bars:
                last_time, last = bars[-1]
                prices = [_number(_row_get(row, "c", "close")) for _, row in bars]
                prices = [value for value in prices if value is not None]
                volumes = [_number(_row_get(row, "v", "volume")) for _, row in bars]
                volumes = [value for value in volumes if value is not None]
                pre = {
                    "price": _number(_row_get(last, "c", "close")),
                    "volume": sum(volumes) if volumes else None,
                    "high": max((_number(_row_get(row, "h", "high")) for _, row in bars if _number(_row_get(row, "h", "high")) is not None), default=None),
                    "low": min((_number(_row_get(row, "l", "low")) for _, row in bars if _number(_row_get(row, "l", "low")) is not None), default=None),
                    "quote_time": last_time.isoformat(timespec="seconds"),
                    "source": "Alpaca feed=iex 历史分钟线",
                    "status": "可用" if last_time.date() == trade_day else "非本时段数据",
                    "session_verified": True,
                    "warning": "IEX 覆盖不完整",
                }
            else:
                pre = _empty_segment("数据不可用")
            payload[symbol] = {
                "after": _empty_segment("回放不可用"),
                "overnight": _empty_segment("回放不可用"),
                "pre": pre,
            }
        end_day = _price_end(self.batch)
        for symbol in symbols:
            close = self._previous_close(symbol, end_day)
            payload[symbol]["pre"]["change_pct"] = _change_pct(payload[symbol]["pre"].get("price"), close)
        return payload, ["Alpaca feed=iex 历史分钟线"]

    def _previous_close(self, symbol: str, end: date) -> float | None:
        rows, _source = self.services.prices.bars(symbol, end)
        from .market_data import calculate_window_metrics

        return _number(calculate_window_metrics(rows, end, (1,)).get("close"))


class MacroReleasesProvider:
    name = "macro_releases"
    scope = "ticker"

    def __init__(self, services: ProviderServices) -> None:
        self.services = services
        self.batch: Any = None

    def prepare(self, batch: Any) -> None:
        self.batch = batch

    def build(self, item: Any, cutoff: datetime | date | str) -> ContextBlock:
        del item
        if self.batch is None:
            raise ValueError("macro_releases 尚未准备")
        trade_day = _trade_date(self.batch)
        as_of = _cutoff_datetime(cutoff)
        start = datetime.combine(trade_day, time.min, EASTERN)
        result = self.services.alpaca.news(None, start, as_of, limit=None, max_pages=20)
        articles = list(result.get("articles", []))
        start_utc = start.astimezone(timezone.utc)
        end_utc = as_of.astimezone(timezone.utc)
        articles = [
            article
            for article in articles
            if (created := _created_at(article)) is not None
            and start_utc <= created <= end_utc
        ]
        truncated = bool(result.get("truncated", False))
        articles.sort(key=lambda article: _created_at(article) or datetime.min.replace(tzinfo=timezone.utc))
        releases: list[dict[str, Any]] = []
        revised: list[dict[str, Any]] = []
        unparsed: list[dict[str, Any]] = []
        post_cutoff_revisions: list[str] = []
        for article in articles:
            title = _headline(article)
            if bool(_row_get(article, "revised_after_cutoff")):
                post_cutoff_revisions.append(title)
            if "Prior Revised" in title:
                revised.append(
                    {
                        "title": title,
                        "created_at": _iso_created(article),
                        "revised_after_cutoff": bool(_row_get(article, "revised_after_cutoff")),
                    }
                )
                continue
            match = MACRO_TITLE_RE.match(title)
            if match:
                releases.append(
                    {
                        "name": match.group("name"),
                        "actual": match.group("actual"),
                        "estimate": match.group("est"),
                        "prior": match.group("prior"),
                        "title": title,
                        "created_at": _iso_created(article),
                        "revised_after_cutoff": bool(_row_get(article, "revised_after_cutoff")),
                    }
                )
            elif title.startswith("USA "):
                unparsed.append(
                    {
                        "title": title,
                        "created_at": _iso_created(article),
                        "revised_after_cutoff": bool(_row_get(article, "revised_after_cutoff")),
                    }
                )
        market_news = [
            {
                "title": _headline(article),
                "created_at": _iso_created(article),
                "revised_after_cutoff": bool(_row_get(article, "revised_after_cutoff")),
            }
            for article in reversed(articles[-20:])
        ]
        calendar_rows = self.services.yahoo.economic_calendar(trade_day, trade_day)
        upcoming = _upcoming_events(calendar_rows or [], trade_day, as_of)

        lines = ["#### 今日经济数据"]
        if releases:
            lines.extend(["| 指标 | 实际 | 预期 | 前值 | 发布时间 |", "|---|---:|---:|---:|---|"])
            for release in releases:
                lines.append(
                    f"| {release['name']} | {release['actual']} | {release['estimate']} | "
                    f"{release['prior'] or '—'} | {release['created_at']} |"
                )
        else:
            lines.append(f"截至 {as_of.strftime('%H:%M:%S')} ET 未见当日经济数据标题。")
        if revised:
            lines.extend(["", "#### 前值修订"])
            lines.extend(f"- {entry['created_at']}：{entry['title']}" for entry in revised)
        if unparsed:
            lines.extend(["", "#### 未解析经济类标题"])
            lines.extend(f"- {entry['created_at']}：{entry['title']}" for entry in unparsed)
        if truncated:
            lines.extend(["", "标题已截断（达到新闻翻页上限）。"])
        if post_cutoff_revisions:
            lines.extend(["", "内容可能已在截止后修订。"])
        if upcoming:
            lines.extend(["", "#### 今日稍后发布的美国经济数据"])
            lines.extend(f"- {event}" for event in upcoming)
        lines.extend(["", "#### 市场要闻（最新20条）"])
        if market_news:
            lines.extend(f"- {entry['created_at']}：{entry['title']}" for entry in market_news)
        else:
            lines.append("暂无市场要闻标题。")
        data = {
            "trade_date": trade_day.isoformat(),
            "as_of": as_of.isoformat(),
            "releases": releases,
            "prior_revised": revised,
            "unparsed_economic_titles": unparsed,
            "market_news": market_news,
            "upcoming_events": upcoming,
            "truncated": truncated,
            "post_cutoff_revisions": post_cutoff_revisions,
        }
        return ContextBlock(self.name, "\n".join(lines), data, as_of, ("Alpaca Benzinga 新闻", *(["Yahoo Finance 经济日历"] if upcoming else [])))


def _row_get(row: Any, *keys: str) -> Any:
    for key in keys:
        value = row.get(key) if isinstance(row, Mapping) else getattr(row, key, None)
        if value is not None:
            return value
    return None


def futu_symbol(symbol: str) -> str:
    return "US." + symbol.strip().upper().replace("-", ".")


def _empty_segment(status: str) -> dict[str, Any]:
    return {
        "price": None,
        "change_pct": None,
        "volume": None,
        "high": None,
        "low": None,
        "quote_time": None,
        "source": None,
        "status": status,
        "session_verified": False,
    }


def _change_pct(price: Any, close: Any) -> float | None:
    price_value, close_value = _number(price), _number(close)
    if price_value is None or close_value in {None, 0.0}:
        return None
    return (price_value / close_value - 1) * 100


def _session_bounds(session: str, trade_day: date, price_end: date) -> tuple[datetime, datetime]:
    if session == "after":
        return datetime.combine(price_end, time(16), EASTERN), datetime.combine(price_end, time(20), EASTERN)
    if session == "overnight":
        return datetime.combine(trade_day - timedelta(days=1), time(20), EASTERN), datetime.combine(trade_day, time(4), EASTERN)
    return datetime.combine(trade_day, time(4), EASTERN), datetime.combine(trade_day, time(9, 30), EASTERN)


def _futu_segment(
    row: Mapping[str, Any] | None,
    segment: str,
    trade_day: date,
    price_end: date,
    cutoff: datetime,
) -> dict[str, Any] | None:
    if row is None:
        return None
    names = {"pre": "pre", "after": "after", "overnight": "overnight"}
    prefix = names[segment]
    price = _number(row.get(f"{prefix}_price"))
    if price is None:
        return None
    segment_timestamp = row.get(f"{prefix}_update_time")
    source_update_time = row.get("update_time")
    quote_time = _parse_datetime(segment_timestamp)
    verified = quote_time is not None
    if quote_time is None and segment == "pre":
        quote_time = _parse_datetime(source_update_time)
    start, end = _session_bounds(segment, trade_day, price_end)
    status = "可用"
    if quote_time is None:
        status = "时段未核验（无分时段时间）"
    elif not start <= quote_time < end:
        status = "非本时段数据"
    elif segment == "pre" and time(4) <= cutoff.timetz().replace(tzinfo=None) < time(9, 30):
        if (cutoff - quote_time).total_seconds() > 30 * 60:
            status = "过期"
    return {
        "price": price,
        "previous_close": _number(row.get("prev_close_price")),
        "volume": _number(row.get(f"{prefix}_volume")),
        "high": _number(row.get(f"{prefix}_high_price")),
        "low": _number(row.get(f"{prefix}_low_price")),
        "quote_time": quote_time.isoformat(timespec="seconds") if quote_time is not None else None,
        "source_update_time": source_update_time,
        "source": "富途",
        "status": status,
        "session_verified": verified,
    }


def _snapshot_component(snapshot: Any, name: str) -> Any:
    if not isinstance(snapshot, Mapping):
        return None
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    return snapshot.get(name) or snapshot.get(snake)


def _alpaca_segment(
    snapshot: Any,
    source: str,
    trade_day: date,
    price_end: date,
    cutoff: datetime,
) -> dict[str, Any] | None:
    if not isinstance(snapshot, Mapping):
        return None
    trade = _snapshot_component(snapshot, "latestTrade") or _snapshot_component(snapshot, "latest_trade")
    if not isinstance(trade, Mapping):
        trade = snapshot
    price = _number(_row_get(trade, "p", "price"))
    if price is None:
        return None
    timestamp = _parse_datetime(_row_get(trade, "t", "timestamp"), timezone.utc)
    if timestamp is None:
        timestamp = _parse_datetime(_row_get(snapshot, "updated_at", "as_of"), timezone.utc)
    if timestamp is None:
        return None
    segment = "overnight" if "overnight" in source else "pre"
    start, end = _session_bounds(segment, trade_day, price_end)
    status = "可用" if start <= timestamp < end else "非本时段数据"
    if segment == "pre" and status == "可用" and time(4) <= cutoff.timetz().replace(tzinfo=None) < time(9, 30) and (cutoff - timestamp).total_seconds() > 30 * 60:
        status = "过期"
    daily = _snapshot_component(snapshot, "dailyBar") or _snapshot_component(snapshot, "daily_bar") or {}
    return {
        "price": price,
        "previous_close": _number(_row_get(_snapshot_component(snapshot, "prevDailyBar") or _snapshot_component(snapshot, "prev_daily_bar") or {}, "c", "close")),
        "volume": _number(_row_get(trade, "s", "size")) or _number(_row_get(daily, "v", "volume")),
        "high": _number(_row_get(daily, "h", "high")),
        "low": _number(_row_get(daily, "l", "low")),
        "quote_time": timestamp.isoformat(timespec="seconds"),
        "source": source,
        "status": status,
        "session_verified": True,
        "warning": "IEX 覆盖不完整" if "iex" in source else None,
    }


def _alpaca_snapshots(alpaca: Any, symbols: Sequence[str], feed: str) -> dict[str, Any]:
    return alpaca.snapshots(list(symbols), feed) if symbols else {}


def _created_at(article: Any) -> datetime | None:
    value = _row_get(article, "created_at")
    if value is None:
        return None
    parsed = _parse_datetime(value, timezone.utc)
    return parsed.astimezone(timezone.utc) if parsed else None


def _iso_created(article: Any) -> str | None:
    value = _created_at(article)
    return value.isoformat(timespec="seconds") if value else None


def _headline(article: Any) -> str:
    return str(_row_get(article, "headline", "title") or "").strip()


def _upcoming_events(rows: Sequence[Mapping[str, Any]], trade_day: date, cutoff: datetime) -> list[str]:
    output = []
    for row in rows:
        event_time = None
        for key in ("start_time", "event_time", "date", "datetime", "timestamp"):
            event_time = _parse_datetime(row.get(key), EASTERN)
            if event_time is not None:
                break
        if event_time is None or event_time.date() != trade_day or event_time <= cutoff:
            continue
        title = _row_get(row, "event", "name", "title", "event_name")
        if title:
            output.append(f"{event_time.strftime('%H:%M ET')} {title}")
    return output


PROVIDER_CLASSES = {
    "market_regime": MarketRegimeProvider,
    "sector_strength": SectorStrengthProvider,
    "extended_hours": ExtendedHoursProvider,
    "macro_releases": MacroReleasesProvider,
}


def make_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    for name, provider_class in PROVIDER_CLASSES.items():
        registry.register(name, lambda services, cls=provider_class: cls(services))
    return registry


def create_context_manager(
    provider_names: Sequence[str],
    *,
    services: ProviderServices | None = None,
    registry: ProviderRegistry | None = None,
) -> ContextManager:
    return ContextManager(provider_names, services=services, registry=registry)

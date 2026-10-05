from __future__ import annotations

import sys
import types
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import exchange_calendars
import pandas as pd
import pytest

from daily_analyzer.config import WatchlistItem
from daily_analyzer.context.base import (
    ContextBlock,
    ContextManager,
    ProviderRegistry,
    ProviderServices,
    render_context,
    serialize_blocks,
)
from daily_analyzer.context.market_data import (
    DailyPriceService,
    calculate_window_metrics,
    previous_trading_day,
)
from daily_analyzer.context.providers import (
    EASTERN,
    ExtendedHoursProvider,
    MacroReleasesProvider,
    MarketRegimeProvider,
    SectorStrengthProvider,
)


class FakePrices:
    def __init__(self, metrics=None, rows=None):
        self.provided_metrics = metrics or {}
        self.rows = rows or {}
        self.calls = []

    def metrics(self, symbols, end, windows):
        self.calls.append((list(symbols), end, tuple(windows)))
        return {symbol: self.provided_metrics.get(symbol, {}) for symbol in symbols}

    def bars(self, symbol, end):
        if symbol in self.rows:
            return self.rows[symbol], "Alpaca SIP adjustment=all"
        return [], "不可用"


class FakeYahoo:
    def __init__(self, sectors=None, bars=None, calendar=None):
        self.sectors = sectors or {}
        self.bars = bars or {}
        self.calendar = calendar
        self.sector_calls = []
        self.calendar_calls = []

    def sector_etf(self, symbol):
        self.sector_calls.append(symbol)
        return self.sectors.get(symbol)

    def daily_bars(self, symbol, start, end):
        return self.bars.get(symbol)

    def economic_calendar(self, start, end):
        self.calendar_calls.append((start, end))
        if isinstance(self.calendar, Exception):
            return None
        return self.calendar or []


class FakeAlpaca:
    def __init__(self, *, news=None, snapshots=None, minute_bars=None, daily_error=None):
        self.news_result = news or {"articles": [], "truncated": False}
        self.snapshot_rows = snapshots or {}
        self.minute_rows = minute_bars or {}
        self.daily_error = daily_error
        self.calls = []

    def daily_bars(self, symbols, start, end):
        self.calls.append(("daily", list(symbols), start, end))
        if self.daily_error:
            raise self.daily_error
        return {symbol: [] for symbol in symbols}

    def snapshots(self, symbols, feed):
        self.calls.append(("snapshots", list(symbols), feed))
        return {symbol: self.snapshot_rows.get(feed, {}).get(symbol, {}) for symbol in symbols}

    def iex_minute_bars(self, symbols, start, end):
        self.calls.append(("minutes", list(symbols), start, end))
        return {symbol: self.minute_rows.get(symbol, []) for symbol in symbols}

    def news(self, symbols, start, end, *, limit=None, max_pages=20):
        self.calls.append(("news", symbols, start, end, limit, max_pages))
        if isinstance(self.news_result, Exception):
            raise self.news_result
        return self.news_result


class FakeFutu:
    def __init__(self, *, rows=None, snapshots=None, mode="subscription"):
        self.rows = rows or {}
        self.snapshot_rows = snapshots or {}
        self.mode = mode
        self.warning = None
        self.start_symbols = []
        self.quote_calls = []
        self.snapshot_calls = []

    def start_batch(self, symbols):
        self.start_symbols = list(symbols)
        return self

    def get_quotes(self, symbols):
        self.quote_calls.append(list(symbols))
        return self.rows

    def get_snapshots(self, symbols):
        self.snapshot_calls.append(list(symbols))
        return self.snapshot_rows

    def close(self):
        pass


class FakeIndexMetadata:
    def __init__(self, benchmarks=None):
        self.benchmarks = benchmarks or {}
        self.calls = []

    def lookup(self, symbols):
        self.calls.append(symbols)
        rows = {symbol: dict(self.benchmarks.get(symbol, {"benchmark_symbol": "SPY", "benchmark_kind": "default",
                                                        "benchmark_reason": "行业未识别；指数成员未核验，默认SPY"})) for symbol in symbols}
        for row in rows.values():
            row.setdefault("index_symbol", row["benchmark_symbol"] if row["benchmark_kind"] == "index" else None)
        return rows


def _services(*, prices=None, alpaca=None, futu=None, yahoo=None, index_metadata=None):
    return ProviderServices(
        alpaca=alpaca or FakeAlpaca(),
        futu=futu or FakeFutu(mode="unavailable"),
        yahoo=yahoo or FakeYahoo(),
        prices=prices or FakePrices(),
        index_metadata=index_metadata or FakeIndexMetadata(),
    )


def _sessions(end: date, count: int):
    calendar = exchange_calendars.get_calendar("XNYS")
    sessions = calendar.sessions_in_range(
        pd.Timestamp(end - timedelta(days=count * 3 + 5)), pd.Timestamp(end)
    )
    return [session.date() for session in sessions][-count:]


def _rows(end: date, count: int, values=None):
    sessions = _sessions(end, count)
    values = values or (lambda index: 100 + index)
    return [{"t": session.isoformat(), "c": values(index)} for index, session in enumerate(sessions)]


def _complete_metric(*, close=100.0, sma20=99.0, sma50=98.0, sma200=97.0, r5=0.01, r20=0.02, r60=0.03):
    return {
        "close": close,
        "sma_20d": sma20,
        "sma_50d": sma50,
        "sma_200d": sma200,
        "return_5d": r5,
        "return_20d": r20,
        "return_60d": r60,
        "status": "可用",
        "source": "Alpaca SIP adjustment=all",
    }


def test_previous_session_and_fixed_window_formulas() -> None:
    end = date(2026, 9, 11)
    rows = _rows(end, 61, lambda index: 100 + index * 2)

    result = calculate_window_metrics(rows, end, (20, 50))

    expected_closes = [100 + index * 2 for index in range(61)]
    assert result["return_20d"] == pytest.approx(expected_closes[-1] / expected_closes[-21] - 1, abs=1e-12)
    assert result["sma_50d"] == pytest.approx(sum(expected_closes[-50:]) / 50, abs=1e-12)
    assert previous_trading_day(date(2026, 9, 14)) == end


def test_window_metrics_mark_unupdated_and_insufficient_without_filling() -> None:
    p = date(2026, 9, 11)
    older = _rows(date(2026, 9, 10), 60)
    insufficient = _rows(p, 20)

    unupdated = calculate_window_metrics(older, p, (5, 20))
    too_short = calculate_window_metrics(insufficient, p, (20,))

    assert unupdated["status"] == "未更新"
    assert unupdated["return_5d"] is None
    assert unupdated["sma_20d"] is None
    assert too_short["return_20d"] is None
    assert too_short["status_20d"] == "数据不足"


def test_daily_price_service_falls_back_to_auto_adjust_yahoo() -> None:
    end = date(2026, 9, 30)
    yahoo_rows = _rows(end, 3)
    alpaca = FakeAlpaca(daily_error=RuntimeError("service unavailable"))
    yahoo = FakeYahoo(bars={"NVDA": yahoo_rows})
    service = DailyPriceService(alpaca, yahoo)

    rows, source = service.bars("NVDA", end)
    vix_rows, vix_source = service.bars("^VIX", end)

    assert rows == yahoo_rows
    assert source == "yfinance auto_adjust=True"
    assert vix_rows == []
    assert vix_source == "不可用"
    assert len(alpaca.calls) == 1


@pytest.mark.parametrize(
    ("trend_close", "sma50", "sma200", "vix_close", "vix_change", "expected"),
    [
        (101, 100, 100, 16, 0.05, "偏强"),
        (101, 100, 100, 19, 0.30, "偏弱"),
        (101, 100, 100, 22, 0.01, "中性"),
        (101, None, 100, 16, 0.05, "数据不足"),
    ],
)
def test_market_regime_rules(trend_close, sma50, sma200, vix_close, vix_change, expected) -> None:
    data = {
        "SPY": _complete_metric(close=trend_close, sma50=sma50, sma200=sma200),
        "QQQ": _complete_metric(close=trend_close, sma50=sma50, sma200=sma200),
        "IWM": _complete_metric(),
        "DIA": _complete_metric(),
        "^VIX": _complete_metric(close=vix_close, r5=vix_change),
    }
    if sma50 is None:
        data["SPY"]["sma_50d"] = None
    if vix_change > 0.20:
        data["SPY"]["sma_200d"] = 102
        data["QQQ"]["sma_200d"] = 102
    provider = MarketRegimeProvider(_services(prices=FakePrices(data)))
    provider.prepare({"trade_date": date(2026, 10, 1), "price_data_end_date": date(2026, 9, 30)})

    block = provider.build(None, "2026-10-01T08:31:00-04:00")

    assert block.data["label"] == expected
    assert "相对200日线" in block.markdown
    assert block.as_of == date(2026, 9, 30)


def test_sector_ranking_ties_manual_override_and_unknown_sector() -> None:
    p = date(2026, 9, 30)
    metrics = {symbol: _complete_metric(r5=0.01, r20=0.01, r60=0.02) for symbol in ["SPY", "SMH", *(
        "XLK XLF XLE XLV XLY XLP XLI XLB XLU XLRE XLC".split()
    )]}
    metrics["XLK"] = _complete_metric(r20=0.015, r60=0.03)
    metrics["XLC"] = _complete_metric(r20=0.015, r60=0.04)
    metrics["XLRE"] = _complete_metric(r20=None, r60=None)
    metrics["NVDA"] = _complete_metric(r5=0.03, r20=0.05, r60=0.07)
    yahoo = FakeYahoo(sectors={"UNKNOWN": None})
    provider = SectorStrengthProvider(_services(prices=FakePrices(metrics), yahoo=yahoo))
    items = [
        WatchlistItem(symbol="NVDA", type="stock", sector_etf="SMH"),
        WatchlistItem(symbol="UNKNOWN", type="stock"),
        WatchlistItem(symbol="SPY", type="etf"),
    ]
    provider.prepare({"trade_date": date(2026, 10, 1), "price_data_end_date": p, "items": items})

    stock = provider.build(items[0], "2026-10-01T08:31:00-04:00")
    unknown = provider.build(items[1], "2026-10-01T08:31:00-04:00")
    etf = provider.build(items[2], "2026-10-01T08:31:00-04:00")
    order = [row["symbol"] for row in provider.ranking]

    assert order.index("XLC") < order.index("XLK")
    assert provider.ranking[-1]["symbol"] == "XLRE"
    assert provider.ranking[-1]["rank"] is None
    assert stock.data["sector_etf"] == "SMH"
    assert stock.data["manual_override"] is True
    assert stock.data["sector_excess_20d"] == pytest.approx(0.04)
    assert stock.data["benchmark_symbol"] == "SMH"
    assert stock.data["benchmark_excess_20d"] == pytest.approx(0.04)
    assert "未能识别所属板块" in unknown.markdown
    assert unknown.data["benchmark_symbol"] == "SPY" and unknown.data["benchmark_kind"] == "default"
    assert "sector_etf" not in etf.data

    manager = ContextManager(
        ["sector_strength"],
        services=_services(prices=FakePrices(metrics), yahoo=FakeYahoo()),
    )
    batch = {"trade_date": date(2026, 10, 1), "price_data_end_date": p, "items": [items[0]]}
    assert manager.prepare(batch) == {}
    managed = manager.build(items[0], "2026-10-01T08:31:00-04:00")["sector_strength"]
    assert managed.data["sector_etf"] == "SMH"
    assert managed.data["sector_excess_20d"] == pytest.approx(0.04)


def test_index_benchmark_and_backfill_use_same_price_cutoff():
    end = date(2026, 9, 30)
    prices = FakePrices({"TSLA": _complete_metric(r20=0.10), "QQQ": _complete_metric(r20=0.03),
                         "SPY": _complete_metric(r20=0.02)})
    metadata = FakeIndexMetadata({"TSLA": {"benchmark_symbol": "QQQ", "benchmark_kind": "index",
                                          "benchmark_reason": "指数成员已核验"}})
    item = WatchlistItem(symbol="TSLA", type="stock")
    provider = SectorStrengthProvider(_services(prices=prices, index_metadata=metadata))
    provider.prepare({"trade_date": date(2026, 10, 1), "price_data_end_date": end, "items": [item]})
    block = provider.build(item, "2026-10-01T08:31:00-04:00")
    assert block.data["benchmark_excess_20d"] == pytest.approx(0.07)
    assert "sector_excess_20d" not in block.data and block.data["sector_rank"] is None
    assert prices.calls[0][1] == end and "QQQ" in prices.calls[0][0]
    provider = SectorStrengthProvider(_services(prices=prices, index_metadata=metadata))
    provider.prepare({"mode": "backfill", "trade_date": date(2026, 10, 1), "price_data_end_date": end, "items": [item]})
    block = provider.build(item, "2026-10-01T08:31:00-04:00")
    assert len(metadata.calls) == 1
    assert block.data["benchmark_symbol"] == "SPY" and "历史" in block.data["benchmark_reason"]
    assert block.data["benchmark_excess_20d"] == pytest.approx(0.08)


def test_sector_override_kept_when_index_metadata_or_price_missing():
    metadata = FakeIndexMetadata()
    item = WatchlistItem(symbol="TSLA", type="stock", sector_etf="XLY")
    provider = SectorStrengthProvider(_services(index_metadata=metadata))
    provider.prepare({"trade_date": date(2026, 10, 1), "items": [item]})
    block = provider.build(item, "2026-10-01T08:31:00-04:00")
    assert metadata.calls == [["TSLA"]] and block.data["benchmark_symbol"] == "XLY"
    assert block.data["benchmark_excess_20d"] is None


@pytest.mark.parametrize("sector,index,expected", [
    ("XLY", "QQQ", ["XLY", "QQQ"]), ("XLY", None, ["XLY", "SPY"]),
    (None, "QQQ", ["QQQ"]), (None, None, ["SPY"]),
])
def test_sector_and_index_comparison_combinations(sector, index, expected):
    row = {"benchmark_symbol": index or "SPY", "benchmark_kind": "index" if index else "default",
           "index_symbol": index, "benchmark_reason": "指数成员未核验"}
    item = WatchlistItem(symbol="TSLA", type="stock")
    provider = SectorStrengthProvider(_services(yahoo=FakeYahoo({"TSLA": sector}),
                                                index_metadata=FakeIndexMetadata({"TSLA": row})))
    provider.prepare({"trade_date": date(2026, 10, 2), "items": [item]})
    block = provider.build(item, "2026-10-02T08:31:00-04:00")
    data = block.data
    assert [row["symbol"] for row in data["comparisons"]] == expected
    for comparison in data['comparisons']:
        label=f"{comparison['name']}（{comparison['symbol']}）："
        assert f"TSLA 相对 {label}" in block.markdown
        assert not any(line.startswith(label) for line in block.markdown.splitlines())
    assert data["comparisons"][0]["name"] in {"消费可选", "纳斯达克100", "标普500"}


def test_normalized_chart_uses_common_start_and_never_future_bars():
    end = date(2026, 10, 1)
    stock = _rows(end, 65, lambda i: 100 + i * 2)
    benchmark = _rows(end, 65, lambda i: 200 + i)
    stock.append({"t": "2026-10-02", "c": 9999})
    stock.pop(10)
    prices = FakePrices(rows={"TSLA": stock, "QQQ": benchmark})
    metadata = FakeIndexMetadata({"TSLA": {"benchmark_symbol": "QQQ", "benchmark_kind": "index", "benchmark_reason": "指数成员"}})
    provider = SectorStrengthProvider(_services(prices=prices, index_metadata=metadata))
    item = WatchlistItem(symbol="TSLA", type="stock")
    provider.prepare({"trade_date": date(2026, 10, 2), "items": [item]})
    chart = provider.build(item, "2026-10-02T08:31:00-04:00").data["comparisons"][0]["chart"]
    assert chart["stock"][0] == chart["benchmark"][0] == 100
    assert chart["dates"][-1] == end.isoformat() and len(chart["dates"]) == 60
    assert chart["stock"][-1] == pytest.approx(228 / 108 * 100)
    assert chart["benchmark"][-1] == pytest.approx(264 / 204 * 100)
    prices.rows["QQQ"] = benchmark[:-1]
    chart = provider.build(item, "2026-10-02T08:31:00-04:00").data["comparisons"][0]["chart"]
    assert chart is None


def _futu_row(
    symbol: str,
    *,
    update_time="2026-10-01 08:31:00",
    after_time="2026-09-30 19:59:00",
    overnight_time="2026-10-01 03:59:00",
    pre_time="2026-10-01 08:29:00",
):
    row = {"code": f"US.{symbol}", "update_time": update_time}
    for segment, price, update in (
        ("after", 99.0, after_time),
        ("overnight", 100.5, overnight_time),
        ("pre", 101.0, pre_time),
    ):
        row.update(
            {
                f"{segment}_price": price,
                f"{segment}_high_price": price + 1,
                f"{segment}_low_price": price - 1,
                f"{segment}_volume": 1000,
                f"{segment}_update_time": update,
            }
        )
    return row


def _extended_provider(futu, alpaca=None):
    price_rows = {
        symbol: [{"t": "2026-09-30", "c": 100.0}]
        for symbol in ["NVDA", "SPY", "QQQ", "IWM", "DIA"]
    }
    services = _services(
        futu=futu,
        alpaca=alpaca or FakeAlpaca(),
        prices=FakePrices(rows=price_rows),
    )
    provider = ExtendedHoursProvider(services)
    batch = {
        "mode": "live",
        "trade_date": date(2026, 10, 1),
        "price_data_end_date": date(2026, 9, 30),
        "items": [WatchlistItem(symbol="NVDA", type="stock")],
    }
    provider.prepare(batch)
    return provider, batch


def test_extended_hours_futu_timestamp_and_session_rules() -> None:
    rows = {f"US.{symbol}": _futu_row(symbol) for symbol in ["NVDA", *("SPY QQQ IWM DIA".split())]}
    rows["US.NVDA"].pop("after_update_time")
    rows["US.NVDA"].pop("overnight_update_time")
    futu = FakeFutu(rows=rows)
    provider, _batch = _extended_provider(futu)

    block = provider.build(WatchlistItem(symbol="NVDA", type="stock"), "2026-10-01T08:40:00-04:00")

    assert block.data["NVDA"]["overnight"]["status"] == "时段未核验（无分时段时间）"
    assert block.data["NVDA"]["overnight"]["quote_time"] is None
    assert block.data["NVDA"]["overnight"]["source_update_time"] == "2026-10-01 08:31:00"
    assert block.data["NVDA"]["overnight"]["session_verified"] is False
    assert block.data["NVDA"]["after"]["status"] == "时段未核验（无分时段时间）"
    assert block.data["NVDA"]["after"]["quote_time"] is None
    assert block.data["NVDA"]["after"]["source_update_time"] == "2026-10-01 08:31:00"
    assert block.data["NVDA"]["after"]["session_verified"] is False
    assert "时段未核验（无分时段时间）" in block.markdown
    assert "2026-09-30T19:59:59" not in block.markdown
    assert block.data["NVDA"]["pre"]["quote_time"].endswith("08:29:00-04:00")
    assert block.data["NVDA"]["pre"]["session_verified"] is True
    assert block.data["NVDA"]["pre"]["change_pct"] == pytest.approx(1.0)
    assert block.data["premarket_relative_to_spy_pct"] == pytest.approx(0.0)
    assert block.data["NVDA"]["overnight"]["status"] != "过期"


def test_extended_hours_marks_stale_premarket_and_wrong_prior_after_hours() -> None:
    row = _futu_row("NVDA", after_time="2026-09-29 19:59:00", pre_time="2026-10-01 08:00:00")
    futu = FakeFutu(rows={"US.NVDA": row})
    provider, _batch = _extended_provider(futu)

    block = provider.build(WatchlistItem(symbol="NVDA", type="stock"), "2026-10-01T08:31:00-04:00")

    assert block.data["NVDA"]["after"]["status"] == "非本时段数据"
    assert block.data["NVDA"]["after"]["change_pct"] is None
    assert block.data["NVDA"]["pre"]["status"] == "过期"


def test_extended_hours_excludes_exact_session_end() -> None:
    rows = {f"US.{symbol}": _futu_row(symbol) for symbol in ["NVDA", *"SPY QQQ IWM DIA".split()]}
    rows["US.NVDA"]["pre_update_time"] = "2026-10-01 09:30:00"
    futu = FakeFutu(rows=rows)
    provider, _batch = _extended_provider(futu)

    block = provider.build(WatchlistItem(symbol="NVDA", type="stock"), "2026-10-01T09:30:00-04:00")

    assert block.data["NVDA"]["pre"]["status"] == "非本时段数据"


def test_extended_hours_uses_futu_snapshot_before_alpaca() -> None:
    subscribed = {"US.NVDA": _futu_row("NVDA", pre_time="2026-10-01 07:50:00")}
    snapshot = {"US.NVDA": _futu_row("NVDA", pre_time="2026-10-01 08:29:00")}
    futu = FakeFutu(rows=subscribed, snapshots=snapshot)
    alpaca = FakeAlpaca()
    provider, _batch = _extended_provider(futu, alpaca)

    block = provider.build(WatchlistItem(symbol="NVDA", type="stock"), "2026-10-01T08:31:00-04:00")

    assert futu.snapshot_calls
    assert block.data["NVDA"]["pre"]["source"] == "富途快照"
    assert not any(
        "NVDA" in call[1]
        for call in alpaca.calls
        if call[0] == "snapshots" and call[2] == "iex"
    )


def test_extended_hours_respects_disabled_futu_setting() -> None:
    futu = FakeFutu()
    alpaca = FakeAlpaca()
    services = _services(futu=futu, alpaca=alpaca)
    services.futu_enabled = False
    provider = ExtendedHoursProvider(services)
    batch = {
        "mode": "live",
        "trade_date": date(2026, 10, 1),
        "price_data_end_date": date(2026, 9, 30),
        "items": [WatchlistItem(symbol="NVDA", type="stock")],
    }

    provider.prepare(batch)

    assert futu.start_symbols == []


def test_extended_hours_alpaca_fallback_and_backfill_minute_bars() -> None:
    snapshots = {
        "overnight": {
            "NVDA": {
                "latestTrade": {"p": 100.5, "s": 10, "t": "2026-10-01T07:59:00Z"},
                "dailyBar": {"h": 101, "l": 100, "v": 50},
            }
        },
        "iex": {
            "NVDA": {
                "latestTrade": {"p": 101.0, "s": 20, "t": "2026-10-01T12:29:00Z"},
                "dailyBar": {"h": 102, "l": 99, "v": 80},
            }
        },
    }
    alpaca = FakeAlpaca(snapshots=snapshots)
    futu = FakeFutu(mode="unavailable")
    provider, batch = _extended_provider(futu, alpaca)

    live = provider.build(WatchlistItem(symbol="NVDA", type="stock"), "2026-10-01T08:31:00-04:00")
    assert live.data["NVDA"]["overnight"]["source"] == "Alpaca feed=overnight"
    assert live.data["NVDA"]["pre"]["source"] == "Alpaca feed=iex"
    assert live.data["NVDA"]["pre"]["warning"] == "IEX 覆盖不完整"

    batch["mode"] = "backfill"
    alpaca.minute_rows["NVDA"] = [
        {"t": "2026-10-01T12:30:00Z", "o": 100, "h": 101, "l": 99, "c": 100.5, "v": 10},
        {"t": "2026-10-01T12:31:00Z", "o": 101, "h": 103, "l": 100, "c": 102, "v": 20},
        {"t": "2026-10-01T12:32:00Z", "o": 102, "h": 105, "l": 101, "c": 104, "v": 30},
    ]
    replay = provider.build(WatchlistItem(symbol="NVDA", type="stock"), "2026-10-01T08:31:00-04:00")
    assert replay.data["NVDA"]["overnight"]["status"] == "回放不可用"
    assert replay.data["NVDA"]["pre"]["price"] == pytest.approx(100.5)
    assert replay.data["NVDA"]["pre"]["volume"] == pytest.approx(10)
    assert alpaca.calls[-1][0] == "minutes"
    assert alpaca.calls[-1][3] == datetime(2026, 10, 1, 8, 31, tzinfo=EASTERN)


def _article(title: str, created_at: str, updated_at: str | None = None, revised: bool = False):
    return {
        "headline": title,
        "created_at": created_at,
        "updated_at": updated_at or created_at,
        "symbol": "",
        "source": "Benzinga",
        "revised_after_cutoff": revised,
    }


def test_macro_releases_parse_claims_revisions_and_latest_twenty() -> None:
    articles = [
        _article("USA Initial Jobless Claims 197K Vs 201K Est.", "2026-10-01T12:30:18Z"),
        _article("USA Continuing Jobless Claims 1,701k Vs 1,730K Est.; 1,712K Prior", "2026-10-01T12:30:56Z"),
        _article("USA Prior Revised: Initial Jobless Claims 201K", "2026-10-01T12:30:57Z", revised=True),
        _article("USA Unrecognized Economic Title", "2026-10-01T12:30:58Z"),
        _article("Outside cutoff", "2026-10-01T12:32:00Z"),
    ]
    articles.extend(
        _article(f"Market headline {index}", f"2026-10-01T12:20:{index:02d}Z")
        for index in range(25)
    )
    articles.sort(key=lambda item: item["created_at"])
    alpaca = FakeAlpaca(news={"articles": articles, "truncated": False})
    provider = MacroReleasesProvider(
        _services(
            alpaca=alpaca,
            yahoo=FakeYahoo(
                calendar=[{"start_time": "2026-10-01T13:30:00-04:00", "title": "ISM Manufacturing PMI"}]
            ),
        )
    )
    provider.prepare({"trade_date": date(2026, 10, 1), "mode": "live"})

    block = provider.build(None, "2026-10-01T08:31:00-04:00")

    assert block.data["releases"][0]["name"] == "Initial Jobless Claims"
    assert block.data["releases"][0]["actual"] == "197K"
    assert block.data["releases"][0]["estimate"] == "201K"
    assert block.data["releases"][0]["prior"] is None
    assert block.data["releases"][1]["actual"] == "1,701k"
    assert block.data["releases"][1]["prior"] == "1,712K"
    assert len(block.data["prior_revised"]) == 1
    assert block.data["post_cutoff_revisions"] == ["USA Prior Revised: Initial Jobless Claims 201K"]
    assert len(block.data["unparsed_economic_titles"]) == 1
    assert len(block.data["market_news"]) == 20
    assert "标题已截断" not in block.markdown
    assert "内容可能已在截止后修订" in block.markdown
    assert block.data["upcoming_events"] == ["13:30 ET ISM Manufacturing PMI"]
    assert alpaca.calls[0][1] is None
    assert alpaca.calls[0][4:] == (None, 20)


def test_macro_marks_truncation_and_no_releases_at_cutoff() -> None:
    truncated_provider = MacroReleasesProvider(
        _services(alpaca=FakeAlpaca(news={"articles": [], "truncated": True}))
    )
    truncated_provider.prepare({"trade_date": date(2026, 10, 1), "mode": "live"})
    truncated = truncated_provider.build(None, "2026-10-01T08:31:00-04:00")
    assert "标题已截断" in truncated.markdown

    empty_provider = MacroReleasesProvider(_services(alpaca=FakeAlpaca()))
    empty_provider.prepare({"trade_date": date(2026, 10, 1), "mode": "live"})
    empty = empty_provider.build(None, "2026-10-01T08:31:00-04:00")
    assert "截至 08:31:00 ET 未见当日经济数据标题" in empty.markdown

    unparsed_provider = MacroReleasesProvider(
        _services(alpaca=FakeAlpaca(news={"articles": [_article("USA Unrecognized Title", "2026-10-01T12:30:00Z")], "truncated": False}))
    )
    unparsed_provider.prepare({"trade_date": date(2026, 10, 1), "mode": "live"})
    unparsed = unparsed_provider.build(None, "2026-10-01T08:31:00-04:00")
    assert "截至 08:31:00 ET 未见当日经济数据标题" in unparsed.markdown
    assert unparsed.data["unparsed_economic_titles"][0]["title"] == "USA Unrecognized Title"


def test_macro_processes_all_one_hundred_thirty_news_articles_without_truncation() -> None:
    articles = [
        _article(
            f"USA Indicator {index} 1K Vs 2K Est.",
            f"2026-10-01T12:30:{index % 60:02d}Z",
        )
        for index in range(130)
    ]
    provider = MacroReleasesProvider(
        _services(alpaca=FakeAlpaca(news={"articles": articles, "truncated": False}))
    )
    provider.prepare({"trade_date": date(2026, 10, 1), "mode": "live"})

    block = provider.build(None, "2026-10-01T08:31:00-04:00")

    assert len(block.data["releases"]) == 130
    assert block.data["truncated"] is False
    assert "标题已截断" not in block.markdown


def test_provider_registry_custom_class_empty_override_and_safe_failure(caplog) -> None:
    calls = []
    module = types.ModuleType("test_market_context_extension")

    class ExtensionProvider:
        name = "extension"
        scope = "ticker"

        def prepare(self, batch):
            calls.append(("prepare", batch))

        def build(self, item, cutoff):
            calls.append(("build", item, cutoff))
            return ContextBlock("自定义", "扩展块", {"symbol": item["symbol"]}, cutoff, ["fixture"])

    module.ExtensionProvider = ExtensionProvider
    sys.modules[module.__name__] = module
    registry = ProviderRegistry()
    registry.register("default", lambda services: ExtensionProvider())
    services = _services()
    manager = ContextManager(
        ["default"],
        services=services,
        registry=registry,
    )
    batch = {
        "context_as_of": "2026-10-01T08:31:00-04:00",
        "items": [
            {"symbol": "NVDA", "context_providers": ["test_market_context_extension:ExtensionProvider"]},
            {"symbol": "SPY", "context_providers": []},
        ],
    }
    manager.prepare(batch)
    nvda = manager.build(batch["items"][0], batch["context_as_of"])
    spy = manager.build(batch["items"][1], batch["context_as_of"])

    assert list(nvda) == ["test_market_context_extension:ExtensionProvider"]
    assert nvda[next(iter(nvda))].data == {"symbol": "NVDA"}
    assert spy == {}
    serial = serialize_blocks(nvda)
    assert serial[next(iter(serial))]["as_of"] == batch["context_as_of"]
    assert "附加市场上下文（截至" in render_context(nvda, batch["context_as_of"])

    class FailingProvider:
        name = "broken"
        scope = "ticker"

        def prepare(self, batch):
            raise RuntimeError("authorization: APCA_API_SECRET_KEY=never-show")

        def build(self, item, cutoff):
            raise AssertionError("prepare failed providers are not built")

    broken_registry = ProviderRegistry()
    broken_registry.register("broken", lambda services: FailingProvider())
    broken = ContextManager(["broken"], services=services, registry=broken_registry)
    broken.prepare({"items": [{"symbol": "NVDA"}], "context_as_of": batch["context_as_of"]})
    block = broken.build({"symbol": "NVDA"}, batch["context_as_of"])["broken"]
    assert "该维度数据不可用" in block.markdown
    assert "RuntimeError" in block.markdown
    assert "never-show" not in block.markdown
    assert "上下文提供器 broken prepare 失败：RuntimeError" in caplog.text
    assert "never-show" not in caplog.text


def test_macro_provider_network_failure_becomes_unavailable_context() -> None:
    manager = ContextManager(
        ["macro_releases"],
        services=_services(alpaca=FakeAlpaca(news=RuntimeError("network failure"))),
    )
    item = WatchlistItem(symbol="NVDA", type="stock")
    manager.prepare(
        {
            "trade_date": date(2026, 10, 1),
            "mode": "live",
            "context_as_of": "2026-10-01T08:31:00-04:00",
            "items": [item],
        }
    )

    block = manager.build(item, "2026-10-01T08:31:00-04:00")["macro_releases"]

    assert block.markdown == "该维度数据不可用：RuntimeError；经济数据与要闻不可用。"


def test_quality_flags_are_numbered_once_and_referenced():
    blocks = {"sample": ContextBlock("样本", "IEX 覆盖不完整；IEX 覆盖不完整", {
        "segments": [{"warning": "IEX 覆盖不完整"}, {"warnings": ["IEX 覆盖不完整"], "status": "过期"}],
        "truncated": True,
    }, "2026-10-02", ["Alpaca"])}
    text = render_context(blocks, "2026-10-02")
    assert text.count("IEX 覆盖不完整") == 1
    assert text.count("数据限制#1") == 2
    assert "1. IEX 覆盖不完整" in text and "2. 过期" in text and "3. 新闻翻页达到上限" in text
    assert text.index("数据质量与限制") > text.index("### 样本")



def test_extended_price_base_is_official_and_mismatch_is_visible():
    row = _futu_row("NVDA")
    row["prev_close_price"] = 98.0
    provider, _ = _extended_provider(FakeFutu(rows={"US.NVDA":row}))
    item = WatchlistItem(symbol="NVDA",type="stock")
    segment = provider.build(item,"2026-10-01T08:31:00-04:00").data["NVDA"]["pre"]
    assert segment["source_previous_close"] == 98
    assert segment["official_previous_close"] == 100
    assert segment["change_pct"] == pytest.approx(1)
    assert "不一致" in segment["warning"]
    provider.services.prices.rows["NVDA"] = []
    segment = provider.build(item,"2026-10-01T08:31:00-04:00").data["NVDA"]["pre"]
    assert segment["change_pct"] is None
    assert "基准未核验" in segment["warning"]


def test_extended_futu_prior_session_close_is_convention_not_mismatch():
    row = _futu_row("NVDA")
    row["prev_close_price"] = 98.0
    provider, _ = _extended_provider(FakeFutu(rows={"US.NVDA": row}))
    provider.services.prices.rows["NVDA"] = [{"t": "2026-09-29", "c": 98.0}, {"t": "2026-09-30", "c": 100.0}]
    block = provider.build(WatchlistItem(symbol="NVDA", type="stock"), "2026-10-01T08:31:00-04:00")
    segment = block.data["NVDA"]["pre"]
    assert segment["change_pct"] == pytest.approx(1)
    assert "不一致" not in (segment.get("warning") or "")
    assert segment["previous_close_convention"] == "futu_prior_session"
    assert block.markdown.count("新交易日开盘前口径") == 1

    row["prev_close_price"] = 95.0
    segment = provider.build(WatchlistItem(symbol="NVDA", type="stock"), "2026-10-01T08:31:00-04:00").data["NVDA"]["pre"]
    assert "不一致" in segment["warning"]


def test_extended_alpaca_overnight_previous_close_is_listed_not_compared():
    snapshots = {"overnight": {"NVDA": {
        "latestTrade": {"p": 100.5, "s": 10, "t": "2026-10-01T07:59:00Z"},
        "prevDailyBar": {"c": 103.0},
    }}}
    provider, _ = _extended_provider(FakeFutu(mode="unavailable"), FakeAlpaca(snapshots=snapshots))
    block = provider.build(WatchlistItem(symbol="NVDA", type="stock"), "2026-10-01T08:31:00-04:00")
    segment = block.data["NVDA"]["overnight"]
    assert segment["source"] == "Alpaca feed=overnight" and segment["source_previous_close"] == 103
    assert "不一致" not in (segment.get("warning") or "")
    assert "仅列示，不参与核对" in block.markdown


def test_context_extend_keeps_batch_and_isolates_new_ticker_failure():
    calls = []
    class BatchProvider:
        scope = 'batch'
        def prepare(self, batch): calls.append(('market', batch['items']))
        def build(self, item, cutoff): return ContextBlock('市场', '固定市场', {}, cutoff, ['fixture'])
    class TickerProvider:
        scope = 'ticker'
        def prepare(self, batch):
            self.symbols = [item['symbol'] for item in batch['items']]
            calls.append(('ticker', self.symbols))
            if 'FAIL' in self.symbols: raise ValueError('增量失败')
        def build(self, item, cutoff):
            assert item['symbol'] in self.symbols
            return ContextBlock('标的', '增量上下文', {'symbol':item['symbol']}, cutoff, ['fixture'])
    registry = ProviderRegistry()
    registry.register('market', lambda _: BatchProvider())
    registry.register('ticker', lambda _: TickerProvider())
    manager = ContextManager(['market','ticker'], services=_services(), registry=registry)
    first = {'symbol':'NVDA'}
    batch = manager.prepare({'items':[first], 'context_as_of':'2026-10-02T08:30:00-04:00'})
    manager.extend([{'symbol':'TSLA'}, {'symbol':'FAIL'}])
    blocks = manager.build({'symbol':'TSLA'}, '2026-10-02T08:40:00-04:00')
    assert blocks['market'] is batch['market']
    assert blocks['ticker'].data == {'symbol':'TSLA'}
    assert blocks['ticker'].as_of == '2026-10-02T08:40:00-04:00'
    assert manager.build(first,'2026-10-02T08:41:00-04:00')['ticker'].data == {'symbol':'NVDA'}
    assert 'ValueError' in manager.build({'symbol':'FAIL'},'2026-10-02T08:42:00-04:00')['ticker'].markdown
    assert [row for row in calls if row[0] == 'market'] == [('market',[first])]
    assert ('ticker',['TSLA']) in calls and ('ticker',['FAIL']) in calls
    manager.close()


def test_context_extend_prepares_new_quotes_and_earnings_only(monkeypatch):
    from types import SimpleNamespace
    from tradingagents.dataflows import router
    calls = []
    class Calendars:
        def calendars(self, start, end, symbols, cutoff):
            calls.append(list(symbols))
            return {'earnings':[{'security':'US.'+symbol} for symbol in symbols], 'economics':[], 'warnings':[]}
    monkeypatch.setattr(router, 'route_to_vendor', lambda *args: '固定宏观数据')
    services = _services(futu=FakeFutu(), prices=FakePrices())
    services.futu_data = Calendars()
    services.clock = lambda: datetime(2026,10,2,8,40,tzinfo=EASTERN)
    manager = ContextManager(['extended_hours','macro_releases'], services=services)
    nvda, tsla = WatchlistItem(symbol='NVDA',type='stock'), WatchlistItem(symbol='TSLA',type='stock')
    manager.prepare({'items':[nvda], 'trade_date':date(2026,10,2), 'price_data_end_date':date(2026,10,1),
                     'mode':'live','context_as_of':datetime(2026,10,2,8,30,tzinfo=EASTERN)})
    original_symbols = list(services.futu.start_symbols)
    manager.extend([tsla])
    extension = manager._extensions['TSLA']
    assert 'TSLA' in extension.services.futu.start_symbols
    assert 'NVDA' not in extension.services.futu.start_symbols
    assert services.futu.start_symbols == original_symbols
    assert calls == [['NVDA'],['TSLA']]
    assert extension._providers['macro_releases'].calendars['earnings'] == [{'security':'US.TSLA'}]
    manager.close()


def test_after_open_live_premarket_reuses_history_and_excludes_opening_bar():
    alpaca = FakeAlpaca(snapshots={'iex':{'NVDA':{'latestTrade':{'p':110,'t':'2026-10-01T13:31:00Z'}}}},
                         minute_bars={'NVDA':[{'t':'2026-10-01T13:29:00Z','c':101,'h':102,'l':100,'v':10},
                                              {'t':'2026-10-01T13:30:00Z','c':110,'h':110,'l':110,'v':100}]})
    provider, _ = _extended_provider(FakeFutu(mode='unavailable'),alpaca)
    block = provider.build(WatchlistItem(symbol='NVDA',type='stock'),'2026-10-01T09:31:00-04:00')
    pre=block.data['NVDA']['pre']
    assert pre['price']==101 and pre['volume']==10
    assert pre['status']=='可用' and '历史分钟线' in pre['source']
    assert pre['quote_time']=='2026-10-01T09:29:00-04:00'
    assert pre['warning']=='IEX 覆盖不完整'
    assert [row for row in alpaca.calls if row[0]=='minutes'][0][3]==datetime(2026,10,1,9,30,tzinfo=EASTERN)


def test_macro_fresh_releases_includes_late_indexed_and_unparsed_titles() -> None:
    from daily_analyzer.context.providers import macro_seen_titles

    articles = [
        _article("USA Nonfarm Payrolls For Sept. 29K Vs 89K Est.", "2026-10-02T12:30:12Z"),
        _article("USA Private Nonfarm Payrolls For Sept. 46K Vs 85K Est", "2026-10-02T12:30:25Z"),
        _article("USA Participation Rate For September 61.8% Vs 61.6% Prior", "2026-10-02T12:30:18Z"),
        _article("USA Nonfarm Payrolls For Sept. Revises Prior From 162K To 133K", "2026-10-02T12:30:47Z"),
        _article("Market headline", "2026-10-02T12:31:30Z"),
        _article("Yesterday", "2026-10-01T20:00:00Z"),
    ]
    alpaca = FakeAlpaca(news={"articles": articles, "truncated": False})
    provider = MacroReleasesProvider(_services(alpaca=alpaca))
    provider.prepare({"trade_date": date(2026, 10, 2), "mode": "live"})

    rows = provider.fresh_releases("2026-10-02T08:40:00-04:00")

    parsed = {row["title"]: row for row in rows if row.get("actual")}
    assert parsed["USA Nonfarm Payrolls For Sept. 29K Vs 89K Est."]["actual"] == "29K"
    # 末尾无句点的 Est 也应解析
    assert parsed["USA Private Nonfarm Payrolls For Sept. 46K Vs 85K Est"]["estimate"] == "85K"
    raw = [row["title"] for row in rows if not row.get("actual")]
    assert raw == [
        "USA Participation Rate For September 61.8% Vs 61.6% Prior",
        "USA Nonfarm Payrolls For Sept. Revises Prior From 162K To 133K",
    ]
    assert all(not row["title"].startswith(("Market", "Yesterday")) for row in rows)
    assert alpaca.calls[-1][1] is None

    block = provider.build(None, "2026-10-02T08:40:00-04:00")
    assert sorted(macro_seen_titles(block.data)) == sorted(row["title"] for row in rows)


def test_context_manager_refresh_macro_requires_prepared_provider() -> None:
    manager = ContextManager([], services=_services(alpaca=FakeAlpaca(news={"articles": [], "truncated": False})))
    with pytest.raises(RuntimeError, match="macro_releases 未启用"):
        manager.refresh_macro_releases(WatchlistItem(symbol="NVDA", type="stock"), datetime(2026, 10, 2, 8, 40, tzinfo=EASTERN))


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Average Hourly Earnings MoM For Sept. 0.1% Vs 0.3% Expected", ("Average Hourly Earnings MoM For Sept.", "0.1%", "0.3%")),
        ("GDP QoQ 2.2% Vs 1.5% Expected", ("GDP QoQ", "2.2%", "1.5%")),
        ("GDP Price Index QoQ 6.1% Vs 6.4% Expected", ("GDP Price Index QoQ", "6.1%", "6.4%")),
        # 以下真实标题不属于美国经济数据或格式不同，不得按 Expected 格式解析
        ("U.K. Gross Domestic Product (QoQ) For Q2 0.5% Vs. 0.4% Est.; 0.6% Prior", None),
        ("Reported Earlier, Japan Tokyo Core Consumer Price Index (YoY) For September 2.7% Vs. 2.4% Est.; 1.8% Prior", None),
        ("Cardinal Health Affirms FY2027 Adj EPS Of $12.40-$12.60 vs $12.04 Est", None),
        ("Jabil Sees Q1 Adj EPS $3.80-$4.20 Vs $3.60 Expected", None),
    ],
)
def test_macro_expected_format_parses_only_us_style_titles(title, expected) -> None:
    from daily_analyzer.context.providers import _classify_macro_articles

    releases, _, _, _ = _classify_macro_articles([_article(title, "2026-10-02T12:30:05Z")])
    if expected is None:
        assert releases == []
    else:
        assert [(row["name"], row["actual"], row["estimate"], row["prior"]) for row in releases] == [(*expected, None)]


@pytest.mark.parametrize("clock,stamp,session", [
    ("08:31", "08:30", "pre"), ("12:09", "12:07", "regular"),
    ("16:31", "16:29", "after"), ("02:31", "02:29", "overnight"),
])
def test_analysis_quote_four_sessions_raw_time(clock, stamp, session):
    from daily_analyzer.context.analysis_quote import observation, raw_alpaca
    cutoff = datetime.fromisoformat(f"2026-10-01T{clock}:00-04:00")
    candidate = raw_alpaca({"latestTrade": {"p": 200.36, "t": f"2026-10-01T{stamp}:00-04:00"}}, "Alpaca feed=iex")
    quote = observation("SMTC", cutoff, candidate)
    assert quote["status"] == "可用" and quote["session"] == session
    assert quote["price"] == 200.36 and quote["change_pct"] is None


def test_analysis_quote_sdk_regular_time_and_no_extended_time_inference():
    from daily_analyzer.context.analysis_quote import raw_futu, observation
    row = {"last_price": 336.365, "data_date": "2026-10-01", "data_time": "12:08:59", "pre_price": 330}
    cutoff = datetime.fromisoformat("2026-10-01T12:09:57-04:00")
    quote = observation("COHR", cutoff, raw_futu(row, "regular", "富途订阅报价"))
    assert quote["status"] == "可用" and quote["quote_time"].endswith("12:08:59-04:00")
    from daily_analyzer.context.providers import _futu_segment
    pre = _futu_segment(row, "pre", date(2026,10,1), date(2026,9,30), cutoff)
    assert pre["quote_time"] is None and not pre["session_verified"]
    assert pre["source_update_time"] == "2026-10-01 12:08:59"


def test_future_raw_and_snapshot_refresh_are_not_trade_time():
    from daily_analyzer.context.providers import _alpaca_segment
    cutoff = datetime.fromisoformat("2026-10-01T08:31:00-04:00")
    assert _alpaca_segment({"latestTrade":{"p":100}, "updated_at":cutoff.isoformat()}, "Alpaca feed=iex", date(2026,10,1),date(2026,9,30),cutoff) is None
    candidate = _alpaca_segment({"latestTrade":{"p":100,"t":"2026-10-01T12:32:00Z"}}, "Alpaca feed=iex", date(2026,10,1),date(2026,9,30),cutoff)
    assert candidate["status"].startswith("未来报价")


def test_regular_observation_survives_historical_premarket_fallback_without_injection():
    alpaca = FakeAlpaca(snapshots={"iex":{"NVDA":{"latestTrade":{"p":200.36,"t":"2026-10-01T16:07:39Z"}}}},
        minute_bars={"NVDA":[{"t":"2026-10-01T12:30:00Z","c":101}]})
    provider, _ = _extended_provider(FakeFutu(mode="unavailable"), alpaca)
    block = provider.build(WatchlistItem(symbol="NVDA",type="stock"), "2026-10-01T12:09:40-04:00")
    assert block.data["NVDA"]["pre"]["price"] == 101
    assert block.data["NVDA"]["analysis_quote"]["price"] == 200.36
    assert block.data["NVDA"]["analysis_quote"]["status"] == "可用"
    assert "200.36" not in block.markdown


def test_analysis_observation_is_absent_from_entire_model_context():
    from copy import deepcopy
    cutoff = "2026-10-01T08:31:00-04:00"
    block = ContextBlock("extended_hours", "固定扩展表", {"NVDA": {"pre": {"status": "可用"}}}, datetime.fromisoformat(cutoff), ["富途"])
    original = render_context({"extended_hours": block}, cutoff)
    changed = deepcopy(block)
    changed.data["NVDA"]["analysis_quote"] = {"status": "报价观测独有状态", "warning": "报价观测独有警示", "price": 987.65}
    assert render_context({"extended_hours": changed}, cutoff) == original


@pytest.mark.parametrize("stamp,valid", [
    ("2026-10-02T20:31:00-04:00", False),
    ("2026-10-04T20:31:00-04:00", True),
    ("2026-09-06T20:31:00-04:00", False),
])
def test_analysis_overnight_uses_next_natural_trading_day(stamp, valid):
    from daily_analyzer.context.analysis_quote import observation
    cutoff = datetime.fromisoformat(stamp)
    quote = observation("SMTC", cutoff, {"price": 200, "quote_time": stamp, "time_field": "latestTrade.t", "source": "Alpaca feed=overnight"})
    assert (quote['status'] == '可用') == valid


def test_active_overnight_stale_futu_analysis_fetches_fresh_alpaca_without_changing_extended_semantics():
    row = _futu_row("NVDA", overnight_time="2026-10-01 01:00:00")
    row["overnight_price"] = 99
    futu = FakeFutu(rows={"US.NVDA": row})
    alpaca = FakeAlpaca(snapshots={"overnight": {"NVDA": {"latestTrade": {"p":100.5,"t":"2026-10-01T06:30:00Z"}}}})
    provider, _ = _extended_provider(futu, alpaca)
    block = provider.build(WatchlistItem(symbol="NVDA", type="stock"), "2026-10-01T02:31:00-04:00")
    assert block.data["NVDA"]["overnight"]["price"] == 99
    assert block.data["NVDA"]["overnight"]["status"] == "可用"
    quote = block.data["NVDA"]["analysis_quote"]
    assert quote["price"] == 100.5 and quote["status"] == "可用"
    assert quote["source"] == "Alpaca feed=overnight"
    assert any(call[0] == "snapshots" and call[2] == "overnight" and call[1].count("NVDA") == 1 for call in alpaca.calls)

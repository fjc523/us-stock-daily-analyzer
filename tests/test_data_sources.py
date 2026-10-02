from __future__ import annotations

import pytest
import ast
import sys
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

from daily_analyzer.data_sources.alpaca import AlpacaDataSource
from daily_analyzer.data_sources.futu import FutuQuoteManager
from daily_analyzer.data_sources.yfinance import YahooDataSource


ROOT = Path(__file__).resolve().parents[1]


class FakeAlpacaClient:
    def __init__(self) -> None:
        self.calls = []

    def get_bars(self, *args, **kwargs):
        self.calls.append(("bars", args, kwargs))
        return {symbol: [] for symbol in args[0]}

    def get_snapshots(self, *args, **kwargs):
        self.calls.append(("snapshots", args, kwargs))
        return {symbol: {} for symbol in args[0]}

    def get_news(self, *args, **kwargs):
        self.calls.append(("news", args, kwargs))
        return {"articles": [], "truncated": False}


def test_alpaca_adapter_uses_fork_client_with_expected_parameters() -> None:
    client = FakeAlpacaClient()
    source = AlpacaDataSource(client=client)
    source.daily_bars(["SPY", "XLK"], date(2026, 1, 1), date(2026, 9, 30))
    source.snapshots(["NVDA"], "overnight")
    source.snapshots(["NVDA"], "iex")
    source.iex_minute_bars(["NVDA"], "2026-10-01T04:00:00-04:00", "2026-10-01T08:31:00-04:00")
    start = datetime.fromisoformat("2026-10-01T00:00:00-04:00")
    end = datetime.fromisoformat("2026-10-01T08:31:00-04:00")
    source.news(None, start, end, limit=None, max_pages=20)

    assert client.calls[0] == (
        "bars",
        (["SPY", "XLK"], date(2026, 1, 1), date(2026, 9, 30)),
        {"feed": "sip", "adjustment": "all", "timeframe": "1Day"},
    )
    assert client.calls[1][2] == {"feed": "overnight"}
    assert client.calls[2][2] == {"feed": "iex"}
    assert client.calls[3][2] == {"feed": "iex", "adjustment": "raw", "timeframe": "1Min"}
    assert client.calls[4][0] == "news"
    assert client.calls[4][1] == (None, start, end)
    assert client.calls[4][2] == {"limit": None, "max_pages": 20}


def test_alpaca_default_client_is_fork_shared_singleton(monkeypatch) -> None:
    import tradingagents.dataflows.vendors.alpaca.client as shared

    sentinel = FakeAlpacaClient()
    monkeypatch.setattr(shared, "get_shared_client", lambda: sentinel)
    source = AlpacaDataSource()

    assert source.client is sentinel
    assert source.client is source.client


def test_main_project_has_no_direct_alpaca_http_client() -> None:
    package = ROOT / "src" / "daily_analyzer"
    forbidden_imports = {"requests", "httpx", "urllib.request", "alpaca.data"}
    for path in package.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                names = {node.module or ""}
            else:
                continue
            if path.name in {"index_metadata.py", "vix.py"}:
                # 发行方持仓允许独立HTTP读取，不允许把Alpaca入口混入此例外。
                assert not names.intersection(forbidden_imports - {"requests"}), path
                from urllib.parse import urlsplit
                from daily_analyzer.data_sources.index_metadata import HOLDINGS_URLS
                assert {urlsplit(url).hostname for url in HOLDINGS_URLS.values()} == {"dng-api.invesco.com", "www.ssga.com", "www.ishares.com"}
                continue
            assert not names.intersection(forbidden_imports), path
        content = path.read_text(encoding="utf-8")
        assert "data.alpaca.markets" not in content


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


class FakeFutuContext:
    def __init__(self, *, remain: int = 100, subscription_error: bool = False) -> None:
        self.remain = remain
        self.subscription_error = subscription_error
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []
        self.subscribed_at: float | None = None
        self.unsubscribed_at: float | None = None
        self.closed = False
        self.snapshot_calls: list[list[str]] = []
        self.quote_calls: list[list[str]] = []
        self.manager_clock: FakeClock | None = None

    def query_subscription(self, *, is_all_conn: bool):
        assert is_all_conn is True
        return 0, {"remain": self.remain}

    def subscribe(self, codes, subtypes, **kwargs):
        assert subtypes == ["QUOTE"]
        assert kwargs["extended_time"] is True
        if self.subscription_error:
            return -1, "订阅失败"
        self.subscribed.extend(codes)
        if self.subscribed_at is None and self.manager_clock is not None:
            self.subscribed_at = self.manager_clock.now()
        return 0, "ok"

    def unsubscribe(self, codes, subtypes):
        self.unsubscribed.extend(codes)
        if self.manager_clock is not None:
            self.unsubscribed_at = self.manager_clock.now()
        return 0, "ok"

    def get_stock_quote(self, codes):
        self.quote_calls.append(list(codes))
        return 0, [{"code": code, "pre_price": 101} for code in codes]

    def get_market_snapshot(self, codes):
        self.snapshot_calls.append(list(codes))
        return 0, [{"code": code, "pre_price": 101} for code in codes]

    def close(self):
        self.closed = True


def _futu_manager(context, clock, *, max_subscriptions=40):
    context.manager_clock = clock
    return FutuQuoteManager(
        max_subscriptions=max_subscriptions,
        context_factory=lambda **kwargs: context,
        quote_subtype="QUOTE",
        clock=clock.now,
        sleep=clock.sleep,
    )


def test_futu_subscription_lifecycle_waits_until_sixty_seconds() -> None:
    clock = FakeClock()
    context = FakeFutuContext()
    manager = _futu_manager(context, clock).start_batch(["NVDA", "BRK-B"])
    assert manager.mode == "subscription"
    assert context.subscribed == ["US.NVDA", "US.BRK.B"]
    assert manager.get_quotes(["NVDA"]) == {"US.NVDA": {"code": "US.NVDA", "pre_price": 101}}

    clock.value = 20
    manager.close()

    assert clock.sleeps == [40]
    assert context.unsubscribed == ["US.NVDA", "US.BRK.B"]
    assert context.unsubscribed_at == 60
    assert context.closed is True


def test_futu_insufficient_quota_uses_snapshot_and_chunks_at_four_hundred() -> None:
    clock = FakeClock()
    context = FakeFutuContext(remain=10)
    manager = _futu_manager(context, clock).start_batch([f"S{i}" for i in range(20)])
    assert manager.mode == "snapshot"
    assert manager.warning == "额度不足，使用快照"
    quotes = manager.get_quotes([f"S{i}" for i in range(401)])
    assert len(quotes) == 401
    assert [len(codes) for codes in context.snapshot_calls] == [400, 1]
    assert context.subscribed == []
    manager.close()
    assert context.closed is True


def test_futu_batch_subscription_cap_and_failed_quote_are_reported_safely() -> None:
    clock = FakeClock()
    context = FakeFutuContext()
    manager = _futu_manager(context, clock).start_batch([f"S{i}" for i in range(41)])

    assert manager.mode == "snapshot"
    assert context.subscribed == []
    assert "额度不足" in manager.warning

    context.get_market_snapshot = lambda codes: (-1, "https://private.example/token=secret")
    assert manager.get_snapshots(["NVDA"]) == {}
    assert manager.warning == "富途快照不可用：接口返回失败"
    assert "secret" not in manager.warning
    manager.close()


def test_futu_unavailable_reports_unusable_without_raising() -> None:
    clock = FakeClock()

    def unavailable(**kwargs):
        raise ConnectionError("OpenD down")

    manager = FutuQuoteManager(
        context_factory=unavailable,
        quote_subtype="QUOTE",
        clock=clock.now,
        sleep=clock.sleep,
    ).start_batch(["NVDA"])
    assert manager.mode == "unavailable"
    assert manager.get_quotes(["NVDA"]) == {}
    manager.close()


def test_futu_snapshot_rate_limit_allows_sixty_calls_per_thirty_seconds() -> None:
    clock = FakeClock()
    context = FakeFutuContext(remain=0)
    manager = _futu_manager(context, clock).start_batch(["NVDA"])
    for _ in range(61):
        manager.get_snapshots(["NVDA"])
    assert len(context.snapshot_calls) == 61
    assert clock.sleeps == [30]
    assert clock.value == 30
    manager.close()


class FakeTicker:
    def __init__(self, *, rows=None, sector="Technology", error=None) -> None:
        self.rows = rows if rows is not None else []
        self.sector = sector
        self.error = error
        self.history_calls = []
        self.info_calls = 0

    def history(self, **kwargs):
        self.history_calls.append(kwargs)
        if self.error:
            raise self.error
        return self.rows

    @property
    def info(self):
        self.info_calls += 1
        if self.error:
            raise self.error
        return {"sector": self.sector}


def test_yfinance_daily_adjustment_and_end_date_filter() -> None:
    ticker = FakeTicker(
        rows=[
            {"Date": "2026-09-30", "Close": 100},
            {"Date": "2026-10-01", "Close": 110},
        ]
    )
    source = YahooDataSource(ticker_factory=lambda symbol: ticker)

    rows = source.daily_bars("SPY", date(2026, 9, 1), date(2026, 9, 30))

    assert rows == [{"Date": "2026-09-30", "Close": 100}]
    assert ticker.history_calls == [
        {"start": "2026-09-01", "end": "2026-10-01", "auto_adjust": True, "timeout": 10}
    ]


def test_yfinance_sector_mapping_is_cached_inside_project(tmp_path: Path) -> None:
    ticker = FakeTicker(sector="Technology")
    source = YahooDataSource(project_root=tmp_path, ticker_factory=lambda symbol: ticker)

    assert source.sector_etf("nvda") == "XLK"
    assert source.sector_etf("NVDA") == "XLK"
    cache_path = tmp_path / "data" / "cache" / "sector_map.json"
    assert cache_path.exists()
    assert cache_path.read_text(encoding="utf-8").find('"NVDA": "XLK"') >= 0
    assert ticker.info_calls == 1


def test_yfinance_rate_limit_and_optional_calendar_fail_as_unavailable(tmp_path) -> None:
    ticker = FakeTicker(error=RuntimeError("HTTP 429"))
    source = YahooDataSource(
        project_root=tmp_path,
        ticker_factory=lambda symbol: ticker,
        calendar_factory=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("HTTP 429")),
    )
    assert source.daily_bars("NVDA", "2026-09-01", "2026-09-30") is None
    assert source.sector_etf("NVDA") is None
    assert source.economic_calendar("2026-10-01", "2026-10-01") is None


def test_futu_daily_loader_paginates_and_closes():
    import pandas as pd
    from daily_analyzer.data_sources.futu import FutuDataSource
    closed = []
    calls = []
    class Quote:
        def __init__(self, **kwargs): pass
        def request_history_kline(self, **kwargs):
            calls.append(kwargs)
            day = "2026-09-30" if kwargs['page_req_key'] is None else "2026-10-01"
            return 0, pd.DataFrame([{'time_key': day, 'open': 1, 'high': 2, 'low': 1, 'close': 2, 'volume': 10}]), b'next' if kwargs['page_req_key'] is None else None
        def close(self): closed.append(True)
    source = FutuDataSource(context_factory=Quote)
    data = source._history_daily_bars('TSLA', '2026-09-01', '2026-10-01')
    assert len(data) == 2 and len(closed) == 2 and calls[1]['page_req_key'] == b'next'
    assert calls[0]['autype'] == 'qfq' and data.columns.tolist() == ['Date','Open','High','Low','Close','Volume']


@pytest.mark.parametrize('failure', ['quota exceeded', '未知的协议ID', '没有权限'])
def test_futu_loader_classifies_vendor_failure(failure):
    from daily_analyzer.data_sources.futu import FutuDataSource
    from tradingagents.dataflows.errors import VendorUnavailableError
    class Quote:
        def __init__(self, **kwargs): pass
        def request_history_kline(self, **kwargs): return -1, failure
        def close(self): pass
    with pytest.raises(VendorUnavailableError, match='富途'):
        FutuDataSource(context_factory=Quote)._history_daily_bars('TSLA', '2026-09-01', '2026-10-01')


def test_futu_loader_connection_failure_is_vendor_unavailable():
    from daily_analyzer.data_sources.futu import FutuDataSource
    from tradingagents.dataflows.errors import VendorUnavailableError
    def broken(**kwargs): raise ConnectionError('断线')
    with pytest.raises(VendorUnavailableError, match='ConnectionError'):
        FutuDataSource(context_factory=broken).daily_bars('TSLA', '2026-09-01', '2026-10-01')


@pytest.fixture
def daily_subscription_source():
    from daily_analyzer.data_sources.futu import FutuDataSource
    from datetime import datetime
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo('America/New_York')).date().isoformat()
    state = {'now': 0, 'remain': 5, 'subscribe': [], 'read': [], 'release': [], 'closed': 0, 'timers': [], 'history': []}
    def row(day):
        return {'time_key':day + ' 00:00:00','open':1,'high':2,'low':1,'close':2,'volume':10}
    state['rows'] = [row('2026-09-29'), row('2026-09-30'), row('2026-10-01'), row(today)]
    class Timer:
        def __init__(self, delay, callback):
            self.delay, self.callback, self.cancelled = delay, callback, False
            state['timers'].append(self)
        def start(self): pass
        def cancel(self): self.cancelled = True
    class Quote:
        def __init__(self, **kwargs): pass
        def query_subscription(self, **kwargs): return 0, {'remain':state['remain']}
        def subscribe(self, codes, types, **kwargs):
            state['subscribe'].append((codes, types))
            return 0, ''
        def get_cur_kline(self, code, **kwargs):
            state['read'].append((code,kwargs))
            return state.get('read_ret',0), state['rows']
        def unsubscribe(self, codes, types):
            state['release'].extend(codes)
            return 0, ''
        def close(self): state['closed'] += 1
        def request_history_kline(self, **kwargs):
            state['history'].append(kwargs)
            return 0, [row(kwargs['start']), row(kwargs['end'])], None
    return FutuDataSource(context_factory=Quote, clock=lambda:state['now'], timer_factory=Timer), state, today


def test_futu_subscription_window_today_filter_and_batch_cache(daily_subscription_source):
    source, state, today = daily_subscription_source
    frame = source.daily_bars('TSLA','2026-09-30', today)
    assert frame.Date.tolist() == ['2026-09-30','2026-10-01']
    frame.loc[0,'Close'] = 999
    narrow = source.daily_bars('US.TSLA','2026-10-01','2026-10-01')
    assert narrow.Close.tolist() == [2]
    assert len(state['subscribe']) == len(state['read']) == 1
    assert state['read'][0][1] == {'num':1000,'ktype':'K_DAY','autype':'qfq'}
    assert not state['history'] and not state['release']


def test_futu_subscription_timer_releases_only_owned_codes(daily_subscription_source):
    source, state, _ = daily_subscription_source
    source.daily_bars('TSLA','2026-09-30','2026-10-01')
    state['now'] = 30
    source.daily_bars('SPY','2026-09-30','2026-10-01')
    state['now'] = 60
    state['timers'][0].callback()
    assert state['release'] == ['US.TSLA'] and state['closed'] == 0
    state['now'] = 90
    state['timers'][1].callback()
    assert state['release'] == ['US.TSLA','US.SPY'] and state['closed'] == 1
    source.close_batch()
    assert state['closed'] == 1


def test_futu_batch_end_does_not_wait_or_unsubscribe_early(daily_subscription_source):
    source, state, _ = daily_subscription_source
    source.daily_bars('TSLA','2026-09-30','2026-10-01')
    source.close_batch()
    assert not state['release'] and not state['closed']
    assert state['timers'][0].delay == 60
    state['now'] = 61
    source.close_batch()
    assert state['release'] == ['US.TSLA'] and state['closed'] == 1
    assert state['timers'][0].cancelled


def test_futu_subscription_quota_failure_never_touches_other_subscriptions(daily_subscription_source):
    from tradingagents.dataflows.errors import VendorUnavailableError
    source, state, _ = daily_subscription_source
    state['remain'] = 0
    with pytest.raises(VendorUnavailableError,match='额度不足'):
        source.daily_bars('TSLA','2026-09-30','2026-10-01')
    assert not state['subscribe'] and not state['release'] and not state['history']
    assert state['closed'] == 1


def test_futu_outside_current_coverage_uses_history_quota(daily_subscription_source, caplog):
    import logging
    source, state, _ = daily_subscription_source
    with caplog.at_level(logging.INFO):
        frame = source.daily_bars('TSLA','2020-01-01','2026-09-30')
    assert frame.Date.tolist() == ['2020-01-01','2026-09-30']
    assert len(state['subscribe']) == 1 and len(state['history']) == 1
    assert '消耗历史K线额度' in caplog.text


def test_futu_read_failure_keeps_timer_cleanup_without_history_fallback(daily_subscription_source):
    from tradingagents.dataflows.errors import VendorUnavailableError
    source, state, _ = daily_subscription_source
    state['read_ret'] = -1
    with pytest.raises(VendorUnavailableError,match='读取不可用'):
        source.daily_bars('TSLA','2026-09-30','2026-10-01')
    assert not state['history']
    state['now'] = 60
    state['timers'][0].callback()
    assert state['release'] == ['US.TSLA'] and state['closed'] == 1

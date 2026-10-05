"""DQ6合成raw合同；不代表真实逐分钟回放，SDK及HTTP均显式fake。"""
from datetime import date, datetime, timedelta
import threading
from unittest.mock import Mock

import pytest

from daily_analyzer.context.extended_minutes import ExtendedMinuteBatch, RequestBudget, minute_summary
from daily_analyzer.context.analysis_quote import observation


def instant(value):
    return datetime.fromisoformat(value)


def futu_row(time, price, volume, high=None, low=None):
    return {'time_key': time, 'close': price, 'volume': volume, 'high': high or price, 'low': low or price}


def sip_row(time, price, volume):
    return {'t': time, 'c': price, 'v': volume, 'h': price, 'l': price}


@pytest.fixture(autouse=True)
def no_real_sdk(monkeypatch):
    # 防止测试改动遗漏注入后连到localhost真实OpenD。
    import futu
    monkeypatch.setattr(futu, 'OpenQuoteContext', Mock(side_effect=AssertionError('禁止真实OpenD')))


def test_complete_endpoint_zero_volume_and_same_source():
    start, end = instant('2026-10-05T04:00:00-04:00'), instant('2026-10-05T09:30:00-04:00')
    now = instant('2026-10-05T08:31:41-04:00')
    rows = [sip_row('2026-10-05T08:15:00-04:00', 100, 50), sip_row('2026-10-05T08:16:00-04:00', 999, 900)]
    result = minute_summary(rows, 'sip', start, end, cutoff=now, now=now)
    assert result['quote_time'] == '2026-10-05T08:16:00-04:00'
    assert result['price'] == result['high'] == result['low'] == 100
    assert result['cumulative_volume'] == 50
    rows = [futu_row('2026-10-05 08:23:00', 193.36, 50), futu_row('2026-10-05 08:24:00', 999, 0), futu_row('2026-10-05 08:32:00', 1000, 50)]
    result = minute_summary(rows, 'futu', start, end, cutoff=now, now=now)
    assert result['price'] == 193.36 and result['cumulative_volume'] == 50 and result['traded_minutes'] == 1


def test_historical_sip_no_cutoff_minus15_and_night04_endpoint():
    start, end = instant('2026-10-02T16:00:00-04:00'), instant('2026-10-02T20:00:00-04:00')
    cutoff = instant('2026-10-02T19:58:00-04:00')
    now = instant('2026-10-05T08:30:00-04:00')
    result = minute_summary([sip_row('2026-10-02T19:57:00-04:00', 20, 4)], 'sip', start, end, cutoff=cutoff, now=now)
    assert result['price'] == 20 and result['quote_time'] == cutoff.isoformat()
    start, end = instant('2026-10-04T20:00:00-04:00'), instant('2026-10-05T04:00:00-04:00')
    result = minute_summary([futu_row('2026-10-04 20:00:00', 999, 50), futu_row('2026-10-05 04:00:00', 21, 5)], 'futu', start, end, cutoff=now, now=now)
    assert result['price'] == 21 and result['cumulative_volume'] == 5


class FakeSDK:
    def __init__(self, calls, *, fail=False, cycle=False):
        self.calls, self.fail, self.cycle, self.closed = calls, fail, cycle, False
    def get_market_state(self, codes):
        self.calls.append(('market', codes)); return 0, []
    def get_history_kl_quota(self, get_detail):
        self.calls.append(('quota',)); return 0, (6, 100, [])
    def request_history_kline(self, code, **kwargs):
        self.calls.append(('history', code, kwargs))
        if self.fail: return -1, '拒绝', None
        return 0, [futu_row('2026-10-05 08:23:00', 193.36, 6862, 198, 193.03)], b'repeat' if self.cycle else None
    def close(self): self.closed = True


class FakeAlpaca:
    def __init__(self): self.calls = []
    def complete_minute_bars(self, symbols, start, end, **kwargs):
        self.calls.append((symbols, start, end, kwargs))
        return {symbol: [sip_row('2026-10-05T08:10:00-04:00', 193.55, 12649)] for symbol in symbols}


def make_batch(*, fail=False, cycle=False, options=None):
    calls, contexts, alpaca = [], [], FakeAlpaca()
    def factory(**kwargs):
        context = FakeSDK(calls, fail=fail, cycle=cycle); contexts.append(context); return context
    now = instant('2026-10-05T08:31:41-04:00')
    batch = ExtendedMinuteBatch(alpaca, context_factory=factory, clock=lambda: now, options=options)
    batch.prepare(['SMTC', 'SPY'], date(2026, 10, 5), date(2026, 10, 2), now)
    return batch, calls, contexts, alpaca, now


def test_once_health_two_ranges_cache_cutoff_filter_and_cross_check():
    batch, calls, contexts, alpaca, now = make_batch()
    start, end = instant('2026-10-05T04:00:00-04:00'), instant('2026-10-05T09:30:00-04:00')
    first = batch.segment('SMTC', 'pre', start, end, now, close=194.88)
    assert first['price'] == 193.36 and first['quote_time'].endswith('08:23:00-04:00')
    assert first['cumulative_volume'] == 6862 and first['high'] == 198 and first['low'] == 193.03
    assert first['cross_check'][0]['price'] == 193.55
    assert first['adv20_status'] == '20日均量口径未核实'
    older = batch.segment('SMTC', 'pre', start, end, instant('2026-10-05T08:15:00-04:00'))
    assert older['price'] == 193.55 and older['quote_time'].endswith('08:11:00-04:00')
    batch.prepare(['SMTC', 'SPY'], date(2026, 10, 5), date(2026, 10, 2), now)
    assert sum(row[0] == 'market' for row in calls) == sum(row[0] == 'quota' for row in calls) == 1
    assert len(alpaca.calls) == 1
    assert batch.ranges['history'] == (date(2026, 10, 2), date(2026, 10, 4))
    assert all(context.closed for context in contexts)
    backfill = batch.segment('SMTC', 'pre', start, end, now, backfill=True)
    assert backfill['price'] == 193.55 and backfill['source'].startswith('Alpaca feed=sip')


def test_failure_vs_no_trade_fallback_and_pagination_cycle():
    batch, calls, _, _, now = make_batch(fail=True)
    start, end = instant('2026-10-05T04:00:00-04:00'), instant('2026-10-05T09:30:00-04:00')
    result = batch.segment('SMTC', 'pre', start, end, now)
    assert result['source'].startswith('Alpaca feed=sip') and result['fallback_used']
    assert result['source_failures'][0]['source'] == 'futu'
    assert sum(row[0] == 'history' for row in calls) == 2
    batch.segment('SMTC', 'pre', start, end, now)
    assert sum(row[0] == 'history' for row in calls) == 2
    empty = minute_summary([], 'futu', start, end, cutoff=now, now=now)
    assert empty['status'] == '无成交' and empty['price'] is None
    batch, _, _, _, _ = make_batch(cycle=True)
    with pytest.raises(RuntimeError, match='token循环'): batch._futu('SMTC', 'today')
    assert ('SMTC', 'today') not in batch.cache


def test_thin_config_and_unknown_adjustment():
    batch, _, _, _, now = make_batch()
    start, end = instant('2026-10-05T04:00:00-04:00'), instant('2026-10-05T09:30:00-04:00')
    unknown = batch.segment('SMTC', 'pre', start, end, now, adv20={'source': 'sip', 'adjustment': 'all', 'count': 20, 'value': 3e6})
    assert unknown['volume_adv20_ratio'] is None
    batch.options = {'thin_enabled': False}
    assert batch.segment('SMTC', 'pre', start, end, now)['liquidity_note'] == '稀薄阈值已关闭'
    batch.options = {'thin_min_traded_minutes': 0, 'thin_adv20_ratio': .0005}
    good = batch.segment('SMTC', 'pre', start, end, now, adv20={'source': 'sip', 'adjustment': 'raw', 'count': 20, 'value': 2e7})
    assert good['volume_adv20_ratio'] == 6862 / 2e7 and good['liquidity_note'] == '成交稀薄，仅列示'


def test_timeout_retry_late_context_and_result_never_cached():
    gate, created, contexts = threading.Event(), threading.Event(), []
    def factory(**kwargs):
        created.set(); gate.wait()
        context = FakeSDK([]); contexts.append(context); return context
    batch = ExtendedMinuteBatch(FakeAlpaca(), context_factory=factory, timeout=.01)
    with pytest.raises(TimeoutError): batch._bounded(lambda context: '迟到结果')
    gate.set()
    for _ in range(100):
        if len(contexts) == 2 and all(context.closed for context in contexts): break
        threading.Event().wait(.002)
    assert len(contexts) == 2 and all(context.closed for context in contexts)
    assert batch.cache == {}


def test_request_budget_shared_60_per30():
    now = [0.0]
    sleeps = []
    def sleep(seconds): sleeps.append(seconds); now[0] += seconds
    budget = RequestBudget(clock=lambda: now[0], sleep=sleep)
    for _ in range(61): budget.acquire()
    assert sleeps == [30] and budget.total == 61


def test_analysis_quote_endpoint_sip45_futu30_and_closed_after():
    now = instant('2026-10-05T08:30:00-04:00')
    candidate = {'price': 100, 'quote_time': '2026-10-05T07:50:00-04:00', 'source': 'Alpaca feed=sip 完整分钟', 'time_field': 'sip_minute.t'}
    assert observation('ABC', now, candidate)['status'] == '可用'
    assert observation('ABC', now, dict(candidate, time_field='futu_kline.time_key', source='富途'))['status'] == '过期'
    candidate.update(quote_time='2026-10-02T20:00:00-04:00')
    assert observation('ABC', instant('2026-10-04T08:30:00-04:00'), candidate, recent_after=True)['status'] == '可用'


def test_alpaca_actual_http_entry_page_loop_and_retry_budget(monkeypatch):
    from tradingagents.dataflows.vendors.alpaca.client import AlpacaClient
    monkeypatch.setenv('APCA_API_KEY_ID', 'fixture')
    monkeypatch.setenv('APCA_API_SECRET_KEY', 'fixture')
    response = Mock(status_code=200, headers={})
    response.json.return_value = {'bars': {'ABC': []}, 'next_page_token': 'same'}
    session = Mock(); session.get.return_value = response
    client = AlpacaClient(session=session)
    with pytest.raises(Exception, match='token循环'):
        client.get_bars(['ABC'], instant('2026-10-02T16:00:00-04:00'), instant('2026-10-02T20:00:00-04:00'), feed='sip', adjustment='raw', timeframe='1Min', timeout=10, retries=1, max_pages=8)
    assert session.get.call_count == 2 and session.get.call_args.kwargs['timeout'] == 10
    with pytest.raises(ValueError): client.get_bars(['ABC'], date(2026, 10, 2), date(2026, 10, 2), feed='overnight')


def test_real_provider_path_preflight_extension_cache_and_symbols():
    from daily_analyzer.context.base import ProviderServices, ContextManager
    from daily_analyzer.context.providers import make_registry
    from daily_analyzer.source_status import SourceStatusCollector
    batch, calls, _, alpaca, now = make_batch()
    quotes = Mock(mode='snapshot', warning=None)
    prices = Mock()
    prices.bars.return_value = ([{'t': '2026-10-01', 'c': 194}, {'t': '2026-10-02', 'c': 194.88}], 'Alpaca SIP adjustment=all')
    prices._cache = {}
    services = ProviderServices(alpaca=alpaca, futu=quotes, prices=prices, extended_minutes=batch, clock=lambda: now)
    manager = ContextManager(['extended_hours'], services=services, registry=make_registry())
    item = {'symbol': 'SMTC', 'type': 'stock'}
    manager.prepare({'items': [item], 'trade_date': date(2026, 10, 5), 'price_data_end_date': date(2026, 10, 2), 'mode': 'live', 'context_as_of': now})
    block = manager.build(item, now)['extended_hours'].to_dict()
    assert set(batch.symbols) == {'SMTC', 'SPY', 'QQQ', 'IWM', 'DIA'}
    assert block['data']['SMTC']['analysis_quote']['price'] == 193.36
    assert '时段累计量' in block['markdown'] and '有量分钟' in block['markdown']
    assert block['data']['preflight']['sip']['status'] == '分钟接口可达'
    collector = SourceStatusCollector()
    collector._context({'extended_hours': block})
    assert any((event.get('statement_metadata') or {}).get('minute_contract') for event in collector.events)
    manager.extend([{'symbol': 'ABC', 'type': 'stock'}])
    assert manager._extensions['ABC'].services.extended_minutes is batch
    assert sum(row[0] == 'market' for row in calls) == 1


def test_timeout_late_query_cannot_replace_retry_result_and_close_failure():
    gate, finished = threading.Event(), threading.Event()
    count = [0]
    contexts = []
    class Context:
        def __init__(self): self.closed = False
        def close(self):
            self.closed = True
            raise RuntimeError('合成close失败')
    def factory(**kwargs):
        context = Context(); contexts.append(context); return context
    def query(context):
        count[0] += 1
        if count[0] == 1:
            gate.wait(); finished.set(); return '迟到旧结果'
        return '第二次成功'
    batch = ExtendedMinuteBatch(FakeAlpaca(), context_factory=factory, timeout=.01)
    assert batch._bounded(query) == '第二次成功'
    gate.set(); assert finished.wait(1)
    assert all(context.closed for context in contexts)


def test_two_ranges_8pages_one_retry_actual32_history_budget():
    attempts = {}
    class PagedSDK(FakeSDK):
        def request_history_kline(self, code, **kwargs):
            key = code, kwargs['start'], kwargs['page_req_key']
            attempts[key] = attempts.get(key, 0) + 1
            if attempts[key] == 1: return -1, '合成首轮失败', None
            page = int(kwargs['page_req_key'] or 0)
            return 0, [], str(page + 1)
    now = instant('2026-10-05T08:31:41-04:00')
    batch = ExtendedMinuteBatch(FakeAlpaca(), context_factory=lambda **kwargs: PagedSDK([]), clock=lambda: now)
    batch.prepare(['SMTC'], date(2026, 10, 5), date(2026, 10, 2), now)
    for key in ('today', 'history'):
        with pytest.raises(RuntimeError, match='8页预算耗尽'): batch._futu('SMTC', key)
    assert sum(attempts.values()) == batch.history_attempts['SMTC'] == 32
    assert batch.history_pages['SMTC'] == 16 and not batch.cache


def test_added_symbol_queries_only_missing_cached_symbols():
    batch, _, _, alpaca, now = make_batch()
    batch.prepare(['ABC'], date(2026, 10, 5), date(2026, 10, 2), now)
    batch._sip('sip', instant('2026-10-05T04:00:00-04:00'), now)
    assert alpaca.calls[-1][0] == ['ABC']


def test_actual_preflight_permission_and_quota_reasons_retained():
    class Denied(FakeSDK):
        def get_market_state(self, codes): return -1, 'permission denied: market-state entitlement'
        def get_history_kl_quota(self, get_detail): return -1, 'quota exhausted for current account'
    now = instant('2026-10-05T08:31:41-04:00')
    batch = ExtendedMinuteBatch(FakeAlpaca(), context_factory=lambda **kwargs: Denied([]), clock=lambda: now)
    batch.prepare(['SMTC'], date(2026, 10, 5), date(2026, 10, 2), now)
    health = batch.health['futu']
    assert health['market_state']['ret'] == -1 and health['market_state']['reason'] == 'permission denied: market-state entitlement'
    assert health['history_quota']['ret'] == -1 and health['history_quota']['reason'] == 'quota exhausted for current account'
    result = batch.segment('SMTC', 'pre', instant('2026-10-05T04:00:00-04:00'), instant('2026-10-05T09:30:00-04:00'), now)
    assert 'quota exhausted for current account' in result['source_failures'][0]['reason']
    assert '额度未知' not in result['source_failures'][0]['reason']

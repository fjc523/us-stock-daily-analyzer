"""非交易日当前分析的固定样本回归；行情、新闻与图均不真实调用。"""
from datetime import date, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import json
import threading

import pytest

from daily_analyzer.time_utils import NEW_YORK, select_run_window
from daily_analyzer.context.analysis_quote import observation
from daily_analyzer.context.providers import ExtendedHoursProvider, MacroReleasesProvider
from daily_analyzer.site import _summary_premarket
from daily_analyzer.live_information import _wrap, install_live_information_adapter, live_information_scope
from test_context_providers import FakeFutu, FakeAlpaca, FakePrices, _services
from test_runner import _project, _ContextManager, _FakeGraph, _run
from daily_analyzer.runner import run_analysis


def stamp(value):
    return datetime.fromisoformat(value)


def batch(now):
    window = select_run_window(None, now)
    return {'trade_date': window.trade_date, 'price_data_end_date': window.price_data_end_date,
            'mode': 'live', 'context_as_of': now, 'items': []}


@pytest.mark.parametrize('value,p', [
    ('2026-10-04T11:00:00-04:00', '2026-10-02'),
    ('2026-09-07T11:00:00-04:00', '2026-09-04'),
    ('2026-11-27T13:00:00-05:00', '2026-11-27'),
    ('2026-10-02T20:10:00-04:00', '2026-10-02'),
])
def test_当前窗口使用最近完整收盘(value, p):
    window = select_run_window(None, stamp(value))
    assert window.price_data_end_date.isoformat() == p
    assert window.mode == 'live' and window.news_cutoff_utc is None


def test_周末盘后分钟线保留真实时间与页面年龄():
    now = stamp('2026-10-04T11:00:00-04:00')
    alpaca = FakeAlpaca(snapshots={'iex': {'NVDA': {'latestTrade': {'p': 999, 't': '2026-10-02T16:00:00-04:00'}}}},
                        minute_bars={'NVDA': [{'c': 105, 't': '2026-10-02T19:58:00-04:00'},
                                              {'c': 900, 't': '2026-10-02T20:00:00-04:00'}]})
    prices = FakePrices(rows={'NVDA': [{'date': date(2026, 10, 2), 'close': 100}]})
    provider = ExtendedHoursProvider(_services(alpaca=alpaca, prices=prices))
    provider.prepare(batch(now))
    block = provider.build({'symbol': 'NVDA'}, now)
    quote = block.data['NVDA']['analysis_quote']
    assert quote['price'] == 105 and quote['quote_time'] == '2026-10-02T19:58:00-04:00'
    assert quote['status'] == '可用' and 'IEX' in quote['warning'] and '陈旧' in quote['warning']
    assert '最近交易日盘后' in block.markdown and '距获取时点' in block.markdown
    result = {'symbol': 'NVDA', 'mode': 'live', 'context_as_of': now.isoformat(),
              'price_data_end_date': '2026-10-02', 'context_blocks': {'extended_hours': {'as_of': now.isoformat(), 'data': block.data}}}
    projected = _summary_premarket(result)
    assert projected['price'] == '105.00 美元' and '陈旧' in projected['title']
    result['price_data_end_date'] = '2026-10-01'
    assert projected['time'] and _summary_premarket(result)['price'] == ''


@pytest.mark.parametrize('cutoff,quote,field,status', [
    ('2026-10-04T11:00:00-04:00', '2026-10-02T16:00:00-04:00', 'latestTrade.t', '非本时段数据'),
    ('2026-11-28T11:00:00-05:00', '2026-11-27T13:00:00-05:00', 'latestTrade.t', '非本时段数据'),
    ('2026-10-02T16:10:30-04:00', '2026-10-02T16:10:00-04:00', 'minute.t', '分钟尚未完整（超过分析截止）'),
    ('2026-10-02T18:10:00-04:00', '2026-10-02T16:10:00-04:00', 'after_update_time', '过期'),
    ('2026-10-04T11:00:00-04:00', '2026-10-04T11:01:00-04:00', 'after_update_time', '未来报价（超过分析截止）'),
])
def test_盘后边界不接受普通收盘未来或未完整分钟(cutoff, quote, field, status):
    checked = observation('NVDA', stamp(cutoff), {'price': 101, 'quote_time': quote, 'time_field': field}, 100, recent_after=True)
    assert checked['status'] == status


def test_独立富途盘后证据和无时间诚实降级():
    now = stamp('2026-10-03T11:00:00-04:00')
    valid = observation('NVDA', now, {'price': 105, 'quote_time': '2026-10-02T16:00:00-04:00', 'time_field': 'after_update_time'}, recent_after=True)
    assert valid['status'] == '可用'
    provider = ExtendedHoursProvider(_services(futu=FakeFutu(rows={'US.NVDA': {'after_price': 105, 'update_time': '2026-10-03 11:00:00'}})))
    provider.prepare(batch(now))
    quote = provider.build({'symbol': 'NVDA'}, now).data['NVDA']['analysis_quote']
    assert quote['status'] == '真实行情时间未核验' and quote['quote_time'] is None


def test_周日宏观新闻覆盖周六且排除未来():
    now = stamp('2026-10-04T11:00:00-04:00')
    alpaca = FakeAlpaca(news={'articles': [
        {'headline': '周六消息', 'created_at': '2026-10-03T18:00:00Z'},
        {'headline': '同日未来', 'created_at': '2026-10-04T20:00:00Z'}], 'truncated': False})
    provider = MacroReleasesProvider(_services(alpaca=alpaca))
    provider.prepare(batch(now))
    block = provider.build({'symbol': 'NVDA'}, now)
    assert '周六消息' in block.markdown and '同日未来' not in block.markdown
    assert alpaca.calls[-1][2] == stamp('2026-10-02T16:00:00-04:00')


def test_实时adapter单次冻结并发与异常恢复():
    from tradingagents.dataflows.config import run_config, get_config
    barrier = threading.Barrier(2)
    def fetch(fail=False):
        cutoff = get_config()['news_cutoff_utc']
        barrier.wait()
        assert get_config()['news_cutoff_utc'] == cutoff
        if fail:
            raise RuntimeError('固定错误')
        return cutoff
    wrapped = _wrap(fetch)
    assert _wrap(wrapped) is wrapped
    def work(hour, fail):
        now = datetime(2026, 10, 3, hour, tzinfo=NEW_YORK)
        calls = []
        with live_information_scope(lambda: calls.append(now) or now), run_config({'_daily_live_information_clock': lambda: now, 'news_cutoff_utc': None}):
            try:
                result = wrapped(fail)
            except RuntimeError:
                result = '失败'
            assert get_config()['news_cutoff_utc'] is None and len(calls) == 1
            return result
    with ThreadPoolExecutor(2) as pool:
        a, b = list(pool.map(lambda pair: work(*pair), [(11, False), (12, True)]))
    assert a.splitlines()[0] == '2026-10-03T15:00:00+00:00' and b == '失败'


def test_实际Alpaca工具与AV回退按每次查询过滤(monkeypatch):
    from tradingagents.dataflows.config import run_config
    from tradingagents.dataflows import router
    from tradingagents.dataflows.vendors.alpaca import news
    from tradingagents.dataflows.vendors.alpha_vantage import news as av
    from tradingagents.agents.tools import get_news
    now = [stamp('2026-10-04T11:00:00-04:00')]
    class Client:
        def get_news(self, *args, **kwargs):
            return {'articles': [
                {'headline': '已发布', 'created_at': '2026-10-04T14:59:00Z'},
                {'headline': '后续新消息', 'created_at': '2026-10-04T15:05:00Z'},
                {'headline': '未来消息', 'created_at': '2026-10-04T20:00:00Z'}], 'truncated': False}
    monkeypatch.setattr(news, 'get_shared_client', lambda: Client())
    monkeypatch.setattr(av, '_make_api_request', lambda *a: json.dumps({'feed': [
        {'title': 'AV已发布', 'time_published': '20261004T145900'},
        {'title': 'AV未来', 'time_published': '20261004T200000'},
        {'title': 'AV未核验'}]}))
    install_live_information_adapter()
    original = router.VENDOR_METHODS['get_news']['alpaca']
    install_live_information_adapter()
    assert original is router.VENDOR_METHODS['get_news']['alpaca']
    config = {'_daily_live_information_clock': lambda: now[0], 'news_cutoff_utc': None,
              'market_timezone': 'America/New_York', 'tool_vendors': {'get_news': 'alpaca'}}
    with live_information_scope(lambda: now[0]), run_config(config):
        first = get_news.func('NVDA', '2026-10-03', '2026-10-04', '2026-10-04')
        now[0] += timedelta(minutes=10)
        second = get_news.func('NVDA', '2026-10-03', '2026-10-04', '2026-10-04')
        alpha = router.VENDOR_METHODS['get_news']['alpha_vantage']('NVDA', '2026-10-03', '2026-10-04')
    assert '已发布' in first and '后续新消息' not in first and '未来消息' not in second
    assert '后续新消息' in second and 'AV已发布' in alpha and 'AV未来' not in alpha and 'AV未核验' not in alpha
    assert '发布时间无法核验 1 条' in alpha and '不等于没有消息' in first
    with run_config({'news_cutoff_utc': '2026-10-04T14:00:00Z'}):
        assert any(row['title'] == 'AV未来' for row in json.loads(router.VENDOR_METHODS['get_news']['alpha_vantage']('NVDA', '2026-10-03', '2026-10-04'))['feed'])


@pytest.mark.parametrize("failed", [False, True])
def test_休市runner成功及失败都不声称开盘(tmp_path, failed, monkeypatch):
    monkeypatch.setattr("daily_analyzer.runner._codex_version", lambda settings: "固定版本")
    root = _project(tmp_path, ('NVDA',))
    now = stamp('2026-10-03T11:00:00-04:00')
    _FakeGraph.fail_symbols = {"NVDA"} if failed else set()
    result = _run(root, tickers='NVDA', force=True, clock=lambda: now,
                  analyzer_factory=_FakeGraph, context_manager=_ContextManager(), site_builder=lambda root: {})
    assert result.exit_code == (1 if failed else 0)
    _FakeGraph.fail_symbols = set()
    paths = list((root / 'data/runs/2026-10-03/batches').glob('*/results/*.json'))
    saved = json.loads(paths[0].read_text())
    assert saved['target_session'] == '休市日（最近盘后）' and not saved['started_after_open'] and not saved['finished_after_open']
    assert saved['price_data_end_date'] == '2026-10-02' and saved['mode'] == 'live'


def test_社交实际预取与Yahoo回退排除未来(monkeypatch):
    import io
    from types import SimpleNamespace
    from tradingagents.dataflows.config import run_config
    from tradingagents.dataflows import router
    from tradingagents.agents.analysts import sentiment_analyst
    from tradingagents.dataflows.vendors import stocktwits, reddit
    from tradingagents.dataflows.vendors.yahoo import news as yahoo
    now = stamp('2026-10-04T11:00:00-04:00')
    past, future = '2026-10-04T14:59:00Z', '2026-10-04T20:00:00Z'
    monkeypatch.setattr(stocktwits, 'urlopen', lambda *a, **kw: io.BytesIO(json.dumps({'messages': [
        {'body': '已发布社交', 'created_at': past}, {'body': '未来社交', 'created_at': future}, {'body': '无时间'}]}).encode()))
    monkeypatch.setattr(reddit, '_fetch_subreddit_rss', lambda *a, **kw: [
        {'title': '已发布Reddit', 'created_utc': stamp(past.replace('Z', '+00:00')).timestamp(), 'subreddit': 'stocks'},
        {'title': '未来Reddit', 'created_utc': stamp(future.replace('Z', '+00:00')).timestamp(), 'subreddit': 'stocks'}])
    monkeypatch.setattr(yahoo.yf, 'Ticker', lambda *a: SimpleNamespace(get_news=lambda **kw: [
        {'content': {'title': '已发布Yahoo', 'pubDate': past}}, {'content': {'title': '未来Yahoo', 'pubDate': future}}]))
    install_live_information_adapter()
    with live_information_scope(lambda: now), run_config({'_daily_live_information_clock': lambda: now, 'news_cutoff_utc': None}):
        social = sentiment_analyst.fetch_stocktwits_messages('NVDA', start_date='2026-10-03', end_date='2026-10-04')
        discussion = sentiment_analyst.fetch_reddit_posts('NVDA', start_date='2026-10-03', end_date='2026-10-04')
        news = router.VENDOR_METHODS['get_news']['yfinance']('NVDA', '2026-10-03', '2026-10-04')
    assert '已发布社交' in social and '未来社交' not in social and '无时间' not in social
    assert '已发布Reddit' in discussion and '未来Reddit' not in discussion
    assert '已发布Yahoo' in news and '未来Yahoo' not in news


def test_默认私有clock泄漏不影响非图调用与propagate异常恢复(monkeypatch):
    from types import SimpleNamespace
    from tradingagents.dataflows.config import run_config
    from daily_analyzer.analyzer import AnalyzerGraph
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from daily_analyzer.live_information import _ACTIVE_CLOCK
    now = stamp('2026-10-04T11:00:00-04:00')
    wrapper = _wrap(lambda: '原函数')
    with run_config({'_daily_live_information_clock': lambda: now, 'news_cutoff_utc': None}):
        assert wrapper() == '原函数' and _ACTIVE_CLOCK.get() is None
    graph = object.__new__(AnalyzerGraph)
    graph.mode, graph._clock = 'live', lambda: now
    def fail(*a, **kw):
        assert _ACTIVE_CLOCK.get() is graph._clock
        raise RuntimeError('固定错误')
    monkeypatch.setattr(TradingAgentsGraph, 'propagate', fail)
    with pytest.raises(RuntimeError):
        graph.propagate('NVDA', '2026-10-04')
    assert _ACTIVE_CLOCK.get() is None


@pytest.mark.parametrize('field', ['pre_update_time', 'overnight_update_time', 'data_date+data_time'])
def test_最近盘后生产与页面都拒绝跨时段时间证据(field):
    now = stamp('2026-10-04T11:00:00-04:00')
    candidate = {'price': 105, 'quote_time': '2026-10-02T19:58:00-04:00',
                 'time_field': field, 'source': '富途其他时段'}
    produced = observation('NVDA', now, candidate, recent_after=True)
    assert produced['status'] == '真实行情时间未核验'
    # 持久status不能为自身担保，页面独立重验时间字段关联。
    forged = {**candidate, 'status': '可用', 'session_verified': True,
              'symbol': 'NVDA', 'cutoff': now.isoformat()}
    result = {'symbol': 'NVDA', 'mode': 'live', 'context_as_of': now.isoformat(),
              'price_data_end_date': '2026-10-02', 'context_blocks': {'extended_hours': {
              'as_of': now.isoformat(), 'data': {'NVDA': {'analysis_quote': forged}}}}}
    assert _summary_premarket(result)['price'] == ''


def test_富途盘后价缺独立时间不借盘前或夜盘字段():
    now = stamp('2026-10-04T11:00:00-04:00')
    provider = ExtendedHoursProvider(_services(futu=FakeFutu(rows={'US.NVDA': {
        'after_price': 105, 'pre_update_time': '2026-10-02 19:58:00',
        'overnight_update_time': '2026-10-02 19:58:00',
        'data_date': '2026-10-02', 'data_time': '19:58:00'}})))
    provider.prepare(batch(now))
    quote = provider.build({'symbol': 'NVDA'}, now).data['NVDA']['analysis_quote']
    assert quote['status'] == '真实行情时间未核验' and quote['quote_time'] is None

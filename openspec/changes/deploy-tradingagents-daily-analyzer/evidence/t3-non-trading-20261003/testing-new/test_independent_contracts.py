"""固定原始样本独立检查盘后及信息工具契约。"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
import json
import threading
import operator
from typing import Annotated, TypedDict

import pytest

from daily_analyzer.context.analysis_quote import observation, recent_after_window
from daily_analyzer.context.providers import ExtendedHoursProvider, MacroReleasesProvider
from daily_analyzer.context.base import ContextManager, render_context
from daily_analyzer.live_information import install_live_information_adapter, live_information_scope, _ACTIVE_CLOCK
from daily_analyzer.site import _summary_premarket
from test_context_providers import FakeFutu, FakeAlpaca, FakePrices, _services


def dt(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


@pytest.mark.parametrize('time,field,valid', [
    ('2026-10-02T15:59:59-04:00', 'latestTrade.t', False),
    ('2026-10-02T16:00:00-04:00', 'latestTrade.t', False),
    ('2026-10-02T16:00:00-04:00', 'minute.t', False),
    ('2026-10-02T16:00:00-04:00', 'after_update_time', True),
    ('2026-10-02T16:00:01-04:00', 'latestTrade.t', True),
    ('2026-10-02T19:59:00-04:00', 'minute.t', True),
    ('2026-10-02T19:59:30-04:00', 'minute.t', False),
    ('2026-10-02T20:00:00-04:00', 'latestTrade.t', False),
    ('2026-10-01T19:59:00-04:00', 'after_update_time', False),
    ('2026-10-03T13:00:01-04:00', 'after_update_time', False),
    ('2026-10-02T19:59:00-04:00', 'update_time', False),
])
def test_周末盘后真实时段证据严格边界(time, field, valid):
    cutoff = dt('2026-10-03T13:00:00-04:00')
    quote = observation('QQQ', cutoff, {'price': 123.45, 'quote_time': time,
                         'time_field': field, 'source': '固定同源 IEX', 'warning': 'IEX 覆盖不完整'}, recent_after=True)
    assert (quote['status'] == '可用') == valid
    if valid:
        assert quote['session'] == 'after' and quote['quote_time'] == time
        assert quote['source'] == '固定同源 IEX'
        assert quote['age_seconds'] == (cutoff - dt(time)).total_seconds()
        assert '陈旧' in quote['warning'] and 'IEX' in quote['warning']


def test_半日最近盘后按实际十三点至二十点():
    start, end = recent_after_window(dt('2026-11-28T09:00:00-05:00'))
    assert start == dt('2026-11-27T13:00:00-05:00')
    assert end == dt('2026-11-27T20:00:00-05:00')
    for field in ('latestTrade.t', 'minute.t'):
        q = observation('QQQ', end + timedelta(days=1), {'price': 100, 'quote_time': start.isoformat(), 'time_field': field}, recent_after=True)
        assert q['status'] != '可用'


@pytest.mark.parametrize('field', ['pre_update_time', 'overnight_update_time', 'data_date+data_time'])
def test_盘后字段不可借用其他时段时间通过持久结果页面重验(field):
    cutoff = dt('2026-10-04T11:00:00-04:00')
    quote = observation('QQQ', cutoff, {'price': 105, 'quote_time': '2026-10-02T19:58:00-04:00',
                      'time_field': field, 'source': '富途盘前'}, recent_after=True)
    result = {'symbol': 'QQQ', 'mode': 'live', 'context_as_of': cutoff.isoformat(),
              'price_data_end_date': '2026-10-02', 'context_blocks': {'extended_hours': {
              'as_of': cutoff.isoformat(), 'data': {'QQQ': {'analysis_quote': quote}}}}}
    assert quote['status'] != '可用'
    assert _summary_premarket(result)['price'] == ''
    quote['status'] = '可用'
    assert _summary_premarket(result)['price'] == ''


def test_跨收盘P保持冻结且宏观信息仍用后续获取时点():
    initial = dt('2026-10-02T15:59:00-04:00')
    later = dt('2026-10-02T16:02:00-04:00')
    batch = {'trade_date': date(2026, 10, 2), 'price_data_end_date': date(2026, 10, 1),
             'mode': 'live', 'context_as_of': initial, 'items': []}
    alpaca = FakeAlpaca(news={'articles': [
        {'headline': '收盘后最新消息', 'created_at': '2026-10-02T20:01:00Z'},
        {'headline': '未来不能混入', 'created_at': '2026-10-02T20:03:00Z'}], 'truncated': False})
    services = _services(alpaca=alpaca)
    provider = ExtendedHoursProvider(services)
    provider.prepare(batch)
    with pytest.raises(ValueError, match='日线截止不一致'):
        provider.build({'symbol': 'QQQ'}, later)
    assert batch['price_data_end_date'] == date(2026, 10, 1)
    manager = ContextManager(['extended_hours'], services=services)
    manager.prepare({**batch, 'items': [{'symbol': 'QQQ'}]})
    degraded = manager.build({'symbol': 'QQQ'}, later)['extended_hours']
    assert '不可用' in degraded.markdown
    projected = _summary_premarket({'symbol': 'QQQ', 'mode': 'live', 'price_data_end_date': '2026-10-01',
        'context_as_of': later.isoformat(), 'context_blocks': {'extended_hours': {
        'as_of': later.isoformat(), 'data': degraded.data}}})
    assert projected['price'] == ''
    macro = MacroReleasesProvider(services)
    macro.prepare(batch)
    block = macro.build({'symbol': 'QQQ'}, later)
    assert block.as_of == later and '收盘后最新消息' in block.markdown
    assert '未来不能混入' not in block.markdown
    assert alpaca.calls[-1][2:4] == (dt('2026-10-02T16:00:00-04:00'), later)


def test_真实工具fallback逐次查询排除未来并恢复上下文(monkeypatch):
    from tradingagents.dataflows.config import run_config, get_config
    from tradingagents.dataflows import router
    from tradingagents.dataflows.vendors.alpaca import news
    from tradingagents.dataflows.vendors.yahoo import news as yahoo
    from tradingagents.agents.tools import get_news
    from types import SimpleNamespace
    calls = []
    now = [dt('2026-10-04T13:00:00-04:00')]
    class Failure:
        def get_news(self, *args, **kwargs):
            calls.append(('failed_alpaca', get_config()['news_cutoff_utc']))
            raise RuntimeError('固定供应商失败')
    monkeypatch.setattr(news, 'get_shared_client', lambda: Failure())
    def rows(**kwargs):
        calls.append(('yahoo', get_config()['news_cutoff_utc']))
        return [{'content': {'title': title, 'pubDate': time}} for title, time in [
            ('周六新闻', '2026-10-03T21:00:00Z'), ('运行中新消息', '2026-10-04T17:01:00Z'),
            ('同日未来消息', '2026-10-04T23:00:00Z')]]
    monkeypatch.setattr(yahoo.yf, 'Ticker', lambda *args: SimpleNamespace(get_news=rows))
    install_live_information_adapter()
    config = {'news_cutoff_utc': None, '_daily_live_information_clock': lambda: now[0],
              'tool_vendors': {'get_news': 'alpaca,yfinance'}, 'market_timezone': 'America/New_York'}
    with run_config(config):
        with live_information_scope(lambda: now[0]):
            first = get_news.func('QQQ', '2026-10-03', '2026-10-04', '2026-10-04')
            assert get_config()['news_cutoff_utc'] is None
            now[0] += timedelta(minutes=2)
            second = get_news.func('QQQ', '2026-10-03', '2026-10-04', '2026-10-04')
        assert _ACTIVE_CLOCK.get() is None
    assert '周六新闻' in first and '运行中新消息' not in first
    assert '运行中新消息' in second and '同日未来消息' not in second
    assert calls == [('failed_alpaca', '2026-10-04T17:00:00+00:00'), ('yahoo', '2026-10-04T17:00:00+00:00'),
                     ('failed_alpaca', '2026-10-04T17:02:00+00:00'), ('yahoo', '2026-10-04T17:02:00+00:00')]


def test_live与回放并发实际新闻工具各用自己的截止(monkeypatch):
    from tradingagents.dataflows.config import run_config, get_config
    from tradingagents.dataflows.vendors.alpaca import news
    from tradingagents.agents.tools import get_news
    barrier = threading.Barrier(2)
    class Client:
        def get_news(self, *args, **kwargs):
            barrier.wait(timeout=3)
            return {'articles': [{'headline': '回放前', 'created_at': '2026-10-02T12:30:00Z'},
                                  {'headline': '周末后', 'created_at': '2026-10-03T21:00:00Z'}], 'truncated': False}
    monkeypatch.setattr(news, 'get_shared_client', lambda: Client())
    install_live_information_adapter()
    now = dt('2026-10-04T13:00:00-04:00')
    def invoke(historical):
        cutoff = '2026-10-02T12:31:00Z' if historical else None
        config = {'news_cutoff_utc': cutoff, '_daily_live_information_clock': lambda: now,
                  'tool_vendors': {'get_news': 'alpaca'}, 'market_timezone': 'America/New_York'}
        with run_config(config), live_information_scope(lambda: now):
            result = get_news.func('QQQ', '2026-10-01', '2026-10-04', '2026-10-04')
            assert get_config()['news_cutoff_utc'] == cutoff
            return result
    with ThreadPoolExecutor(2) as pool:
        live, replay = list(pool.map(invoke, [False, True]))
    assert '周末后' in live and '周末后' not in replay and '回放前' in replay
    assert _ACTIVE_CLOCK.get() is None


def test_AnalyzerGraph传播作用域经过实际LangGraph并发节点仍传到新闻工具(monkeypatch):
    from langgraph.graph import StateGraph, START, END
    from daily_analyzer.analyzer import AnalyzerGraph
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.dataflows.config import run_config, get_config
    from tradingagents.dataflows.vendors.alpaca import news
    from tradingagents.agents.tools import get_news
    fixed = dt('2026-10-04T13:00:00-04:00')
    barrier = threading.Barrier(2)
    calls = []
    class Client:
        def get_news(self, *args, **kwargs):
            calls.append(get_config()['news_cutoff_utc'])
            barrier.wait(timeout=3)
            return {'articles': [{'headline': '已发布证据', 'created_at': '2026-10-04T16:59:00Z'},
                                  {'headline': '未来不得进入', 'created_at': '2026-10-04T17:01:00Z'}], 'truncated': False}
    monkeypatch.setattr(news, 'get_shared_client', lambda: Client())
    install_live_information_adapter()
    class State(TypedDict):
        notes: Annotated[list[str], operator.add]
    builder = StateGraph(State)
    for name in ('新闻一', '新闻二'):
        builder.add_node(name, lambda state: {'notes': [
            get_news.func('QQQ', '2026-10-03', '2026-10-04', '2026-10-04')]})
        builder.add_edge(START, name)
        builder.add_edge(name, END)
    compiled = builder.compile()
    monkeypatch.setattr(TradingAgentsGraph, 'propagate', lambda self, *a, **kw: compiled.invoke({'notes': []}))
    graph = object.__new__(AnalyzerGraph)
    graph.mode, graph._clock = 'live', lambda: fixed
    with run_config({'news_cutoff_utc': None, '_daily_live_information_clock': lambda: fixed,
                     'tool_vendors': {'get_news': 'alpaca'}, 'market_timezone': 'America/New_York'}):
        result = graph.propagate('QQQ', '2026-10-04')
        assert get_config()['news_cutoff_utc'] is None
    assert len(calls) == 2 and set(calls) == {'2026-10-04T17:00:00+00:00'}
    assert len(result['notes']) == 2
    assert all('已发布证据' in text and '未来不得进入' not in text for text in result['notes'])
    assert _ACTIVE_CLOCK.get() is None

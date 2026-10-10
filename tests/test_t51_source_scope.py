"""T51 日线目标归属：背景成功不能覆盖目标缺失。"""
import pytest
from daily_analyzer.source_status import SourceStatusCollector


def event(symbol, outcome='success', source='alpaca', method='daily_bars'):
    return dict(category='日线', method=method, symbol=symbol, outcome=outcome,
                source=source, error='目标无日线' if outcome != 'success' else '')


def test_background_and_unattributed_success_cannot_cover_target():
    collector = SourceStatusCollector(seed=[event('SPY'), event('QQQ'), event(None), event('SPACEX', 'no_data')])
    row = collector.snapshot({}, {}, symbol='SPACEX', analysis_symbol='SPACEX')[0]
    assert row['status'] == '失败' and row['source'] == '—'
    assert '目标无日线' in row['reason'] and '背景日线2次' in row['reason']
    assert len(row['attempts']) == 4
    assert [e['scope'] for e in row['attempts']] == ['背景', '背景', '归属未明', '目标']


@pytest.mark.parametrize('symbol', ['SPY', 'QQQ'])
def test_healthy_target_ignores_background_failure(symbol):
    collector = SourceStatusCollector(seed=[event(symbol), event('OTHER', 'failed')])
    row = collector.snapshot({}, {}, symbol=symbol, analysis_symbol=symbol)[0]
    assert row['status'] == '正常' and row['source'] == 'alpaca'
    assert '目标无日线' not in row['reason']


def test_explicit_index_proxy_and_fallback():
    collector = SourceStatusCollector(seed=[event('SPY', 'no_data'), event('SPY', source='futu'), event('QQQ')])
    row = collector.snapshot({}, {}, symbol='^GSPC', analysis_symbol='SPY')[0]
    assert row['status'] == '降级' and row['source'] == 'futu'
    assert [e['scope'] for e in row['attempts']] == ['目标', '目标', '背景']


def test_other_symbol_anchor_does_not_supply_target():
    collector = SourceStatusCollector(seed=[event('SPY'), event('SPACEX', 'failed')])
    blocks = {'price_anchors': {'data': {'symbol': 'SPY', 'anchors': {}, 'source': 'futu'}}}
    row = collector.snapshot(blocks, {}, symbol='SPACEX', analysis_symbol='SPACEX')[0]
    assert row['status'] == '失败'
    assert row['attempts'][-1]['scope'] == '背景'


def test_news_scope_remains_cross_symbol():
    collector = SourceStatusCollector(seed=[dict(event('SPY'), category='新闻', method='get_news')])
    row = collector.snapshot({}, {}, symbol='SPACEX', analysis_symbol='SPACEX')[2]
    assert row['status'] == '正常'
    assert 'scope' not in row['attempts'][0]


@pytest.mark.parametrize('mode,expected', [('backfill', '2026-10-08T08:31:00-04:00'), ('live', None)])
def test_analyzer_passes_frozen_cutoff_to_memory_without_date_exemption(monkeypatch, mode, expected):
    from datetime import datetime
    from types import SimpleNamespace
    from daily_analyzer.analyzer import AnalyzerGraph
    import tradingagents.graph.trading_graph as graph_module
    monkeypatch.setattr(graph_module, 'is_historical', lambda *_: False)
    graph = object.__new__(AnalyzerGraph)
    seen = []
    graph.mode = mode
    graph.context_as_of = datetime.fromisoformat('2026-10-08T08:31:00-04:00')
    graph.item = SimpleNamespace(symbol='^GSPC')
    graph.settle_pending = lambda *_: None
    graph.memory_log = SimpleNamespace(get_past_context=lambda ticker, **kw: seen.append((ticker, kw['as_of'])) or '')
    graph.propagator = SimpleNamespace(create_initial_state=lambda *a, **kw: {'instrument_context': kw['instrument_context']})
    graph.resolve_instrument_context = lambda *a: '固定身份'
    graph.injected_context = graph.brief_injected_context = ''
    graph.context_compaction = True
    graph.context_profiles = {}
    graph.create_run_state('SPY', '2026-10-08')
    assert seen == [('^GSPC', expected)]

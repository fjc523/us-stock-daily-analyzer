"""TU53 SDK字段构造行与真实落盘夹具的离线验收；禁止行情和SEC网络。"""
import inspect
import json
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import yaml

from daily_analyzer.context.price_anchors import PriceAnchorsProvider
from daily_analyzer.context.supply_events import SupplyEventsProvider, SupplyEvent
from daily_analyzer.data_sources.futu import FutuDataSource

FIX = Path(__file__).parent / 'fixtures/tu53'
ROOT = Path(__file__).resolve().parents[1]
CUTOFF = datetime.fromisoformat('2026-10-12T08:31:55-04:00')


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import requests
    monkeypatch.setattr(requests.sessions.Session, 'request', lambda *a, **k: pytest.fail('离线测试禁止网络'))


@pytest.mark.parametrize('valid', [True, False, None, float('nan'), 0, 'False', np.bool_(False)])
def test_sdk_fields_and_valuation_states(monkeypatch, valid):
    """按SDK实际键构造的行，不是真实市场快照。"""
    import futu.quote.quote_query as sdk
    source_text = inspect.getsource(sdk)
    keys = ('pe_ttm_ratio', 'pb_ratio', 'total_market_val', 'circular_market_val')
    assert all('"' + key + '"' in source_text or "'" + key + "'" in source_text for key in keys)
    assert all(key not in source_text for key in ('equity_pe_ratio', 'equity_pb_ratio', 'equity_market_val'))
    import tradingagents.dataflows.date_window as window
    monkeypatch.setattr(window, 'is_historical', lambda _: False)
    row = dict(zip(keys, [-2, 0, 123, float('nan')]))
    row['equity_valid'] = valid
    source = FutuDataSource()
    monkeypatch.setattr(source, '_call', lambda method, **kw: ([row],) if method == 'get_market_snapshot' else ({},))
    text = source.fundamentals('TSLA', '2026-10-12')
    false = isinstance(valid, (bool, np.bool_)) and not valid
    assert ('不适用（非正股' in text) == false
    if not false:
        assert '亏损或不适用（原值 -2）' in text and '净资产为负或不适用（原值 0）' in text
        assert '缺失' in text and '123' in text
    assert '快照原始估值' in text and '"pe_ttm_ratio": -2' in text


def bars(symbol):
    return pd.read_csv(FIX / f'daily_bars/{symbol}-alpaca-data.csv').to_dict('records')


def provider(monkeypatch, tmp_path, payload=None, symbol='SPCX'):
    from tradingagents.dataflows.vendors import sec_edgar as sec
    cik = '0001181412' if symbol == 'SPCX' else '0001318605'
    file = 'submissions_CIK0001181412_batch20261012.json' if symbol == 'SPCX' else 'submissions_CIK0001318605.json'
    submission = json.loads((FIX / 'sec' / file).read_text())
    monkeypatch.setattr(sec, 'cik_for', lambda _: cik)
    monkeypatch.setattr(sec, '_cached_json', lambda *a: submission)
    (tmp_path / 'config').mkdir(exist_ok=True)
    (tmp_path / 'config/supply_events.yaml').write_text(payload or (ROOT / 'config/supply_events.yaml').read_text())
    p = SupplyEventsProvider(SimpleNamespace(project_root=tmp_path, prices=SimpleNamespace(bars=lambda *a: (bars('SPCX'), 'Alpaca SIP'))))
    p.prepare({'price_data_end_date': '2026-10-09'})
    return p


def test_supply_window_pit_and_quantity(monkeypatch, tmp_path):
    p = provider(monkeypatch, tmp_path)
    block = p.build({'symbol': 'SPCX', 'type': 'stock'}, CUTOFF)
    assert block.data['status'] == '有事件'
    assert len(block.data['events']) == 3
    for text in ['2026-10-09', '2026-10-24／首个可交易日 2026-10-26', '第2个完整交易日', '最多1,300,000,000股', '≈3.4个20日均量日', '占流通盘：未知']:
        assert text in block.markdown
    old = p.build({'symbol': 'SPCX', 'type': 'stock'}, datetime.fromisoformat('2026-06-11T23:59:00-04:00'))
    assert old.data['status'] == '已核查无' and old.data['events'] == []


@pytest.mark.parametrize('kind,symbol', [('etf','SPY'), ('etf','QQQ'), ('index','^GSPC')])
def test_supply_not_applicable(monkeypatch, tmp_path, kind, symbol):
    p = provider(monkeypatch, tmp_path)
    assert p.build({'symbol': symbol, 'type': kind, 'proxy': 'SPY'}, CUTOFF) is None


def test_supply_checked_unknown_and_invalid(monkeypatch, tmp_path):
    p = provider(monkeypatch, tmp_path, symbol='TSLA')
    assert p.build({'symbol': 'TSLA', 'type': 'stock'}, CUTOFF).data['status'] == '已核查无'
    p = provider(monkeypatch, tmp_path, 'events: []')
    assert p.build({'symbol': 'SPCX', 'type': 'stock'}, CUTOFF).data['status'] == '未知·未录入'
    p = provider(monkeypatch, tmp_path, 'events: [')
    assert p.build({'symbol': 'SPCX', 'type': 'stock'}, CUTOFF).data['status'] == '未知·来源不可得'
    payload = yaml.safe_load((ROOT / 'config/supply_events.yaml').read_text())
    payload['events'].append({'symbol': 'SPCX', 'kind': 'bad'})
    p = provider(monkeypatch, tmp_path, yaml.safe_dump(payload))
    block = p.build({'symbol': 'SPCX', 'type': 'stock'}, CUTOFF)
    assert len(block.data['events']) == 3 and len(block.data['invalid_entries']) == 1
    assert block.data['status'] == '未知·来源不可得'


@pytest.mark.parametrize('symbol', ['SPY', 'QQQ', 'TSLA'])
def test_full_anchors_unchanged(symbol):
    baseline = json.loads((FIX / f'results/result_{symbol}_20261012.json').read_text())
    p = PriceAnchorsProvider(SimpleNamespace(prices=SimpleNamespace(bars=lambda *a: (bars(symbol), 'Alpaca SIP'))))
    p.prepare({'price_data_end_date': '2026-10-09'})
    block = p.build({'symbol': symbol}, CUTOFF)
    # 来源标签与生产原件一致时，满窗Markdown逐字保持。
    original = baseline['price_anchors']
    assert block.markdown.replace('Alpaca SIP', original['data']['source']) == original['markdown']


@pytest.mark.parametrize('symbol,kind', [('SPCX','stock'), ('SPY','etf'), ('SPY','index')])
def test_short_anchors_identity(symbol, kind):
    rows = bars(symbol)[-83:]
    p = PriceAnchorsProvider(SimpleNamespace(prices=SimpleNamespace(bars=lambda *a: (rows, 'Alpaca SIP'))))
    p.prepare({'price_data_end_date': '2026-10-09'})
    block = p.build({'symbol': '^GSPC' if kind == 'index' else symbol, 'proxy': 'SPY' if kind == 'index' else None}, CUTOFF)
    assert '实有83交易日，首个有效日线' in block.markdown
    assert '252d_High' in block.data['anchors'] and '样本起点不代表上市日期' in block.markdown
    if symbol == 'SPCX':
        assert block.data['anchors']['252d_High']['value'] == 225.64
        assert block.data['window_252d_first_date'] == '2026-06-12'
    if kind == 'index':
        assert block.markdown.startswith('标的SPY')


@pytest.mark.parametrize('title', ['SPCX', 'SPY', '^GSPC→SPY'])
def test_news_truncation_coverage_and_unchanged_text(title):
    from tradingagents.dataflows.vendors.alpaca import news
    payload = json.loads((FIX / 'results/news_alpaca_market_news_20261012.json').read_text())
    articles = payload['market_news']
    start = datetime.fromisoformat('2026-10-01T00:00:00-04:00')
    expected = [f'## {title}\n']
    for row in articles:
        expected.extend([f"### {row.get('headline', 'No title')} (source: {row.get('source', 'Alpaca')}, created_at: {row['created_at']})", ''])
    plain = news._format(title, {'articles': articles, 'truncated': False}, start, CUTOFF)
    assert plain == '\n'.join(expected)
    text = news._format(title, {'articles': articles, 'truncated': True}, start, CUTOFF)
    earliest = min(articles, key=lambda row: news._parse_created(row['created_at']))['created_at']
    assert text.startswith(plain) and '结果已截断' in text and f'最早一条 created_at={earliest}' in text
    assert '窗口起点' in text and '未覆盖' in text


def test_supply_configuration_registration_and_default_analysts():
    from daily_analyzer.config import Settings, parse_settings, DEFAULT_ANALYSTS
    from daily_analyzer.context.providers import PROVIDER_CLASSES
    assert 'supply_events' in Settings().context_providers
    for file in ('settings.yaml', 'settings.example.yaml'):
        settings = parse_settings(yaml.safe_load((ROOT / 'config' / file).read_text()))
        assert 'supply_events' in settings.context_providers
    assert PROVIDER_CLASSES['supply_events'] is SupplyEventsProvider
    assert 'fundamentals' not in DEFAULT_ANALYSTS['etf']
    assert 'fundamentals' not in DEFAULT_ANALYSTS['index']


@pytest.mark.parametrize('outside', ['2000-01-01', '2200-01-01'])
def test_supply_dates_outside_calendar_preserve_visible_events(monkeypatch, tmp_path, outside):
    """合法但窗口外旧/远期条款不应使当前窗口有效事件全部丢失。"""
    import copy
    payload = yaml.safe_load((ROOT / 'config/supply_events.yaml').read_text())
    row = copy.deepcopy(payload['events'][0])
    row['date'] = outside
    payload['events'].append(row)
    p = provider(monkeypatch, tmp_path, yaml.safe_dump(payload))
    block = p.build({'symbol': 'SPCX', 'type': 'stock'}, CUTOFF)
    assert block.data['status'] == '有事件'
    assert len(block.data['events']) == 3
    assert '2026-10-24／首个可交易日 2026-10-26' in block.markdown

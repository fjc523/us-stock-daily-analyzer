"""发行方权重、缓存、有效广度及PIT隔离的确定输入测试。"""
from datetime import datetime, date, timedelta, timezone
from io import BytesIO
import json
from types import SimpleNamespace

from openpyxl import Workbook
import pandas as pd
import pytest

from daily_analyzer.config import Settings, WatchlistItem
from daily_analyzer.context.etf_structure import ETFStructureProvider, concentration, share_changes
from daily_analyzer.context.compaction import render_compacted_context
from daily_analyzer.data_sources.etf_holdings import ETFHoldingsSource, parse_holdings
from daily_analyzer.source_status import SourceStatusCollector

NOW = datetime(2026, 10, 4, tzinfo=timezone.utc)
END = date(2026, 10, 2)


def qqq_raw():
    return json.dumps({'effectiveDate': '2026-10-03', 'effectiveBusinessDate': '2026-10-02',
                      'totalNumberOfHoldings': 4,
                      'holdings': [{'ticker': 'AAA', 'percentageOfTotalNetAssets': 60, 'securityTypeName': 'Common Stock'},
                                   {'ticker': 'BBB', 'percentageOfTotalNetAssets': 40.2, 'securityTypeName': 'Common Stock'},
                                   {'ticker': None, 'percentageOfTotalNetAssets': -.2, 'securityTypeName': 'Synthetic Cash'},
                                   {'ticker': 'USDPDV', 'percentageOfTotalNetAssets': None, 'securityTypeName': 'Currency'}]}).encode()


def test_issuer_percent_not_normalized_and_non_equity_rows_preserved():
    data = parse_holdings('QQQ', qqq_raw())
    assert data['weight_unit'] == '%' and '月度' in data['update_frequency']
    assert data['holdings_as_of'] == '2026-10-03' and data['effective_business_date'] == '2026-10-02'
    assert data['published_at'] is None and not data['shares_history']
    metrics = concentration(data['holdings'])
    assert metrics['total_weight_pct'] == pytest.approx(100)
    assert metrics['max_weight_pct'] == 60 and metrics['missing_weight_count'] == 1
    assert data['holdings'][2]['weight_pct'] == -.2


def test_spy_public_weight_column_not_shares_held():
    book = Workbook(); sheet = book.active
    sheet.append(['Holdings:', 'As of 01-Oct-2026'])
    sheet.append(['Name', 'Ticker', 'Weight', 'Shares Held'])
    sheet.append(['甲', 'AAA', 60.2, 99999])
    sheet.append(['乙', 'BBB', 40, 12345])
    stream = BytesIO(); book.save(stream)
    data = parse_holdings('SPY', stream.getvalue())
    assert concentration(data['holdings'])['total_weight_pct'] == pytest.approx(100.2)
    assert data['shares_history'] == [] and data['holdings_as_of'] == '2026-10-01'


def test_one_day_cache_raw_evidence_and_backfill_never_requests_current(tmp_path):
    calls = []
    clock = [NOW]
    def get(url, **kwargs):
        calls.append(url)
        return SimpleNamespace(content=qqq_raw(), raise_for_status=lambda: None)
    source = ETFHoldingsSource(tmp_path, get=get, clock=lambda: clock[0])
    first = source.holdings('QQQ')
    assert first['status'] == 'available' and not first['cache_hit']
    assert source.holdings('QQQ')['cache_hit'] and len(calls) == 1
    again = ETFHoldingsSource(tmp_path, get=get, clock=lambda: clock[0])
    assert again.holdings('QQQ')['cache_hit'] and len(calls) == 1
    saved = json.loads((tmp_path/'QQQ.json').read_text())
    assert saved['raw_response_base64']
    clock[0] += timedelta(days=1)
    assert not source.holdings('QQQ')['cache_hit'] and len(calls) == 2
    assert source.holdings('QQQ', mode='backfill')['status'] == 'unavailable'
    assert len(calls) == 2


def test_unsupported_source_and_missing_weights_degrade(tmp_path):
    source = ETFHoldingsSource(tmp_path, get=lambda *a, **kw: (_ for _ in ()).throw(AssertionError('不得网络')))
    assert source.holdings('SQQQ')['status'] == 'unavailable'
    malformed = json.loads(qqq_raw()); malformed['totalNumberOfHoldings'] = 99
    with pytest.raises(ValueError, match='不完整'):
        parse_holdings('QQQ', json.dumps(malformed).encode())


def make_provider():
    snapshot = {**parse_holdings('QQQ', qqq_raw()), 'status': 'available', 'fetched_at': NOW.isoformat()}
    calls = []
    def bars(symbol, end):
        calls.append(symbol)
        days = pd.bdate_range(end=end, periods=210 if symbol == 'AAA' else 60)
        return [{'date': stamp.date().isoformat(), 'close': i + 1} for i, stamp in enumerate(days)], '固定复权来源'
    services = SimpleNamespace(etf_holdings=SimpleNamespace(holdings=lambda *a, **kw: snapshot),
                               prices=SimpleNamespace(bars=bars), analysis_mode='live')
    provider = ETFStructureProvider(services)
    provider.prepare({'price_data_end_date': END})
    return provider, calls


def test_breadth_valid_counts_weight_cover_and_both_profiles():
    provider, calls = make_provider()
    block = provider.build(WatchlistItem(symbol='^NDX', type='index'), NOW)
    assert block.data['symbol'] == 'QQQ'
    assert calls == ['AAA', 'BBB']
    assert block.data['selected_weight_pct'] == pytest.approx(100.2)
    assert block.data['excluded_weight_pct'] == -.2
    assert block.data['breadth']['50']['valid_count'] == 2
    assert block.data['breadth']['200']['valid_count'] == 1
    assert block.data['breadth']['200']['valid_weight_pct'] == 60
    assert block.data['breadth']['200']['above_pct'] == 100
    assert block.data['share_changes']['change_5d_pct'] is None
    for profile in ('brief', 'full'):
        text = render_compacted_context({'etf_structure': block}, NOW, profile=profile)
        assert 'ETF 结构' in text and 'MA200' in text and '有效权重覆盖' in text
    status = next(row for row in SourceStatusCollector().snapshot({'etf_structure': block.to_dict()}, {})
                  if row['category'] == 'ETF 结构')
    assert status['status'] == '正常' and '覆盖不足' in status['reason']
    assert provider.build(WatchlistItem(symbol='SMTC', type='stock'), NOW) is None
    assert 'etf_structure' in Settings().context_providers


def test_top50_limit_and_concentration():
    provider, calls = make_provider()
    holdings = [{'symbol': f'S{i}', 'weight_pct': 1.0} for i in range(60)]
    source = provider.source.holdings('QQQ')
    provider.source = SimpleNamespace(holdings=lambda *a, **kw: {**source, 'holdings': holdings})
    block = provider.build({'symbol': 'QQQ', 'type': 'etf'}, NOW)
    assert len(calls) == 50 and block.data['selected_count'] == 50
    assert block.data['top10_weight_pct'] == 10 and block.data['selected_weight_pct'] == 50


def test_share_changes_exact_xnys_endpoints_and_unit_guard():
    from daily_analyzer.context.market_data import _expected_sessions
    days = _expected_sessions(END, 21)
    history = [{'date': str(day), 'shares': 100 + i, 'unit': '股'} for i, day in enumerate(days)]
    result = share_changes(history, END)
    assert result['change_20d_pct'] == pytest.approx(20)
    assert result['change_5d_pct'] == pytest.approx((120/115-1)*100)
    history[0]['unit'] = '万股'
    assert all(value is None for value in share_changes(history, END).values())
    assert all(value is None for value in share_changes([], END).values())


@pytest.mark.parametrize('count,available', [(49, False), (50, True), (199, False), (200, True)])
def test_breadth_exact_ma_threshold_without_return_extra_endpoint(count, available):
    from daily_analyzer.context.etf_structure import breadth_averages
    from daily_analyzer.context.market_data import _expected_sessions
    days = _expected_sessions(END, count)
    rows = [{'date': str(day), 'close': i + 1} for i, day in enumerate(days)]
    window = 50 if count <= 50 else 200
    assert (breadth_averages(rows, END)[f'sma_{window}d'] is not None) is available
    if available:
        assert breadth_averages(rows, END)[f'sma_{window}d'] == pytest.approx((count+1)/2)
        assert breadth_averages(rows[:-1], END)[f'sma_{window}d'] is None
        assert breadth_averages(rows[:20] + rows[21:], END)[f'sma_{window}d'] is None


def test_only_index_may_use_proxy_etf_cannot_disguise_complex_or_other_fund():
    provider, _ = make_provider()
    calls = []
    original = provider.source.holdings('QQQ')
    provider.source = SimpleNamespace(holdings=lambda symbol, **kw: calls.append(symbol) or original)
    for item in ({'symbol': 'SQQQ', 'type': 'etf', 'proxy': 'QQQ'},
                 {'symbol': 'SPY', 'type': 'etf', 'proxy': 'QQQ'},
                 {'symbol': '^NDX', 'type': 'index', 'proxy': 'QQQ'},
                 {'symbol': '^GSPC', 'type': 'index'}):
        provider.build(item, NOW)
    assert calls == ['SQQQ', 'SPY', 'QQQ', 'SPY']

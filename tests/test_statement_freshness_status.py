"""来源状态按实际财报来源/期末记录时效，陈旧不得显示正常。"""
import pytest

from daily_analyzer.source_status import SourceStatusCollector
from tradingagents.dataflows import router
from tradingagents.dataflows.config import run_config
from tradingagents.dataflows.errors import StaleVendorDataError
from tradingagents.dataflows.vendor_observer import set_vendor_observer, reset_vendor_observer


@pytest.mark.parametrize('fresh_fallback', [True, False])
def test_router_statement_status_is_actual_and_stale_is_degraded(monkeypatch, fresh_fallback):
    collector = SourceStatusCollector()
    token = set_vendor_observer(collector.observe)
    metadata = {'actual_source': 'sec_edgar', 'latest_period': '2026-04-26', 'expected_period': '2026-07-26',
                'filing_date': '2026-08-26', 'as_of_date': '2026-10-02', 'stale': True, 'reason': '固定SEC汇总缺口'}
    def sec(*args):
        raise StaleVendorDataError('固定SEC汇总缺口', original_text='# SEC原表\n,2026-04-26\nRevenue,1',
                                  statement_metadata=metadata, minimum_period='2026-07-26')
    def fallback(*args):
        return '# Yahoo固定\n,' + ('2026-07-26' if fresh_fallback else '2026-04-26') + '\nRevenue,2'
    monkeypatch.setitem(router.VENDOR_METHODS, 'get_income_statement', {'sec_edgar': sec, 'yfinance': fallback})
    config = {'tool_vendors': {'get_income_statement': 'sec_edgar,yfinance'}}
    try:
        with run_config(config):
            text = router.route_to_vendor('get_income_statement', 'SMTC', 'quarterly', '2026-10-02')
    finally:
        reset_vendor_observer(token)
    row = next(row for row in collector.snapshot({}, config) if row['category'] == '财报报表')
    assert row['status'] == '降级'
    assert row['actual_source'] == ('yfinance' if fresh_fallback else 'sec_edgar')
    assert row['source'] == row['actual_source']
    assert row['stale'] is not fresh_fallback
    assert row['latest_period'] == ('2026-07-26' if fresh_fallback else '2026-04-26')
    assert row['latest_period'] in row['reason'] and '实际来源' in row['reason']
    assert len(row['statements']) == 1
    if not fresh_fallback:
        assert text.startswith('⚠')


def test_annual_coverage_reason_keeps_quarterly_body_period():
    collector = SourceStatusCollector()
    collector.observe({'method': 'get_cashflow', 'source': 'sec_edgar', 'outcome': 'success',
                       'statement_metadata': {'actual_source': 'sec_edgar', 'latest_period': '2026-03-31',
                                              'annual_covered_period': '2026-06-30', 'stale': False,
                                              'reason': '年度申报2026-06-30已收录，第四季度未单列，不推算Q4'}})
    row = next(row for row in collector.snapshot({}, {}) if row['category'] == '财报报表')
    assert row['status'] == '正常' and row['latest_period'] == '2026-03-31'
    assert '2026-06-30' in row['reason'] and '第四季度未单列' in row['reason']


@pytest.mark.parametrize('seeded', [False, True])
def test_statement_metadata_uses_existing_redaction_in_all_projections(seeded):
    import json
    event = {'method': 'get_income_statement', 'source': 'sec_edgar', 'outcome': 'success',
             'statement_metadata': {'actual_source': 'sec_edgar', 'latest_period': '2026-04-26',
                                    'stale': True, 'reason': '合成秘密-123 https://example.test/private?token=synthetic'}}
    if seeded:
        event['category'] = '财报报表'
    collector = SourceStatusCollector(['合成秘密-123'], seed=[event] if seeded else [])
    if not seeded:
        collector.observe(event)
    row = next(row for row in collector.snapshot({}, {}) if row['category'] == '财报报表')
    text = json.dumps(row, ensure_ascii=False)
    assert '合成秘密-123' not in text and 'https://' not in text and 'synthetic' not in text
    assert '[已隐藏]' in text and '[链接已隐藏]' in text
    assert row['latest_period'] == '2026-04-26' and row['stale'] is True


def test_seed_statement_event_error_and_source_use_existing_redaction():
    import json
    secret = '合成种子秘密'
    seed = {'category': '财报报表', 'method': 'get_income_statement',
            'source': 'sec_edgar https://example.test/private?token=synthetic', 'outcome': 'success',
            'error': secret + ' https://example.test/private?token=synthetic',
            'statement_metadata': {'actual_source': 'sec_edgar', 'latest_period': '2026-04-26',
                                   'stale': True, 'reason': secret}}
    collector = SourceStatusCollector([secret], seed=[seed])
    row = next(row for row in collector.snapshot({}, {}) if row['category'] == '财报报表')
    payload = json.dumps(row, ensure_ascii=False)
    assert secret not in payload and 'https://' not in payload and 'synthetic' not in payload
    assert row['latest_period'] == '2026-04-26' and row['stale'] is True
    assert '[已隐藏]' in row['reason'] and '[链接已隐藏]' in row['attempts'][0]['error']

"""上下文瘦身、真实交易日窗口、来源数据不变及兼容档位测试。"""
from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from daily_analyzer.context.base import render_context
from daily_analyzer.context.compaction import calendar_markdown, render_compacted_context
from daily_analyzer.data_sources.treasury import TreasuryYieldSource, summarize_yields
from tradingagents.agents.context import get_instrument_context_from_state

ET = ZoneInfo('America/New_York')
AS_OF = datetime(2026, 10, 2, 9, tzinfo=ET)


def fixture_blocks():
    """构造312条确定输入；真实10-02文件另在ignored evidence回放。"""
    economics = []
    for i in range(312):
        level = 'HIGH' if i < 77 else 'MEDIUM' if i < 219 else 'LOW'
        stamp = AS_OF + timedelta(days=i % 28)
        economics.append({'title': f'美国事件{i}', 'star': level, '发布时间ET': stamp.isoformat(),
                          'previous': '1.00', 'consensus': '2', 'actual': '3'})
    data = {'calendars': {'economics': economics, 'earnings': [{'security': 'US.SMTC', 'date': '2026-10-05'}]},
            'treasury_yield': ''}
    return {'macro_releases': {'title': '经济数据', 'as_of': AS_OF.isoformat(), 'sources': ['固定来源'],
                              'data': data, 'markdown': '固定原文\n#### 决策周期日历（富途）\n[{旧版日历}]'},
            'market_regime': {'title': '市场环境', 'as_of': '2026-10-01', 'sources': ['固定来源'],
                              'data': {}, 'markdown': '市场基线'}}


def test_compaction_retains_all_high_and_raw_312_without_json():
    blocks = fixture_blocks()
    before = deepcopy(blocks)
    full = render_compacted_context(blocks, AS_OF)
    for i in range(77):
        assert f'|事件{i}|' in full
    assert '[{' not in full
    assert '已省略' in full
    assert sum(line.startswith('|') for line in full.splitlines()) > 25
    assert len(blocks['macro_releases']['data']['calendars']['economics']) == 312
    assert blocks == before


def test_brief_uses_five_xnys_sessions_and_future_high_only():
    # 周五起有效期为10月2/5/6/7/8，10月9不属于第五交易日。
    rows = [dict(title=title, star=level, 发布时间ET=stamp, actual='99') for title, level, stamp in [
        ('过去HIGH', 'HIGH', '2026-10-02T08:30:00-04:00'),
        ('第五日HIGH', 'HIGH', '2026-10-08T08:30:00-04:00'),
        ('第六日HIGH', 'HIGH', '2026-10-09T08:30:00-04:00'),
        ('有效MEDIUM', 'MEDIUM', '2026-10-05T08:30:00-04:00'),
        ('LOW', 'LOW', '2026-10-05T08:30:00-04:00'),
    ]]
    short = calendar_markdown({'economics': rows}, AS_OF, short=True)
    assert '第五日HIGH' in short and '未发布' in short and '|99|' not in short
    for title in ('过去HIGH', '第六日HIGH', '有效MEDIUM', 'LOW'):
        assert title not in short
    assert '另有 4 条' in short
    full = calendar_markdown({'economics': rows}, AS_OF)
    assert '过去HIGH' in full and '有效MEDIUM' in full and '第六日HIGH' in full
    assert '|99|' in full


def test_calendar_zero_estimate_and_year_boundary():
    row = dict(title='新年数据', star='HIGH', 发布时间ET='2027-01-04T08:30:00-05:00',
               actual='0', consensus=0, previous='1')
    text = calendar_markdown({'economics': [row]}, datetime(2026, 12, 31, 9, tzinfo=ET))
    assert '2027-01-04' in text and '未发布' in text


def test_legacy_renderer_independent_golden_is_unchanged():
    blocks = {'test': {'title': '固定', 'as_of': '2026-10-01', 'sources': ['来源'], 'data': {},
                       'markdown': '旧表\n[{"事件":1}]'}}
    expected = ('## 附加市场上下文（截至 2026-10-02T09:00:00-04:00）\n\n'
                '### 固定\n数据时间：2026-10-01；数据源：来源\n旧表\n[{"事件":1}]')
    assert render_context(blocks, AS_OF) == expected


@pytest.mark.parametrize('role', ['market_analyst', 'fundamentals_analyst', 'sentiment_analyst',
                                 'bull_researcher', 'bear_researcher', 'trader',
                                 'aggressive_debator', 'conservative_debator', 'neutral_debator'])
def test_brief_role_defaults(role):
    state = {'instrument_context': '原上下文', 'instrument_context_full': '完整版',
             'instrument_context_brief': '精简版', 'context_compaction': True}
    assert get_instrument_context_from_state(state, profile=role) == '精简版'


@pytest.mark.parametrize('role', ['news_analyst', 'research_manager', 'portfolio_manager'])
def test_full_role_defaults_and_disabled_legacy(role):
    state = {'instrument_context': '原上下文', 'instrument_context_full': '完整版',
             'instrument_context_brief': '精简版', 'context_compaction': True}
    assert get_instrument_context_from_state(state, profile=role) == '完整版'
    state['context_compaction'] = False
    assert get_instrument_context_from_state(state, profile=role) == '原上下文'


def test_profile_is_graph_private_and_reports_single_symbol_earnings():
    state = {'instrument_context': '旧', 'instrument_context_full': '全', 'instrument_context_brief': '简',
             'context_compaction': True, 'context_profiles': {'market_analyst': 'full'}}
    other = {**state, 'context_profiles': {'market_analyst': 'brief'}}
    assert get_instrument_context_from_state(state, profile='market_analyst') == '全'
    assert get_instrument_context_from_state(other, profile='market_analyst') == '简'
    brief = render_compacted_context(fixture_blocks(), AS_OF, profile='brief')
    assert 'US.SMTC' in brief and '2026-10-05' in brief
    assert '固定原文' not in brief


def test_yield_summary_calculation_and_constant_range():
    start = AS_OF.date() - timedelta(days=90)
    rows = [{'观测日': (start + timedelta(days=i)).isoformat(), '数值': 3 + i / 100} for i in range(91)]
    text = summarize_yields(rows, 'DGS10', AS_OF.date(), spread=.5, complete=True)
    assert '较5个观测日前+5.00bp' in text and '较20个观测日前+20.00bp' in text
    assert '90日区间3–3.9%' in text and '当前位置100.0%' in text
    assert '10Y-2Y利差+0.50百分点' in text
    fixed = summarize_yields([{'观测日': '2026-10-01', '数值': 4}], 'DGS10', AS_OF.date())
    assert '历史不足' in fixed and '覆盖不足' in fixed and '位置不可计算' in fixed


def test_source_90_day_summary_uses_internal_full_window_but_keeps_40_rows(monkeypatch):
    import tradingagents.dataflows.config as config
    import json
    end = AS_OF.date() - timedelta(days=1)
    monkeypatch.setattr(config, 'get_config', lambda: {'price_data_end_date': end.isoformat()})
    rows = [(end - timedelta(days=89-i)).isoformat() + f',2,{1 if i == 0 else 4}' for i in range(90)]
    response = SimpleNamespace(raise_for_status=lambda: None,
                               text='observation_date,DGS2,DGS10\n' + '\n'.join(rows))
    source = TreasuryYieldSource(lambda *args, **kwargs: response)
    original = source.macro('10y_treasury', AS_OF.date().isoformat(), 90)
    assert len(json.loads(original.rsplit('\n', 1)[1])) == 40
    assert '90日区间1–4%' in source.compact(original)
    assert '10Y-2Y利差+2.00百分点' in source.compact(original)
    fresh_source = TreasuryYieldSource(lambda *args, **kwargs: pytest.fail('历史渲染不补拉网络'))
    assert '90日覆盖不足' in fresh_source.compact(original)
    assert '区间4–4%' in fresh_source.compact(original)


def test_analyzer_state_contains_both_profiles_and_disabled_golden(monkeypatch, tmp_path):
    from daily_analyzer.analyzer import AnalyzerGraph
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.graph.propagation import Propagator
    import daily_analyzer.data_sources.futu as futu

    def init(graph, **kwargs):
        graph.propagator = Propagator()
        graph.memory_log = SimpleNamespace(get_past_context=lambda *a, **kw: '')
    monkeypatch.setattr(TradingAgentsGraph, '__init__', init)
    monkeypatch.setattr(AnalyzerGraph, 'settle_pending', lambda *a: None)
    monkeypatch.setattr(AnalyzerGraph, '_memory_as_of', lambda *a: '2026-10-02')
    monkeypatch.setattr(futu, 'get_shared_data_source', lambda: SimpleNamespace(identity=lambda *a: {}))
    monkeypatch.setattr(TradingAgentsGraph, 'resolve_instrument_context', lambda *a: '固定身份')
    item = SimpleNamespace(type='stock', symbol='SMTC', name=None, analysts=['market'], analysis_symbol='SMTC')
    config = {'context_compaction': False, 'price_data_end_date': '2026-10-01',
              'news_cutoff_utc': '2026-10-02T13:00:00+00:00'}
    old = AnalyzerGraph(item=item, mode='backfill', config=config, state_log_dir=tmp_path,
                        context_blocks=fixture_blocks(), context_as_of=AS_OF, clock=lambda: AS_OF)
    expected_framework = ('## 决策框架\n运行时点：2026-10-02T09:00:00-04:00；附加上下文截至：2026-10-02T09:00:00-04:00；'
                          '信息截止：2026-10-02T13:00:00+00:00。\n最新完整日线日期P：2026-10-01。\n'
                          '方向与目标配置周期：未来5–20个交易日；点位方案有效期：分析当日起5个交易日。\n'
                          '单标的标准仓位=100%，是该标的计划持仓量，不是账户总资产比例或现有持仓买卖比例。')
    assert old.injected_context == expected_framework + '\n\n' + render_context(fixture_blocks(), AS_OF)
    state = old.create_run_state('SMTC', '2026-10-02')
    assert state['instrument_context_full'] == state['instrument_context_brief'] == state['instrument_context']
    new = AnalyzerGraph(item=item, mode='backfill', config={**config, 'context_compaction': True},
                        state_log_dir=tmp_path, context_blocks=fixture_blocks(), context_as_of=AS_OF, clock=lambda: AS_OF)
    state = new.create_run_state('SMTC', '2026-10-02')
    assert state['instrument_context_full'] != state['instrument_context_brief']
    assert state['instrument_context_full'].startswith('固定身份\n\n')
    assert state['instrument_context_brief'].startswith('固定身份\n\n')
    assert '[{' not in state['instrument_context_full']


@pytest.mark.parametrize('offsets', [[0], [10, 5, 0], [90, 89, 88]])
def test_new_source_partial_or_stale_window_does_not_claim_full_90_days(monkeypatch, offsets):
    import tradingagents.dataflows.config as config
    end = AS_OF.date() - timedelta(days=1)
    monkeypatch.setattr(config, 'get_config', lambda: {'price_data_end_date': end.isoformat()})
    csv = 'observation_date,DGS2,DGS10\n' + '\n'.join(
        (end - timedelta(days=n)).isoformat() + ',2,4' for n in offsets)
    source = TreasuryYieldSource(lambda *a, **kw: SimpleNamespace(raise_for_status=lambda: None, text=csv))
    original = source.macro('10y_treasury', AS_OF.date().isoformat(), 90)
    compact = source.compact(original)
    assert '90日覆盖不足' in compact and f'已有{len(offsets)}点' in compact
    assert f'截止P={end}' in compact and '观测年龄' in compact
    assert '90日区间' not in compact


def test_complete_window_weekend_and_us_holiday_boundaries():
    # 2026-07-03为独立日补假，07-04/05周末，最早观测07-06不是覆盖缺失。
    end = datetime(2026, 10, 1).date()
    import pandas as pd
    from pandas.tseries.holiday import USFederalHolidayCalendar
    business_day = pd.offsets.CustomBusinessDay(calendar=USFederalHolidayCalendar())
    rows = [{'观测日': stamp.date().isoformat(), '数值': 4}
            for stamp in pd.date_range('2026-07-06', '2026-10-01', freq=business_day)]
    assert '90日区间' in summarize_yields(rows, 'DGS10', end, complete=True)
    assert '覆盖不足' in summarize_yields(rows[:1] + rows[-1:], 'DGS10', end, complete=True)
    weekend_end = datetime(2026, 10, 3).date()
    rows.append({'观测日': '2026-10-02', '数值': 4})
    assert '90日区间' in summarize_yields(rows, 'DGS10', weekend_end, complete=True)

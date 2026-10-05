"""T38观察权限与展示边界的通用回归；不调用模型或修改历史。"""
from copy import deepcopy
import pytest
from daily_analyzer.evaluation.plan_checks import decision_plan_checks,leg_conflict_flags,check_buy_leg,execution_matrix,_anchor_names,SUPPORTS
from daily_analyzer.site import _marks
from daily_analyzer.context.compaction import _calendar_unit,_difference
from daily_analyzer.evaluation.report import render_report,analyze,scheme_report
from daily_analyzer.evaluation.price_plans import evaluate_leg,evaluate_plan


def payload(buy):
    return {'structured':{'pm_decision':{'rating':'Overweight','buy_legs':buy,
        'reduce_legs':[{'kind':'风险减配','trigger_price':97,'post_allocation_pct':60}]},'trader_proposal':{}},
        'context_blocks':{'price_anchors':{'data':{'anchors':{'P_Low':98,'20d_High':106,'atr':2}}}}}


def active(**extra):
    return {'status':'可执行','zone_low':99,'zone_high':100,'stop_loss':97,'first_target':106,
        'stop_anchor':'P_Low−0.5ATR','target_anchor':'20d_High','target_method':'阻力位',**extra}


@pytest.mark.parametrize('buys', [[active(status='待触发')],
    [active(status='待触发'),{'status':'仅观察','trigger_price':97}], [{'status':'仅观察','trigger_price':97}]])
def test_g1_observation_does_not_mark_r36(buys):
    result=payload(buys);before=deepcopy(result);flags=decision_plan_checks(result,{})
    assert [x['status'] for x in flags['plan_checks']['pm']]==[x['status'] for x in buys]
    assert '点位规则未通过' not in _marks({**result,'decision_flags':flags})
    assert result==before


def test_g2_observation_backsolve_still_marks():
    result=payload([{'status':'仅观察','reason':'为满足盈亏比将止损改到97'}]);flags=decision_plan_checks(result,{})
    assert '点位规则未通过' in _marks({**result,'decision_flags':flags})


def test_g3_executable_unanchored_still_marks():
    result=payload([active(stop_loss=95)]);flags=decision_plan_checks(result,{})
    assert flags['plan_checks']['pm'][0]['checks']['stop_unanchored']
    assert '点位规则未通过' in _marks({**result,'decision_flags':flags})


@pytest.mark.parametrize('status,expected',[('仅观察',False),('可执行',True),('待触发',True),(None,False)])
def test_g4_risk_compares_only_executing_buy(status,expected):
    assert leg_conflict_flags('Overweight',[{'status':status,'zone_low':171.10,'zone_high':179.87}],
        [{'kind':'风险减配','trigger_price':179.87,'post_allocation_pct':100}])['risk_trigger_above_buy_zone']==expected


def test_g5_old_parsed_text_and_persisted_missing_status_keep_marks():
    result=payload([]);result['structured']['pm_decision']['reduce_legs']=[];result['structured']['pm_decision'].update(entry_plan='区间99–100美元',stop_loss=95,first_target=106)
    flags=decision_plan_checks(result,{})
    assert flags['plan_checks']['pm'][0]['status']=='parsed_zone'
    assert '点位规则未通过' in _marks({**result,'decision_flags':flags})
    old={'decision_flags':{'plan_checks':{'pm':[{'checks':{'stop_unanchored':True}}]}}};before=deepcopy(old)
    assert '点位规则未通过' in _marks(old) and old==before


def test_o1_prices_have_two_decimals_without_changing_values():
    buys=[active(zone_low=12345.67,zone_high=12345.678,stop_loss=12300,first_target=12500)]
    before=deepcopy(buys);rows=execution_matrix('Buy',125,buys,[])
    assert '12345.67–12345.68，止损12300.00，目标12500.00' in rows[0]['text']
    assert '补至125%' in rows[1]['text'] and buys==before


@pytest.mark.parametrize('name,key',[('52周高','252d_High'),('MA50','close_50_sma'),('SMA20','close_20_sma'),
    ('P_Low−0.03ATR','P_Low'),('P日前高','P_High'),('60日高点','60d_High')])
def test_o2_clear_aliases(name,key):
    assert list(_anchor_names(name,SUPPORTS))==[key]


@pytest.mark.parametrize('name',['前高','MA500','SMA2000','120日高','150日均线','2520日低','xP_Low','P_Low_extra'])
def test_o2_ambiguous_or_wrong_period_not_guessed(name):
    assert not list(_anchor_names(name,SUPPORTS))


def test_o2_exact_key_wins_and_name_diagnostics_separate_wrong_price():
    assert list(_anchor_names('P_Low−0.03ATR；MA50说明',SUPPORTS))==['P_Low']
    anchors={'P_Low':98,'20d_High':106,'atr':2}
    missing=check_buy_leg(active(stop_anchor='未知别名'),anchors)
    wrong=check_buy_leg(active(stop_loss=95),anchors)
    assert missing['stop_anchor_name_status']=='unrecognized' and wrong['stop_anchor_name_status']=='recognized'
    assert missing['checks']['stop_unanchored'] and wrong['checks']['stop_unanchored']


def test_o6_reduction_v2_label_only_and_original_numeric_contract():
    from test_t37_point_legs import DATES
    bars={day:{'open':105,'high':106,'low':104,'close':103} for day in DATES}
    v1=evaluate_plan({'kind':'减仓','parse_status':'parsed','low':104,'high':106},bars,
        start=DATES[0],end=DATES[-1],basis='next_open')
    v2=evaluate_leg({'kind':'超配回落','zone_low':104,'zone_high':106},bars,
        start=DATES[0],entry_end=DATES[4],end=DATES[-1],basis='next_open')
    assert v1['exit_reason']=='减仓有效期末' and v2['exit_reason']=='减仓20日期末'
    for key in ('entry_price','exit_price','exit_date','direction_adjusted_return','mfe_pct','mae_pct'):
        assert v1[key]==v2[key]


def test_o7_both_report_entries_label_unwritten_and_keep_input():
    from datetime import datetime
    from daily_analyzer.time_utils import NEW_YORK
    rows=[{'run_id':'old','symbol':'TEST','trade_date':'2026-10-02','ratings':{'pm':'Hold'},'windows':{}}]
    before=deepcopy(rows)
    text=render_report(rows,analyze(rows,window=5),datetime(2026,10,5,7,tzinfo=NEW_YORK))
    assert '模型方案计数：default（推断，未写入） n=1' in text
    assert '|default（推断，未写入）|' in scheme_report(rows) and rows==before
    rows.append({**rows[0],'run_id':'new','llm':{'scheme':'default','source':'result_explicit','model_fingerprint':'deep=NOT_REPORTED/NOT_REPORTED;quick=NOT_REPORTED/NOT_REPORTED'}})
    assert 'default（其中推断未写入 n=1）' in scheme_report(rows)


@pytest.mark.parametrize('rate',['月率','年率','季率','参与率','利用率'])
@pytest.mark.parametrize('suffix',['','终值','初值','修正值'])
def test_o8_explicit_rate_suffix_is_percentage_point(rate,suffix):
    unit=_calendar_unit({'title':'美国9月工业'+rate+suffix})
    assert unit=='%' and _difference('0.1','0',unit)=='+0.1百分点（高于预期）'
    assert _calendar_unit({'title':'美国9月订单终值'}) is None

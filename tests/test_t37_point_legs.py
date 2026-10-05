"""逐腿确认、5日入场/20日退出和历史v1冻结，全部合成OHLC。"""
import copy
import json
from datetime import datetime
from pathlib import Path

import exchange_calendars as xcals
import pytest

from daily_analyzer.evaluation.price_plans import extract_plans,evaluate_leg,evaluate_plan,point_report
from daily_analyzer.evaluation.settlement import settle,load_outcomes
from daily_analyzer.config import EvaluationSettings


DATES=[stamp.date().isoformat() for stamp in xcals.get_calendar('XNYS').sessions_in_range('2026-10-05','2026-10-30')]


def breakout(**extra):
    return {'kind':'买入','buy_kind':'突破','status':'待触发','zone_low':201.99,'zone_high':204.9,
        'trigger_rule':'收盘站上','trigger_price':201.99,'confirm_days':1,'stop_loss':190.33,
        'first_target':239.87,'target_method':'ATR替代',**extra}


def bars():
    values={day:{'open':210,'high':215,'low':208,'close':212} for day in DATES}
    values[DATES[0]]={'open':200,'high':203,'low':199,'close':201}
    values[DATES[1]]={'open':201.5,'high':204,'low':200,'close':203}
    values[DATES[2]]={'open':203.5,'high':207,'low':202,'close':205}
    values[DATES[11]]={'open':212,'high':240,'low':210,'close':238}
    return values


def evaluate(plan=None,values=None,**kwargs):
    return evaluate_leg(plan or breakout(),values or bars(),start=DATES[0],entry_end=DATES[4],
        end=kwargs.pop('end',DATES[-1]),basis=kwargs.pop('basis','next_open'),**kwargs)


def test_confirm_then_fill_and_v1_period_difference():
    outcome=evaluate()
    assert outcome['confirmation_date']==DATES[1] and outcome['entry_date']==DATES[2]
    assert outcome['entry_price']==203.5 and outcome['exit_date']==DATES[11]
    assert outcome['exit_reason']=='第一目标' and outcome['realized_r']==pytest.approx(2.761579347)
    legacy=evaluate_plan({'kind':'建仓','parse_status':'parsed','low':201.99,'high':204.9,
        'stop_loss':190.33,'first_target':239.87},bars(),start=DATES[0],end=DATES[4],basis='next_open')
    assert legacy['entry_price']==200 and legacy['trigger_date']==DATES[0]
    assert legacy['exit_date']==DATES[4] and legacy['exit_reason']=='有效期末'


def test_gap_above_waits_for_overlap_and_gap_below_cancels():
    values=bars();values[DATES[2]]={'open':206,'high':210,'low':205.5,'close':207}
    values[DATES[3]]={'open':206,'high':208,'low':204,'close':207}
    outcome=evaluate(values=values)
    assert outcome['entry_date']==DATES[3] and outcome['entry_price']==204.9
    values[DATES[2]]={'open':199,'high':203,'low':197,'close':201}
    outcome=evaluate(values=values)
    assert outcome['triggered'] is False and '确认后跌回区间下方' in outcome['reason']
    assert 'entry_price' not in outcome


def test_two_day_confirmation_strictly_after_and_entry_window_limit():
    values=bars();values[DATES[3]]={'open':204,'high':206,'low':203,'close':205}
    outcome=evaluate(breakout(confirm_days=2),values)
    assert outcome['confirmation_date']==DATES[2] and outcome['entry_date']==DATES[3]
    values=bars()
    for day in DATES[:4]:values[day]['close']=201
    values[DATES[4]]['close']=203
    outcome=evaluate(values=values)
    assert outcome['triggered'] is False and outcome['confirmation_date']==DATES[4]
    assert 'entry_price' not in outcome


def test_risk_next_open_direction_percentages_and_observation_no_trade():
    values={day:{'open':185,'high':187,'low':180,'close':183} for day in DATES}
    values[DATES[2]]={'open':183,'high':184,'low':178,'close':179}
    for day in DATES[3:]:values[day]={'open':178,'high':181,'low':158,'close':160}
    outcome=evaluate({'kind':'风险减配','trigger_rule':'收盘跌破','trigger_price':179.87},values)
    assert outcome['trigger_date']==DATES[2] and outcome['entry_date']==DATES[3]
    assert outcome['direction_adjusted_return']==pytest.approx(18/178)
    assert outcome['mfe_pct']==pytest.approx(20/178) and outcome['mae_pct']==pytest.approx(3/178)
    assert 'realized_r' not in outcome
    observe=evaluate(breakout(status='仅观察'))
    assert observe['level_touched'] is True
    assert not set(observe)&{'entry_price','exit_price','realized_r','triggered'}


def test_per_leg_targets_and_extraction_versions():
    legs=[{'kind':'回踩','status':'可执行','zone_low':727.41,'zone_high':730,
        'stop_loss':715.7,'first_target':754.54,'target_method':'阻力位'},
        {'kind':'突破','status':'待触发','zone_low':754.54,'zone_high':756.91,
         'trigger_rule':'收盘站上','trigger_price':754.54,'confirm_days':1,
         'stop_loss':745.05,'first_target':775.89,'target_method':'ATR替代'}]
    result={'structured':{'pm_decision':{'buy_legs':legs,'first_target':754.54}},
            'context_blocks':{'price_anchors':{'data':{'anchors':{'atr':{'value':9.49}}}}}}
    plans=extract_plans(result)
    assert list(plans)==['buy_1','buy_2']
    assert [plan['first_target'] for plan in plans.values()]==[754.54,775.89]
    assert all(plan['rule_version']=='c4-v2' and plan['provenance']=='structured_legs' for plan in plans.values())
    values={day:{'open':760,'high':765,'low':758,'close':762} for day in DATES}
    values[DATES[0]]={'open':729,'high':731,'low':728,'close':730}
    values[DATES[1]]={'open':749,'high':756,'low':748,'close':755}
    values[DATES[2]]={'open':756,'high':758,'low':755,'close':757}
    values[DATES[11]]={'open':770,'high':776,'low':768,'close':774}
    results=[evaluate(plan,values) for plan in plans.values()]
    assert [out['exit_price'] for out in results]==[754.54,775.89]
    assert results[0]['realized_r']==pytest.approx((754.54-729)/(729-715.7))
    assert results[1]['realized_r']==pytest.approx((775.89-756)/(756-745.05))
    legacy=extract_plans({'structured':{'pm_decision':{'entry_plan':'区间99–100美元'}}})
    assert 'entry_plan' in legacy and 'rule_version' not in legacy['entry_plan']


@pytest.mark.parametrize('kwargs,status', [({'end':None},'pending'),({'mature':False},'pending'),
    ({'units_verified':False},'indeterminate'),({'basis':'same_day_close'},'indeterminate')])
def test_missing_window_and_units_are_not_settled(kwargs,status):
    assert evaluate(**kwargs)['status']==status


def test_conservative_exit_missing_stop_and_post_entry_gap():
    values=bars();values[DATES[2]]={'open':203.5,'high':240,'low':189,'close':205}
    outcome=evaluate(values=values)
    assert outcome['same_day_dual'] and outcome['exit_price']==190.33
    values=bars();values[DATES[3]]={'open':180,'high':185,'low':179,'close':183}
    outcome=evaluate(values=values)
    assert outcome['exit_reason']=='跳空止损' and outcome['exit_price']==180
    assert evaluate(breakout(stop_loss=None))['status']=='indeterminate'


class Services:
    def __init__(self):self.prices=self
    def sector(self,symbol):return None
    def bars(self,symbol,end):
        return [{'date':'2026-10-02','open':200,'high':202,'low':198,'close':200},
                *[{'date':day,**row} for day,row in bars().items()]],'固定合成'


def record(legs=True):
    from test_evaluation import raw
    value=raw('QQQ',finished='2026-10-02T23:00:00-04:00')
    value['price_data_end_date']='2026-10-02'
    value['context_blocks']['price_anchors']['data']={'source':'固定合成','anchors':{
        'P_Close':{'value':200,'date':'2026-10-02'},'atr':{'value':11.6552}}}
    value['structured']={'pm_decision':{'buy_legs':[{**breakout(),'kind':'突破'}]}} if legs else {}
    if not legs:value['final_trade_decision']='**建仓点位**: 区间201.99–204.9美元\n\n**Stop Loss**: 190.33\n\n**First Target**: 239.87'
    return value


def test_settlement_uses_frozen_20_window_and_v1_outcome_unchanged(tmp_path):
    from test_evaluation import write_run
    source=record();write_run(tmp_path,source)
    settle(tmp_path,settings=EvaluationSettings(),services=Services(),now=datetime.fromisoformat('2026-10-09T20:00:00-04:00'))
    row=load_outcomes(tmp_path/'data/evaluation/outcomes.jsonl')[0]
    assert row['point_plans']['buy_1']['outcome']['status']=='pending'
    settle(tmp_path,settings=EvaluationSettings(),services=Services(),now=datetime.fromisoformat('2026-10-30T20:00:00-04:00'))
    row=load_outcomes(tmp_path/'data/evaluation/outcomes.jsonl')[0]
    outcome=row['point_plans']['buy_1']['outcome']
    assert outcome['end']==row['windows']['20']['exit_date']==DATES[-1]
    assert outcome['entry_end']==DATES[4] and outcome['realized_r']==pytest.approx(2.761579347)
    old=record(False);old['run_id']='old';write_run(tmp_path,old)
    settle(tmp_path,settings=EvaluationSettings(),services=Services(),now=datetime.fromisoformat('2026-10-30T20:00:00-04:00'))
    old_row=next(row for row in load_outcomes(tmp_path/'data/evaluation/outcomes.jsonl') if row['run_id']=='old')
    snapshot=json.dumps(old_row['point_plans'],sort_keys=True)
    full_snapshot=json.dumps(old_row,sort_keys=True)
    old['structured']=copy.deepcopy(source['structured']);write_run(tmp_path,old)
    settle(tmp_path,settings=EvaluationSettings(),services=Services(),now=datetime.fromisoformat('2026-11-02T20:00:00-05:00'))
    old_after=next(row for row in load_outcomes(tmp_path/'data/evaluation/outcomes.jsonl') if row['run_id']=='old')
    assert json.dumps(old_after['point_plans'],sort_keys=True)==snapshot
    assert json.dumps(old_after,sort_keys=True)==full_snapshot


def test_report_versions_and_semantic_distance_groups():
    old={'kind':'建仓','outcome':{'status':'settled','triggered':False}}
    new={**breakout(),'rule_version':'c4-v2','target_distance_bucket':'>3ATR','outcome':evaluate()}
    text=point_report([{'symbol':'TEST','point_plans':{'entry_plan':old,'buy_1':new}}])
    assert '点位方案（c4-v1）' in text and '点位方案（c4-v2）' in text
    assert '|买入|待触发|ATR替代|>3ATR|1|' in text


def test_missing_20_window_never_uses_5_day_exit(tmp_path):
    from test_evaluation import write_run
    write_run(tmp_path,record())
    settle(tmp_path,settings=EvaluationSettings(settlement_windows=[5,10]),services=Services(),
        now=datetime.fromisoformat('2026-11-02T20:00:00-05:00'))
    row=load_outcomes(tmp_path/'data/evaluation/outcomes.jsonl')[0]
    outcome=row['point_plans']['buy_1']['outcome']
    assert outcome['status']=='pending' and outcome['end'] is None
    assert '缺20日' in outcome['reason'] and 'exit_price' not in outcome


def test_target_distance_cent_rounding_boundary():
    result=record()
    plans=extract_plans(result)
    # 239.87只是U+3ATR显示到分的结果，不虚增>3ATR档样本。
    assert plans['buy_1']['target_distance_bucket']=='≤3ATR'
    result['structured']['pm_decision']['buy_legs'][0]['first_target']=240
    assert extract_plans(result)['buy_1']['target_distance_bucket']=='>3ATR'


def test_reduce_only_structure_does_not_become_buy_rule_check():
    from daily_analyzer.evaluation.plan_checks import decision_plan_checks
    result={'structured':{'pm_decision':{'rating':'Hold','reduce_legs':[{
        'kind':'超配回落','zone_low':210,'zone_high':215}]}}}
    assert decision_plan_checks(result,{})['plan_checks']['pm']==[]

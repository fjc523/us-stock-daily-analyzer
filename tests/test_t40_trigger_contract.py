"""T40首页可见条件、近似统计隔离和v2确认合同，全部固定/合成数据。"""
from copy import deepcopy

import pytest

from daily_analyzer.evaluation.plan_checks import execution_matrix, check_buy_leg
from daily_analyzer.evaluation.price_plans import evaluate_leg, point_report
from daily_analyzer.site import _marks
from test_t37_point_legs import DATES, breakout, bars, evaluate


def test_matrix_visible_conditions_and_expanded_details():
    buys = [breakout(confirm_days=2, trigger_rule=None)]
    reduces = [{'kind': '超配回落', 'zone_low': 201.99, 'zone_high': 204.9, 'trigger_rule': None},
               {'kind': '风险减配', 'trigger_price': 184.8624, 'post_allocation_pct': 0, 'reason': '仅在展开显示'}]
    flags = ['buy_legs.0.trigger_rule:invalid_value', 'reduce_legs.0.trigger_rule:invalid_value', 'reduce_legs.1.trigger_rule:invalid_value']
    rows = execution_matrix('Overweight', 122, buys, reduces, leg_validation_flags=flags)
    assert '连续2日确认' in rows[0]['text']
    assert '超配≥10个百分点且201.99–204.90触发方式未记录' in rows[2]['text']
    assert '触发方式未记录' in rows[3]['text'] and '184.86' in rows[3]['text']
    assert '触发规则缺失' in rows[3]['full_text']
    assert all('另有条件，见展开原文' not in row['text'] for row in rows)
    assert all('另有条件，见展开原文' in row['full_text'] for row in rows)
    assert '仅在展开显示' not in rows[3]['text'] and '仅在展开显示' in rows[3]['full_text']
    assert execution_matrix('Overweight', 125, buys, [])[3]['text'] == '未设风险减配腿'
    buys[0]['confirm_days'] = None
    assert '确认天数未提供' in execution_matrix('Overweight', 125, buys, [])[0]['text']
    buys[0]['preconditions'] = '等待事件窗口及成交量确认'
    rows = execution_matrix('Overweight', 125, buys, [], 0)
    assert '｜前提：' + buys[0]['preconditions'] in rows[0]['text'] and buys[0]['preconditions'] in rows[0]['full_text']
    assert rows[0]['tolerance_note'] == '容差关闭，按目标精确比较'


@pytest.mark.parametrize('field', ['trigger_rule', 'status', 'kind', 'confirm_days', 'zone_low', 'zone_high',
    'trigger_price', 'stop_loss', 'first_target', 'target_method', 'post_allocation_pct'])
def test_persisted_field_flags_mark_only(field):
    result = {'decision_flags': {'pm': {'leg_validation_flags': [f'buy_legs.0.{field}:invalid_value']}}}
    before = deepcopy(result)
    assert '执行条件字段缺失' in _marks(result) and result == before
    assert '执行条件字段缺失' not in _marks({'decision_flags': {'pm': {'leg_validation_flags': []}}})
    assert '执行条件字段缺失' not in _marks({})
    assert '执行条件字段缺失' not in _marks({'decision_flags': {'pm': {'leg_validation_flags': ['buy_legs.0.reason:invalid_value']}}})


def test_status_none_only_backsolve_and_mismatch_marks():
    result = {'decision_flags': {'plan_checks': {'pm': [{'status': None, 'checks': {'stop_unanchored': True}}]}}}
    assert '点位规则未通过' not in _marks(result)
    result['decision_flags']['plan_checks']['pm'][0]['checks']['rr_reason_text'] = True
    assert '点位规则未通过' in _marks(result)
    assert '执行条件字段缺失' in _marks({'structured': {'pm_decision': {'leg_validation_flags': ['buy_legs.0:trigger_status_mismatch']}}})


def test_atr_alternative_name_diagnostic_is_not_applicable():
    anchors = {'P_Low': 98, '20d_High': 106, 'atr': 2}
    leg = {'zone_low': 99, 'zone_high': 100, 'stop_loss': 97, 'first_target': 106,
           'stop_anchor': 'P_Low', 'target_anchor': 'atr', 'target_method': 'ATR替代'}
    assert check_buy_leg(leg, anchors)['target_anchor_name_status'] == 'not_applicable'
    leg['target_method'] = '阻力位'
    assert check_buy_leg(leg, anchors)['target_anchor_name_status'] == 'unrecognized'


def test_status_contract_accepts_missing_rule_and_rejects_mismatch():
    expected = evaluate(breakout(confirm_days=2))
    assert evaluate(breakout(confirm_days=2, trigger_rule=None)) == expected
    for status, rule in [('待触发', '触及区间'), ('可执行', '收盘站上')]:
        outcome = evaluate(breakout(status=status, trigger_rule=rule))
        assert outcome['status'] == 'indeterminate' and outcome['reason'] == '触发规则与状态不一致'
    executable = breakout(status='可执行', trigger_rule='触及区间')
    assert evaluate({**executable, 'trigger_rule': None}) == evaluate(executable)


@pytest.mark.parametrize('rule,reason', [(None, '触发规则缺失'), ('立即', '非区间受阻规则，C4 v2 不可判'),
    ('其他条件', '非区间受阻规则，C4 v2 不可判')])
def test_excess_requires_explicit_rejection_rule(rule, reason):
    outcome = evaluate({'kind': '超配回落', 'trigger_rule': rule, 'zone_low': 201.99, 'zone_high': 204.9})
    assert outcome['status'] == 'indeterminate' and outcome['reason'] == reason
    assert evaluate({'kind': '超配回落', 'trigger_rule': '进入区间受阻', 'zone_low': 201.99, 'zone_high': 204.9})['status'] == 'settled'


def test_risk_continuous_two_days_and_legacy_last_day_next_open():
    plan = {'kind': '风险减配', 'trigger_rule': '收盘跌破', 'trigger_price': 200}
    values = {day: {'open': 205, 'high': 210, 'low': 190, 'close': 205} for day in DATES}
    values[DATES[0]]['close'] = 199
    values[DATES[2]]['close'] = 199
    assert evaluate({**plan, 'confirm_days': 2}, values)['triggered'] is False
    values[DATES[3]]['close'] = 199
    outcome = evaluate({**plan, 'confirm_days': 2}, values)
    assert outcome['trigger_date'] == DATES[3] and outcome['entry_date'] == DATES[4]
    for day in DATES[:4]:
        values[day]['close'] = 205
    values[DATES[4]]['close'] = 199
    outcome = evaluate(plan, values)
    assert outcome == evaluate({**plan, 'confirm_days': 1}, values)
    assert outcome['trigger_date'] == DATES[4] and outcome['entry_date'] == DATES[5]
    for rule, reason in [(None, '触发规则缺失'), ('其他条件', '非收盘跌破规则')]:
        assert evaluate({**plan, 'trigger_rule': rule}, values)['reason'] == reason


@pytest.mark.parametrize('kwargs', [{}, {'mature': False}, {'end': None}, {'units_verified': False}, {'basis': 'same_day_close'}])
def test_approximation_flag_survives_all_evaluation_paths(kwargs):
    outcome = evaluate(breakout(preconditions='事件窗口后确认'), **kwargs)
    assert outcome['price_only_approximation'] is True
    assert 'price_only_approximation' not in evaluate(breakout(), **kwargs)


def test_price_approximations_excluded_from_every_determinate_metric():
    definite = {**breakout(), 'rule_version': 'c4-v2', 'outcome': evaluate()}
    approximate = {**definite, 'preconditions': '财报核验', 'outcome': {**definite['outcome'],
        'price_only_approximation': True, 'realized_r': 999, 'direction_adjusted_return': 999, 'mfe_pct': 999, 'mae_pct': 999}}
    row = {'symbol': '测试', 'point_plans': {'buy_1': definite}}
    known_report = point_report([row])
    mixed_report = point_report([{**row, 'point_plans': {'buy_1': definite, 'buy_2': approximate}}])
    assert mixed_report.split('\n### 含非价格前置条件')[0].rstrip() == known_report.rstrip()
    assert '|测试|buy_2|买入|settled|是|财报核验|' in mixed_report
    assert '999' not in mixed_report
    only_approx = point_report([{**row, 'point_plans': {'buy_2': approximate}}])
    assert '含非价格前置条件（价格近似）' in only_approx and '|买入|待触发|' not in only_approx

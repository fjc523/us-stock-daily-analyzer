"""首页今日操作与风险复评摘录的纯显示契约。"""
import pytest

from daily_analyzer.evaluation.plan_checks import execution_matrix, today_action
from daily_analyzer.site import _summary_row, build_site


NONE = '今日无立即操作：现有持仓不动，买卖均需按下表条件触发'
BUY = '今日有可执行买入腿，见无仓/低于目标行'
REDUCE = '今日有立即执行的减仓腿，见高于目标/风险行'


@pytest.mark.parametrize('rating,buy,reduce,expected', [
    ('Overweight', [{'status': '可执行'}], [], BUY),
    ('Hold', [], [{'trigger_rule': '立即'}], REDUCE),
    ('Buy', [{'status': '可执行'}], [{'trigger_rule': '立即'}], BUY + '；' + REDUCE),
    ('Underweight', [{'status': '可执行'}], [], NONE),
    ('Sell', [{'status': '可执行'}], [{'trigger_rule': '立即'}], REDUCE),
    ('Overweight', [{'status': '待触发'}], [{'trigger_rule': '进入区间受阻'}], NONE),
    ('Hold', [{'status': '仅观察'}], [{'trigger_rule': '收盘跌破'}], NONE),
    ('Hold', [], [], NONE),
])
def test_today_action_only_uses_structured_status(rating, buy, reduce, expected):
    assert today_action(rating, buy, reduce) == expected


@pytest.mark.parametrize('text,expected', [
    ('超配跌破后复评。目标内失守即警戒；保留持仓。', '未设风险减配腿'),
    ('先核验。失守后复评；进一步警戒。', '未设风险减配腿；复评条件：失守后复评；进一步警戒'),
    ('', '未设风险减配腿'),
])
def test_review_extraction_keeps_other_rows_and_full_text(text, expected):
    before = execution_matrix('Hold', 100, [], [])
    after = execution_matrix('Hold', 100, [], [], reduce_plan=text)
    assert after[:3] == before[:3]
    assert after[3]['text'] == expected
    assert after[3]['full_text'] == before[3]['full_text']


def test_risk_leg_text_and_details_are_unchanged():
    legs = [{'kind': '风险减配', 'trigger_rule': '收盘跌破', 'trigger_price': 97,
             'confirm_days': 2, 'post_allocation_pct': 60, 'preconditions': '同步转弱'}]
    assert execution_matrix('Hold', 100, [], legs, reduce_plan='失守复评。') == execution_matrix('Hold', 100, [], legs)


def test_homepage_uses_pm_legs_and_pm_review_only(tmp_path):
    import json
    result = {
        'symbol': 'QQQ', 'final_rating': 'Overweight', 'status': 'completed',
        'final_trade_decision': '原始减仓正文',
        'structured': {
            'pm_decision': {'rating': 'Overweight', 'target_allocation_pct': 122,
                            'buy_legs': [{'status': '待触发'}], 'reduce_legs': [],
                            'reduce_plan': '动态close_20_sma（现733.52）连续2日失守仅作复评，不预设减后配置或全仓止损。'},
            'trader_proposal': {'buy_legs': [{'status': '可执行'}],
                                'reduce_legs': [{'trigger_rule': '立即'}], 'reduce_plan': '交易员失守复评'},
        },
    }
    row = _summary_row(result, None, '')
    assert row['today_action'] == NONE
    assert row['plans'][3]['text'] == '未设风险减配腿；复评条件：动态close_20_sma（现733.52）连续2日失守仅作复评，不预设减后配置或全仓止损'
    path = tmp_path / 'data/runs/2026-10-08/current/QQQ.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(result, ensure_ascii=False))
    build_site(tmp_path)
    html = (tmp_path / 'site/index.html').read_text()
    assert html.index(NONE) < html.index(row['plans'][0]['text'])
    assert row['plans'][3]['text'] in html
    assert '交易员失守复评' not in html
    result['structured']['pm_decision']['buy_legs'] = []
    result['structured']['pm_decision']['reduce_legs'] = []
    fallback = _summary_row(result, None, '')
    assert fallback['today_action'] == ''
    assert fallback['plans'][3]['text'] == row['plans'][3]['text']
    result['final_rating'] = 'Sell'
    result['structured']['pm_decision']['buy_legs'] = [{'status': '可执行'}]
    assert _summary_row(result, None, '')['today_action'] == NONE


def test_homepage_without_pm_legs_has_no_action_hint(tmp_path):
    import json
    for structured in ({}, {'pm_decision': {}}, {'trader_proposal': {
            'buy_legs': [{'status': '可执行'}], 'reduce_legs': [{'trigger_rule': '立即'}]}}):
        result = {'symbol': 'COHR', 'status': 'pending', 'structured': structured}
        assert _summary_row(result, None, '')['today_action'] == ''
        path = tmp_path / 'data/runs/2026-10-08/current/COHR.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False))
        build_site(tmp_path)
        html = (tmp_path / 'site/index.html').read_text()
        assert NONE not in html and BUY not in html and REDUCE not in html

"""R36通用数值、持仓矩阵和自由文本兼容，不读真实账户。"""
import pytest
from daily_analyzer.evaluation.plan_checks import check_buy_leg, execution_matrix, leg_conflict_flags, decision_plan_checks
from daily_analyzer.evaluation.price_plans import parse_plan
from daily_analyzer.evaluation.calibration import probability, extract_probabilities


def leg(**extra):
    return {'zone_low':99,'zone_high':100,'stop_loss':97,'stop_anchor':'P_Low−0.5ATR',
            'first_target':106,'target_method':'阻力位','target_anchor':'20d_High', **extra}


def test_named_anchors_and_cent_tolerance():
    anchors={'P_Low':98,'20d_High':106,'atr':2}
    result=check_buy_leg(leg(),anchors)
    assert result['qualified'] and result['expected_target']['price']==106
    assert result['d_atr']==1.5 and result['rr']==2
    assert check_buy_leg(leg(stop_loss=96.99),anchors)['qualified']
    assert check_buy_leg(leg(stop_loss=96.97),anchors)['checks']['stop_unanchored']
    assert check_buy_leg(leg(stop_anchor='不具名'),anchors)['checks']['stop_unanchored']
    assert check_buy_leg(leg(target_anchor='不具名'),anchors)['checks']['target_unanchored']


def test_new_high_and_short_ma_are_distinct():
    new_high=check_buy_leg(leg(first_target=106,target_method='ATR替代'),{'P_Low':98,'atr':2})
    assert new_high['expected_target']=={'name':'ATR替代','price':106}
    assert new_high['qualified']
    short_ma=check_buy_leg(leg(),{'P_Low':98,'atr':2,'close_20_sma':100.5})
    assert short_ma['expected_target'] is None and not short_ma['qualified']
    near=check_buy_leg(leg(),{'P_Low':98,'atr':2,'P_High':101,'20d_High':106})
    assert near['checks']['zone_under_horizontal_resistance'] and not near['qualified']


def test_stated_target_and_r36_replay_are_independent():
    result=check_buy_leg(leg(first_target=104,target_method='ATR替代'),{'P_Low':98,'atr':2})
    assert result['qualified'] and result['checks']['target_mismatch']
    assert result['rr']==pytest.approx(4/3) and result['expected_rr']==2
    assert check_buy_leg(leg(reason='因为盈亏比要求止损不超过97'),{'P_Low':98,'20d_High':106,'atr':2})['checks']['rr_reason_text']


def test_conflicts_only_flag_and_matrix_holdings():
    buy=[{'status':'待触发','zone_low':201.99,'zone_high':204.9,'trigger_price':201.99,
          'stop_loss':190.33,'first_target':228.21,'target_method':'ATR替代'}]
    reductions=[{'kind':'超配回落','zone_low':197.08,'zone_high':201.99,'trigger_rule':'进入区间受阻'},
                {'kind':'风险减配','trigger_rule':'收盘跌破','trigger_price':179.87}]
    rows=execution_matrix('Overweight',125,buy,reductions,10)
    assert [row['label'] for row in rows]==['无仓','低于目标','高于目标','风险']
    assert '228.21' in rows[0]['text'] and '补至125%' in rows[1]['text']
    assert '超配≥10个百分点且197.08–201.99受阻时减至125%' in rows[2]['text'] and '（未提供）' in rows[3]['text']
    bearish=execution_matrix('Underweight',80,buy,reductions,0)
    assert '不新建仓' in bearish[0]['text'] and '不加仓' in bearish[1]['text']
    flags=leg_conflict_flags('Sell',buy,reductions)
    assert flags['buy_leg_conflicts_rating'] and flags['risk_reduce_missing_post_allocation']
    assert not flags['risk_trigger_above_buy_zone']
    assert leg_conflict_flags('Hold',[],[])['legs_missing']
    assert decision_plan_checks({'structured':{}},{'price_plan_legs':True})['pm']['legs_missing']


@pytest.mark.parametrize('text', ['待触发：收盘站上102后 区间102–103美元（依据：P_High）',
    '同建仓：区间99–100美元（仅补至目标差额）','超配回落：区间105–106美元（依据：P_High）',
    '风险减配：收盘跌破97降至60%'])
def test_new_explicit_prefixes(text):
    assert parse_plan(text)['parse_status']=='parsed'
    assert parse_plan('同建仓：见上')['parse_status']=='unparsed'


def test_percent_normalization_for_structured_and_freetext():
    assert probability('62%') == .62 and probability('162%') is None
    result=extract_probabilities({'investment_plan':'**Prob Outperform 20d**: 62%'})
    assert result['rm']['20'] == .62


def test_matrix_full_conditions_and_tolerance_zero():
    rows=execution_matrix('Hold',100,[{'status':'待触发','confirm_days':2,
        'reason':'仅收盘确认后执行','stop_anchor':'P_Low'}],
        [{'kind':'风险减配','trigger_rule':'其他条件','trigger_price':97,
          'post_allocation_pct':60,'reason':'支撑反抽失败'}],0)
    assert rows[0]['tolerance_note']=='容差关闭，按目标精确比较'
    assert '连续确认2日' in rows[0]['full_text'] and '仅收盘确认后执行' in rows[0]['full_text']
    assert rows[3]['text'] == '其他条件（未写明） → 降至60%并复评'
    assert '97' in rows[3]['full_text']
    assert '反抽失败' not in rows[3]['text'] and '反抽失败' in rows[3]['full_text']
    assert '<10个百分点' in execution_matrix('Hold',100,[],[],10)[0]['tolerance_note']


def test_descriptive_target_far_does_not_mark_failed():
    from daily_analyzer.site import _marks
    result={'decision_flags':{'plan_checks':{'pm':[{'checks':{'target_far':True}}]}}}
    assert '点位规则未通过' not in _marks(result)
    result['decision_flags']['plan_checks']['pm'][0]['checks']['rr_reason_text']=True
    assert '点位规则未通过' in _marks(result)


@pytest.mark.parametrize('field', ['reason','entry_plan','add_plan'])
def test_structured_leg_also_checks_original_text(field):
    # R37-W12-2：每腿数值资格独立，正文不能绕过禁止倒推措辞诊断。
    buy=leg(reason='具名支撑位')
    data={'rating':'Buy','buy_legs':[buy]}
    if field=='reason':buy[field]='因为盈亏比要求止损不超过97'
    else:data[field]='区间99–100美元；因为盈亏比要求止损不超过97'
    result={'structured':{'pm_decision':data},'context_blocks':{'price_anchors':{
        'data':{'anchors':{'P_Low':98,'20d_High':106,'atr':2}}}}}
    checked=decision_plan_checks(result, {})['plan_checks']['pm'][0]
    assert checked['checks']['rr_reason_text'] and checked['qualified']
    data[field]='突破规则要求止损在具名支撑下方' if field!='reason' else data.get(field)
    buy['reason']='突破规则要求止损在具名支撑下方'
    assert not decision_plan_checks(result,{})['plan_checks']['pm'][0]['checks']['rr_reason_text']


@pytest.mark.parametrize('rating', ['Underweight','Sell'])
def test_final_pm_freetext_controls_borrowed_trader_legs_and_render(tmp_path,rating):
    # R37-W12-3：真实首页评级、目标与可执行矩阵必须来自同一最终PM结论。
    from daily_analyzer.site import _summary_row,render_home
    from test_site import _result
    result=_result('TEST','2026-10-02',rating)
    result['final_trade_decision']='**Rating**: '+rating+'\n\n**目标配置（标准仓位=100%）**: 60%'
    result['structured']={'pm_decision':None,'trader_proposal':{'action':'Buy',
        'target_allocation_pct':140,'buy_legs':[leg(status='可执行')]}}
    row=_summary_row(result,None,'test.html')
    assert '不新建仓' in row['plans'][0]['text'] and '不加仓' in row['plans'][1]['text']
    assert '60%' in row['allocation'] and '140%' not in str(row['plans'])
    (tmp_path/'config').mkdir()
    (tmp_path/'config/watchlist.yaml').write_text('items:\n  - {symbol: TEST, type: stock}\n')
    result.update(_date='2026-10-02',_slug='TEST')
    html=render_home(tmp_path,grouped={'2026-10-02':[result]})
    assert '不新建仓' in html and '不加仓' in html and '目标配置 60%' in html
    assert '补至140%' not in html and '<details' in html


def test_final_pm_priority_unknown_target_and_trader_only():
    from daily_analyzer.site import _summary_row
    result={'symbol':'TEST','type':'stock','structured':{'trader_proposal':{
        'action':'Buy','target_allocation_pct':140,'buy_legs':[leg(status='可执行')]}}}
    row=_summary_row(result,None,'test.html')
    assert '补至140%' in row['plans'][1]['text']
    result.update(final_rating='Overweight',final_trade_decision='最终决定，不提供配置')
    row=_summary_row(result,None,'test.html')
    assert '目标配置未提供' in row['allocation'] and '140%' not in str(row['plans'])
    result['structured']['pm_decision']={'rating':'Overweight','target_allocation_pct':125}
    row=_summary_row(result,None,'test.html')
    assert '125%' in row['allocation'] and '补至125%' in row['plans'][1]['text']


def test_grid_rules_only_layout_plan_rows_not_expanded_text(tmp_path):
    # R37-W12-5：用真实HTML与实际CSS选择结果验证新旧展开正文不成为固定首列。
    import re
    from bs4 import BeautifulSoup
    from daily_analyzer.site import render_home
    from test_site import _result
    old=_result('OLD','2026-10-02','Hold')
    old.update(_date='2026-10-02',_slug='OLD')
    old['final_trade_decision']='\n\n'.join('**'+label+'**: 区间99–100美元；旧完整条件、具名止损与复评。'
        for label in ('建仓点位','加仓点位','减仓点位'))
    new=_result('NEW','2026-10-02','Buy')
    new.update(_date='2026-10-02',_slug='NEW')
    new['structured']={'pm_decision':{'rating':'Buy','target_allocation_pct':140,
        'buy_legs':[leg(status='待触发',trigger_rule='收盘站上',trigger_price=102,
                        confirm_days=2,reason='新完整条件、具名止损与复评。')]}}
    (tmp_path/'config').mkdir()
    (tmp_path/'config/watchlist.yaml').write_text('items:\n  - {symbol: NEW, type: stock}\n  - {symbol: OLD, type: stock}\n')
    soup=BeautifulSoup(render_home(tmp_path,grouped={'2026-10-02':[new,old]}),'html.parser')
    grid_nodes=[]
    for selectors,body in re.findall(r'([^{}]+)\{([^{}]*)\}',soup.style.get_text()):
        if '.price-plans' in selectors and 'grid-template-columns' in body:
            grid_nodes.extend(soup.select(selectors.strip()))
    full=soup.select('.execution-full')
    assert len(grid_nodes)==7 and len(full)==7
    assert all(node.parent.name=='dl' and node.find('dt',recursive=False)
               and node.find('dd',recursive=False) for node in grid_nodes)
    assert not {id(node) for node in grid_nodes} & {id(node) for node in full}
    assert all(node.parent.name=='details' and node.parent.find('summary',recursive=False) for node in full)
    assert any('连续确认2日' in node.get_text() and '新完整条件' in node.get_text() for node in full)
    assert sum('旧完整条件' in node.get_text() for node in full)==3


def test_matrix_spec_briefs_preserve_full_text_and_known_enum():
    leg = {'kind': '风险减配', 'trigger_rule': '其他条件', 'trigger_price': 184.86, 'post_allocation_pct': 0,
           'preconditions': '盘中有效报价触及184.86即退出'}
    rows = execution_matrix('Hold', 100, [], [leg])
    assert rows[3]['text'] == '其他条件：盘中有效报价触及184.86即退出 → 降至0%并复评'
    assert '其他条件 184.86 → 降至0%并复评' in rows[3]['full_text']
    leg['trigger_rule'] = None
    rows = execution_matrix('Hold', 100, [], [leg], leg_validation_raw={'reduce_legs.0.trigger_rule': '盘中触及'})
    assert rows[3]['text'].startswith('盘中触及（未规范） 184.86 → 降至0%并复评')
    buy = {'status': '待触发', 'confirm_days': 2, 'trigger_price': 201.99, 'preconditions': '前' * 35}
    rows = execution_matrix('Hold', 100, [buy], [])
    assert rows[0]['text'].endswith('｜前提：' + '前' * 30 + '…')
    buy['status'] = '仅观察'
    assert '｜' not in execution_matrix('Hold', 100, [buy], [])[0]['text']
    excess = {'kind': '超配回落', 'trigger_rule': '进入区间受阻', 'zone_low': 201.99, 'zone_high': 204.9}
    assert execution_matrix('Hold', 122, [], [excess])[2]['text'] == '超配≥10个百分点且201.99–204.90受阻时减至122%'

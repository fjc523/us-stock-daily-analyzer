"""v5.3 F32–F40及用户覆盖退出日的零模型夹具。"""
from copy import deepcopy
import pytest
from daily_analyzer.evaluation.ab_ledger import Ledger
from daily_analyzer.evaluation.ab_lifecycle import allocate_day, paired_difference_index, MissingPlannedItems
from daily_analyzer.evaluation.ab_reports import simulate_pair


def bar(price):return dict(open=price,high=price,low=price,close=price)
def allocate(old,day,plan,success=None,eligible=None):
    return allocate_day(old,day=day,planned_items=plan,successful=set(plan if success is None else success),eligible={s:True for s in plan} if eligible is None else eligible)


def test_F32_F33_standard_money_mapping_and_drift():
    value=Ledger(('X',),costs={'X':0});value.initialize('d1',{'X':bar(250)})
    assert value.shares('X')==20 and value.standard*1.22/250==24.4
    assert value.allocation('X',300)==120
    value.step('d2',{'X':bar(300)},{'X':300})
    assert value.shares('X')==20
    direct=Ledger(('X',),costs={'X':0},direct=True);direct.initialize('d1',{'X':bar(250)})
    direct.step('d2',{'X':bar(300)},{'X':300},{'X':{'id':'d2','target_allocation_pct':100}})
    assert direct.shares('X')==pytest.approx(5000/300)


def test_F34_F36_F37_subscription_epochs():
    opened=allocate(None,'2026-10-21',['X'])
    assert opened['opened']==['X#1'] and opened['run_symbols']==['X']
    failed=allocate(opened,'2026-10-22',['X'],success=[])
    assert not failed['unsubscribed'] and failed['audit']['X']=='缺失'
    closed=allocate(failed,'2026-10-23',[])
    assert closed['unsubscribed']==['X#1'] and closed['run_symbols']==[]
    again=allocate(closed,'2026-10-26',['X'])
    assert again['opened']==['X#2'] and len(again['pairs'])==2
    ledger=Ledger(('X',),costs={'X':5});ledger.initialize('2026-10-21',{'X':bar(40)})
    assert ledger.shares('X')==125 and ledger.cash==4997.5


def test_F35_pending_exit_cancels_orders_and_keeps_exit_day():
    value=Ledger(('X',),costs={'X':5});value.initialize('d1',{'X':bar(40)})
    value.lots['X'][0]['shares']=150;value.orders['X']=[{'kind':'买入'}]
    value.exit_step('d2',{'X':{'close':41}})
    assert value.shares('X')==150 and value.orders['X']==[]
    row=value.exit_step('d3',{'X':bar(42)})
    assert value.shares('X')==0 and row['nav']==pytest.approx(4997.5+150*42*.9995)
    assert value.trades[-1]['reason']=='退订平仓'


def test_F38_F39_slots_not_expanded_by_subscription_count():
    state=allocate(None,'d1',['A','B','C','D','Y','SPACEX'],eligible={s:s!='SPACEX' for s in ['A','B','C','D','Y','SPACEX']})
    assert len(state['run_symbols'])==4 and state['audit']['Y']=='名额已满，未纳入'
    assert state['audit']['SPACEX']=='不可建账'
    nextday=allocate(state,'d2',['A','B','C','Y'])
    assert nextday['opened']==['Y#1'] and nextday['unsubscribed']==['D#1']
    assert len(nextday['run_symbols'])==4
    assert allocate_day(nextday,day='d2',planned_items=nextday['planned_items'],successful=set(),eligible={})==nextday


def test_missing_old_planned_snapshot_rejects():
    with pytest.raises(MissingPlannedItems,match='NOT_TESTED'):allocate_day(None,day='d1',planned_items=None,successful=set(),eligible={})


def test_F40_synthetic_index_exit_day_and_no_sample():
    def pair(key,days,returns):
        nav=10000.;rows=[]
        for day,r in zip(days,returns):nav*=1+r;rows.append({'day':day,'nav':nav})
        return {'id':key,'A':{'daily':rows},'B':{'daily':[{'day':d,'nav':10000} for d in days]}}
    p1=pair('P1',['d1','d2','d3','d4'],[.01,-.01,.02,-.005])
    p2=pair('P2',['d2','d3'],[.03,-.02])
    rows=paired_difference_index([p1,p2],['d1','d2','d3','d4','d5'])
    assert [r['pair_count'] for r in rows]==[1,2,2,1,0]
    assert rows[2]['cumulative_difference']==pytest.approx(.0201)
    assert rows[3]['cumulative_difference']==pytest.approx(1.0201*.995-1)
    assert rows[4]['daily_difference'] is None and rows[4]['synthetic_index']==rows[3]['synthetic_index']


def test_exit_and_same_day_new_pair_all_contribute():
    pairs=[]
    for i in range(5):
        pairs.append({'id':str(i),'A':{'daily':[{'day':'d1','nav':9990 if i==0 else 9995}]},'B':{'daily':[{'day':'d1','nav':9995}]}})
    row=paired_difference_index(pairs,['d1'])[0]
    assert row['pair_count']==5 and row['daily_difference']==pytest.approx(-.0001)


def test_simulation_exit_overnight_cost_and_no_later_return():
    days=['2026-10-12','2026-10-13','2026-10-14'];bars={'X':{d:bar(p) for d,p in zip(['2026-10-09',*days],[40,40,42,43])}}
    pair={'id':'X#1','symbol':'X','opened_at':days[0],'unsubscribed_at':days[1]}
    result=simulate_pair(pair,days,bars,{'A':{},'B':{}},costs={'X':5})
    assert result['closed_at']==days[1] and result['days']==2
    assert result['A']['daily'][0]['nav']==9997.5
    assert result['A']['daily'][-1]['nav']==pytest.approx(4997.5+125*42*.9995)


def test_report_real_pipeline_account_nav_and_synthetic_index(tmp_path):
    from datetime import datetime
    from types import SimpleNamespace
    from zoneinfo import ZoneInfo
    import json
    from daily_analyzer.evaluation.ab_path import calendar_after,experiment_root
    from daily_analyzer.evaluation.ab_reports import build_ledgers
    from daily_analyzer.storage import atomic_write_json
    area=experiment_root(tmp_path);state=calendar_after('2026-10-09')
    atomic_write_json(area/'experiment.json',state)
    allocation=allocate(None,'2026-10-12',['X'])
    atomic_write_json(area/'allocations/2026-10-12.json',allocation)
    allocation=allocate(allocation,'2026-10-13',[])
    atomic_write_json(area/'allocations/2026-10-13.json',allocation)
    class Prices:
        def bars(self,symbol,cutoff):
            return [dict(date=d,**bar(p)) for d,p in [('2026-10-09',40),('2026-10-12',40),('2026-10-13',42),('2026-10-14',43)] if d<=cutoff.isoformat()],'合成同源'
    result=build_ledgers(tmp_path,now=datetime(2026,10,14,18,tzinfo=ZoneInfo('America/New_York')),services=SimpleNamespace(prices=Prices()),costs={'SPY':2,'X':5})
    report=json.loads(open(result['path']).read())
    assert report['index_name']=='合成配对差值指数'
    assert report['pairs'][0]['A']['daily'][-1]['nav']==pytest.approx(4997.5+125*42*.9995)
    assert [r['pair_count'] for r in report['paired_difference_curve']]==[1,1,0]
    assert report['paired_difference_curve'][-1]['daily_difference'] is None
    assert report['pairs'][0]['status']=='已退订'


def test_pending_exit_not_reported_closed():
    days=['2026-10-12','2026-10-13']
    bars={'X':{'2026-10-09':bar(40),days[0]:bar(40),days[1]:{'close':41}}}
    result=simulate_pair({'id':'X#1','symbol':'X','opened_at':days[0],'unsubscribed_at':days[1]},days,bars,{'A':{},'B':{}},costs={'X':5})
    assert result['closed_at'] is None and result['status']=='待平仓'
    assert result['A']['daily'][-1]['shares']['X']==125


def test_pair_window_retains_other_paths_delayed_exit():
    days=['2026-10-12','2026-10-13','2026-10-14']
    bars={'X':{'2026-10-09':bar(40),days[0]:bar(40),days[1]:{'close':41},days[2]:bar(42)}}
    pair={'id':'X#1','symbol':'X','opened_at':days[0],'unsubscribed_at':days[1]}
    decision={'id':'sell','target_allocation_pct':0,'reduce_legs':[{'kind':'风险减配','trigger_rule':'立即','post_allocation_pct':0}]}
    result=simulate_pair(pair,days,bars,{'A':{days[0]:{'X':decision}},'B':{}},costs={'X':5})
    assert result['closed_at']==days[2]
    assert len(result['A']['daily'])==len(result['B']['daily'])==3
    assert result['A']['daily'][-1]['nav']==result['A']['daily'][-2]['nav']
    curve=paired_difference_index([result],days)
    assert curve[-1]['pair_count']==1 and curve[-1]['daily_difference']<0


def test_unadmitted_fallback_and_maturity_records_excluded():
    from daily_analyzer.evaluation.ab_reports import admitted_records
    pair={'symbol':'SPY','opened_at':'2026-10-12','unsubscribed_at':'2026-10-14'}
    rows=[{'symbol':s,'trade_date':d} for s,d in [('SPY','2026-10-12'),('Y','2026-10-12'),('SPY','2026-10-14'),('SPY','2026-11-09')]]
    result=admitted_records({'A':rows,'B':rows},[pair],'2026-11-06')
    assert result=={'A':[rows[0]],'B':[rows[0]]}


def test_original_report_event_thresholds_and_execution_rate():
    from daily_analyzer.evaluation.ab_reports import event_diagnostics,_metrics
    account={'daily':[{'day':'d1','nav':10000}], 'cost_total':0,
        'events':[{'day':'d1','symbol':'X','reason':'目标偏离至少10个百分点'},
                  {'day':'d1','symbol':'X','reason':'前提受限','clauses':['风险上限未触发']}],
        'trades':[{'day':'d1','symbol':'X','side':'buy','reason':'买入腿','shares':1,'price':40,'cost':0}],
        'event_counts':{'目标偏离至少10个百分点':1,'前提受限':1,'同日双触':1}}
    pair={'id':'X#1','A':deepcopy(account),'B':deepcopy(account)}
    report=event_diagnostics([pair])
    assert report['passive_and_stop_dominated_pairs']==['X#1']
    assert report['daily_precision_limited_accounts']==['X#1/A','X#1/B']
    assert report['precondition_unmatched_clauses']['X#1/A']==[('风险上限未触发',1)]
    assert _metrics(account)['execution']['execution_rate']==1
    for path in ('A','B'):
        pair[path]['events']=[{'day':f'd{i}','symbol':'X','reason':'目标偏离至少10个百分点'} for i in range(5)]+[{'day':f'd{i}','symbol':'X','reason':'前提受限','clauses':['风险上限未触发']} for i in range(4) for _ in range(3)]
        pair[path]['trades']=[{**account['trades'][0],'reason':'初始仓'}]+[deepcopy(account['trades'][0]) for _ in range(4)]
    diagnostics=event_diagnostics([pair])
    assert diagnostics['passive_and_stop_dominated_pairs']==[]
    assert diagnostics['daily_precision_limited_accounts']==[]
    assert diagnostics['daily_precision_ratios']['X#1/A']['ratio']==.2
    assert diagnostics['restricted_deviation_day_ratios']['X#1/A']['ratio']==.8


def test_mature_TS_direction_only_annotates_existing_curve(tmp_path):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    import json
    from daily_analyzer.evaluation.ab_path import experiment_root,calendar_after
    from daily_analyzer.evaluation.ab_reports import maturity_report
    from daily_analyzer.storage import atomic_write_json
    area=experiment_root(tmp_path)
    atomic_write_json(area/'experiment.json',calendar_after('2026-10-09'))
    atomic_write_json(area/'allocations/2026-10-12.json',allocate(None,'2026-10-12',['TSLA']))
    atomic_write_json(area/'ledger/curves.json',{'paired_difference_curve':[{'cumulative_difference':.02}]})
    for path,target in [('A',110),('B',100)]:
        record={'run_id':'r','symbol':'TSLA','trade_date':'2026-10-12','final_rating':'Hold','structured':{'pm_decision':{'target_allocation_pct':target}}}
        target_path=area/'A/data/runs/2026-10-12/batches/r/results/TSLA.json' if path=='A' else area/'B/2026-10-12/TSLA.json'
        atomic_write_json(target_path,record)
        outcomes=area/'A/data/evaluation/outcomes.jsonl' if path=='A' else tmp_path/'data/evaluation/outcomes.jsonl'
        outcomes.parent.mkdir(parents=True,exist_ok=True)
        outcomes.write_text(json.dumps({'run_id':'r','symbol':'TSLA','windows':{'5':{'status':'settled','settled_at':'2026-10-20T09:00:00-04:00','primary_return':.1,'excess_vs_spy':.1}}})+'\n')
    original=(area/'ledger/curves.json').read_bytes()
    report=maturity_report(tmp_path,label='D25',as_of=datetime(2026,11,13,17,tzinfo=ZoneInfo('America/New_York')))
    assert report['TS_direction_annotation']['5']['description']=='方向一致'
    assert report['TS_direction_annotation']['5']['sum_TS']==pytest.approx(.01)
    assert report['TS_direction_annotation']['20']['description']=='未成熟或无样本'
    assert (area/'ledger/curves.json').read_bytes()==original

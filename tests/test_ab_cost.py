"""cost-v1 F41–F45，仅合成结果JSON和零模型模拟账本。"""
from copy import deepcopy
import pytest
from daily_analyzer.evaluation.ab_ledger import resolve_cost,Ledger,COST_POLICY_VERSION
from daily_analyzer.evaluation.ab_lifecycle import allocate_day
from daily_analyzer.evaluation.ab_reports import simulate_pair


def bar(p):return dict(open=p,high=p,low=p,close=p)
def allocate(previous,day,types,success=None):
    return allocate_day(previous,day=day,planned_items=list(types),successful=set(types if success is None else success),eligible={s:True for s in types},cost_policies={s:resolve_cost(s,t) for s,t in types.items()})


@pytest.mark.parametrize('symbol,kind,price,bp,cash',[('X','stock',40,15,4992.5),('Y','etf',100,10,4995)])
def test_F41_F42_class_default(symbol,kind,price,bp,cash):
    state=allocate(None,'2026-10-12',{symbol:kind});pair=state['pairs'][0]
    assert pair['cost_bp']==bp and pair['cost_source']=='class_default'
    result=simulate_pair(pair,['2026-10-12'],{symbol:{'2026-10-09':bar(price),'2026-10-12':bar(price)}},{'A':{},'B':{}},costs={})
    for path in ('A','B'):
        assert result[path]['cash']==cash and result[path]['daily'][0]['shares'][symbol]==5000/price
        assert result[path]['cost_total']==pytest.approx(5000*bp/10000)


@pytest.mark.parametrize('symbol,kind,bp',[('SPY','etf',2),('QQQ','etf',2),('TSLA','stock',5),('SPCX','stock',15)])
def test_F43_registry_priority(symbol,kind,bp):
    policy=resolve_cost(symbol,kind)
    assert policy['cost_bp']==bp and policy['cost_source']=='registry'


def test_F44_unassigned_is_symbol_local():
    types={'Z':'index','W':None,'BAD':'future','INVALID':[],'SPY':'etf'}
    state=allocate(None,'d1',types)
    assert state['run_symbols']==['SPY'] and len(state['pairs'])==1
    for symbol in ('Z','W','BAD','INVALID'):
        assert state['audit'][symbol].startswith('成本未赋值，未纳入：')
        assert resolve_cost(symbol,types[symbol])['cost_bp'] is None
    assert 'type=index' in state['audit']['Z'] and 'type 缺失' in state['audit']['W']


def test_F45_lock_epoch_and_sensitivity():
    state=allocate(None,'2026-10-12',{'X':'stock'})
    changed=allocate(state,'2026-10-13',{'X':'etf'})
    assert changed['pairs'][0]['cost_bp']==15 and changed['pairs'][0]['type']=='stock'
    unsub=allocate(changed,'2026-10-14',{})
    again=allocate(unsub,'2026-10-15',{'X':'etf'})
    assert again['pairs'][-1]['cost_bp']==10 and again['pairs'][-1]['id']=='X#2'
    pair=state['pairs'][0]
    assert pair['cost_policy_version']==COST_POLICY_VERSION
    for multiple,cost in [(0,0),(2,15)]:
        result=simulate_pair(pair,['2026-10-12'],{'X':{'2026-10-09':bar(40),'2026-10-12':bar(40)}},{'A':{},'B':{}},costs={'X':10},multiple=multiple)
        assert result['A']['cost_total']==result['B']['cost_total']==cost


def test_F44_production_result_type_dispatch_and_report_local_skip(tmp_path,monkeypatch):
    from datetime import datetime
    import json
    from types import SimpleNamespace
    from test_ab_orchestrator import configured,Prices,NY,fake_executor
    import daily_analyzer.evaluation.ab_orchestrator as module
    from daily_analyzer.evaluation.ab_path import experiment_root
    from daily_analyzer.storage import atomic_write_json
    _,record=configured(tmp_path)
    batch_path=tmp_path/'data/runs/2026-10-12/batches/run2026-10-12/batch.json'
    batch=json.loads(batch_path.read_text());batch['planned_items']=['SPY','X','Y','Z','W']
    # items中故意放相反类型，成本必须只读成功结果JSON。
    batch['items']={s:{'type':'stock'} for s in batch['planned_items']};atomic_write_json(batch_path,batch)
    for symbol,kind in [('X','stock'),('Y','etf'),('Z','index'),('W',None)]:
        copy=deepcopy(record);copy['symbol']=copy['analyzed_symbol']=symbol;copy['consistency_input']['state']['company_of_interest']=symbol
        if kind is None:copy.pop('type')
        else:copy['type']=kind
        atomic_write_json(batch_path.parent/'results'/f'{symbol}.json',copy)
    monkeypatch.setattr(module,'_current_ta_dirty',lambda:False)
    monkeypatch.setattr(module,'prepare_shadow_context',lambda *a,**k:'隔离影子历史')
    seen=[]
    def execute(snapshot,*args,**kwargs):
        seen.append(snapshot['state']['company_of_interest']);return fake_executor(snapshot,*args,**kwargs)
    result=module.dispatch(tmp_path,now=datetime(2026,10,12,17,tzinfo=NY),executor=execute,reflector_factory=lambda *a:object(),services=SimpleNamespace(prices=Prices()),settings=__import__('daily_analyzer.config',fromlist=['EvaluationSettings']).EvaluationSettings())
    assert result['status']=='completed' and result['ledger']['status']=='completed',result
    assert seen==['SPY','X','Y']
    assert '成本未赋值' in result['allocation']['audit']['Z'] and 'type 缺失' in result['allocation']['audit']['W']
    report=json.loads((experiment_root(tmp_path)/'ledger/curves.json').read_text())
    assert report['cost_policy_version']==COST_POLICY_VERSION and report['class_default_pair_count']==2
    pairs={p['symbol']:p for p in report['pairs']}
    assert pairs['SPY']['cost_bp']==2 and pairs['X']['cost_bp']==15 and pairs['Y']['cost_bp']==10
    assert pairs['X']['A']['cost_total']==pairs['X']['B']['cost_total']==7.5
    assert {p['symbol']:p for p in report['scenarios']['cost2']}['X']['A']['cost_total']==15
    assert {p['symbol']:p for p in report['scenarios']['cost0']}['X']['A']['cost_total']==0


def test_old_policy_report_original_bytes_preserved(tmp_path):
    from datetime import datetime
    import json
    from types import SimpleNamespace
    from test_ab_orchestrator import Prices,NY
    from daily_analyzer.evaluation.ab_path import experiment_root,calendar_after
    from daily_analyzer.evaluation.ab_reports import build_ledgers
    from daily_analyzer.storage import atomic_write_json
    area=experiment_root(tmp_path)
    atomic_write_json(area/'experiment.json',calendar_after('2026-10-09'))
    atomic_write_json(area/'allocations/2026-10-12.json',allocate(None,'2026-10-12',{'SPY':'etf'}))
    output=area/'ledger';output.mkdir()
    original_json=b'{"cost_policy_version":"cost-v0", "marker":"\\u539f\\u4ef6"}\r\n'
    original_md='# 原件\r\n  保留空格\r\n'.encode()
    (output/'curves.json').write_bytes(original_json);(output/'report.md').write_bytes(original_md)
    result=build_ledgers(tmp_path,now=datetime(2026,10,12,17,tzinfo=NY),services=SimpleNamespace(prices=Prices()))
    assert result['status']=='completed'
    archive=output/'policy-archive/cost-v0'
    assert (archive/'curves.json').read_bytes()==original_json
    assert (archive/'report.md').read_bytes()==original_md
    assert json.loads((archive/'superseded.json').read_text())['superseded_by_cost_policy_version']==COST_POLICY_VERSION

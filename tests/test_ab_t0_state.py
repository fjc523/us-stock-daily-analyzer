"""T0同源证据只影响实验；全部使用零模型生产runner夹具。"""
import json
from copy import deepcopy
from datetime import datetime
import pytest
from daily_analyzer.evaluation.ab_path import capture_t0_b_state, verify_t0_b_states, experiment_root
from daily_analyzer.evaluation.consistency import PathIntegrityError
from daily_analyzer.storage import atomic_write_json
from test_ab_orchestrator import configured,NY
from test_runner import _project,_run,_FakeGraph


@pytest.mark.parametrize('damage',['missing','hash','projection','identity','result','state_shape'])
def test_t0_evidence_rejects_before_reflection(tmp_path,monkeypatch,damage):
    import daily_analyzer.evaluation.ab_orchestrator as module
    import daily_analyzer.evaluation.ab_path as path_module
    _,record=configured(tmp_path)
    proof_path=experiment_root(tmp_path)/'T0-state'/record['run_id']/'SPY.json'
    proof=json.loads(proof_path.read_text())
    if damage=='missing':proof_path.unlink()
    else:
        if damage=='state_shape':
            proof['full_state']=[];proof['state_sha256']=path_module._evidence_hash([])
        if damage=='hash':proof['state_sha256']='broken'
        if damage=='projection':
            proof['full_state']['final_trade_decision']='不同正文'
            proof['state_sha256']=path_module._evidence_hash(proof['full_state'])
        if damage=='identity':
            proof['full_state']['company_of_interest']='QQQ'
            proof['state_sha256']=path_module._evidence_hash(proof['full_state'])
        if damage=='result':
            proof['result']['extra']='不同工件'
            proof['result_sha256']=path_module._evidence_hash(proof['result'])
        atomic_write_json(proof_path,proof)
    monkeypatch.setattr(module,'_current_ta_dirty',lambda:False)
    def forbidden(*a,**k):pytest.fail('同源验收失败不得进入反思或A')
    monkeypatch.setattr(module,'prepare_shadow_context',forbidden)
    with pytest.raises(PathIntegrityError):
        module.dispatch(tmp_path,now=datetime(2026,10,12,17,tzinfo=NY),executor=forbidden,reflector_factory=forbidden)
    assert json.loads((experiment_root(tmp_path)/'budget-stop.json').read_text())['category']=='integrity'
    assert module.dispatch(tmp_path,now=datetime(2026,10,12,17,tzinfo=NY))['status']=='stopped'


@pytest.mark.parametrize('enabled,day,scheduled,mode,planned',[(False,'2026-10-12',True,'live',['SPY']),(True,'2026-10-13',True,'live',['SPY']),(True,'2026-10-12',False,'live',['SPY']),(True,'2026-10-12',True,'reconstructed',['SPY']),(True,'2026-10-12',True,'live',['QQQ'])])
def test_capture_outside_authorized_t0_has_no_artifacts(tmp_path,enabled,day,scheduled,mode,planned):
    area=experiment_root(tmp_path)
    atomic_write_json(area/'experiment.json',{'enabled':enabled,'t0':'2026-10-12'})
    batch=tmp_path/'batch';atomic_write_json(batch/'batch.json',{'scheduled':scheduled,'mode':mode,'planned_items':planned})
    capture_t0_b_state(tmp_path,batch,{'symbol':'SPY','upstream_trade_date':day},{},'Hold')
    assert not (area/'T0-state').exists() and not (area/'budget-stop.json').exists()


@pytest.mark.parametrize('fail_write',[False,True])
def test_real_runner_t0_capture_keeps_formal_B_success(tmp_path,monkeypatch,fail_write):
    import daily_analyzer.evaluation.ab_path as module
    import daily_analyzer.evaluation.ab_orchestrator as orchestrator
    root=_project(tmp_path,symbols=('SPY',))
    area=experiment_root(root)
    atomic_write_json(area/'experiment.json',{'enabled':True,'t0':'2026-10-02'})
    # 本节点只验证生产采集，不自动执行实验。
    monkeypatch.setattr(orchestrator,'completed_batch_hook',lambda *a,**k:{'status':'测试隔离，零A调用'})
    original=module.atomic_write_json
    def write(path,value):
        if fail_write and 'T0-state' in str(path):raise OSError('合成工件写入失败')
        return original(path,value)
    monkeypatch.setattr(module,'atomic_write_json',write)
    _FakeGraph.fail_symbols=set();_FakeGraph.errors_by_symbol={}
    outcome=_run(root,clock=lambda:datetime(2026,10,2,9,tzinfo=NY),scheduled=True)
    assert outcome.exit_code==0
    batch_path=next((root/'data/runs/2026-10-02/batches').glob('*/batch.json'))
    batch=json.loads(batch_path.read_text());record=json.loads((batch_path.parent/'results/SPY.json').read_text())
    assert record['status']=='success'
    if fail_write:
        assert json.loads((area/'budget-stop.json').read_text())['category']=='integrity'
    else:
        proof=json.loads((area/'T0-state'/batch['run_id']/'SPY.json').read_text())
        assert proof['full_state']['market_report']=='market'
        assert proof['result']==record
        assert verify_t0_b_states(root,batch,{'SPY':record})['status']=='passed'


def test_dispatch_real_upstream_date_preserves_original_B(tmp_path,monkeypatch):
    import daily_analyzer.evaluation.ab_orchestrator as module
    import daily_analyzer.evaluation.ab_reports as reports
    from test_ab_orchestrator import capture_fixture,fake_executor,Prices
    from daily_analyzer.config import EvaluationSettings
    from types import SimpleNamespace
    _,record=configured(tmp_path);record.pop('trade_date')
    source=tmp_path/'data/runs/2026-10-12/batches/run2026-10-12/results/SPY.json'
    atomic_write_json(source,record);before=source.read_bytes();capture_fixture(tmp_path,record)
    monkeypatch.setattr(module,'_current_ta_dirty',lambda:False)
    monkeypatch.setattr(module,'prepare_shadow_context',lambda root,row,**k: '原生产日期已标准化' if row['trade_date']==row['upstream_trade_date'] else pytest.fail('日期不一致'))
    monkeypatch.setattr(reports,'build_ledgers',lambda *a,**k:{'status':'隔离账户，不涉及本项'})
    result=module.dispatch(tmp_path,now=datetime(2026,10,12,17,tzinfo=NY),executor=fake_executor,
        reflector_factory=lambda *a:object(),services=SimpleNamespace(prices=Prices()),settings=EvaluationSettings())
    assert result['status']=='completed',result
    assert source.read_bytes()==before
    assert (experiment_root(tmp_path)/'B/2026-10-12/SPY.json').read_bytes()==before
    assert 'trade_date' not in json.loads(before)


@pytest.mark.parametrize('date_value',[None,'2026-10-13'])
def test_production_date_missing_or_conflicting_stops(tmp_path,date_value):
    _,record=configured(tmp_path)
    if date_value is None:record.pop('upstream_trade_date')
    else:record['upstream_trade_date']=date_value
    batch_path=tmp_path/'data/runs/2026-10-12/batches/run2026-10-12/batch.json'
    with pytest.raises(PathIntegrityError):verify_t0_b_states(tmp_path,json.loads(batch_path.read_text()),{'SPY':record})
    assert json.loads((experiment_root(tmp_path)/'budget-stop.json').read_text())['category']=='integrity'


def test_frozen_real_B_date_is_only_normalized_in_report_copy(tmp_path):
    from daily_analyzer.evaluation.ab_reports import frozen_results
    _,record=configured(tmp_path);record.pop('trade_date')
    path=experiment_root(tmp_path)/'B/2026-10-12/SPY.json';atomic_write_json(path,record);before=path.read_bytes()
    assert frozen_results(tmp_path)['B'][0]['trade_date']=='2026-10-12'
    assert path.read_bytes()==before

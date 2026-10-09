"""F2采集默认无行为变化；真实runner只读边界与工件失败不改B。"""
import hashlib,json
from datetime import datetime
from pathlib import Path
import pytest
from daily_analyzer.evaluation.ab_evidence import capture_evidence
from daily_analyzer.storage import atomic_write_json,append_log
from test_runner import _project,_run,_FakeGraph,NEW_YORK

class Graph(_FakeGraph):
    def propagate(self,*args,**kwargs):
        state,_=super().propagate(*args,**kwargs)
        return state,'Hold'

@pytest.mark.parametrize('enabled',[False,True])
def test_real_runner_collects_boundaries_without_enabling_experiment(tmp_path,enabled):
    from tradingagents.memory.log import TradingMemoryLog
    root=_project(tmp_path/'project',symbols=('SPY',));output=tmp_path/'evidence'
    atomic_write_json(root/'config/t49-evidence.json',{'enabled':enabled,'start_date':'2026-10-02','output_dir':str(output)})
    memory=root/'data/tradingagents/memory/trading_memory.md'
    TradingMemoryLog({'memory_log_path':str(memory)}).store_decision('NVDA','2026-10-01','真实格式的手动共同条目','Hold')
    initial=memory.read_bytes()
    cache=root/'data/tradingagents/cache/SPY-alpaca-data.csv';cache.parent.mkdir(parents=True);cache.write_text('Date,Close\n2026-10-01,100\n')
    def settle(root,now):
        p=root/'data/evaluation/outcomes.jsonl';p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{"合成":"结算原件"}\n')
        append_log(root,now.date(),now,'合成真实runner结算回执')
    _FakeGraph.fail_symbols=set();_FakeGraph.errors_by_symbol={}
    result=_run(root,clock=lambda:datetime(2026,10,2,9,tzinfo=NEW_YORK),scheduled=True,analyzer_factory=Graph,settler=settle)
    assert result.exit_code==0
    assert not (root/'data/evaluation/ab-path/experiment.json').exists()
    if not enabled:assert not output.exists();return
    receipts=[json.loads(p.read_text()) for p in output.glob('*/*/*/receipt.json')]
    events={r['event']:r for r in receipts}
    assert set(events)=={'batch_start','B_append_before','B_append_after','settlement_before','settlement_after','batch_end'}
    assert all(r['scheduled'] and r['mode']=='live' for r in receipts)
    assert events['batch_end']['qualifying_golden_batch']
    copied=next(s for s in events['batch_start']['sources'] if s['path']==str(memory))
    assert Path(copied['copy']).read_bytes()==initial
    for receipt in receipts:
        for source in receipt['sources']:
            if source.get('copy'):assert hashlib.sha256(Path(source['copy']).read_bytes()).hexdigest()==source['sha256']
    final=next(s for s in events['B_append_after']['sources'] if s['path']==str(memory))
    assert b'NVDA' in Path(final['copy']).read_bytes() and b'SPY' in Path(final['copy']).read_bytes()
    assert any('合成真实runner结算回执' in Path(s['copy']).read_text() for s in events['settlement_after']['sources'] if s.get('copy') and s['path'].endswith('.log'))


def test_collection_write_failure_does_not_change_formal_B(tmp_path):
    root=_project(tmp_path/'project',symbols=('SPY',));blocked=tmp_path/'blocked';blocked.write_text('文件不能作目录')
    atomic_write_json(root/'config/t49-evidence.json',{'enabled':True,'start_date':'2026-10-02','output_dir':str(blocked)})
    _FakeGraph.fail_symbols=set();_FakeGraph.errors_by_symbol={}
    outcome=_run(root,clock=lambda:datetime(2026,10,2,9,tzinfo=NEW_YORK),scheduled=True,analyzer_factory=Graph)
    assert outcome.exit_code==0
    row=json.loads(next((root/'data/runs/2026-10-02/batches').glob('*/results/SPY.json')).read_text())
    assert row['status']=='success'


def test_manual_evidence_is_retained_but_never_golden(tmp_path):
    root=tmp_path/'project';output=tmp_path/'evidence';batch=root/'data/runs/2026-10-12/batches/manual'
    atomic_write_json(root/'config/t49-evidence.json',{'enabled':True,'start_date':'2026-10-12','output_dir':str(output)})
    atomic_write_json(batch/'batch.json',{'run_id':'manual','trade_date':'2026-10-12','scheduled':False,'mode':'live','status':'completed'})
    result=capture_evidence(root,batch,'batch_end')
    receipt=json.loads(Path(result['receipt']).read_text())
    assert not receipt['scheduled'] and not receipt['qualifying_golden_batch']



def test_future_A_append_and_common_sync_capture_boundaries(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import pandas as pd
    import tradingagents.memory.settlement as memory_settlement
    from test_ab_orchestrator import configured,fake_executor,Prices
    from daily_analyzer.evaluation.ab_path import fork_history,prepare_shadow_context
    from daily_analyzer.evaluation.ab_orchestrator import _write_shadow_result
    from daily_analyzer.config import EvaluationSettings
    root=tmp_path/'project';output=tmp_path/'evidence'
    fork_history(root,'2026-10-12',now=datetime(2026,10,9,12,tzinfo=NEW_YORK))
    _,record=configured(root)
    atomic_write_json(root/'config/t49-evidence.json',{'enabled':True,'start_date':'2026-10-12','output_dir':str(output)})
    _write_shadow_result(root,record,fake_executor(None,None))
    monkeypatch.setattr(memory_settlement,'get_closes',lambda *a:pd.Series(dtype=float))
    def forbidden(**kwargs):pytest.fail('新采集夹具不得触发反思')
    prepare_shadow_context(root,record,reflector=SimpleNamespace(reflect_on_final_decision=forbidden),
        services=SimpleNamespace(prices=Prices()),previous_batch_finished=datetime(2026,10,9,9,tzinfo=NEW_YORK),settings=EvaluationSettings())
    receipts=[json.loads(p.read_text()) for p in output.glob('*/*/*/receipt.json')]
    events=[r['event'] for r in receipts]
    assert events.count('A_append_before')==events.count('A_append_after')==1
    assert events.count('A_common_sync_before')==events.count('A_common_sync_after')==2
    for receipt in receipts:
        assert receipt['run_id']==record['run_id'] and receipt['symbol']=='SPY'
        if 'sync' in receipt['event']:assert receipt['extra']['visible_at']=='2026-10-09T09:00:00-04:00'
        assert any('ab-path/A/data/tradingagents/memory' in s['path'] and s.get('copy') for s in receipt['sources'])



def test_control_stat_failure_is_isolated(tmp_path,monkeypatch):
    original=Path.exists
    def exists(path):
        if path.name=='t49-evidence.json':raise PermissionError('合成配置元数据读取失败')
        return original(path)
    monkeypatch.setattr(Path,'exists',exists)
    assert capture_evidence(tmp_path,tmp_path/'batch','batch_start')['status']=='failed'

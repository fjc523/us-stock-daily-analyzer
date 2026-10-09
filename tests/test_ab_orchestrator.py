"""T49 零付费编排、预算及成熟管线夹具。"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from daily_analyzer.config import EvaluationSettings
from daily_analyzer.evaluation.ab_budget import CallBudget, BudgetStop
from daily_analyzer.evaluation.ab_path import calendar_after, experiment_root, fork_history, copy_common_settlements
from daily_analyzer.evaluation.ab_orchestrator import dispatch, completed_batch_hook, mature_review
from daily_analyzer.evaluation.consistency import implementation_version
from daily_analyzer.storage import atomic_write_json
from test_consistency import fixture_snapshot

NY=ZoneInfo('America/New_York')


def test_budget_atomic_hard_cap_and_persistent_failed_attempts(tmp_path,monkeypatch):
    import daily_analyzer.evaluation.ab_budget as module
    monkeypatch.setattr(module,'LIMITS',{'codex_exec':20,'claude_exec':10})
    def reserve(_):
        try:CallBudget(tmp_path,'2026-10-12')('codex_exec',{'call_type':'reflection'});return True
        except BudgetStop:return False
    with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(reserve,range(35)))
    assert sum(results)==20
    assert len(CallBudget(tmp_path,'2026-10-12').rows())==20
    assert [r['attempt'] for r in CallBudget(tmp_path,'2026-10-12').rows()]==list(range(1,21))
    with pytest.raises(BudgetStop):CallBudget(tmp_path,'2026-10-13')('codex_exec',{})


def test_budget_calibration_stops_on_daily_excess(tmp_path):
    budget=CallBudget(tmp_path,'2026-10-12')
    for _ in range(19):budget('claude_exec',{})
    assert budget.calibrate(1)['stop'] is True
    with pytest.raises(BudgetStop):budget('codex_exec',{})


def test_disabled_hook_never_creates_runtime_or_calls_models(tmp_path,monkeypatch):
    import daily_analyzer.evaluation.ab_orchestrator as module
    monkeypatch.setattr(module,'dispatch',lambda *a,**k:pytest.fail('未启用不得派发'))
    assert completed_batch_hook(tmp_path,now=datetime(2026,10,12,10,tzinfo=NY))['model_calls']==0
    assert not experiment_root(tmp_path).exists()


class Prices:
    def bars(self,symbol,cutoff):
        import exchange_calendars as xcals
        import pandas as pd
        days=xcals.get_calendar('XNYS').sessions_in_range(pd.Timestamp('2026-10-08'),pd.Timestamp(cutoff))
        return [dict(date=d.date().isoformat(),open=100,high=103,low=99,close=101) for d in days],'合成同源日线'


def configured(tmp_path, day='2026-10-12'):
    area=experiment_root(tmp_path);state=calendar_after('2026-10-09')
    state.update(enabled=True,symbols=['SPY','QQQ','TSLA','SPCX'],previous_batch_finished='2026-10-09T09:00:00-04:00')
    atomic_write_json(area/'experiment.json',state)
    atomic_write_json(area/'A/fork.json',{'t0':state['t0']})
    version=implementation_version()
    batch={'planned_items':['SPY','QQQ','TSLA','SPCX'],'run_id':'run'+day,'trade_date':day,'mode':'live','scheduled':True,'status':'completed',
           'finished_at':day+'T09:00:00-04:00','tradingagents_dirty':False,
           'tradingagents_commit':version['heads']['TradingAgents'],'implementation_version':version}
    path=tmp_path/'data/runs'/day/'batches'/batch['run_id']
    atomic_write_json(path/'batch.json',batch)
    snapshot=fixture_snapshot();snapshot['config']['trade_date']=day;snapshot['state']['company_of_interest']='SPY';snapshot['state']['trade_date']=day
    record={'analyzed_symbol':'SPY','status':'success','symbol':'SPY','type':'etf','run_id':batch['run_id'],'mode':'live','trade_date':day,
            'finished_at':batch['finished_at'],'price_data_end_date':'2026-10-09','consistency_input':snapshot,
            'final_rating':'Hold','final_trade_decision':'**Recommendation**: Hold\n**Target Allocation**: 100%',
            'structured':{'pm_decision':{'rating':'Hold','target_allocation_pct':100,'buy_legs':[],'reduce_legs':[]}}}
    atomic_write_json(path/'results/SPY.json',record)
    return state,record


def fake_executor(snapshot,output,**kwargs):
    return {'final_rating':'Hold','final_trade_decision':'**Recommendation**: Hold\n**Target Allocation**: 100%',
            'structured_pm_decision':{'rating':'Hold','target_allocation_pct':100,'buy_legs':[],'reduce_legs':[]}}


def test_dispatch_success_idempotent_and_frozen_first_batch(tmp_path,monkeypatch):
    import daily_analyzer.evaluation.ab_orchestrator as module
    state,record=configured(tmp_path)
    monkeypatch.setattr(module,'_current_ta_dirty',lambda:False)
    monkeypatch.setattr(module,'prepare_shadow_context',lambda *a,**k:'影子历史')
    import daily_analyzer.evaluation.ab_reports as reports
    monkeypatch.setattr(reports,'build_ledgers',lambda *a,**k:{'status':'账户方式待投研裁定，测试仅隔离编排'})
    options=dict(now=datetime(2026,10,12,17,tzinfo=NY),executor=fake_executor,
                 reflector_factory=lambda *a:object(),services=SimpleNamespace(prices=Prices()),settings=EvaluationSettings())
    result=dispatch(tmp_path,**options)
    assert result['status']=='completed',result
    assert result['symbols']['SPY']['status']=='completed'
    assert result['symbols']['SPCX']['status']=='symmetric_missing'
    assert dispatch(tmp_path,**options)['status']=='idempotent'
    assert json.loads((experiment_root(tmp_path)/'B/2026-10-12/SPY.json').read_text())==record
    assert not (tmp_path/'data/evaluation/outcomes.jsonl').exists()


def test_F25_retry_before_next_pipeline_and_reject_after(tmp_path,monkeypatch):
    import daily_analyzer.evaluation.ab_orchestrator as module
    state,record=configured(tmp_path)
    monkeypatch.setattr(module,'_current_ta_dirty',lambda:False)
    monkeypatch.setattr(module,'prepare_shadow_context',lambda *a,**k:'影子历史')
    import daily_analyzer.evaluation.ab_reports as reports
    monkeypatch.setattr(reports,'build_ledgers',lambda *a,**k:{'status':'账户方式待投研裁定，测试仅隔离编排'})
    options=dict(reflector_factory=lambda *a:object(),services=SimpleNamespace(prices=Prices()),settings=EvaluationSettings())
    def fail(*a,**k):raise RuntimeError('合成失败')
    first=dispatch(tmp_path,now=datetime(2026,10,12,17,tzinfo=NY),executor=fail,**options)
    assert first['status']=='failed'
    retried=dispatch(tmp_path,now=datetime(2026,10,13,8,tzinfo=NY),retry_date='2026-10-12',executor=fake_executor,**options)
    assert retried['status']=='completed',retried
    atomic_write_json(experiment_root(tmp_path)/'days/2026-10-13.json',{'day':'2026-10-13','status':'running','symbols':{}})
    with pytest.raises(ValueError,match='截止'):
        dispatch(tmp_path,now=datetime(2026,10,13,10,tzinfo=NY),retry_date='2026-10-12',executor=fake_executor,**options)


def test_common_c2_does_not_leak_current_batch_settlement(tmp_path):
    area=experiment_root(tmp_path)
    fork_history(tmp_path,'2026-10-12',now=datetime(2026,10,9,12,tzinfo=NY))
    path=tmp_path/'data/evaluation/outcomes.jsonl';path.parent.mkdir(parents=True,exist_ok=True)
    row={'trade_date':'2026-10-09','run_id':'old','symbol':'SPY','is_current':True,'windows':{'5':{'status':'settled','exit_date':'2026-10-15','primary_return':.2,'settled_at':'2026-10-16T09:00:00-04:00'}}}
    path.write_text(json.dumps(row)+'\n')
    memory=area/'A/data/tradingagents/memory/trading_memory.md';memory.parent.mkdir(parents=True,exist_ok=True);memory.write_text('')
    copy_common_settlements(tmp_path,visible_at=datetime(2026,10,15,9,tzinfo=NY))
    result=json.loads((area/'A/data/evaluation/outcomes.jsonl').read_text())
    assert result['windows']['5']['status']=='pending' and result['windows']['5']['primary_return'] is None
    assert result['windows']['5']['exit_date']=='2026-10-15'


def test_mature_pipeline_no_model_factory_and_writes_real_report(tmp_path,monkeypatch):
    import daily_analyzer.evaluation.ab_orchestrator as module
    _,record=configured(tmp_path)
    from daily_analyzer.evaluation.ab_lifecycle import allocate_day
    area=experiment_root(tmp_path)
    allocation=allocate_day(None,day='2026-10-12',planned_items=['SPY'],successful={'SPY'},eligible={'SPY':True})
    atomic_write_json(area/'allocations/2026-10-12.json',allocation)
    atomic_write_json(area/'B/2026-10-12/SPY.json',record)
    monkeypatch.setattr(module,'_reflector',lambda *a:pytest.fail('成熟期禁止模型构造'))
    from daily_analyzer.cli import main
    observed=[]
    def controlled_review(root,**kwargs):
        result=mature_review(root,now=datetime(2026,11,13,17,tzinfo=NY),services=SimpleNamespace(prices=Prices(),sector_lookup=lambda s:{'status':'none','benchmark':None}),settings=EvaluationSettings())
        observed.append(result);return result
    monkeypatch.setattr(module,'mature_review',controlled_review)
    monkeypatch.chdir(tmp_path)
    assert main(['ab-path','mature'])==0
    outcome=observed[0]
    assert outcome['model_calls']==0 and outcome['status']=='mature_review'
    assert outcome['ledger']['status']=='completed'
    assert json.loads((area/'ledger/curves.json').read_text())['index_name']=='合成配对差值指数'
    assert (experiment_root(tmp_path)/'reports/D25.json').exists()
    assert not (experiment_root(tmp_path)/'reports/D30.json').exists()


def test_shadow_production_functions_pit_reflection_and_c2_lag(tmp_path,monkeypatch):
    from daily_analyzer.evaluation.ab_path import prepare_shadow_context, shadow_config
    from daily_analyzer.evaluation.ab_orchestrator import _write_shadow_result
    from tradingagents.memory.log import TradingMemoryLog
    import tradingagents.memory.settlement as memory_settlement
    from tradingagents.dataflows.config import get_config
    import exchange_calendars as xcals
    import pandas as pd
    fork_history(tmp_path,'2026-10-12',now=datetime(2026,10,9,12,tzinfo=NY))
    state,record=configured(tmp_path)
    # configured只写fork标记，完整准备真实分叉目录。
    target=experiment_root(tmp_path)/'A'
    memory=target/'data/tradingagents/memory/trading_memory.md';memory.parent.mkdir(parents=True,exist_ok=True);memory.write_text('')
    out=target/'data/evaluation/outcomes.jsonl';out.parent.mkdir(parents=True,exist_ok=True);out.write_text('')
    _write_shadow_result(tmp_path,record,fake_executor(None,None))
    calls=[];cutoffs=[]
    def closes(symbol,start,end):
        cutoff=get_config()['price_data_end_date'];cutoffs.append(cutoff)
        sessions=xcals.get_calendar('XNYS').sessions_in_range(pd.Timestamp(start),pd.Timestamp(min(cutoff,end)))
        return pd.Series([100+i for i in range(len(sessions))],index=sessions)
    monkeypatch.setattr(memory_settlement,'get_closes',closes)
    reflector=SimpleNamespace(reflect_on_final_decision=lambda **kwargs:calls.append(kwargs) or '合成反思')
    contexts=[]
    cal=xcals.get_calendar('XNYS')
    for day in state['days'][1:7]:
        current=deepcopy(record);current['trade_date']=day
        previous=cal.previous_session(pd.Timestamp(day)).date().isoformat()
        context=prepare_shadow_context(tmp_path,current,reflector=reflector,
            services=SimpleNamespace(prices=Prices(),sector_lookup=lambda s:{'status':'none','benchmark':None}),
            previous_batch_finished=datetime.fromisoformat(previous+'T09:00:00-04:00'),settings=EvaluationSettings())
        contexts.append(context)
        assert cutoffs[-1]==previous
    assert all('2026-10-12' not in s for s in contexts[:5])
    assert '2026-10-12' in contexts[5] and len(calls)==1
    log=TradingMemoryLog(shadow_config(tmp_path,record['consistency_input']['config'],state['days'][6]))
    own=log.load_entries()[0]
    assert own['resolved']=='2026-10-19' and own['reflection']=='合成反思'


def test_B_all_symbols_frozen_before_first_A_failure(tmp_path,monkeypatch):
    import daily_analyzer.evaluation.ab_orchestrator as module
    _,record=configured(tmp_path)
    for symbol in ('QQQ','TSLA','SPCX'):
        copied=deepcopy(record);copied['symbol']=symbol;copied['analyzed_symbol']=symbol;copied['consistency_input']['state']['company_of_interest']=symbol
        atomic_write_json(tmp_path/'data/runs/2026-10-12/batches/run2026-10-12/results'/f'{symbol}.json',copied)
    monkeypatch.setattr(module,'_current_ta_dirty',lambda:False)
    monkeypatch.setattr(module,'prepare_shadow_context',lambda *a,**k:'影子历史')
    import daily_analyzer.evaluation.ab_reports as reports
    monkeypatch.setattr(reports,'build_ledgers',lambda *a,**k:{'status':'账户方式待投研裁定，测试仅隔离编排'})
    def fail(*a,**k):raise RuntimeError('首SPY失败')
    result=dispatch(tmp_path,now=datetime(2026,10,12,17,tzinfo=NY),executor=fail,
        reflector_factory=lambda *a:object(),services=SimpleNamespace(prices=Prices()),settings=EvaluationSettings())
    assert result['status']=='failed'
    assert sorted(p.stem for p in (experiment_root(tmp_path)/'B/2026-10-12').glob('*.json'))==['QQQ','SPCX','SPY','TSLA']


@pytest.mark.parametrize('fatal,attempts',[(True,0),(False,48)])
def test_integrity_stop_and_failed_day_calibration(tmp_path,monkeypatch,fatal,attempts):
    import daily_analyzer.evaluation.ab_orchestrator as module
    from tradingagents.llm_clients.codex_exec.runner import reserve_model_call
    from daily_analyzer.evaluation.consistency import PathIntegrityError
    configured(tmp_path)
    monkeypatch.setattr(module,'_current_ta_dirty',lambda:False)
    def fail(*a,**k):
        for _ in range(attempts):reserve_model_call('codex_exec')
        if fatal:raise PathIntegrityError('明确保护指纹失配')
        raise RuntimeError('瞬时失败，实际尝试已超过日校准')
    monkeypatch.setattr(module,'prepare_shadow_context',fail)
    options=dict(now=datetime(2026,10,12,17,tzinfo=NY),executor=fake_executor,
                 reflector_factory=lambda *a:object(),services=SimpleNamespace(prices=Prices()),settings=EvaluationSettings())
    result=dispatch(tmp_path,**options)
    assert result['status']=='failed'
    area=experiment_root(tmp_path)
    assert (area/'budget-stop.json').exists() and (area/'budget-report.json').exists()
    assert dispatch(tmp_path,**options)['status']=='stopped'
    if fatal:assert json.loads((area/'budget-stop.json').read_text())['category']=='integrity'
    else:assert len(CallBudget(area,'2026-10-12').rows())==48


@pytest.mark.parametrize('wrong',['analyzed','both_symbol','date'])
def test_allocation_identity_mismatch_stops_before_model(tmp_path,monkeypatch,wrong):
    import daily_analyzer.evaluation.ab_orchestrator as module
    from daily_analyzer.evaluation.consistency import PathIntegrityError
    _,record=configured(tmp_path)
    if wrong=='date':record['consistency_input']['state']['trade_date']='2026-10-13'
    else:
        record['analyzed_symbol']='QQQ'
        if wrong=='both_symbol':record['consistency_input']['state']['company_of_interest']='QQQ'
    atomic_write_json(tmp_path/'data/runs/2026-10-12/batches/run2026-10-12/results/SPY.json',record)
    monkeypatch.setattr(module,'_current_ta_dirty',lambda:False)
    with pytest.raises(PathIntegrityError,match='身份'):
        dispatch(tmp_path,now=datetime(2026,10,12,17,tzinfo=NY),executor=lambda *a:pytest.fail('身份错误不得调用'),services=SimpleNamespace(prices=Prices()),settings=EvaluationSettings())
    assert json.loads((experiment_root(tmp_path)/'budget-stop.json').read_text())['category']=='integrity'


def test_dynamic_symbol_uses_record_identity_not_filename_slug(tmp_path,monkeypatch):
    import daily_analyzer.evaluation.ab_orchestrator as module
    _,record=configured(tmp_path)
    batch_path=tmp_path/'data/runs/2026-10-12/batches/run2026-10-12/batch.json'
    batch=json.loads(batch_path.read_text());batch['planned_items']=['BRK.B'];atomic_write_json(batch_path,batch)
    record['symbol']=record['analyzed_symbol']='BRK.B';record['consistency_input']['state']['company_of_interest']='BRK.B'
    old=batch_path.parent/'results/SPY.json';old.unlink()
    atomic_write_json(batch_path.parent/'results/BRK-B.json',record)
    monkeypatch.setattr(module,'_current_ta_dirty',lambda:False)
    monkeypatch.setattr(module,'prepare_shadow_context',lambda *a,**k:'影子历史')
    import daily_analyzer.evaluation.ab_reports as reports
    monkeypatch.setattr(reports,'build_ledgers',lambda *a,**k:{'status':'仅验证动态原件文件映射，不决定费用'})
    result=dispatch(tmp_path,now=datetime(2026,10,12,17,tzinfo=NY),executor=fake_executor,reflector_factory=lambda *a:object(),services=SimpleNamespace(prices=Prices()),settings=EvaluationSettings())
    assert result['status']=='completed',result
    assert result['allocation']['run_symbols']==['BRK.B']
    assert result['symbols']['BRK.B']['status']=='completed'

"""T49 禁用的批次完成接入与独立路径编排，成熟期只做离线结算。"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
import fcntl
import hashlib
import json
from pathlib import Path

from daily_analyzer.storage import atomic_write_json
from daily_analyzer.time_utils import NEW_YORK, previous_trading_day, session_bounds
from .ab_path import SYMBOLS, experiment_root, calendar_after, fork_history, shadow_config, prepare_shadow_context, adapt_result
from .ab_budget import CallBudget, BudgetStop
from tradingagents.llm_clients.claude_exec.runner import ClaudeConfigError
from tradingagents.llm_clients.codex_exec.errors import CodexFatalConfigError
from .consistency import run_consistency, implementation_version, input_hash, isolated_config, PathIntegrityError


def read_state(root):
    path=experiment_root(root)/'experiment.json'
    return json.loads(path.read_text()) if path.exists() else {'enabled':False,'status':'待投研最终审核'}


def batches(root):
    values=[]
    for path in (Path(root)/'data/runs').glob('*/batches/*/batch.json'):
        row=json.loads(path.read_text());row['_path']=str(path)
        if row.get('mode')=='live' and row.get('scheduled') and row.get('status')=='completed' and row.get('finished_at'):
            values.append(row)
    return sorted(values,key=lambda row:(row['trade_date'],row['finished_at'],row['run_id']))


def check_idle(root):
    """仅核查生产锁，不接管正在运行的批次。"""
    path=Path(root)/'data/run.lock'
    if path.exists():
        with path.open('r') as stream:
            try:fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise ValueError('生产批次尚未释放运行锁') from None
            finally:fcntl.flock(stream.fileno(),fcntl.LOCK_UN)


def prepare_experiment(root, accepted_at, review_reference, *, now):
    """仅供最终投研通过后主负责人准备；分叉和空跑完成仍保持禁用。"""
    if not review_reference.strip():raise ValueError('必须记录最终投研审核通过原件')
    check_idle(root)
    state=calendar_after(accepted_at)
    completed=batches(root)
    previous=[b for b in completed if b['trade_date']<state['t0']]
    if not previous or previous[-1]['trade_date']!=previous_trading_day(date.fromisoformat(state['t0'])).isoformat():
        raise ValueError('T0−1成功定时批次及结算尚未具备，不能分叉')
    fork_history(root,state['t0'],now=now)
    state.update(enabled=False,status='已分叉待空跑',review_reference=review_reference,
                 symbols=list(SYMBOLS),account_mode='v5.3',prepared_at=now.isoformat(),previous_batch_finished=previous[-1]['finished_at'])
    atomic_write_json(experiment_root(root)/'experiment.json',state)
    return dry_run(root,now=now)


def dry_run(root, *, now):
    """不创建图、不调用模型，只核分叉、时点与动态名额编排配置。"""
    check_idle(root);state=read_state(root)
    fork=experiment_root(root)/'A/fork.json'
    if not fork.exists():raise ValueError('影子分叉未准备')
    if any(b['trade_date']>=state['t0'] for b in batches(root)) or now.astimezone(NEW_YORK)>=session_bounds(date.fromisoformat(state['t0']))[0]:
        raise ValueError('T0批次前空跑未完成，T0须顺延')
    state.update(dry_run_at=now.isoformat(),status='空跑通过待主负责人启用')
    atomic_write_json(experiment_root(root)/'experiment.json',state)
    return state


def enable(root, *, now):
    """主负责人最终投研通过后的启用步骤，开发交付不调用。"""
    state=dry_run(root,now=now)
    if not state.get('review_reference'):raise ValueError('缺最终投研审核通过原件')
    state.update(enabled=True,status='等待T0生产成功批次')
    atomic_write_json(experiment_root(root)/'experiment.json',state)
    return state


def disable(root):
    """停止新的实验模型调用，已生成结果保留供离线续评。"""
    state=read_state(root);state.update(enabled=False,status='已停用新模型调用')
    atomic_write_json(experiment_root(root)/'experiment.json',state)
    return state


def _current_ta_dirty():
    import subprocess
    path=Path(__file__).resolve().parents[3]/'TradingAgents'
    return bool(subprocess.check_output(['git','-C',str(path),'status','--porcelain'],text=True).strip())


def check_version(batch):
    """日批次记录的实际源码与入口必须完全一致，dirty批次不放行。"""
    version=implementation_version()
    if _current_ta_dirty() or batch.get('tradingagents_dirty') is not False or batch.get('tradingagents_commit')!=version['heads']['TradingAgents']:
        raise PathIntegrityError('生产TA版本或dirty与测试入口不一致')
    if batch.get('implementation_version')!=version:
        raise PathIntegrityError('生产实现指纹缺失或不一致，不得用当前版本补跑')
    return version


def _reflector(snapshot, config):
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    return TradingAgentsGraph(selected_analysts=snapshot['selected_analysts'],config=config).reflector


def _write_shadow_result(root, record, state, calls=None, artifact=None):
    from tradingagents.memory.log import TradingMemoryLog
    cfg=shadow_config(root,record['consistency_input']['config'],record['trade_date'])
    rating=state.get('final_rating') or (state.get('structured_pm_decision') or {}).get('rating')
    if rating not in ('Buy','Overweight','Hold','Underweight','Sell') or not state.get('final_trade_decision'):
        raise ValueError('影子最终评级或正文缺失，不能记入路径')
    result=adapt_result(record,state,rating)
    result['llm_usage']=calls or []
    result['experiment_artifact']=str(artifact) if artifact else None
    result.setdefault('llm',{}).pop('roles',None)
    from daily_analyzer.model_usage import apply_execution_labels
    from .plan_checks import decision_plan_checks
    result['decision_flags']=decision_plan_checks(result,cfg)
    apply_execution_labels(result,{**cfg,'role_llm_scheme':'A'})
    target=experiment_root(root)/'A/data/runs'/record['trade_date']
    atomic_write_json(target/'batches'/record['run_id']/'results'/f"{record['symbol']}.json",result)
    atomic_write_json(target/'current'/f"{record['symbol']}.json",result)
    from .ab_evidence import capture_evidence
    source_batch=Path(root)/'data/runs'/record['trade_date']/'batches'/record['run_id']
    capture_evidence(root,source_batch,'A_append_before',symbol=record['symbol'])
    TradingMemoryLog(cfg).store_decision(record['symbol'],record['trade_date'],state['final_trade_decision'],rating)
    capture_evidence(root,source_batch,'A_append_after',symbol=record['symbol'])
    return result


def dispatch(root, *, now, retry_date=None, executor=None, reflector_factory=None, services=None, settings=None):
    """生产成功完成并释放锁后执行；唯一首成功定时批次、日期幂等、截止锁定。"""
    state=read_state(root)
    if not state.get('enabled'):return {'status':'disabled','model_calls':0}
    check_idle(root)
    area=experiment_root(root);area.mkdir(parents=True,exist_ok=True)
    with (area/'dispatch.lock').open('a+') as lock:
        try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return {'status':'already_running','model_calls':0}
        available={}
        for batch in batches(root):available.setdefault(batch['trade_date'],batch)
        today=now.astimezone(NEW_YORK).date().isoformat()
        if today>state['days'][19]:
            return mature_review(root,now=now,services=services,settings=settings)
        if (area/'budget-stop.json').exists():return {'status':'stopped','model_calls':0,'report':str(area/'budget-stop.json')}
        requested=retry_date or today
        if requested>today:raise ValueError('不能运行未来决策日')
        if retry_date and any(p.stem>requested for p in (area/'days').glob('*.json')):
            raise ValueError('重试超过下一次A管线启动截止，永久拒收')
        day=next((d for d in state['days'][:20] if d==requested and d in available),None)
        if day is None:return {'status':'waiting_successful_batch','model_calls':0}
        batch=available[day]
        if datetime.fromisoformat(batch['finished_at'])>now:raise ValueError('批次完成时刻尚未到达')
        journal=area/'days'/f'{day}.json'
        previous=json.loads(journal.read_text()) if journal.exists() else {}
        if previous.get('status') in ('completed','missing_locked'):
            return {'status':'idempotent','day':day,'model_calls':0}
        try:check_version(batch)
        except PathIntegrityError as exc:
            atomic_write_json(area/'budget-stop.json',{'category':'integrity','reason':'版本/身份/保护指纹失配，立即停止交开发','error':str(exc)})
            raise
        # 当本日管线启动时，旧日未完成结果永久锁定；永不事后插入记忆。
        for old in (area/'days').glob('*.json') if (area/'days').exists() else []:
            value=json.loads(old.read_text())
            if value['day']<day and value.get('status') not in ('completed','missing_locked'):
                value.update(status='missing_locked',retry_deadline=now.isoformat())
                atomic_write_json(old,value)
        for older in state['days'][:20]:
            if older>=day:break
            absent=area/'days'/f'{older}.json'
            if not absent.exists():atomic_write_json(absent,{'day':older,'status':'missing_locked','retry_deadline':now.isoformat(),'symbols':{s:{'status':'symmetric_missing'} for s in SYMBOLS}})
        from .ab_lifecycle import MissingPlannedItems
        if 'planned_items' not in batch:
            raise MissingPlannedItems('NOT_TESTED：批次缺不可变完整planned_items，拒绝生命周期重建')
        result={**previous,'day':day,'run_id':batch['run_id'],'status':'running','pipeline_started_at':previous.get('pipeline_started_at',now.isoformat()),'symbols':previous.get('symbols',{})}
        atomic_write_json(journal,result)
        records={}
        for path in (Path(batch['_path']).parent/'results').glob('*.json'):
            record=json.loads(path.read_text())
            records[record['symbol']]=record
        # B冻结独立于A成败，先一次保存本批全部成功可冻结标的。
        for symbol in batch['planned_items']:
            record=records.get(symbol)
            if record and record.get('status')=='success' and record.get('consistency_input'):
                frozen=area/'B'/day/f'{symbol}.json'
                if frozen.exists() and json.loads(frozen.read_text())!=record:
                    atomic_write_json(area/'budget-stop.json',{'category':'integrity','reason':'首批B冻结原件发生变化，停止交开发'})
                    raise PathIntegrityError('首批B冻结原件发生变化')
                atomic_write_json(frozen,record)
        from .ab_path import verify_t0_b_states, experiment_record
        verify_t0_b_states(root,batch,records)
        # 正式B与冻结原件不补写字段；仅实验工作副本采用标准日期。
        try:
            records={symbol:experiment_record(record)
                     for symbol,record in records.items() if record.get('status')=='success'}
        except PathIntegrityError as exc:
            atomic_write_json(area/'budget-stop.json',{'category':'integrity','reason':'生产日期适配失败','error':str(exc)})
            raise
        previous_finished=max((b['finished_at'] for b in available.values() if b['trade_date']<day),default=state['previous_batch_finished'])
        from daily_analyzer.config import load_project_config
        from .settlement import SettlementServices
        if settings is None:settings=load_project_config(root).settings.evaluation
        services=services or SettlementServices(area/'A')
        from .ab_lifecycle import allocate_day
        from .ab_ledger import resolve_cost
        from .settlement import bar_prices
        allocation_file=area/'allocations'/f'{day}.json'
        if allocation_file.exists():
            allocation=json.loads(allocation_file.read_text())
        else:
            older=sorted(p for p in (area/'allocations').glob('*.json') if p.stem<day)
            previous_allocation=json.loads(older[-1].read_text()) if older else None
            eligible={}
            price_cutoff=previous_trading_day(date.fromisoformat(day))
            for symbol in batch['planned_items']:
                record=records.get(symbol,{})
                snapshot=record.get('consistency_input') or {}
                identity=(snapshot.get('state') or {}).get('company_of_interest')
                analyzed=record.get('analyzed_symbol')
                if record.get('status')=='success' and snapshot:
                    snapshot_day=(snapshot.get('state') or {}).get('trade_date')
                    if not (symbol==record.get('symbol')==analyzed==identity and day==record.get('trade_date')==snapshot_day):
                        atomic_write_json(area/'budget-stop.json',{'category':'integrity','reason':'冻结身份或日期失配，立即停止交开发','symbol':symbol})
                        raise PathIntegrityError('冻结身份或日期失配')
                if not identity or not analyzed:
                    eligible[symbol]=False;continue
                raw,_=services.prices.bars(symbol,price_cutoff)
                bar=bar_prices(raw,price_cutoff,include_extremes=True).get(price_cutoff,{})
                eligible[symbol]=all(bar.get(k) is not None and bar[k]>0 for k in ('open','high','low','close'))
            successful={s for s,r in records.items() if r.get('status')=='success' and r.get('consistency_input')}
            allocation=allocate_day(previous_allocation,day=day,planned_items=batch['planned_items'],successful=successful,eligible=eligible,cost_policies={s:resolve_cost(s,records.get(s,{}).get('type')) for s in batch['planned_items']})
            atomic_write_json(allocation_file,allocation)
        result['allocation']=allocation
        for symbol,status in allocation['audit'].items():
            if status!='运行A':result['symbols'][symbol]={'status':'symmetric_missing' if status=='缺失' else status}
        atomic_write_json(journal,result)
        budget=CallBudget(area,day)
        from tradingagents.llm_clients.codex_exec.runner import model_call_guard, codex_usage_context
        from .consistency import execute_saved
        try:
            with model_call_guard(budget):
                for symbol in allocation['run_symbols']:
                    if result['symbols'].get(symbol,{}).get('status')=='completed':continue
                    record=records.get(symbol)
                    if not record or record.get('status')!='success' or not record.get('consistency_input'):
                        result['symbols'][symbol]={'status':'symmetric_missing'};continue
                    cfg=shadow_config(root,record['consistency_input']['config'],day)
                    saved=area/'A/data/runs'/day/'batches'/record['run_id']/'results'/f'{symbol}.json'
                    if saved.exists():
                        recovered=json.loads(saved.read_text())
                        from tradingagents.memory.log import TradingMemoryLog
                        TradingMemoryLog(cfg).store_decision(symbol,day,recovered['final_trade_decision'],recovered['final_rating'])
                        result['symbols'][symbol]={'status':'completed','artifact':recovered.get('experiment_artifact'),'recovered_from_saved_result':True}
                        atomic_write_json(journal,result)
                        continue
                    reflect=(reflector_factory or _reflector)(record['consistency_input'],cfg)
                    with codex_usage_context(ticker=symbol,call_type='reflection'):
                        past=prepare_shadow_context(root,record,reflector=reflect,services=services,
                              previous_batch_finished=datetime.fromisoformat(previous_finished),settings=settings)
                    past_file=area/'A/past-context'/day/f'{symbol}.txt';past_file.parent.mkdir(parents=True,exist_ok=True);past_file.write_text(past,encoding='utf-8')
                    outcome=run_consistency(root,batch['run_id'],repeats=1,from_stage='debate',test_mode=True,
                        symbols=[symbol],executor=executor or execute_saved,overrides={'role_llm_scheme':'A'},
                        group='abpath-A',path_mode=True,past_context_file=past_file)
                    artifact=Path(outcome['report']).parent/symbol/'1/result.json'
                    content=json.loads(artifact.read_text())
                    if content['state'].get('data_queries'):raise PathIntegrityError('冻结A发生新增取数')
                    # 写入前再次核截止；不同进程不能把旧结果追加到新日之后。
                    if any(p.stem>day for p in (area/'days').glob('*.json')):raise ValueError('A结果超过下一管线启动截止，拒收')
                    _write_shadow_result(root,record,content['state'],content['llm_usage'],artifact)
                    result['symbols'][symbol]={'status':'completed','artifact':str(artifact),
                        'b_past_context_hash':hashlib.sha256(record['consistency_input']['state']['past_context'].encode()).hexdigest(),
                        'a_past_context_hash':hashlib.sha256(past.encode()).hexdigest(),
                        'reflection_count':past.count('REFLECTION:'),'input_hash':content['input_hash']}
                    atomic_write_json(journal,result)
            result['status']='completed';result['finished_at']=now.isoformat()
            atomic_write_json(journal,result)
            complete=len([p for p in (area/'days').glob('*.json') if json.loads(p.read_text()).get('status')=='completed'])
            budget.calibrate(complete)
            from .ab_reports import build_ledgers
            result['ledger']=build_ledgers(root,now=now,services=services)
        except Exception as exc:
            if isinstance(exc,(PathIntegrityError,ClaudeConfigError,CodexFatalConfigError)):
                atomic_write_json(area/'budget-stop.json',{'category':'integrity','reason':'版本/身份/保护指纹失配，立即停止交开发','error':str(exc)})
            budget.calibrate(max(1,len({r['day'] for r in budget.rows()})))
            if 'Quota' in type(exc).__name__:
                result['quota_limited']=True
                preceding=[json.loads(p.read_text()) for p in (area/'days').glob('*.json') if p.stem<day]
                if preceding and max(preceding,key=lambda j:j['day']).get('quota_limited'):
                    atomic_write_json(area/'budget-stop.json',{'reason':'连续2个决策日额度触限，请用户裁决顺延或终止','day':day})
            result.update(status='failed',error=f'{type(exc).__name__}: {exc}')
            atomic_write_json(journal,result)
            return result
        return result


def mature_review(root, *, now, services=None, settings=None):
    """D21/D25/D30/D40仅结算既有决策，不实例化模型或生成新反思。"""
    from .settlement import settle, SettlementServices
    from daily_analyzer.config import load_project_config
    area=experiment_root(root);state=read_state(root)
    today=now.astimezone(NEW_YORK).date().isoformat()
    if today<=state['days'][19]:return {'status':'sampling_not_finished','model_calls':0}
    settings=settings or load_project_config(root).settings.evaluation
    services=services or SettlementServices(area/'A')
    settle(area/'A',now=now,services=services,settings=settings,manual={})
    from .ab_reports import build_ledgers, maturity_report
    ledger=build_ledgers(root,now=now,services=services)
    reports=[]
    for label,day in [('D21',state['main_report']),*zip(('D25','D30','D40'),state['mature_reviews'])]:
        path=area/'reports'/f'{label}.json'
        if today>=day and not path.exists():
            content=maturity_report(root,label=label,as_of=now)
            atomic_write_json(path,content);reports.append(str(path))
    return {'status':'mature_review','model_calls':0,'reports':reports,'ledger':ledger}


def completed_batch_hook(root, *, now):
    """默认只读无实验配置即返回；失败仅写实验目录，不改变生产结果。"""
    if not read_state(root).get('enabled'):return {'status':'disabled','model_calls':0}
    try:return dispatch(root,now=now)
    except Exception as exc:
        result={'status':'failed','error':f'{type(exc).__name__}: {exc}'}
        atomic_write_json(experiment_root(root)/'hook-error.json',result)
        return result

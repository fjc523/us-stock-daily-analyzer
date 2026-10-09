"""T49 独立路径基础：只写实验根，复用正式记忆与结算函数。"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
import hashlib
import json
from pathlib import Path

import exchange_calendars as xcals
import pandas as pd

from daily_analyzer.storage import atomic_write_json
from daily_analyzer.time_utils import NEW_YORK, previous_trading_day

SYMBOLS = ('SPY', 'QQQ', 'TSLA', 'SPCX')


def experiment_root(root):
    """固定唯一实验写入根，不接受任意输出路径。"""
    return Path(root).resolve() / 'data/evaluation/ab-path'


def calendar_after(accepted_at):
    """验收按美东日计，T0 严格晚于验收日，生成 D1–D40。"""
    accepted = datetime.fromisoformat(accepted_at) if isinstance(accepted_at, str) and 'T' in accepted_at else accepted_at
    day = accepted.astimezone(NEW_YORK).date() if isinstance(accepted, datetime) and accepted.tzinfo else (accepted.date() if isinstance(accepted, datetime) else date.fromisoformat(str(accepted)))
    cal = xcals.get_calendar('XNYS')
    first = cal.date_to_session(pd.Timestamp(day), direction='next')
    if first.date() <= day:
        first = cal.next_session(first)
    days = [cal.session_offset(first, i).date().isoformat() for i in range(40)]
    return {'acceptance_et_date': day.isoformat(), 't0': days[0], 'days': days,
            'sampling_end': days[19], 'main_report': days[20],
            'mature_reviews': [days[i-1] for i in (25, 30, 40)]}


def _memory_blocks(path):
    from tradingagents.memory.log import TradingMemoryLog
    if not path.exists():
        return []
    return [block for block in path.read_text(encoding='utf-8').split(TradingMemoryLog._SEPARATOR)
            if block.strip()]


def _block_date(block):
    return block.strip().splitlines()[0][1:11]


def fork_history(root, t0, *, now):
    """T0 批次开始前分叉共同历史，既有分叉禁止覆盖。"""
    from daily_analyzer.time_utils import session_bounds
    from tradingagents.memory.log import TradingMemoryLog
    root = Path(root).resolve()
    target = experiment_root(root) / 'A'
    if (target/'fork.json').exists():
        raise ValueError('影子分叉已存在，禁止覆盖')
    t0_day = date.fromisoformat(t0)
    # 分叉必须先于 T0 生产批次，而不只先于开盘。
    for path in (root/'data/runs'/t0).glob('batches/*/batch.json'):
        raise ValueError('T0 生产批次已启动，须顺延交易日')
    if now.astimezone(NEW_YORK) >= session_bounds(t0_day)[0]:
        raise ValueError('已过T0开盘，须顺延交易日')
    memory = root/'data/tradingagents/memory/trading_memory.md'
    blocks = [b for b in _memory_blocks(memory) if _block_date(b) < t0]
    destination = target/'data/tradingagents/memory/trading_memory.md'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(TradingMemoryLog._SEPARATOR.join(blocks)+(TradingMemoryLog._SEPARATOR if blocks else ''), encoding='utf-8')
    outcomes = root/'data/evaluation/outcomes.jsonl'
    rows = [json.loads(line) for line in outcomes.read_text().splitlines() if line.strip()] if outcomes.exists() else []
    rows = [r for r in rows if r.get('trade_date', '') < t0]
    out = target/'data/evaluation/outcomes.jsonl'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(''.join(json.dumps(r, ensure_ascii=False, sort_keys=True)+'\n' for r in rows), encoding='utf-8')
    atomic_write_json(target/'fork.json', {'t0': t0, 'forked_at': now.isoformat(),
        'symbols': list(SYMBOLS), 'source_memory_sha256': hashlib.sha256(memory.read_bytes()).hexdigest() if memory.exists() else None})
    return target


def shadow_config(root, config, day):
    """影子行情/模型日志及记忆路径均与正式目录隔离。"""
    target = experiment_root(root)/'A'
    result = deepcopy(config)
    result.update(memory_log_path=str(target/'data/tradingagents/memory/trading_memory.md'),
                  evaluation_outcomes_path=str(target/'data/evaluation/outcomes.jsonl'),
                  data_cache_dir=str(target/'data/tradingagents/cache'),
                  results_dir=str(target/'data/tradingagents/results'),
                  codex_usage_log_path=str(target/'llm_calls.jsonl'),
                  price_data_end_date=previous_trading_day(date.fromisoformat(day)).isoformat(),
                  role_llm_fallback=False, claude_retries=0, codex_retries=0, settlement_strict_errors=True)
    return result


def copy_common_settlements(root, *, visible_at=None):
    """只同步 T0 前共同条目的生产结算和反思原文，不重新调用模型。"""
    from tradingagents.memory.log import TradingMemoryLog
    target = experiment_root(root)/'A'
    fork = json.loads((target/'fork.json').read_text())
    formal = {_block_date(b)+b.strip().splitlines()[0].split('|')[1].strip(): b
              for b in _memory_blocks(Path(root)/'data/tradingagents/memory/trading_memory.md')
              if _block_date(b) < fork['t0']}
    memory = target/'data/tradingagents/memory/trading_memory.md'
    blocks = _memory_blocks(memory)
    blocks = [formal.get(_block_date(b)+b.strip().splitlines()[0].split('|')[1].strip(), b)
              if _block_date(b) < fork['t0'] else b for b in blocks]
    memory.write_text(TradingMemoryLog._SEPARATOR.join(blocks)+(TradingMemoryLog._SEPARATOR if blocks else ''), encoding='utf-8')
    from daily_analyzer.evaluation.settlement import load_outcomes, write_outcomes
    source = load_outcomes(Path(root)/'data/evaluation/outcomes.jsonl')
    path = target/'data/evaluation/outcomes.jsonl'
    own = [r for r in load_outcomes(path) if r.get('trade_date', '') >= fork['t0']]
    common = [r for r in source if r.get('trade_date', '') < fork['t0']]
    if visible_at is not None:
        for row in common:
            for key,window in list(row.get('windows',{}).items()):
                stamp=window.get('settled_at')
                if stamp and datetime.fromisoformat(stamp)>visible_at:
                    row['windows'][key]={'status':'pending','exit_date':window['exit_date'],'raw_return':None,'excess_vs_spy':None,'excess_vs_sector':None,'primary_return':None}
    write_outcomes(path, common + own)


def adapt_result(record, final_state, rating):
    """冻结生产元信息，最终字段复用 runner，绝不写正式 runs。"""
    from daily_analyzer.runner import final_state_result_fields
    result = deepcopy(record)
    result.update(final_state_result_fields(final_state, rating))
    for key in ('investment_plan','trader_investment_plan','decision_flags'):
        result[key]=deepcopy(final_state.get(key))
    result.update(test_only=True, production_decision=False, data_queries=[])
    return result


def prepare_shadow_context(root, record, *, reflector, services, previous_batch_finished, settings):
    """反思严格 t−1；C2 先按前批完成时刻结算，再生成本日事实表。"""
    from tradingagents.memory.log import TradingMemoryLog
    from tradingagents.memory.settlement import settle_pending
    from tradingagents.dataflows.config import run_config
    from daily_analyzer.evaluation.settlement import settle
    target = experiment_root(root)/'A'
    fork = json.loads((target/'fork.json').read_text())
    day = record['trade_date']
    cutoff = previous_trading_day(date.fromisoformat(day))
    if previous_batch_finished.astimezone(NEW_YORK).date() > cutoff:
        raise ValueError('影子C2时刻越过t−1，拒绝未来日线')
    from .ab_evidence import capture_evidence
    source_batch=Path(root)/'data/runs'/day/'batches'/record['run_id']
    capture_evidence(root,source_batch,'A_common_sync_before',symbol=record['symbol'],extra={'visible_at':previous_batch_finished.isoformat()})
    copy_common_settlements(root, visible_at=previous_batch_finished)
    capture_evidence(root,source_batch,'A_common_sync_after',symbol=record['symbol'],extra={'visible_at':previous_batch_finished.isoformat()})
    cfg = shadow_config(root, record['consistency_input']['config'], day)
    log = TradingMemoryLog(cfg)
    # 共同 pending 不进入反思；由正式原文同步完成。
    class OwnMemory:
        def get_pending_entries(self):
            return [e for e in log.get_pending_entries() if e['date'] >= fork['t0']]
        def batch_update_with_outcomes(self, updates):
            if any(u.get('resolution_date', '9999') > cutoff.isoformat() for u in updates):
                raise ValueError('反思结算超过t−1')
            log.batch_update_with_outcomes(updates)
    class StrictReflector:
        error = None
        def reflect_on_final_decision(self, **kwargs):
            try:
                return reflector.reflect_on_final_decision(**kwargs)
            except Exception as exc:
                self.error = exc
                raise
    strict = StrictReflector()
    with run_config(cfg):
        settle_pending(record['symbol'], OwnMemory(), strict, {**cfg, 'asset_type': record.get('type', 'stock')})
    if strict.error:
        raise RuntimeError('影子反思失败，本日A缺失') from strict.error
    settle(target, now=previous_batch_finished, services=services, settings=settings, manual={})
    from .ab_evidence import capture_evidence
    source_batch=Path(root)/'data/runs'/day/'batches'/record['run_id']
    capture_evidence(root,source_batch,'A_common_sync_before',symbol=record['symbol'],extra={'visible_at':previous_batch_finished.isoformat()})
    copy_common_settlements(root, visible_at=previous_batch_finished)
    capture_evidence(root,source_batch,'A_common_sync_after',symbol=record['symbol'],extra={'visible_at':previous_batch_finished.isoformat()})
    return log.get_past_context(record['symbol'], as_of=cutoff.isoformat())


def _evidence_hash(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def _t0_projection(record, final_state, rating):
    """复用生产适配合同；整个result另与同次原件逐字段相等核验。"""
    from daily_analyzer.runner import final_state_result_fields
    adapted=adapt_result(record,final_state,rating)
    keys=tuple(final_state_result_fields(final_state,rating))+('investment_plan','trader_investment_plan')
    return {key:adapted.get(key) for key in keys}


def production_trade_date(record):
    """生产原件只读upstream日期；工作副本标准字段不得与它矛盾。"""
    from .consistency import PathIntegrityError
    day=record.get('upstream_trade_date')
    if not day or (record.get('trade_date') is not None and record['trade_date']!=day):
        raise PathIntegrityError('生产upstream_trade_date缺失或与实验trade_date冲突')
    return day


def experiment_record(record):
    """规范化只发生于实验工作副本，不回写正式或冻结B原件。"""
    return {**record,'trade_date':production_trade_date(record)}


def capture_t0_b_state(root, batch_dir, record, final_state, rating):
    """只捕获已启用T0定时B的现成完整state；工件失败不改变正式B结果。"""
    area=experiment_root(root);state_file=area/'experiment.json'
    if not state_file.exists():return {'status':'disabled'}
    try:
        state=json.loads(state_file.read_text())
        if not state.get('enabled') or record.get('upstream_trade_date')!=state.get('t0'):return {'status':'not_T0'}
        batch=json.loads((Path(batch_dir)/'batch.json').read_text())
        if not batch.get('scheduled') or batch.get('mode')!='live' or record['symbol'] not in batch.get('planned_items',[]):
            return {'status':'not_scheduled_plan'}
        body={'run_id':record['run_id'],'symbol':record['symbol'],'trade_date':production_trade_date(record),
              'full_state':deepcopy(final_state),'rating':str(rating),'result':deepcopy(record)}
        body['state_sha256']=_evidence_hash(body['full_state']);body['result_sha256']=_evidence_hash(body['result'])
        projected=_t0_projection(record,final_state,rating)
        if any(record.get(key)!=value for key,value in projected.items()):raise ValueError('完整B state与同次result投影不一致')
        atomic_write_json(area/'T0-state'/record['run_id']/f"{record['symbol']}.json",body)
        return {'status':'captured'}
    except Exception as exc:
        # 此失败属于实验，不把正式B成功改写为失败。
        try:atomic_write_json(area/'budget-stop.json',{'category':'integrity','reason':'T0完整B同源证据捕获失败','error':str(exc)})
        except OSError:
            import logging
            logging.getLogger(__name__).exception('T0实验停止证据写入失败；A前缺件核验仍拒绝执行')
        return {'status':'failed','error':str(exc)}


def verify_t0_b_states(root, batch, records):
    """T0首成功B冻结后、任何A反思前校验同源完整state与result原件。"""
    from .consistency import PathIntegrityError
    area=experiment_root(root);state_file=area/'experiment.json'
    state=json.loads(state_file.read_text()) if state_file.exists() else {}
    if not state.get('enabled') or batch['trade_date']!=state.get('t0'):return {'status':'not_T0'}
    checked=[]
    try:
        for symbol in batch['planned_items']:
            record=records.get(symbol,{})
            if record.get('status')!='success' or not record.get('consistency_input'):continue
            path=area/'T0-state'/batch['run_id']/f'{symbol}.json'
            proof=json.loads(path.read_text())
            if not isinstance(proof,dict) or not isinstance(proof.get('full_state'),dict):
                raise ValueError('T0完整B证据或state不是对象')
            source=proof['full_state']
            if not (proof['run_id']==record['run_id']==batch['run_id'] and
                    proof['symbol']==record['symbol']==record['analyzed_symbol']==symbol==source.get('company_of_interest') and
                    proof['trade_date']==production_trade_date(record)==batch['trade_date']==source.get('trade_date')):
                raise ValueError('T0完整B证据身份或日期不一致')
            if proof['state_sha256']!=_evidence_hash(source) or proof['result_sha256']!=_evidence_hash(proof['result']):
                raise ValueError('T0完整B同源证据哈希失配')
            if proof['result']!=record:raise ValueError('T0同次result与首次冻结B逐字段不同')
            expected=_t0_projection(record,source,proof['rating'])
            if any(record.get(key)!=value for key,value in expected.items()):raise ValueError('T0完整B state/result逐字段投影不同')
            checked.append({'symbol':symbol,'state_sha256':proof['state_sha256'],'result_sha256':proof['result_sha256'],'fields':list(expected)})
        atomic_write_json(area/'T0-state'/batch['run_id']/'verification.json',{'status':'passed','checked':checked})
        return {'status':'passed','checked':checked}
    except (OSError,ValueError,KeyError,TypeError) as exc:
        atomic_write_json(area/'budget-stop.json',{'category':'integrity','reason':'T0完整B同源对照失败，A前停止','error':str(exc)})
        raise PathIntegrityError('T0完整B同源对照失败：'+str(exc)) from exc

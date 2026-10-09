"""F2自然证据只读采集；独立默认关闭，不调用行情、模型或改变正式B结果。"""
from __future__ import annotations
from datetime import datetime,timezone
import hashlib
import json
import logging
from pathlib import Path
import time


def capture_evidence(root, batch_dir, event, *, symbol=None, extra=None):
    """记录真实调用边界；并行分析之间不保证单标原子TA反思快照。"""
    target=None
    try:
        root=Path(root).resolve();control=root/'config/t49-evidence.json'
        if not control.exists():return {'status':'disabled'}
        config=json.loads(control.read_text())
        if not config.get('enabled'):return {'status':'disabled'}
        batch_dir=Path(batch_dir);batch=json.loads((batch_dir/'batch.json').read_text())
        if batch.get('mode')!='live' or batch.get('trade_date','')<config['start_date']:
            return {'status':'outside_collection'}
        # 手动批次原样保全并显式标记，永不计入成功定时金标。
        output=Path(config['output_dir']).expanduser()
        if not output.is_absolute() or output.resolve().is_relative_to(root):raise ValueError('证据目录必须位于项目外的绝对路径')
        target=output/batch['trade_date']/batch['run_id']/f'{time.time_ns()}-{event}-{symbol or "all"}'
        target.mkdir(parents=True,exist_ok=False)
        paths=[root/'data/tradingagents/memory/trading_memory.md',root/'data/evaluation/outcomes.jsonl',
               root/'data/evaluation/ab-path/A/data/tradingagents/memory/trading_memory.md',root/'data/evaluation/ab-path/A/data/evaluation/outcomes.jsonl',batch_dir/'batch.json']
        if symbol:
            from daily_analyzer.site import symbol_slug
            paths.append(batch_dir/'results'/f'{symbol_slug(symbol)}.json')
            paths.append(root/'data/evaluation/ab-path/A/data/runs'/batch['trade_date']/'batches'/batch['run_id']/'results'/f'{symbol}.json')
        if event in ('batch_start','settlement_before','settlement_after','batch_end'):
            paths += [control,root/'config/settings.yaml',root/'config/watchlist.yaml',root/'logs'/f"{batch['trade_date']}.log"]
            paths += list((batch_dir/'results').glob('*.json'))
            paths += list((root/'data/tradingagents/cache').glob('*-alpaca-data.csv'))
            paths += list((root/'data/tradingagents/cache').glob('*-YFin-data.csv'))
        sources=[]
        for source in dict.fromkeys(paths):
            if not source.exists():sources.append({'path':str(source),'status':'missing'});continue
            before=source.stat();raw=source.read_bytes();after=source.stat();destination=target/'sources'/source.relative_to(root)
            destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(raw)
            sources.append({'path':str(source),'copy':str(destination),'sha256':hashlib.sha256(raw).hexdigest(),
                            'size':len(raw),'mtime_ns':after.st_mtime_ns,'unchanged_during_read':before.st_mtime_ns==after.st_mtime_ns and before.st_size==after.st_size})
        receipt={'event':event,'symbol':symbol,'captured_at_utc':datetime.now(timezone.utc).isoformat(),
                 'trade_date':batch['trade_date'],'run_id':batch['run_id'],'scheduled':batch.get('scheduled'),'mode':batch['mode'],
                 'batch_status':batch.get('status'),'batch_finished_at':batch.get('finished_at'),
                 'qualifying_golden_batch':batch.get('scheduled') is True and batch.get('status')=='completed',
                 'extra':extra or {},'sources':sources,'boundary':'实际runner边界只读副本；并行TA反思并非单标原子快照，缺件/读取中变化不得冒称完整通过'}
        (target/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
        return {'status':'captured','receipt':str(target/'receipt.json')}
    except Exception as exc:
        # 采集失败只缺证；不得改变正式B成败或自行触发额外调用。
        logging.getLogger(__name__).warning('T49自然证据采集失败（%s）：%s',event,exc)
        if target is not None:
            try:(target/'capture-error.json').write_text(json.dumps({'event':event,'error':str(exc)},ensure_ascii=False))
            except OSError:pass
        return {'status':'failed','error':str(exc)}

"""T49 实验调用次数账本，跨进程持锁预留每一次 provider 尝试。"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path

from daily_analyzer.storage import atomic_write_json
from tradingagents.llm_clients.errors import LLMNonRecoverableError

LIMITS = {'claude_exec':270,'codex_exec':700}
EXPECTED_DAILY = {'claude_exec':12,'codex_exec':31}


class BudgetStop(LLMNonRecoverableError):
    """实验预算或校准须报告，禁止继续派发。"""


class CallBudget:
    """不设开发会话预算；只有显式实验 provider 作用域引用本账本。"""
    def __init__(self, root, day):
        self.root = Path(root)
        self.day = day
        self.path = self.root/'model-attempts.jsonl'

    def rows(self):
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()] if self.path.exists() else []

    def __call__(self, provider, context):
        self.root.mkdir(parents=True,exist_ok=True)
        with (self.root/'budget.lock').open('a+') as lock:
            fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
            config=self.root/'experiment.json'
            if config.exists():
                state=json.loads(config.read_text())
                from daily_analyzer.time_utils import NEW_YORK
                if not state.get('enabled') or datetime.now(NEW_YORK).date().isoformat()>state['days'][19]:
                    raise BudgetStop('实验已停用或20日采样结束，禁止新模型调用及反思')
            if (self.root/'budget-stop.json').exists():
                raise BudgetStop('实验预算已暂停，请主负责人处理报告')
            counts=Counter(r['provider'] for r in self.rows())
            if provider not in LIMITS or counts[provider]>=LIMITS[provider]:
                atomic_write_json(self.root/'budget-stop.json',{'reason':'调用次数硬上限','provider':provider,'counts':dict(counts),'day':self.day})
                raise BudgetStop('实验调用次数已达硬上限')
            row={'day':self.day,'provider':provider,'attempt':counts[provider]+1,
                 'timestamp':datetime.now(timezone.utc).isoformat(),**context}
            with self.path.open('a') as stream:
                stream.write(json.dumps(row,ensure_ascii=False,sort_keys=True)+'\n');stream.flush()
                import os
                os.fsync(stream.fileno())

    def calibrate(self, completed_days):
        """日实测超过预计1.5倍或全期投影越限时持久暂停并报告。"""
        rows=self.rows();total=Counter(r['provider'] for r in rows)
        today=Counter(r['provider'] for r in rows if r['day']==self.day)
        observed=max(completed_days,len({r['day'] for r in rows}))
        projected={p:total[p]/observed*20 for p in LIMITS} if observed else {}
        stop=any(today[p]>EXPECTED_DAILY[p]*1.5 or projected.get(p,0)>LIMITS[p] for p in LIMITS)
        result={'day':self.day,'today':dict(today),'total':dict(total),'projected':projected,
                'expected_daily':EXPECTED_DAILY,'hard_limits':LIMITS,'stop':stop,
                'measurement':'provider进程尝试前保守预留，失败/重试仍保留；tokens/估计费用以llm_calls.jsonl原件为准'}
        atomic_write_json(self.root/'budget-report.json',result)
        if stop:
            atomic_write_json(self.root/'budget-stop.json',{'reason':'日实测或20日投影超限',**result})
        return result

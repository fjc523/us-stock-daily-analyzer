"""PM点位方案的日线事后检验；不可判路径不混入确定统计。"""
from collections import Counter, defaultdict
from datetime import date
import re
import statistics

import exchange_calendars as xcals
import pandas as pd

from .settlement import number

KINDS={'entry_plan':'建仓','add_plan':'加仓','reduce_plan':'减仓'}


def explicit_number(text, label):
    """只读显式数值标签，不从论点或参考价格猜止损/目标。"""
    match=re.search(r'(?m)^\s*\*\*'+re.escape(label)+r'\*\*\s*[:：]\s*\$?([0-9]+(?:\.[0-9]+)?)',str(text or ''))
    return number(match[1],positive=True) if match else None


def parse_plan(text):
    """区间或首句不适用之外均记解析失败。"""
    text=str(text or '').strip()
    if text.startswith('不适用'):
        # 日期、突破、区间或多个待选价位不能冒充唯一回踩等待价。
        tail=text.split('等待',1)[1] if '等待' in text else ''
        candidates=re.findall(r'(?<![\d.-])(?:\$\s*)?([0-9]+(?:\.[0-9]+)?)\s*美元',tail)
        ambiguous=bool(re.search(r'突破|区间|[0-9]+(?:\.[0-9]+)?\s*[–—~-]\s*[0-9]+(?:\.[0-9]+)?\s*美元', re.sub(r'(?<![0-9])[0-9]{4}-[0-9]{2}-[0-9]{2}(?![0-9])','日期',tail)))
        wait=number(candidates[0],positive=True) if len(candidates)==1 and not ambiguous else None
        return {'parse_status':'not_applicable','text':text,'wait_price':wait,'wait_price_reason':None if wait is not None else '无唯一明确美元回踩等待价位；日期/突破/区间不猜测'}
    match=re.match(r'区间\s*\$?([0-9]+(?:\.[0-9]+)?)\s*[–—~-]\s*\$?([0-9]+(?:\.[0-9]+)?)\s*美元',text)
    if match:
        low,high=map(float,match.groups())
        if 0<low<=high:
            return {'parse_status':'parsed','text':text,'low':low,'high':high}
    return {'parse_status':'unparsed','text':text,'reason':'首句无明确区间或不适用；不猜测'}


def extract_plans(result, layer='pm'):
    """新结构优先；旧Markdown仅解析显式行，不伪称model_dump。"""
    from daily_analyzer.site import _decision_section
    key='pm_decision' if layer=='pm' else 'trader_proposal'
    structured=(result.get('structured') or {}).get(key)
    text=result.get('final_trade_decision' if layer=='pm' else 'trader_investment_plan') or ''
    structured=structured if isinstance(structured,dict) else None
    plans={}
    for field,label in KINDS.items():
        value=structured.get(field) if structured is not None else _decision_section(text,label+'点位')
        plan=parse_plan(value)
        plan.update(kind=label,stop_loss=number(structured.get('stop_loss'),positive=True) if structured is not None else explicit_number(text,'Stop Loss'),
                    first_target=number(structured.get('first_target'),positive=True) if structured is not None else explicit_number(text,'First Target'),
                    provenance='structured_model_dump' if structured is not None else 'legacy_explicit_text')
        plans[field]=plan
    return plans


def evaluate_plan(plan, bars, *, start, end, basis, mature=True, units_verified=True):
    """日线执行约定与路径限制一并记录，不模拟仓位或成本。"""
    base={'kind':plan.get('kind'),'parse_status':plan.get('parse_status'),'status':'pending','triggered':None,'realized_r':None}
    if not mature:
        return base
    if plan.get('parse_status')=='unparsed':
        return {**base,'status':'unparsed','reason':plan.get('reason')}
    if not units_verified:
        return {**base,'status':'indeterminate','reason':'分析点位与OHLC复权/拆股单位未核验'}
    if basis=='same_day_close':
        return {**base,'status':'indeterminate','reason':'入场日为收盘近似，日线不能核验入场后的触发路径'}
    calendar=xcals.get_calendar('XNYS')
    dates=[stamp.date().isoformat() for stamp in calendar.sessions_in_range(start,end)]
    selected=[(day,bars.get(date.fromisoformat(day),bars.get(day))) for day in dates]
    if any(not row or any(number(row.get(field),positive=True) is None for field in ('open','high','low','close')) for _,row in selected):
        return {**base,'status':'unavailable','reason':'同源完整OHLC缺失'}
    if plan.get('parse_status')=='not_applicable':
        wait=plan.get('wait_price')
        reached=any(row['low']<=wait<=row['high'] for _,row in selected) if wait else None
        return {**base,'status':'not_applicable','wait_price':wait,'wait_reached':reached,'reason':None if wait else plan.get('wait_price_reason','无可解析的明确等待价位')}
    low,high=plan['low'],plan['high'];short=plan.get('kind')=='减仓';direction=-1 if short else 1
    for index,(day,bar) in enumerate(selected):
        if bar['low']<=high and bar['high']>=low:
            entry=max(bar['open'],low) if short else min(bar['open'],high)
            trigger=index;break
    else:
        return {**base,'status':'settled','triggered':False}
    base.update(triggered=True,trigger_date=day,entry_price=entry)
    stop,target=number(plan.get('stop_loss'),positive=True),number(plan.get('first_target'),positive=True)
    risk=direction*(entry-stop) if stop is not None else None
    if risk is None or risk<=0 or target is None or direction*(target-entry)<=0:
        return {**base,'status':'indeterminate','reason':'缺少方向正确的真实止损/第一目标或风险分母非正'}
    exit_price=selected[-1][1]['close'];exit_reason='有效期末';exit_day=selected[-1][0];dual=False;path_note='日线MFE/MAE为区间近似，极值先后及触发日入场前后不可分'
    considered=[]
    for offset,(current_day,row) in enumerate(selected[trigger:]):
        considered.append(row)
        hit_stop=row['high']>=stop if short else row['low']<=stop
        hit_target=row['low']<=target if short else row['high']>=target
        if hit_stop:
            dual=hit_target
            gap=row['open']>=stop if short else row['open']<=stop
            exit_price=row['open'] if gap else stop
            exit_reason='跳空止损' if gap else '同日双触（保守止损）' if dual else '止损'
            exit_day=current_day;break
        if hit_target:
            entry_at_open=low<=row['open']<=high or (row['open']>=low if short else row['open']<=high)
            if offset==0 and not entry_at_open:
                return {**base,'status':'indeterminate','reason':'触发日仅目标触及，日线无法判断目标在入场前还是后'}
            exit_price=target;exit_reason='第一目标';exit_day=current_day;break
    favorable=max((entry-row['low']) if short else (row['high']-entry) for row in considered)
    adverse=max((row['high']-entry) if short else (entry-row['low']) for row in considered)
    return {**base,'status':'settled','exit_price':exit_price,'exit_date':exit_day,'exit_reason':exit_reason,'same_day_dual':dual,
            'realized_r':direction*(exit_price-entry)/risk,'mfe_r':max(0,favorable)/risk,'mae_r':max(0,adverse)/risk,
            'mfe_pct':max(0,favorable)/entry,'mae_pct':max(0,adverse)/entry,'path_note':path_note}


def point_report(rows):
    """确定统计的分母与不可判/未成熟样本并列。"""
    lines=['## 点位方案','','无资金/仓位/费用/滑点模拟；同日双触保守止损，日线极值近似不能证明盘中路径。']
    groups=defaultdict(list);statuses=Counter()
    for row in rows:
        for plan in row.get('point_plans',{}).values():
            outcome=plan.get('outcome') or {'status':'pending'};statuses[outcome['status']]+=1
            for key in [('评级',row.get('ratings',{}).get('pm') or '未提供'),('标的',row['symbol']),('类型',plan['kind'])]:
                groups[key].append(outcome)
    lines += ['状态：'+('；'.join(f'{name} n={n}' for name,n in sorted(statuses.items())) or '无记录，未成熟/未配置'),'',
              '|分组|值|触发可判n|退出可判触发n|不可判n|触发率|止损率|目标率|平均R|中位R|同日双触|','|---|---|---|---|---|---|---|---|---|---|---|']
    lines.append('触发率仅以成熟且触发布尔值可判样本为分母；止损/目标/双触以退出路径可判的已触发样本为分母，R仅取有真实R值的样本。')
    for (kind,key),group in sorted(groups.items()):
        trigger_known=[out for out in group if isinstance(out.get('triggered'),bool) and out['status'] not in {'pending','unavailable','unparsed'}]
        known_trigger=[out for out in trigger_known if out['triggered']]
        exits=[out for out in known_trigger if out['status']=='settled']
        rs=[out['realized_r'] for out in exits if out.get('realized_r') is not None]
        ratio=lambda n,den:f'{n/den:.1%}' if den else '不可计算'
        dual=sum(bool(out.get('same_day_dual')) for out in exits)
        stop=sum('止损' in str(out.get('exit_reason','')) for out in exits);target=sum(out.get('exit_reason')=='第一目标' for out in exits)
        lines.append('|'+ '|'.join(map(str,[kind,key,len(trigger_known),len(exits),sum(out['status']=='indeterminate' for out in group),ratio(len(known_trigger),len(trigger_known)),ratio(stop,len(exits)),ratio(target,len(exits)),f'{statistics.mean(rs):.3f}' if rs else '不可计算',f'{statistics.median(rs):.3f}' if rs else '不可计算',ratio(dual,len(exits))]))+'|')
        if len(trigger_known)<30 or len(exits)<30:lines.append(f'{kind} {key}：样本不足，仅供参考。')
        if exits and dual/len(exits)>.2:lines.append(f'{kind} {key}双触超过20%，建议另议Alpaca分钟线细化；本任务不自动请求分钟线。')
    reasons=Counter(out.get('reason') for row in rows for plan in row.get('point_plans',{}).values() if (out:=plan.get('outcome',{})).get('reason'))
    lines += ['',* [f'- {reason}：n={n}' for reason,n in reasons.items()]]
    return '\n'.join(lines)

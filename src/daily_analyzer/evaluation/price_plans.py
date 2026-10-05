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
    for prefix in ('待触发：', '同建仓：', '同建仓', '超配回落：', '风险减配：'):
        if text.startswith(prefix):
            body = text[len(prefix):].strip()
            if prefix == '风险减配：':
                match = re.match(r'收盘跌破\s*([0-9]+(?:\.[0-9]+)?)\s*降至\s*([0-9]+(?:\.[0-9]+)?)%', body)
                if match and float(match[1]) > 0:
                    return {'parse_status': 'parsed', 'text': text, 'prefix': prefix,
                            'trigger_rule': '收盘跌破', 'trigger_price': float(match[1]),
                            'post_allocation_pct': float(match[2])}
                return {'parse_status': 'unparsed', 'text': text, 'reason': '风险减配缺明确触发价或减后配置'}
            zone = re.search(r'区间\s*([0-9]+(?:\.[0-9]+)?)\s*[–—~-]\s*([0-9]+(?:\.[0-9]+)?)\s*美元', body)
            trigger = re.match(r'收盘站上\s*([0-9]+(?:\.[0-9]+)?)\s*后', body) if prefix == '待触发：' else None
            if zone and 0 < float(zone[1]) <= float(zone[2]) and (prefix != '待触发：' or trigger):
                plan = {'parse_status': 'parsed', 'text': text, 'prefix': prefix, 'low': float(zone[1]), 'high': float(zone[2])}
                if trigger:
                    plan.update(status='待触发', trigger_rule='收盘站上', trigger_price=float(trigger[1]), confirm_days=1)
                return plan
            return {'parse_status': 'unparsed', 'text': text, 'reason': '新前缀无明确区间/确认价；不猜测'}
    if text.startswith('不适用'):
        # 固定双阈值模板分别保留回踩与突破，其他歧义仍不猜测。
        dual = re.search(r'等待回踩至\s*\$?([0-9]+(?:\.[0-9]+)?)\s*(?:美元)?\s*或突破\s*\$?([0-9]+(?:\.[0-9]+)?)\s*(?:美元)?\s*确认', text)
        if dual:
            wait, breakout = (number(value, positive=True) for value in dual.groups())
            if wait is not None and breakout is not None:
                return {'parse_status':'not_applicable','text':text,'wait_price':wait,'breakout_price':breakout,'wait_price_reason':None}
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
    if structured is not None and (structured.get('buy_legs') or structured.get('reduce_legs')):
        anchors = ((result.get('context_blocks') or {}).get('price_anchors') or {}).get('data') or {}
        atr_row = (anchors.get('anchors') or {}).get('atr')
        atr = number(atr_row.get('value') if isinstance(atr_row,dict) else atr_row, positive=True)
        for field, prefix in (('buy_legs', 'buy'), ('reduce_legs', 'reduce')):
            for index, leg in enumerate(structured.get(field) or []):
                if not isinstance(leg, dict):
                    continue
                leg_id = f'{prefix}_{index + 1}'
                upper = number(leg.get('zone_high'), positive=True)
                target = number(leg.get('first_target'), positive=True)
                distance = (target - upper) / atr if target is not None and upper is not None and atr else None
                far = target - upper > 3 * atr + 0.01 + 1e-9 if distance is not None else None
                plans[leg_id] = {**leg, 'leg_id': leg_id,
                    'kind': '买入' if field == 'buy_legs' else leg.get('kind'),
                    'buy_kind': leg.get('kind') if field == 'buy_legs' else None,
                    'parse_status': 'parsed', 'provenance': 'structured_legs', 'rule_version': 'c4-v2',
                    'target_distance_atr': distance,
                    'target_distance_bucket': ('>3ATR' if far else '≤3ATR') if distance is not None else '不可核验'}
        return plans
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
        breakout=plan.get('breakout_price')
        confirmed=any(row['close']>breakout for _,row in selected) if breakout else None
        return {**base,'status':'not_applicable','wait_price':wait,'wait_reached':reached,'breakout_price':breakout,'breakout_confirmed':confirmed,'reason':None if wait else plan.get('wait_price_reason','无可解析的明确等待价位')}
    low,high=plan['low'],plan['high'];short=plan.get('kind')=='减仓';direction=-1 if short else 1
    for index,(day,bar) in enumerate(selected):
        if bar['low']<=high and bar['high']>=low:
            entry=max(bar['open'],low) if short else min(bar['open'],high)
            trigger=index;break
    else:
        return {**base,'status':'settled','triggered':False}
    base.update(triggered=True,trigger_date=day,entry_price=entry)
    if short:
        # 减仓不是做空交易；只检验避免持有至期末的方向收益，不借多头止损/目标。
        terminal=selected[-1][1]['close']
        considered=[row for _,row in selected[trigger:]]
        return {**base,'status':'settled','exit_price':terminal,'exit_date':selected[-1][0],'exit_reason':'减仓有效期末',
                'direction_adjusted_return':(entry-terminal)/entry,
                'mfe_pct':max(0.,max(entry-row['low'] for row in considered))/entry,
                'mae_pct':max(0.,max(row['high']-entry for row in considered))/entry,
                'path_note':'日线极值为区间近似，触发日入场前后及极值先后不可分；减仓无专门回补止损，不计算R'}
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


def evaluate_leg(plan, bars, *, start, entry_end, end=None, basis, mature=True, units_verified=True):
    """v2先在入场有效期确认成交，再沿同源20日快照检验每腿退出。"""
    base={'kind':plan.get('kind'),'rule_version':'c4-v2','status':'pending'}
    if plan.get('preconditions'):
        base['price_only_approximation'] = True
    if end is None:
        return {**base,'reason':'缺20日退出日期，不能提前结算'}
    if not mature:
        return base
    if entry_end > end:
        return {**base,'status':'indeterminate','reason':'入场有效期超过20日退出窗口'}
    if not units_verified:
        return {**base,'status':'indeterminate','reason':'分析点位与OHLC复权/拆股单位未核验'}
    if basis=='same_day_close':
        return {**base,'status':'indeterminate','reason':'入场日为收盘近似，日线不能核验入场后的触发路径'}
    calendar=xcals.get_calendar('XNYS')
    dates=[stamp.date().isoformat() for stamp in calendar.sessions_in_range(start,end)]
    selected=[(day,bars.get(date.fromisoformat(day),bars.get(day))) for day in dates]
    if any(not row or any(number(row.get(field),positive=True) is None for field in ('open','high','low','close')) for _,row in selected):
        return {**base,'status':'unavailable','reason':'同源完整OHLC缺失'}
    entry_rows=[(day,row) for day,row in selected if day<=entry_end]
    low=number(plan.get('zone_low'),positive=True)
    high=number(plan.get('zone_high'),positive=True)
    trigger_price=number(plan.get('trigger_price'),positive=True)
    is_buy=plan.get('kind')=='买入'
    if is_buy and plan.get('status')=='仅观察':
        touched=(any(row['low']<=high and row['high']>=low for _,row in entry_rows)
                 if low is not None and high is not None and low<=high else
                 any(row['low']<=trigger_price<=row['high'] for _,row in entry_rows) if trigger_price else None)
        return {**base,'status':'observation','level_touched':touched}
    if plan.get('kind')=='风险减配':
        if plan.get('trigger_rule') is None:
            return {**base,'status':'indeterminate','reason':'触发规则缺失'}
        if plan.get('trigger_rule')!='收盘跌破':
            return {**base,'status':'indeterminate','reason':'非收盘跌破规则'}
        if trigger_price is None:
            return {**base,'status':'indeterminate','reason':'风险减配缺明确收盘跌破价'}
        confirm_days = plan.get('confirm_days') if plan.get('confirm_days') is not None else 1
        if confirm_days not in (1, 2):
            return {**base,'status':'indeterminate','reason':'风险减配确认天数不可判'}
        trigger = None
        streak = 0
        for index, (day, row) in enumerate(entry_rows):
            streak = streak + 1 if row['close'] < trigger_price else 0
            if streak >= confirm_days:
                trigger = index
                break
        if trigger is None:
            return {**base,'status':'settled','triggered':False}
        if trigger+1>=len(selected):
            return {**base,'status':'indeterminate','reason':'风险触发后无下一开盘'}
        trigger_day=selected[trigger][0]
        entry_day,bar=selected[trigger+1]
        entry=bar['open'];terminal=selected[-1][1]['close']
        considered=[row for _,row in selected[trigger+1:]]
        return {**base,'status':'settled','triggered':True,'trigger_date':trigger_day,
                'entry_date':entry_day,'entry_price':entry,'exit_date':end,'exit_price':terminal,
                'exit_reason':'风险减配20日期末','direction_adjusted_return':(entry-terminal)/entry,
                'mfe_pct':max(0.,max(entry-row['low'] for row in considered))/entry,
                'mae_pct':max(0.,max(row['high']-entry for row in considered))/entry,
                'path_note':'收盘条件确认后下一开盘减配；方向收益为避免持有至20日期末，日线极值为近似'}
    if not is_buy and plan.get('kind') == '超配回落':
        if plan.get('trigger_rule') is None:
            return {**base,'status':'indeterminate','reason':'触发规则缺失'}
        if plan.get('trigger_rule') != '进入区间受阻':
            return {**base,'status':'indeterminate','reason':'非区间受阻规则，C4 v2 不可判'}
    if low is None or high is None or low>high:
        return {**base,'status':'indeterminate','reason':'缺少有效明确区间'}
    confirmation=None
    expected_rule = {'可执行': '触及区间', '待触发': '收盘站上'}.get(plan.get('status')) if is_buy else None
    if expected_rule and plan.get('trigger_rule') is not None and plan['trigger_rule'] != expected_rule:
        return {**base,'status':'indeterminate','reason':'触发规则与状态不一致'}
    if is_buy and plan.get('status')=='待触发':
        confirm_days=plan.get('confirm_days')
        if trigger_price is None or confirm_days not in (1,2):
            return {**base,'status':'indeterminate','reason':'待触发腿缺明确收盘确认价或1–2日确认'}
        streak=0
        for index,(day,bar) in enumerate(entry_rows):
            streak=streak+1 if bar['close']>trigger_price else 0
            if streak>=confirm_days:
                confirmation=day
                candidates=entry_rows[index+1:]
                break
        else:
            return {**base,'status':'settled','triggered':False,'reason':'有效期内未完成收盘确认'}
    elif is_buy and plan.get('status')!='可执行':
        return {**base,'status':'indeterminate','reason':'买入腿状态不可判，不猜测执行权限'}
    elif not is_buy and plan.get('kind')!='超配回落':
        return {**base,'status':'indeterminate','reason':'减仓类别不可判'}
    else:
        candidates=entry_rows
    for day,bar in candidates:
        if confirmation is not None and bar['open']<low:
            return {**base,'status':'settled','triggered':False,'confirmation_date':confirmation,
                    'reason':'确认后跌回区间下方，未成交'}
        if bar['low']<=high and bar['high']>=low:
            entry_day=day
            break
    else:
        return {**base,'status':'settled','triggered':False,
                **({'confirmation_date':confirmation} if confirmation else {}),
                'reason':'有效期内没有确认后的区间成交' if confirmation else '有效期内区间未触及'}
    # 复用v1的保守日线路径、止损/目标及减仓百分比，入场日此前的K线不传入。
    legacy={**plan,'kind':'建仓' if is_buy else '减仓','low':low,'high':high,'parse_status':'parsed'}
    outcome=evaluate_plan(legacy,bars,start=entry_day,end=end,basis=basis,units_verified=units_verified)
    outcome.update(kind=plan.get('kind'),rule_version='c4-v2',entry_date=entry_day)
    if base.get('price_only_approximation'):
        outcome['price_only_approximation'] = True
    if outcome.get('exit_reason') == '减仓有效期末':
        outcome['exit_reason'] = '减仓20日期末'
    if confirmation:
        outcome['confirmation_date']=confirmation
    return outcome


def _point_report_v1(rows):
    """确定统计的分母与不可判/未成熟样本并列。"""
    lines=['## 点位方案','','无资金/仓位/费用/滑点模拟；同日双触保守止损，日线极值近似不能证明盘中路径。']
    groups=defaultdict(list);reductions=defaultdict(list);waiting=[];statuses=Counter()
    for row in rows:
        for plan in row.get('point_plans',{}).values():
            outcome=plan.get('outcome') or {'status':'pending'};statuses[outcome['status']]+=1
            for key in [('评级',row.get('ratings',{}).get('pm') or '未提供'),('标的',row['symbol']),('类型',plan['kind'])]:
                (reductions if plan['kind']=='减仓' else groups)[key].append(outcome)
            if outcome.get('wait_price') is not None or outcome.get('breakout_price') is not None:
                waiting.append((row['symbol'],plan['kind'],outcome))
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
    lines += ['', '### 减仓独立检验', '', '减仓不进入上述平均R/中位R；方向收益=(成交价−期末收盘价)/成交价；MFE/MAE为百分比，不借多头止损/目标。',
              '|分组|值|触发可判n|已触发成熟n|触发率|平均方向收益|平均MFE|平均MAE|', '|---|---|---|---|---|---|---|---|']
    for (kind,key),group in sorted(reductions.items()):
        known=[out for out in group if isinstance(out.get('triggered'),bool) and out['status']=='settled']
        triggered=[out for out in known if out['triggered'] and out.get('direction_adjusted_return') is not None]
        mean=lambda field:f'{statistics.mean(out[field] for out in triggered):.2%}' if triggered else '不可计算'
        rate=f'{len(triggered)/len(known):.1%}' if known else '不可计算'
        lines.append('|'+ '|'.join(map(str,[kind,key,len(known),len(triggered),rate,mean('direction_adjusted_return'),mean('mfe_pct'),mean('mae_pct')]))+'|')
        if len(triggered)<30:lines.append(f'{kind} {key}：样本不足，仅供参考。')
    if waiting:
        lines += ['', '### 等待条件分别检验', '', '|标的|类型|回踩价|回踩到达|突破价|收盘站上|', '|---|---|---|---|---|---|']
        for symbol,kind,out in waiting:
            fmt=lambda value:'不可得' if value is None else str(value)
            lines.append('|'+ '|'.join(map(str,[symbol,kind,fmt(out.get('wait_price')),fmt(out.get('wait_reached')),fmt(out.get('breakout_price')),fmt(out.get('breakout_confirmed'))]))+'|')
    reasons=Counter(out.get('reason') for row in rows for plan in row.get('point_plans',{}).values() if (out:=plan.get('outcome',{})).get('reason'))
    lines += ['',* [f'- {reason}：n={n}' for reason,n in reasons.items()]]
    return '\n'.join(lines)


def point_report(rows):
    """v1保持旧汇总，v2按腿语义分表，不混合分母。"""
    versions={'c4-v1':[],'c4-v2':[]}
    for row in rows:
        for version in versions:
            plans={key:plan for key,plan in row.get('point_plans',{}).items()
                   if plan.get('rule_version','c4-v1')==version}
            if plans:
                versions[version].append({**row,'point_plans':plans})
    if not versions['c4-v2']:
        return _point_report_v1(rows)
    lines=[_point_report_v1(versions['c4-v1']).replace('## 点位方案','## 点位方案（c4-v1）',1),
           '', '## 点位方案（c4-v2）', '',
           '逐腿独立止损和目标；入场用冻结有效期，退出到该记录20日exit_date。仅观察不交易；无资金/仓位/费用/滑点模拟。',
           '', '|类别|状态|目标方法|目标距离|腿数|触发可判n|已触发退出可判n|触发率|止损率|目标率|平均R|平均方向收益|平均MFE|平均MAE|观察触及n|',
           '|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    groups=defaultdict(list)
    approximations=[]
    for row in versions['c4-v2']:
        for leg_id, plan in row['point_plans'].items():
            outcome = plan.get('outcome') or {'status':'pending'}
            if plan.get('preconditions') or outcome.get('price_only_approximation'):
                approximations.append((row, leg_id, plan, outcome))
                continue
            key=(plan.get('kind') or '未提供',plan.get('status') or '未提供',
                 plan.get('target_method') or '不适用',plan.get('target_distance_bucket') or '不可核验')
            groups[key].append(plan.get('outcome') or {'status':'pending'})
    for key,outcomes in sorted(groups.items()):
        known=[out for out in outcomes if isinstance(out.get('triggered'),bool) and out.get('status') not in ('pending','unavailable')]
        triggered=[out for out in known if out['triggered']]
        exited=[out for out in triggered if out['status']=='settled']
        rs=[out['realized_r'] for out in exited if out.get('realized_r') is not None]
        returns=[out['direction_adjusted_return'] for out in exited if out.get('direction_adjusted_return') is not None]
        rate=f'{len(triggered)/len(known):.1%}' if known else '不可计算'
        ratio=lambda count:f'{count/len(exited):.1%}' if exited else '不可计算'
        mean_pct=lambda field:f'{statistics.mean(out[field] for out in exited if out.get(field) is not None):.2%}' if any(out.get(field) is not None for out in exited) else '不可计算'
        lines.append('|'+ '|'.join(map(str,[*key,len(outcomes),len(known),len(exited),rate,
            ratio(sum('止损' in str(out.get('exit_reason')) for out in exited)),
            ratio(sum(out.get('exit_reason')=='第一目标' for out in exited)),
            f'{statistics.mean(rs):.3f}' if rs else '不可计算',
            f'{statistics.mean(returns):.2%}' if returns else '不可计算',
            mean_pct('mfe_pct'),mean_pct('mae_pct'),
            sum(out.get('level_touched') is True for out in outcomes)]))+'|')
        if len(exited)<30:
            lines.append(' / '.join(key)+'：样本不足，仅供参考。')
    statuses=Counter(out.get('status') for group in groups.values() for out in group)
    lines+=['', 'v2状态：'+'；'.join(f'{name} n={count}' for name,count in sorted(statuses.items()))]
    reasons=Counter(out.get('reason') for group in groups.values() for out in group if out.get('reason'))
    lines+=['', *[f'- {reason}：n={count}' for reason,count in reasons.items()]]
    if approximations:
        lines += ['', '### 含非价格前置条件（价格近似）', '',
                  '以下仅按价格评价，未核验非价格前置条件；全部排除于上方确定统计的触发/退出分母、比率、R、收益、MFE和MAE。', '',
                  '|标的|腿|类别|价格评价状态|价格触发|前置条件|', '|---|---|---|---|---|---|']
        for row, leg_id, plan, outcome in approximations:
            cells = [row.get('symbol'), leg_id, plan.get('kind'), outcome.get('status'),
                     '是' if outcome.get('triggered') is True else '否' if outcome.get('triggered') is False else '不可判',
                     plan.get('preconditions') or '未提供（已有近似标签）']
            lines.append('|' + '|'.join(str(cell or '').replace('|', '／').replace('\n', ' ') for cell in cells) + '|')
    return '\n'.join(lines)

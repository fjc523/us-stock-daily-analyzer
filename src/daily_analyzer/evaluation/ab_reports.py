"""T49 逐订阅段独立模拟账户、合成配对差值指数与成熟评分。"""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import statistics
import exchange_calendars as xcals
import pandas as pd
from daily_analyzer.storage import atomic_write_json
from .ab_path import experiment_root
from .ab_ledger import Ledger, INITIAL, COST_BP, VERSION, COST_POLICY_VERSION
from .ab_lifecycle import paired_difference_index
from .settlement import last_complete_session, bar_prices, entry_plan, load_outcomes, number


def frozen_results(root):
    """B只读首次冻结批次，A只读成功独立结果。"""
    area=experiment_root(root)
    from .ab_path import experiment_record
    return {'B':[experiment_record(json.loads(p.read_text())) for p in sorted((area/'B').glob('*/*.json'))],
            'A':[json.loads(p.read_text()) for p in sorted((area/'A/data/runs').glob('*/batches/*/results/*.json'))]}


def admitted_records(records, pairs, sampling_end):
    """只统计纳入决策配对日；退订日没有新A决策。"""
    return {path:[r for r in rows if r['trade_date']<=sampling_end and any(
        p['symbol']==r['symbol'] and p['opened_at']<=r['trade_date'] and
        (not p.get('unsubscribed_at') or r['trade_date']<p['unsubscribed_at']) for p in pairs)]
        for path,rows in records.items()}


def _decisions(records):
    cal=xcals.get_calendar('XNYS');days=defaultdict(dict)
    for record in records:
        plan=entry_plan(datetime.fromisoformat(record['finished_at']));effective=date.fromisoformat(plan['date'])
        if plan['basis']=='same_day_close':effective=cal.next_session(pd.Timestamp(effective)).date()
        pm=(record.get('structured') or {}).get('pm_decision') or {}
        days[effective.isoformat()][record['symbol']]={**pm,'id':record['run_id'],'rating':record.get('final_rating')}
    return days


def _metrics(result):
    values=[INITIAL]+[r['nav'] for r in result['daily']];peak=INITIAL;drawdown=0
    for value in values:peak=max(peak,value);drawdown=min(drawdown,value/peak-1)
    returns=[b/a-1 for a,b in zip(values,values[1:])]
    deviations={(e['day'],e['symbol']) for e in result['events'] if e['reason']=='目标偏离至少10个百分点'}
    executed={(t['day'],t['symbol']) for t in result['trades'] if t['reason'] not in ('初始仓','退订平仓','批次止损','跳空止损')}
    return {'cumulative_return':values[-1]/INITIAL-1,'max_drawdown':drawdown,
            'daily_volatility':statistics.stdev(returns) if len(returns)>1 else None,
            'turnover':sum(t['shares']*t['price'] for t in result['trades'])/(statistics.mean(values[1:]) if len(values)>1 else INITIAL),
            'total_cost':result['cost_total'],'trade_count':len(result['trades']),
            'nonexecution_reasons':result['event_counts'],
            'execution':{'deviation_days':len(deviations),'executed_days':len(deviations & executed),
                'execution_rate':len(deviations & executed)/len(deviations) if deviations else None}}


def simulate_pair(pair, days, bars, decisions, *, costs, multiple=1, direct=False, passive=False):
    """逐本账户复用同一成交规则；退出日完成后不再生成日收益行。"""
    symbol=pair['symbol'];start=pair['opened_at'];cal=xcals.get_calendar('XNYS')
    selected=[d for d in days if d>=start]
    if not selected:return None
    first=bars.get(symbol,{}).get(start,{})
    if not all(number(first.get(k),positive=True) for k in ('open','high','low','close')):return None
    output={**pair};closed=[]
    for path in ('A','B'):
        locked_cost=pair['cost_bp'] if 'cost_bp' in pair else costs[symbol]
        ledger=Ledger((symbol,),costs={symbol:locked_cost},cost_multiple=multiple,direct=direct)
        ledger.initialize(start,{symbol:first})
        for day in selected:
            bar=bars.get(symbol,{}).get(day,{})
            if pair.get('unsubscribed_at') and day>=pair['unsubscribed_at']:
                ledger.exit_step(day,{symbol:bar})
                if ledger.shares(symbol)==0:closed.append(day);break
            else:
                prev=cal.previous_session(pd.Timestamp(day)).date().isoformat()
                reference=bars.get(symbol,{}).get(prev,{}).get('close')
                ledger.step(day,{symbol:bar},{symbol:reference},{symbol:decisions[path].get(day,{}).get(symbol,{})} if not passive and symbol in decisions[path].get(day,{}) else {},splits=(symbol,) if bar.get('split_event') else ())
        output[path]=ledger.result()
    # 共同配对窗口：零仓路径按现金估值，直到另一条实际退出。
    paired_days=sorted({r['day'] for path in ('A','B') for r in output[path]['daily']})
    for path in ('A','B'):
        present={r['day'] for r in output[path]['daily']}
        last=output[path]['daily'][-1]
        for day in paired_days:
            if day not in present:output[path]['daily'].append({**last,'day':day})
        output[path]['daily'].sort(key=lambda row:row['day'])
    output['closed_at']=max(closed) if len(closed)==2 else None
    output['days']=len(output['A']['daily'])
    output['status']=('已退订' if output['closed_at'] else '待平仓') if pair.get('unsubscribed_at') else '满期' if output['days']==20 else '未满期' if len(days)==20 else '进行中'
    output['metrics']={p:_metrics(output[p]) for p in ('A','B')}
    output['A_minus_B']=output['metrics']['A']['cumulative_return']-output['metrics']['B']['cumulative_return']
    return output


def event_diagnostics(main):
    """用已记录事件生成原规格受限与精度提示，不改变成交。"""
    restricted={};precision=[];limited=[];ratios={};unexecutable_days={}
    for pair in main:
        for path in ('A','B'):
            account=pair[path];counts=account['event_counts'];key=f"{pair['id']}/{path}"
            clauses=Counter(clause for event in account['events'] if event['reason']=='前提受限' for clause in event.get('clauses',[]))
            restricted[key]=clauses.most_common()
            buys=sum(t['side']=='buy' for t in account['trades'])
            ratios[key]={'same_day_double_touch_count':counts.get('同日双触',0),'executed_buy_batches_including_initial':buys,'ratio':counts.get('同日双触',0)/buys if buys else None}
            if counts.get('同日双触',0)>.2*buys:precision.append(key)
            deviations={e['day'] for e in account['events'] if e['reason']=='目标偏离至少10个百分点'}
            restricted_days={e['day'] for e in account['events'] if e['reason'] in ('不可执行','规则缺失','前提受限')} & deviations
            unexecutable_days[key]={'deviation_days':len(deviations),'restricted_days':len(restricted_days),'ratio':len(restricted_days)/len(deviations) if deviations else None}
        if all(unexecutable_days[f"{pair['id']}/{path}"]['deviation_days'] and unexecutable_days[f"{pair['id']}/{path}"]['restricted_days']>.8*unexecutable_days[f"{pair['id']}/{path}"]['deviation_days'] for path in ('A','B')):limited.append(pair['id'])
    return {'precondition_unmatched_clauses':restricted,'daily_precision_ratios':ratios,'restricted_deviation_day_ratios':unexecutable_days,
            'daily_precision_limited_accounts':precision,'passive_and_stop_dominated_pairs':limited}


def build_ledgers(root, *, now, services, costs=None):
    """从当时落盘的名额表重放，零模型；不构造跨账户现金池或组合NAV。"""
    area=experiment_root(root);state=json.loads((area/'experiment.json').read_text())
    cutoff=min(last_complete_session(now),date.fromisoformat(state['days'][19]));days=[d for d in state['days'][:20] if d<=cutoff.isoformat()]
    if not days:return {'status':'waiting_first_close'}
    files=sorted(p for p in (area/'allocations').glob('*.json') if p.stem<=days[-1])
    if not files:return {'status':'NOT_TESTED_missing_planned_allocations'}
    allocations=[json.loads(p.read_text()) for p in files];pairs=allocations[-1]['pairs']
    costs=dict(COST_BP if costs is None else costs)
    unassigned=[p['id'] for p in pairs if p.get('cost_bp') is None and p['symbol'] not in costs]
    pairs=[p for p in pairs if p['id'] not in unassigned]
    bars={};sources={};hashes={}
    for symbol in {p['symbol'] for p in pairs}|{'SPY'}:
        raw,source=services.prices.bars(symbol,cutoff)
        bars[symbol]={d.isoformat():b for d,b in bar_prices(raw,cutoff,include_extremes=True).items()}
        for row in raw:
            event_day=str(row.get('date',row.get('Date',row.get('t',''))))[:10]
            if row.get('Stock Splits',row.get('split_ratio',row.get('split',0))) not in (None,0,1,1.0) and event_day in bars[symbol]:bars[symbol][event_day]['split_event']=True
        sources[symbol]=source;hashes[symbol]=hashlib.sha256(json.dumps(raw,sort_keys=True,default=str).encode()).hexdigest()
    records=admitted_records(frozen_results(root),pairs,state['days'][19]);decisions={p:_decisions(records[p]) for p in ('A','B')}
    scenarios={}
    for name,multiple,direct,passive in [('main',1,False,False),('cost0',0,False,False),('cost2',2,False,False),('L1',1,True,False),('passive',1,False,True)]:
        scenarios[name]=[result for pair in pairs if (result:=simulate_pair(pair,days,bars,decisions,costs=costs,multiple=multiple,direct=direct,passive=passive)) is not None]
    main=scenarios['main'];curve=paired_difference_index(main,days)
    strata={status:paired_difference_index([p for p in main if p['status']==status],days) for status in ('满期','未满期','已退订','待平仓','进行中')}
    leave_one={p['id']:paired_difference_index([q for q in main if q['id']!=p['id']],days) for p in main}
    alternatives={name:paired_difference_index(scenarios[name],days) for name in ('cost0','cost2','L1')}
    availability={path:{(r['trade_date'],r['symbol']) for r in records[path]} for path in records}
    grid=[]
    byday={a['day']:a for a in allocations}
    for day in days:
        last=next((a for a in reversed(allocations) if a['day']<=day),None)
        for pair in (last or {}).get('pairs',[]):
            if pair['opened_at']<=day and (not pair.get('unsubscribed_at') or day<pair['unsubscribed_at']):
                grid.append({'day':day,'pair_id':pair['id'],'A_available':(day,pair['symbol']) in availability['A'],'B_available':(day,pair['symbol']) in availability['B']})
    missing=sum(not cell['A_available'] for cell in grid)
    stop=json.loads((area/'budget-stop.json').read_text()) if (area/'budget-stop.json').exists() else {}
    fallback=sum((r.get('llm') or {}).get('scheme')=='B+fallback' for r in records['B'])
    delta=curve[-1]['cumulative_difference'];threshold=max([.005]+[p[path]['cost_total']/INITIAL for p in main for path in ('A','B')])
    if missing>8 or fallback>8 or stop.get('category')=='integrity' or not main:code='E0'
    elif abs(delta)<threshold:code='E1'
    else:
        sign=1 if delta>0 else -1
        tests=[c[-1]['cumulative_difference'] for c in [alternatives['L1'],alternatives['cost2'],*leave_one.values()] if any(r['pair_count'] for r in c)]
        weeks=defaultdict(float)
        for row in curve:
            if row['daily_difference'] is not None:weeks[date.fromisoformat(row['day']).isocalendar()[:2]]+=row['daily_difference']
        code='E2' if all(v*sign>0 for v in tests) and len(weeks)>=3 and sum(v*sign>0 for v in weeks.values())>=2 else 'E3'
    for pair in main:
        pair['weekly_metrics']={}
        for path in ('A','B'):
            week_rows=defaultdict(list)
            for row in pair[path]['daily']:week_rows[date.fromisoformat(row['day']).isocalendar()[:2]].append(row)
            previous_nav=INITIAL;pair['weekly_metrics'][path]={}
            for week,rows in week_rows.items():
                key=f'{week[0]}-W{week[1]:02}';dates={r['day'] for r in rows}
                pair['weekly_metrics'][path][key]={'return':rows[-1]['nav']/previous_nav-1,'cost':sum(t['cost'] for t in pair[path]['trades'] if t['day'] in dates),'trade_count':sum(t['day'] in dates for t in pair[path]['trades'])}
                previous_nav=rows[-1]['nav']
        start=pair['opened_at'];spy=bars['SPY'].get(start,{}).get('open')
        quantity=INITIAL/(spy*(1+costs['SPY']/10000)) if spy else None
        pair['SPY_buy_hold']=[{'day':r['day'],'nav':quantity*bars['SPY'][r['day']]['close']} for r in pair['A']['daily'] if quantity and r['day'] in bars['SPY']]
    versions=[{'day':a['day'],'planned_items':a['planned_items'],'audit':a['audit']} for a in allocations]
    from .ab_orchestrator import batches
    batches_by_day={}
    for batch in batches(root):batches_by_day.setdefault(batch['trade_date'],batch)
    for item in versions:item.update(implementation_version=batches_by_day.get(item['day'],{}).get('implementation_version'),role_configuration=batches_by_day.get(item['day'],{}).get('effective_config'))
    segments=[]
    difference_by_day={r['day']:r['daily_difference'] for r in curve}
    for item in versions:
        digest=hashlib.sha256(json.dumps({'source':item['implementation_version'],'config':item['role_configuration']},sort_keys=True,default=str).encode()).hexdigest()
        if not segments or segments[-1]['fingerprint']!=digest:segments.append({'start':item['day'],'end':item['day'],'fingerprint':digest,'days':[]})
        segments[-1]['end']=item['day'];segments[-1]['days'].append({'day':item['day'],'daily_paired_difference':difference_by_day[item['day']]})
    reruns=[]
    for p in (Path(root)/'data/runs').glob('*/batches/*/batch.json'):
        batch=json.loads(p.read_text())
        if batch.get('trade_date') in days and not batch.get('scheduled'):reruns.append({'day':batch['trade_date'],'run_id':batch['run_id'],'asymmetry':'B可能包含手动记忆，A不跟随'})
    report={'version':VERSION,'cost_policy_version':COST_POLICY_VERSION,'cost_assumption':'成本为模拟假设，来源：投研 v5.3 成本补充','class_default_pair_count':sum(p.get('cost_source')=='class_default' for p in pairs),'unassigned_pairs':unassigned,'valuation_through':days[-1],'sampling_complete':len(days)==20,
        'parameters':{'E0':INITIAL,'S':5000,'initial_exposure_pct':50,'max_A_slots':4},
        'index_name':'合成配对差值指数','index_boundary':'连乘等权账户日收益差；不是实际组合NAV，也不是A/B NAV比。退出日隔夜收益及成本计入，完成平仓后关闭。',
        'pairs':main,'paired_difference_curve':curve,'strata':strata,'leave_one_pair_out':leave_one,
        'sign_counts':{'A_better':sum(p['A_minus_B']>0 for p in main),'total':len(main)},
        'scenarios':scenarios,'alternative_difference_curves':alternatives,'availability_grid':grid,
        'missing_pair_days':missing,'B_fallback_pair_days':fallback,'stop_reason':stop,
        'conclusion_code':code if code=='E0' or len(days)==20 else '主期未结束，不作E1–E3最终结论','provisional_code':code,
        'versions_by_day':versions,'version_segments':segments,'manual_reruns':reruns,'sources':sources,'raw_price_sha256':hashes,
        'limitations':['共享模型记忆，配对不是独立模型样本；仅描述，不作因果或显著性结论','v5.2共享现金敞口80%不可与本版50%直接比较','F40退订日遗漏由用户最新明确口径覆盖：包含退出日全部损益','投研前提预标注金标及完整未来五日历史对照NOT_TESTED','现金零收益，未模拟分红及流动性；拆股只依据同源明确事件字段冻结，源无字段时识别NOT_TESTED']}
    report.update(event_diagnostics(main))
    if report['daily_precision_limited_accounts']:report['limitations'].append('日线精度不足：同日双触超过已成交买入批次（含初仓）20%；不自动取分钟线')
    if report['passive_and_stop_dominated_pairs']:report['limitations'].append('所列配对两路径不可执行及前提受限超过偏离天数80%，曲线主要反映被动持有与止损，腿差异受限')
    report['version_boundary']='按实际生产批次源码/配置分段；check_version拒绝A单边源码变更。未发生自然版本切换，真实单边阶段比较NOT_TESTED。'
    output=area/'ledger'
    previous_report=output/'curves.json'
    if previous_report.exists():
        old=json.loads(previous_report.read_text())
        if old.get('cost_policy_version')!=COST_POLICY_VERSION:
            archive=output/'policy-archive'/(old.get('cost_policy_version') or 'unversioned')
            archive.mkdir(parents=True,exist_ok=True)
            (archive/'curves.json').write_bytes(previous_report.read_bytes())
            if (output/'report.md').exists():
                (archive/'report.md').write_bytes((output/'report.md').read_bytes())
            atomic_write_json(archive/'superseded.json',{'old_cost_policy_version':old.get('cost_policy_version'),'superseded_by_cost_policy_version':COST_POLICY_VERSION,'说明':'旧曲线与报告原字节保全，替代说明单列'})
    atomic_write_json(output/'curves.json',report)
    (output/'report.md').write_text('# T49 逐账户实际NAV与合成配对差值指数\n\n'+COST_POLICY_VERSION+'：'+report['cost_assumption']+'\n\n'+report['index_boundary']+'\n\n'+report['conclusion_code']+'\n\n逐订阅段NAV、指标、同期SPY、被动持有、L1、成本敏感性、分层及逐配对剔除数列见 curves.json。\n',encoding='utf-8')
    return {'status':'completed','path':str(output/'curves.json'),'valuation_through':days[-1]}


def maturity_report(root, *, label, as_of):
    """TS/Brier/评级方向/C4并列，仅纳入已到期实际结算窗口。"""
    from .calibration import extract_probabilities, calibration
    area=experiment_root(root);records=frozen_results(root)
    allocations=sorted((area/'allocations').glob('*.json'))
    state=json.loads((area/'experiment.json').read_text())
    records=admitted_records(records,json.loads(allocations[-1].read_text())['pairs'] if allocations else [],state['days'][19])
    outcome={'A':load_outcomes(area/'A/data/evaluation/outcomes.jsonl'),'B':load_outcomes(__import__('pathlib').Path(root)/'data/evaluation/outcomes.jsonl')}
    indexed={p:{(r['run_id'],r['symbol']):r for r in outcome[p]} for p in ('A','B')}
    rows=[]
    for b in records['B']:
        a=next((r for r in records['A'] if (r['run_id'],r['symbol'])==(b['run_id'],b['symbol'])),None)
        for window in ('5','10','20'):
            pair={p:(indexed[p].get((b['run_id'],b['symbol']),{}).get('windows',{}).get(window) or {}) for p in ('A','B')}
            valid=all(w.get('status')=='settled' and w.get('settled_at') and datetime.fromisoformat(w['settled_at'])<=as_of for w in pair.values())
            weight={p:number(((r or {}).get('structured') or {}).get('pm_decision',{}).get('target_allocation_pct')) for p,r in [('A',a),('B',b)]}
            excess=0 if b['symbol']=='SPY' else pair['B'].get('excess_vs_spy')
            ts=(weight['A']-weight['B'])/100*excess if valid and excess is not None and all(v is not None for v in weight.values()) else None
            rows.append({'run_id':b['run_id'],'symbol':b['symbol'],'trade_date':b['trade_date'],'window':window,'status':'settled' if valid else 'pending_or_missing','TS':ts,'windows':pair if valid else {},'A_missing':a is None})
    scoring={}
    for path in ('A','B'):
        scoring[path]={}
        for window in ('5','20'):
            pairs=[];hits=[]
            for record in records[path]:
                row=indexed[path].get((record['run_id'],record['symbol']),{});w=row.get('windows',{}).get(window,{})
                if w.get('status')!='settled' or not w.get('settled_at') or datetime.fromisoformat(w['settled_at'])>as_of:continue
                value=w.get('primary_return');prob=extract_probabilities(record)['pm'][window]
                if value is not None:
                    pairs.append((prob,value>0))
                    sign=1 if record.get('final_rating') in ('Buy','Overweight') else -1 if record.get('final_rating') in ('Underweight','Sell') else 0
                    if sign:hits.append(value*sign>0)
            scoring[path][window]={'calibration':calibration(pairs),'direction_hit_rate':sum(hits)/len(hits) if hits else None,'n_direction':len(hits)}
    curve_path=area/'ledger/curves.json'
    main_difference=json.loads(curve_path.read_text())['paired_difference_curve'][-1]['cumulative_difference'] if curve_path.exists() else None
    alignment={}
    for window in ('5','10','20'):
        sample=[row['TS'] for row in rows if row['window']==window and row['TS'] is not None]
        total=sum(sample) if sample else None
        alignment[window]={'n':len(sample),'sum_TS':total,'description':'未成熟或无样本' if total is None or main_difference is None else '方向一致' if total*main_difference>0 else '方向不一致或零差值'}
    return {'TS_direction_annotation':alignment,'label':label,'as_of':as_of.isoformat(),'model_calls':0,'TS_is_return_curve':False,'rows':rows,'scores':scoring,
            'C4':{p:[{'run_id':r['run_id'],'symbol':r['symbol'],'point_plans':r.get('point_plans',{})} for r in outcome[p] if any(x['run_id']==r['run_id'] and x['symbol']==r['symbol'] for x in records[p])] for p in ('A','B')},
            'conclusion_boundary':'成熟TS仅注记与主曲线方向一致/不一致，不改变E1–E3；未成熟窗口不作结论'}

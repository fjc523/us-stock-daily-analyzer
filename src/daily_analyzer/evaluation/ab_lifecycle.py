"""T49 有序生产计划驱动的配对名额与订阅段，不读取订阅文件。"""
from copy import deepcopy


class MissingPlannedItems(ValueError):
    """旧批次无不可变原计划，不能推断退订。"""


def allocate_day(previous, *, day, planned_items, successful, eligible, cost_policies=None):
    """确定性分配最多四个名额；eligible由当时可见日线及身份验证生成。"""
    if not isinstance(planned_items, list) or any(not isinstance(s,str) for s in planned_items):
        raise MissingPlannedItems('NOT_TESTED：批次缺不可变完整planned_items，拒绝生命周期重建')
    if len(set(planned_items)) != len(planned_items):raise ValueError('原计划包含重复标的')
    state=deepcopy(previous or {'pairs':[], 'queue':[], 'seen':[]})
    if state.get('day') == day:return state
    if state.get('day','') > day:raise ValueError('不能逆序改变订阅生命周期')
    audit={};opened=[];unsubscribed=[]
    for pair in state['pairs']:
        if not pair.get('unsubscribed_at') and pair['symbol'] not in planned_items:
            pair['unsubscribed_at']=day;unsubscribed.append(pair['id'])
    for symbol in planned_items:
        if symbol not in state['seen']:state['seen'].append(symbol)
    active=[p for p in state['pairs'] if not p.get('unsubscribed_at')]
    active_symbols={p['symbol'] for p in active}
    # 先到先得队列；离开计划的未开户项不占名额，重新进入仍保留首次计划顺序。
    state['queue']=[s for s in state['seen'] if s in planned_items and s not in active_symbols]
    for symbol in state['queue']:
        if symbol not in successful:audit[symbol]='缺失';continue
        if not eligible.get(symbol,False):audit[symbol]='不可建账';continue
        policy=cost_policies.get(symbol,{}) if cost_policies is not None else None
        if policy is not None and policy.get('cost_bp') is None:
            audit[symbol]='成本未赋值，未纳入：'+policy.get('cost_unassigned_reason','type 缺失');continue
        if len(active)>=4:audit[symbol]='名额已满，未纳入';continue
        epoch=1+sum(p['symbol']==symbol for p in state['pairs'])
        pair={'id':f'{symbol}#{epoch}','symbol':symbol,'epoch':epoch,'opened_at':day}
        if policy is not None:pair.update(policy)
        state['pairs'].append(pair);active.append(pair);opened.append(pair['id'])
    for pair in active:
        audit[pair['symbol']]='运行A' if pair['symbol'] in successful and eligible.get(pair['symbol'],False) else '缺失'
    state.update(day=day,planned_items=list(planned_items),opened=opened,unsubscribed=unsubscribed,
                 run_symbols=[p['symbol'] for p in active if audit[p['symbol']]=='运行A'],audit=audit)
    return state


def paired_difference_index(pairs, days):
    """连乘账户日收益差的等权均值；退出日保留，关闭后无样本。"""
    by_day={day:[] for day in days}
    for pair in pairs:
        rows={path:{r['day']:r for r in pair[path]['daily']} for path in ('A','B')}
        previous={'A':10000.0,'B':10000.0}
        for day in days:
            if not all(day in rows[p] for p in ('A','B')):continue
            changes={p:rows[p][day]['nav']/previous[p]-1 for p in ('A','B')}
            by_day[day].append({'pair_id':pair['id'],'difference':changes['A']-changes['B']})
            previous={p:rows[p][day]['nav'] for p in ('A','B')}
    level=1.;result=[]
    for day in days:
        samples=by_day[day];mean=sum(x['difference'] for x in samples)/len(samples) if samples else None
        if mean is not None:level*=1+mean
        result.append({'day':day,'pair_count':len(samples),'daily_difference':mean,
                       'synthetic_index':level,'cumulative_difference':level-1,'samples':samples,
                       'sample_status':'有样本' if samples else '无样本'})
    return result

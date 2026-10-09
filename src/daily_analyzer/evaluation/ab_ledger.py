"""T49 v5.3 逐账户日线模拟账本；冻结决策与日线的确定性纯函数，不调用模型。"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import math
import re

from .settlement import number

VERSION = 'v5.3-1'
COST_BP = {'SPY': 2, 'QQQ': 2, 'TSLA': 5, 'SPCX': 15}
CLASS_DEFAULT_BP = {'etf':10,'stock':15}
COST_POLICY_VERSION = 'cost-v1-2026-10-10'
STANDARD = 5000.0
INITIAL = 10000.0


def resolve_cost(symbol, result_type):
    """登记优先，其次结果JSON资产类型；仅为投研批准的模拟假设。"""
    source='registry' if symbol in COST_BP else 'class_default' if isinstance(result_type,str) and result_type in CLASS_DEFAULT_BP else 'unassigned'
    amount=COST_BP[symbol] if source=='registry' else CLASS_DEFAULT_BP.get(result_type) if isinstance(result_type,str) else None
    reason=None if amount is not None else 'type 缺失' if result_type is None else 'type=index' if result_type=='index' else 'type 非法'
    return {'cost_bp':amount,'cost_source':source,'type':result_type,'cost_policy_version':COST_POLICY_VERSION,'cost_unassigned_reason':reason}


def preconditions(text, *, allocation, target, age):
    """每一子句完整匹配预注册白名单；未知语义不放行。"""
    failures = []
    for clause in filter(None, (s.strip() for s in re.split(r'[；;。，]|且', text or ''))):
        accepted = False
        if re.fullmatch(r'(?:先)?(?:核实|核对|核对实际|已核实)(?:[A-Z]+)?(?:实际)?持仓(?:及|与)标准量', clause):
            accepted = True
        elif (match := re.fullmatch(r'(?:实际|常态)?配置\s*(≥|>=|>|高于)\s*(\d+(?:\.\d+)?)%', clause)):
            bound = float(match[2]); accepted = allocation > bound if match[1] in ('>', '高于') else allocation >= bound
        elif (match := re.fullmatch(r'高于(\d+(?:\.\d+)?)%至少(\d+(?:\.\d+)?)个百分点', clause)):
            accepted = allocation >= float(match[1]) + float(match[2])
        elif clause == '超额尚未调整完成':
            accepted = allocation-target >= 10
        elif re.fullmatch(r'(?:仅常规时段(?:（执行）|\(执行\))?|仅常规开盘|常规时段流动性正常)', clause):
            accepted = True
        elif (match := re.fullmatch(r'(?:(?:分析日|当日)起(\d+)个?交易日有效|有效(\d+)交易日)', clause)):
            accepted = age <= int(match[1] or match[2])
        elif re.fullmatch(r'与\d+(?:\.\d+)?%相差不到10个百分点不操作|避免重复减仓|保护腿优先', clause):
            accepted = True
        if not accepted:
            failures.append(clause)
    return not failures, failures


def buy_price(leg, bar, *, confirmed=False):
    """返回价格与实际时点；止损缺失/倒置、区间外未触及均不成交。"""
    low, high, stop = (number(leg.get(k), positive=True) for k in ('zone_low','zone_high','stop_loss'))
    if low is None or high is None or stop is None or not stop < low <= high:
        return None, '不可执行'
    opened = bar['open']
    if opened <= stop or (confirmed and opened < low):
        return None, '腿失效'
    if low <= opened <= high:
        return opened, '开盘'
    if opened > high and bar['low'] <= high:
        return high, '盘中'
    if stop < opened < low and bar['high'] >= low:
        return low, '盘中'
    return None, '价格未触及'


class Ledger:
    """单账户账本；历史规则夹具可显式传入旧参数。"""
    def __init__(self, symbols=('SPY',), *, cost_multiple=1, direct=False, initial=INITIAL, standard=STANDARD, costs=None):
        self.symbols = tuple(symbols)
        self.cost_multiple = cost_multiple
        self.direct = direct
        self.initial = float(initial)
        self.standard = float(standard)
        self.costs = dict(COST_BP if costs is None else costs)
        self.cash = self.initial
        self.lots = {s: [] for s in symbols}
        self.decisions = {}
        self.orders = {s: [] for s in symbols}
        self.confirmations = {}
        self.used = set()
        self.invalid = set()
        self.trades = []
        self.events = []
        self.daily = []
        self.previous = {}
        self.index = -1

    def shares(self, symbol):
        return sum(lot['shares'] for lot in self.lots[symbol])

    def allocation(self, symbol, reference):
        return self.shares(symbol)*reference/self.standard*100

    def cost(self, symbol):
        return self.costs[symbol]*self.cost_multiple/10000

    def event(self, symbol, reason, **details):
        self.events.append({'day': self.day, 'symbol': symbol, 'reason': reason, **details})

    def _sale(self, symbol, shares, price, reason, *, lot=None):
        remaining = min(shares, self.shares(symbol))
        quantity = remaining
        selected = [lot] if lot is not None else self.lots[symbol]
        for item in selected:
            sold = min(remaining, item['shares'])
            item['shares'] -= sold
            remaining -= sold
            if remaining <= 1e-10:
                break
        self.lots[symbol] = [item for item in self.lots[symbol] if item['shares'] > 1e-10]
        quantity -= remaining
        if quantity <= 1e-10:
            return
        cost = quantity*price*self.cost(symbol)
        self.cash += quantity*price-cost
        self.trades.append({'day': self.day, 'symbol': symbol, 'side': 'sell', 'shares': quantity,
                            'price': price, 'cost': cost, 'reason': reason})

    def _buy_batch(self, requests):
        need = sum(q*p*(1+self.cost(s)) for s,q,p,leg,key,timing in requests)
        factor = min(1.0, self.cash/need) if need else 0
        for symbol, quantity, price, leg, key, timing in requests:
            quantity *= factor
            if quantity <= 1e-10:
                self.event(symbol, '现金不足'); continue
            cost = quantity*price*self.cost(symbol)
            self.cash -= quantity*price+cost
            self.lots[symbol].append({'shares': quantity, 'stop_loss': leg.get('stop_loss'),
                                      'bought_index': self.index, 'source': key, 'timing': timing})
            self.trades.append({'day': self.day, 'symbol': symbol, 'side': 'buy', 'shares': quantity,
                                'price': price, 'cost': cost, 'reason': '目标直达' if self.direct else '买入腿', 'source': key})
            self.used.add(key)
        if abs(self.cash) < 1e-8:
            self.cash = 0.0
        assert self.cash >= -1e-8, '现金不得为负'

    def initialize(self, day, bars):
        """T0 各标的按开盘价买入固定标准仓，无止损。"""
        self.day = day
        for symbol in self.symbols:
            opened = bars[symbol]['open']
            quantity = self.standard/opened
            cost = self.standard*self.cost(symbol)
            self.cash -= self.standard+cost
            self.lots[symbol] = [{'shares': quantity, 'stop_loss': None, 'bought_index': 0, 'source': '初始仓', 'timing': '开盘'}]
            self.trades.append({'day': day, 'symbol': symbol, 'side': 'buy', 'shares': quantity, 'price': opened, 'cost': cost, 'reason':'初始仓'})
        assert self.cash >= 0

    def _target(self, symbol):
        decision = self.decisions.get(symbol)
        return decision['target'] if decision else 100

    def _valid(self, symbol):
        return symbol in self.decisions and self.index-self.decisions[symbol]['index'] <= 5

    def _allowed(self, symbol, leg, target, reference, age):
        okay, failed = preconditions(leg.get('preconditions'), allocation=self.allocation(symbol,reference), target=target, age=age)
        if not okay:
            self.event(symbol,'前提受限',clauses=failed)
        return okay

    def step(self, day, bars, references, decisions=None, *, splits=()):
        """决策须已按生产完成时刻换算生效日；输入日线须截止本估值日。"""
        self.index += 1; self.day = day
        decisions = decisions or {}
        usable = {}
        for symbol in self.symbols:
            bar = bars.get(symbol, {})
            if symbol in splits:
                self.event(symbol, '拆股冻结'); continue
            if not all(number(bar.get(k),positive=True) for k in ('open','high','low','close')) or not number(references.get(symbol), positive=True):
                self.event(symbol, '缺价'); continue
            usable[symbol] = bar
        for symbol in set(self.symbols)-set(usable):
            for key in list(self.confirmations):
                if key[0]==symbol:self.confirmations.pop(key)
        fresh = set()
        for symbol, decision in decisions.items():
            if symbol not in self.symbols:
                continue
            old = self.decisions.get(symbol)
            if old and old['id'] == decision.get('id', day):
                continue
            if old:
                for key, count in list(self.confirmations.items()):
                    if key[:2] == (symbol,old['id']) and count:
                        self.event(symbol, '确认未完成（被取代）', source=key)
                        self.confirmations.pop(key)
                self.event(symbol, '旧决策被取代', source=old['id'])
            target = number(decision.get('target_allocation_pct',decision.get('target_allocation')))
            self.decisions[symbol] = {**deepcopy(decision), 'id': decision.get('id',day), 'index':self.index,
                                      'target': max(0,min(200,target)) if target is not None else self._target(symbol)}
            fresh.add(symbol)
        for symbol in usable:
            if self._valid(symbol) and abs(self.allocation(symbol,references[symbol])-self._target(symbol)) >= 10:
                self.event(symbol,'目标偏离至少10个百分点')
        sold = set()
        old_stops = set()
        # 1 开盘止损，已有批次盘中止损标记用于实际盘中买入屏蔽。
        for symbol, bar in usable.items():
            for lot in list(self.lots[symbol]):
                stop = number(lot.get('stop_loss'),positive=True)
                if stop is None or self.index-lot['bought_index'] >= 20:
                    continue
                if bar['open'] <= stop:
                    self._sale(symbol,lot['shares'],bar['open'],'跳空止损',lot=lot)
                elif bar['low'] <= stop:
                    old_stops.add(symbol)
        # 2 所有开盘减仓指令先合并，再判断容差。
        for symbol, bar in usable.items():
            reference = references[symbol]; current = self.allocation(symbol,reference)
            decision = self.decisions.get(symbol, {})
            target = self._target(symbol)
            instructions = []
            for order in self.orders[symbol]:
                if order['kind'] == '买入':
                    continue
                level = order['level']
                if order['kind'] == '超配回落' and symbol in fresh:
                    level = max(level,target)
                    if level != order['level']:
                        self.event(symbol,'次日开盘单被缩小',source=order['key'])
                if current-level < 10:
                    self.event(symbol, '已达到，无需卖出' if order['kind']=='风险减配' else '次日开盘单被取消',source=order['key'])
                instructions.append((level,order['kind'],order['key']))
            if self._valid(symbol):
                if self.direct:
                    instructions.append((target,'目标直达',(symbol,decision['id'],'L1')))
                elif symbol in fresh:
                    for i,leg in enumerate(decision.get('reduce_legs') or []):
                        key = (symbol,decision['id'],'reduce',i)
                        if leg.get('trigger_rule') != '立即':
                            continue
                        level = number(leg.get('post_allocation_pct'))
                        if level is None and leg.get('kind')=='超配回落':level=target
                        if level is None or leg.get('kind') not in ('超配回落','风险减配'):
                            self.event(symbol,'不可执行',source=key);continue
                        if self._allowed(symbol,leg,target,reference,0):instructions.append((max(0,min(200,level)),leg['kind'],key))
            if instructions:
                chosen = min(instructions,key=lambda item:(item[0],item[1]!='风险减配'))
                if current-chosen[0] >= 10:
                    quantity = (current-chosen[0])/100*self.standard/reference
                    self._sale(symbol,quantity,bar['open'],chosen[1]); self.trades[-1]['source']=chosen[2]; sold.add(symbol)
                    for item in instructions:
                        if item is not chosen:self.event(symbol,'已被合并',source=item[2])
        # 3/5 买入按实际时点分组；同标多腿只补目标一次。
        candidates = {'开盘':[], '盘中':[]}
        for symbol, bar in usable.items():
            reference = references[symbol]; target = self._target(symbol)
            decision = self.decisions.get(symbol,{})
            age = self.index-decision.get('index',self.index)
            options = []
            for order in self.orders[symbol]:
                if order['kind']=='买入':
                    level = min(order['level'],target) if symbol in fresh else order['level']
                    if level < order['level']:self.event(symbol,'次日开盘单被缩小',source=order['key'])
                    options.append((order['leg'],order['key'],level,True,order.get('age',0)+1))
            if self._valid(symbol):
                if self.direct:
                    options.append(({},(symbol,decision['id'],'L1'),target,False,age))
                else:
                    for i,leg in enumerate(decision.get('buy_legs') or []):
                        if leg.get('status')=='可执行' and leg.get('trigger_rule')=='触及区间':
                            options.append((leg,(symbol,decision['id'],'buy',i),target,False,age))
                        elif leg.get('status') not in ('待触发',):
                            self.event(symbol,'仅观察' if leg.get('status')=='仅观察' else '不可执行')
            selected = None
            for leg,key,level,confirmed,leg_age in options:
                current = self.allocation(symbol,reference)
                if (key in self.used and not confirmed) or key in self.invalid:continue
                if symbol in sold:
                    self.event(symbol,'同日不反向',source=key);continue
                if decision.get('rating') in ('Underweight','Sell') or level-current < 10:
                    if confirmed:self.event(symbol,'次日开盘单被取消',source=key)
                    continue
                if not self._allowed(symbol,leg,level,reference,leg_age):continue
                price,timing = (bar['open'],'开盘') if self.direct else buy_price(leg,bar,confirmed=confirmed)
                if price is None:
                    self.event(symbol,timing,source=key)
                    if timing=='腿失效':self.invalid.add(key)
                    continue
                if timing=='盘中' and symbol in old_stops:
                    self.event(symbol,'盘中止损屏蔽',source=key);continue
                request = (symbol,(level-current)/100*self.standard/reference,price,leg,key,timing)
                if selected is None or timing=='开盘':
                    selected = request
                    if timing=='开盘':break
            if selected:candidates[selected[-1]].append(selected)
        self._buy_batch(candidates['开盘'])
        self._buy_batch(candidates['盘中'])
        # 6 盘中止损在所有买入之后，回款只在次日供买入使用。
        for symbol, bar in usable.items():
            for lot in list(self.lots[symbol]):
                stop = number(lot.get('stop_loss'),positive=True)
                if stop is not None and self.index-lot['bought_index'] < 20 and bar['low'] <= stop:
                    if lot['bought_index']==self.index and lot['timing']=='盘中' and bar['open']<stop+0.000001:
                        self.event(symbol,'同日双触',source=lot['source'])
                    elif lot['bought_index']==self.index and lot['timing']=='盘中':
                        # 下方上行买入（O<L）时，无法确认日内最低点先后。
                        source=lot['source'];dec=self.decisions.get(symbol,{})
                        legs=dec.get('buy_legs') or []
                        if len(source)>3 and source[2]=='buy' and source[3]<len(legs) and bar['open']<legs[source[3]].get('zone_low',0):self.event(symbol,'同日双触',source=source)
                    self._sale(symbol,lot['shares'],stop,'批次止损',lot=lot)
        # 7 收盘确认只计同一决策生效后的完整日线。
        for symbol in self.symbols:
            self.orders[symbol] = []
            if symbol not in usable or not self._valid(symbol) or self.direct:continue
            bar=usable[symbol];reference=references[symbol];decision=self.decisions[symbol];target=decision['target'];age=self.index-decision['index']
            for family in ('buy','reduce'):
                for i,leg in enumerate(decision.get(family+'_legs') or []):
                    key=(symbol,decision['id'],family,i)
                    if key in self.used or key in self.invalid:continue
                    rule=leg.get('trigger_rule');kind='买入' if family=='buy' else leg.get('kind')
                    if family=='buy' and not (leg.get('status')=='待触发' and rule=='收盘站上'):
                        continue
                    if family=='reduce' and rule not in ('收盘跌破','进入区间受阻'):
                        if rule not in ('立即',):self.event(symbol,'不可执行',source=key)
                        continue
                    if not self._allowed(symbol,leg,target,reference,age):continue
                    count=leg.get('confirm_days')
                    if count is None and kind=='风险减配' and rule=='收盘跌破':count=1
                    trigger=number(leg.get('trigger_price'),positive=True)
                    if rule=='进入区间受阻':
                        low,high=number(leg.get('zone_low'),positive=True),number(leg.get('zone_high'),positive=True)
                        if kind!='超配回落' or low is None or high is None or low>high:
                            self.event(symbol,'不可执行',source=key);continue
                        condition=bar['high']>=low and bar['close']<=high;count=1
                    else:
                        if count not in (1,2) or trigger is None or (family=='reduce' and kind!='风险减配'):
                            self.event(symbol,'不可执行',source=key);continue
                        condition=bar['close']>trigger if family=='buy' else bar['close']<trigger
                    self.confirmations[key]=self.confirmations.get(key,0)+1 if condition else 0
                    if self.confirmations[key]>=count:
                        level=target if family=='buy' else number(leg.get('post_allocation_pct'))
                        if level is None and kind=='超配回落':level=target
                        if level is None:self.event(symbol,'不可执行',source=key);continue
                        self.orders[symbol].append({'kind':kind,'level':max(0,min(200,level)),'leg':deepcopy(leg),'key':key,'age':age})
                        self.used.add(key)
                        self.confirmations.pop(key,None)
        for symbol,bar in usable.items():self.previous[symbol]=bar['close']
        positions={s:self.shares(s)*self.previous.get(s,references.get(s,0)) for s in self.symbols}
        nav=self.cash+sum(positions.values())
        row={'day':day,'cash':self.cash,'nav':nav,'return':nav/self.initial-1,'positions':positions,
             'shares':{s:self.shares(s) for s in self.symbols}}
        self.daily.append(row)
        return row

    def exit_step(self, day, bars):
        """退订后只等待有开盘价时全部平仓；退出日损益保留在日收益中。"""
        self.index += 1; self.day = day
        for symbol in self.symbols:
            self.orders[symbol] = []
            opened = number(bars.get(symbol, {}).get('open'), positive=True)
            if opened is not None and self.shares(symbol):
                self._sale(symbol, self.shares(symbol), opened, '退订平仓')
            closed = number(bars.get(symbol, {}).get('close'), positive=True)
            if closed is not None:self.previous[symbol] = closed
        self.confirmations.clear()
        positions = {s:self.shares(s)*self.previous.get(s,0) for s in self.symbols}
        nav = self.cash+sum(positions.values())
        row = {'day':day,'cash':self.cash,'nav':nav,'return':nav/self.initial-1,
               'positions':positions,'shares':{s:self.shares(s) for s in self.symbols}}
        self.daily.append(row)
        return row

    def result(self):
        """输出不含时钟和随机字段，重复计算逐字节一致。"""
        return {'version':VERSION,'cash':self.cash,'lots':deepcopy(self.lots),'daily':self.daily,
                'trades':self.trades,'events':self.events,'event_counts':dict(Counter(e['reason'] for e in self.events)),
                'cost_total':sum(t['cost'] for t in self.trades)}

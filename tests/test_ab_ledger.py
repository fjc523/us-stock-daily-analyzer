"""v5.2 F1–F31 的日线夹具；不访问外部数据或模型。"""
from copy import deepcopy
import pytest

from daily_analyzer.evaluation.ab_ledger import Ledger, preconditions


def leg(**changes):
    return dict(status='可执行',trigger_rule='触及区间',zone_low=100,zone_high=102,stop_loss=97,**changes)


def decision(target=100, **changes):
    return dict(id='d1',rating='Hold',target_allocation_pct=target,buy_legs=[leg()],reduce_legs=[],**changes)


def bar(o=101,h=104,lo=99,c=101):
    return dict(open=o,high=h,low=lo,close=c)


def ledger(a=80,stop=None):
    value=Ledger(('SPY',),cost_multiple=0,initial=100000,standard=20000)
    value.lots['SPY']=[dict(shares=a/100*20000/100,stop_loss=stop,bought_index=0,source='初始仓',timing='开盘')]
    return value


def buys(value):return [t for t in value.trades if t['side']=='buy']
def sales(value):return [t for t in value.trades if t['side']=='sell']


@pytest.mark.parametrize('fid,b,price,stop,dual',[
 ('F1',bar(),101,False,False),('F2',bar(o=104,lo=101.5),102,False,False),
 ('F3',bar(o=104,lo=102.5),None,False,False),('F4',bar(o=99,h=100.5,lo=98.5),100,False,False),
 ('F5',bar(o=99,h=99.8,lo=98.5),None,False,False),('F6',bar(o=96.8,lo=96),None,False,False),
 ('F7',bar(o=101,lo=96.5),101,True,False),('F8',bar(o=99,h=100.5,lo=96.5),100,True,True)])
def test_F1_F8(fid,b,price,stop,dual):
    value=ledger();value.step('d1',{'SPY':b},{'SPY':100},{'SPY':decision()})
    assert ([t['price'] for t in buys(value)] or [None])==[price]
    assert bool(sales(value))==stop
    assert bool(value.result()['event_counts'].get('同日双触'))==dual
    if stop:assert sales(value)[0]['price']==97


def confirmed(value, *, post=None, kind='买入', zone=(105,107),stop=97):
    value.orders['SPY']=[dict(kind=kind,level=100 if post is None else post,leg=dict(zone_low=zone[0],zone_high=zone[1],stop_loss=stop),key=('SPY','old','buy' if kind=='买入' else 'reduce',0))]


@pytest.mark.parametrize('fid,o,target,rating,price',[
 ('F9',104.5,100,'Hold',None),('F10',106,90,'Hold',106),('F11',106,100,'Underweight',None)])
def test_F9_F11(fid,o,target,rating,price):
    value=ledger();confirmed(value)
    d=decision(target);d['rating']=rating;d['buy_legs']=[]
    value.step('d2',{'SPY':bar(o=o,h=108,lo=105,c=106)},{'SPY':100},{'SPY':d})
    assert ([t['price'] for t in buys(value)] or [None])==[price]
    if fid=='F10':assert value.allocation('SPY',100)==pytest.approx(90)


def test_F12_replaced_confirmation():
    value=ledger();d=decision();d['buy_legs']=[dict(status='待触发',trigger_rule='收盘站上',zone_low=105,zone_high=107,stop_loss=97,trigger_price=105,confirm_days=2)]
    value.step('d1',{'SPY':bar(o=104,h=108,lo=103,c=106)},{'SPY':100},{'SPY':d})
    d2=decision();d2.update(id='d2',buy_legs=[])
    value.step('d2',{'SPY':bar(o=106,h=108,lo=105,c=106)},{'SPY':100},{'SPY':d2})
    assert not buys(value)
    assert value.result()['event_counts']['确认未完成（被取代）']==1


@pytest.mark.parametrize('fid,h,c,generated',[('F13',780,777,True),('F14a',784,783,False),('F14b',778,777,False)])
def test_F13_F14(fid,h,c,generated):
    value=ledger(140);value.lots['SPY'][0]['shares']=140/100*20000/779
    d=decision(125);d['buy_legs']=[];d['reduce_legs']=[dict(kind='超配回落',trigger_rule='进入区间受阻',zone_low=779,zone_high=782,post_allocation_pct=125,preconditions='实际配置≥135%；仅常规时段；当日起5交易日有效')]
    value.step('d1',{'SPY':bar(o=779,h=h,lo=770,c=c)},{'SPY':779},{'SPY':d})
    assert bool(value.orders['SPY'])==generated
    if generated:
        d2=deepcopy(d);d2.update(id='d2',reduce_legs=[])
        value.step('d2',{'SPY':bar(o=777,h=780,lo=775,c=778)},{'SPY':779},{'SPY':d2})
        assert value.allocation('SPY',779)==pytest.approx(125)
        assert sales(value)[0]['price']==777


def test_F15prime_cash_is_account_local():
    value=Ledger(('SPY',));value.cash=1000
    value.lots['SPY']=[dict(shares=18,stop_loss=None,bought_index=0,source='初始仓',timing='开盘')]
    other=Ledger(('QQQ',));other.cash=5000
    d=decision(200);d['buy_legs']=[dict(status='可执行',trigger_rule='触及区间',zone_low=500,zone_high=510,stop_loss=490)]
    value.step('d1',{'SPY':bar(o=505,h=510,lo=502,c=505)},{'SPY':500},{'SPY':d})
    assert buys(value)[0]['shares']==pytest.approx(1000/(505*1.0002))
    assert value.cash==0 and other.cash==5000


@pytest.mark.parametrize('fid,a,level,expected',[('F16',140,110,110),('F17',100,60,60),('F20',82,75,82)])
def test_F16_F17_F20(fid,a,level,expected):
    value=ledger(a)
    if fid=='F16':confirmed(value,post=125,kind='超配回落')
    d=decision(level if fid=='F20' else 100);d['reduce_legs']=[dict(kind='风险减配' if fid=='F17' else '超配回落',trigger_rule='立即',post_allocation_pct=level)]
    value.step('d1',{'SPY':bar()},{'SPY':100},{'SPY':d})
    assert value.allocation('SPY',100)==pytest.approx(expected)
    assert len(sales(value))==(0 if fid=='F20' else 1)
    assert not buys(value)


@pytest.mark.parametrize('fid,text,expected',[
 ('F18','核实持仓及标准量；常态配置≥85%；风险上限未触发；仅常规时段；有效5交易日，CPI后重算',False),
 ('F19','已核实持仓及标准量，配置≥85%；常规时段流动性正常；分析日起5交易日有效',True)])
def test_F18_F19(fid,text,expected):
    value=ledger(100);d=decision(75);d.update(buy_legs=[],reduce_legs=[dict(kind='超配回落',trigger_rule='立即',post_allocation_pct=75,preconditions=text)])
    value.step('d1',{'SPY':bar()},{'SPY':100},{'SPY':d})
    assert bool(sales(value))==expected
    assert value.allocation('SPY',100)==pytest.approx(75 if expected else 100)


def test_F21_intraday_stop_blocks_intraday_buy():
    value=ledger(stop=98);value.step('d1',{'SPY':bar(o=104,lo=97.5)},{'SPY':100},{'SPY':decision()})
    assert not buys(value);assert sales(value)[0]['price']==98


def test_F22_gap_stop():
    value=ledger(stop=97);value.step('d1',{'SPY':bar(o=95,lo=94)},{'SPY':100})
    assert sales(value)[0]['price']==95


def test_F23_fifo():
    value=ledger(100);value.lots['SPY'].append(dict(shares=40,stop_loss=97,bought_index=0,source='新批',timing='开盘'))
    d=decision(105);d.update(buy_legs=[],reduce_legs=[dict(kind='超配回落',trigger_rule='立即',post_allocation_pct=105)])
    value.step('d1',{'SPY':bar()},{'SPY':100},{'SPY':d})
    assert [lot['shares'] for lot in value.lots['SPY']]==[170,40]
    assert value.lots['SPY'][1]['stop_loss']==97


@pytest.mark.parametrize('rule',['其他条件',None])
def test_F24_nonmechanical_rules(rule):
    value=ledger(100);d=decision(60);d.update(buy_legs=[],reduce_legs=[dict(kind='风险减配',trigger_rule=rule,post_allocation_pct=60)])
    value.step('d1',{'SPY':bar()},{'SPY':100},{'SPY':d})
    assert not sales(value)
    assert value.result()['event_counts']['不可执行']


@pytest.mark.parametrize('fid,post,new_target,a,expected',[
 ('F26',0,125,100,0),('F27',60,125,100,60),('F28a',100,125,140,125),('F28b',100,125,130,130)])
def test_F26_F28(fid,post,new_target,a,expected):
    value=ledger(a);confirmed(value,post=post,kind='超配回落' if fid.startswith('F28') else '风险减配')
    d=decision(new_target);d['rating']='Overweight'
    value.step('d2',{'SPY':bar(o=93,h=104,lo=92,c=94)},{'SPY':100},{'SPY':d})
    assert value.allocation('SPY',100)==pytest.approx(expected)
    assert not buys(value)
    if not fid.startswith('F28'):assert sales(value)[0]['reason']=='风险减配'


def test_F29_all_sells_merged_and_risk_attribution():
    value=ledger(100);confirmed(value,post=60,kind='风险减配')
    d=decision(125);d['reduce_legs']=[dict(kind='风险减配',trigger_rule='立即',post_allocation_pct=40),dict(kind='超配回落',trigger_rule='立即',post_allocation_pct=80)]
    value.step('d2',{'SPY':bar()},{'SPY':100},{'SPY':d})
    assert len(sales(value))==1 and sales(value)[0]['reason']=='风险减配'
    assert value.allocation('SPY',100)==pytest.approx(40)
    assert value.result()['event_counts']['已被合并']==2


@pytest.mark.parametrize('fid,o,bought',[('F30',104,False),('F31',101,True)])
def test_F30_F31_actual_fill_timing(fid,o,bought):
    value=ledger(80,stop=98);confirmed(value,zone=(100,102),stop=97)
    d=decision();d['buy_legs']=[]
    value.step('d2',{'SPY':bar(o=o,h=105,lo=97.5,c=101)},{'SPY':100},{'SPY':d})
    assert bool(buys(value))==bought
    assert sales(value)[0]['price']==98
    assert value.orders['SPY']==[]
    if bought:
        assert buys(value)[0]['price']==101
        assert value.lots['SPY'][0]['stop_loss']==97
    else:assert value.result()['event_counts']['盘中止损屏蔽']==1


def test_confirmed_order_is_executable_next_day_once():
    value=ledger();d=decision();d['buy_legs']=[dict(status='待触发',trigger_rule='收盘站上',trigger_price=105,confirm_days=1,zone_low=105,zone_high=107,stop_loss=97)]
    value.step('d1',{'SPY':bar(o=104,h=108,lo=103,c=106)},{'SPY':100},{'SPY':d})
    assert value.orders['SPY']
    value.step('d2',{'SPY':bar(o=106,h=108,lo=105,c=106)},{'SPY':100})
    assert len(buys(value))==1


def test_missing_ohlc_splits_and_stale_decisions():
    value=ledger();value.step('d1',{'SPY':bar()},{'SPY':100},{'SPY':dict(id='d1',rating='Hold',target_allocation_pct=100,buy_legs=[],reduce_legs=[])})
    before=value.shares('SPY')
    value.step('d2',{'SPY':{'close':105}},{'SPY':100})
    assert value.shares('SPY')==before
    value.step('d3',{'SPY':bar()},{'SPY':100},splits=('SPY',))
    assert value.result()['event_counts']['缺价']==1 and value.result()['event_counts']['拆股冻结']==1
    for i in range(4,9):value.step('d'+str(i),{'SPY':bar()},{'SPY':100})
    assert not value._valid('SPY')


def test_risk_null_confirmation_defaults_to_one_only():
    for count,expected in [(None,True),(0,False),(3,False)]:
        value=ledger(100);d=decision();d.update(buy_legs=[],reduce_legs=[dict(kind='风险减配',trigger_rule='收盘跌破',trigger_price=95,post_allocation_pct=60,confirm_days=count)])
        value.step('d1',{'SPY':bar(o=96,h=98,lo=93,c=94)},{'SPY':100},{'SPY':d})
        assert bool(value.orders['SPY'])==expected


@pytest.mark.parametrize('family',['buy','reduce'])
def test_missing_bar_breaks_consecutive_confirmation(family):
    value=ledger(100 if family=='reduce' else 80);d=decision()
    d['buy_legs']=[];d['reduce_legs']=[]
    d[family+'_legs']=[dict(kind='风险减配',status='待触发',trigger_rule='收盘站上' if family=='buy' else '收盘跌破',trigger_price=105 if family=='buy' else 110,confirm_days=2,zone_low=105,zone_high=107,stop_loss=97,post_allocation_pct=60)]
    for day,b in [('d1',bar(o=106,h=108,lo=105,c=106)),('d2',{}),('d3',bar(o=106,h=108,lo=105,c=106))]:
        value.step(day,{'SPY':b},{'SPY':100},{'SPY':d} if day=='d1' else None)
    assert not value.orders['SPY']

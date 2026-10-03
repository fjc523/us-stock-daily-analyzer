"""独立评估固定样本，合成数值仅验证代码，绝不作为真实收益。"""

import copy
from datetime import date, datetime, timedelta
import json
from pathlib import Path

import exchange_calendars as xcals
import pandas as pd
import pytest

from daily_analyzer.config import EvaluationSettings, parse_settings
from daily_analyzer.evaluation.settlement import entry_plan, exit_date, settle, new_record, bar_prices
from daily_analyzer.evaluation.report import analyze, attribution, baseline_comparison, bearish_warning, bootstrap_mean, evaluate, hit_rates, rank_ic, spearman
from daily_analyzer.storage import atomic_write_json


def stamp(value):
    return datetime.fromisoformat(value)


class FixtureServices:
    def __init__(self, missing=None):
        self.prices = self
        self.missing = missing or set()
        self.calls = []

    def sector(self, symbol):
        return 'XLK' if symbol == 'TECH' else None

    def bars(self, symbol, end):
        self.calls.append((symbol, end))
        calendar = xcals.get_calendar('XNYS')
        sessions = calendar.sessions_in_range(pd.Timestamp('2026-08-01'), pd.Timestamp(end))
        initial, step = {'SPY': (100, .2), 'XLK': (100, .4)}.get(symbol, (100, 1))
        return [dict(date=s.date().isoformat(), open=initial+i*step, close=initial+i*step+.5) for i,s in enumerate(sessions) if (symbol,s.date()) not in self.missing], 'fixture合成'


def raw(symbol='QQQ', kind='etf', run='batch', finished='2026-10-02T08:00:00-04:00'):
    return dict(run_id=run, symbol=symbol, analyzed_symbol='SPY' if kind=='index' else symbol, type=kind, mode='live', status='success',
                upstream_trade_date='2026-10-02', finished_at=finished, price_data_end_date='2026-10-01', target_session='盘前',
                final_rating='Hold', investment_plan='**Recommendation**: Overweight\n\n**目标配置（标准仓位=100%）**: 60%',
                trader_investment_plan='**Action**: Hold\n\n**目标配置（标准仓位=100%）**: 未提供',
                final_trade_decision='**目标配置（标准仓位=100%）**: 40%',
                context_blocks={'price_anchors': {'data': {'anchors': {'P_Close': {'value':100}, 'atr':{'value':2}, 'close_200_sma':{'value':90}}}},
                                'market_regime':{'data':{'label':'偏强'}}})


def write_run(root, result, current=True):
    directory = root/'data/runs'/result['upstream_trade_date']
    atomic_write_json(directory/'batches'/result['run_id']/'results'/f"{result['symbol']}.json",result)
    if current:
        atomic_write_json(directory/'current'/f"{result['symbol']}.json", result)


def rows(root):
    return [json.loads(line) for line in (root/'data/evaluation/outcomes.jsonl').read_text().splitlines()]


@pytest.mark.parametrize('finished,basis,day', [
    ('2026-10-02T08:00:00-04:00','same_day_open','2026-10-02'),
    ('2026-10-02T09:30:00-04:00','same_day_close','2026-10-02'),
    ('2026-10-02T12:00:00-04:00','same_day_close','2026-10-02'),
    ('2026-10-02T16:00:00-04:00','same_day_close','2026-10-02'),
    ('2026-10-02T16:00:01-04:00','next_open','2026-10-05'),
    ('2026-10-03T10:00:00-04:00','next_open','2026-10-05'),
    ('2026-11-26T10:00:00-05:00','next_open','2026-11-27'),
    ('2026-11-27T13:00:00-05:00','same_day_close','2026-11-27'),
    ('2026-11-27T13:00:01-05:00','next_open','2026-11-30'),
])
def test_entry_actual_calendar(finished,basis,day):
    assert entry_plan(stamp(finished)) == {'basis':basis,'date':day}


def test_window_complete_sessions():
    assert exit_date({'basis':'same_day_open','date':'2026-10-02'},5).isoformat()=='2026-10-08'
    assert exit_date({'basis':'same_day_close','date':'2026-10-02'},5).isoformat()=='2026-10-09'
    assert exit_date({'basis':'next_open','date':'2026-10-05'},20).isoformat()=='2026-10-30'


@pytest.mark.parametrize('symbol,kind,primary,sector', [('SPY','etf','raw_return',None),('QQQ','etf','raw_return',None),('^GSPC','index','raw_return',None),('SMTC','stock','excess_vs_spy',None),('TECH','stock','excess_vs_spy','XLK'),('XLK','etf','excess_vs_spy',None)])
def test_six_asset_metrics(tmp_path,symbol,kind,primary,sector):
    write_run(tmp_path,raw(symbol,kind))
    result=settle(tmp_path,now=stamp('2026-11-02T17:00:00-05:00'),services=FixtureServices(),settings=EvaluationSettings())
    row=rows(tmp_path)[0]; outcome=row['windows']['5']
    assert result['records']==1 and row['primary_metric']==primary and row['sector_benchmark']==sector
    assert outcome['status']=='settled' and outcome['primary_return']==outcome[primary]
    assert (outcome['excess_vs_spy'] is None)==(row['analysis_symbol']=='SPY')
    assert (outcome['excess_vs_sector'] is not None)==(sector is not None)
    assert row['ratings']=={'rm':'Overweight','trader':'Hold','pm':'Hold'}
    assert row['target_allocation']=={'rm':60,'trader':None,'pm':40}


def test_config_custom_broad_and_window():
    setting=parse_settings({'evaluation': {'broad_market_etfs':[' xlk '], 'settlement_windows':[10,5]}}).evaluation
    row=new_record(raw('XLK'),setting,{},FixtureServices())
    assert row['primary_metric']=='raw_return' and set(row['windows'])=={'5','10'}
    with pytest.raises(ValueError):
        EvaluationSettings(settlement_windows=[1])
    with pytest.raises(ValueError):
        EvaluationSettings(broad_market_etfs=['QQQ','qqq'])


def test_pending_future_no_price_and_idempotent_current(tmp_path):
    services=FixtureServices()
    for symbol in ('QQQ','SPY'):
        write_run(tmp_path,raw(symbol,run='one'))
    write_run(tmp_path,raw('QQQ',run='two'))
    failed=raw('FAIL',run='failed');failed['status']='failed';write_run(tmp_path,failed)
    replay=raw('BACK',run='replay');replay['mode']='backfill';write_run(tmp_path,replay)
    now=stamp('2026-10-03T10:00:00-04:00')
    first=settle(tmp_path,now=now,services=services,settings=EvaluationSettings())
    content=(tmp_path/'data/evaluation/outcomes.jsonl').read_bytes()
    second=settle(tmp_path,now=now,services=services,settings=EvaluationSettings())
    assert first['records']==3 and first['current']==2 and first['windows']['pending']==9
    assert not second['changed'] and content==(tmp_path/'data/evaluation/outcomes.jsonl').read_bytes()
    assert len({(row['run_id'],row['symbol']) for row in rows(tmp_path)})==3
    assert all(end<=date(2026,10,2) for _,end in services.calls)


def test_future_entry_and_open_missing_no_close_fallback(tmp_path):
    write_run(tmp_path,raw('QQQ',finished='2026-10-02T23:00:00-04:00'))
    result=settle(tmp_path,now=stamp('2026-10-03T10:00:00-04:00'),services=FixtureServices(),settings=EvaluationSettings())
    row=rows(tmp_path)[0];assert row['entry']['date']=='2026-10-05' and row['entry']['price'] is None and row['entry']['basis']=='next_open'
    class MissingOpen(FixtureServices):
        def bars(self,symbol,end):
            values,source=super().bars(symbol,end)
            for item in values:
                if item['date']=='2026-10-05':item.pop('open')
            return values,source
    settle(tmp_path,now=stamp('2026-11-02T17:00:00-05:00'),services=MissingOpen(),settings=EvaluationSettings())
    row=rows(tmp_path)[0];assert row['entry']['basis']=='unavailable' and row['entry']['price'] is None
    assert all(w['status']=='unavailable' for w in row['windows'].values())


def test_missing_benchmark_and_suspension_backfill_frozen(tmp_path):
    write_run(tmp_path,raw('SMTC','stock'))
    now=stamp('2026-11-02T17:00:00-05:00')
    missing={('SPY',date(2026,10,2)),('SMTC',date(2026,10,8))}
    settle(tmp_path,now=now,services=FixtureServices(missing),settings=EvaluationSettings())
    assert all(w['status']=='unavailable' for w in rows(tmp_path)[0]['windows'].values())
    settle(tmp_path,now=now,services=FixtureServices(),settings=EvaluationSettings())
    previous=rows(tmp_path)[0]
    changed=raw('SMTC','stock');changed['final_rating']='Buy';write_run(tmp_path,changed)
    settle(tmp_path,now=stamp('2026-11-03T17:00:00-05:00'),services=FixtureServices(missing),settings=EvaluationSettings(broad_market_etfs=['SMTC']))
    assert rows(tmp_path)[0]==previous


def test_exact_dates_positive_and_timezone():
    values=bar_prices([{'t':'2026-10-03T00:00:00Z','o':100,'c':101},{'date':'2026-10-05','o':9,'c':10},{'date':'2026-10-01','o':float('nan'),'c':0}],date(2026,10,2))
    assert values[date(2026,10,2)]=={'open':100,'close':101}
    assert date(2026,10,5) not in values and values[date(2026,10,1)]=={'open':None,'close':None}


def sample(score,value,day='2026-10-02',atr=.02):
    return {'score':score,'return':value,'date':day,'atr_pct':atr,'close':100,'ma200':90,'momentum':.1}


def test_deadzone_hold_and_sign_known_answers():
    values=[sample(0,0),sample(1,.1),sample(-1,-.1),sample(0,.1),sample(1,0),sample(-1,-.01)]
    hits=hit_rates(values,5)
    assert hits['three_n']==6 and hits['three']==.5
    assert hits['sign_n']==4 and hits['sign']==.75
    assert hit_rates([sample(0,0,atr=None)],5)['three'] is None


def test_ic_cross_pool_ties_constants_and_one_date():
    assert spearman([1,1,2,3],[2,2,3,4])==pytest.approx(1)
    assert spearman([0,0,0],[1,2,3]) is None
    assert spearman([1,2,3],[0,0,0]) is None
    assert rank_ic([sample(i,i) for i in range(4)])['mode']=='池化'
    cross=rank_ic([sample(i,i) for i in range(5)])
    assert cross['mode']=='横截面' and cross['mean']==pytest.approx(1) and cross['std'] is None and cross['t'] is None
    cross=rank_ic([sample(i,i) for i in range(5)]+[sample(i,-i,'2026-10-01') for i in range(5)])
    assert cross['n']==10 and cross['mean']==pytest.approx(0) and cross['std']==pytest.approx(2**.5) and cross['t']==pytest.approx(0)


def test_bootstrap_fixed_value():
    assert bootstrap_mean([])==[None,None]
    assert bootstrap_mean([.2])==pytest.approx([.2,.2])
    assert bootstrap_mean([0,1,2])==bootstrap_mean([0,1,2])
    assert bootstrap_mean([0,1,2])==pytest.approx([0,2])


def test_baselines_same_samples_and_known_scores():
    values=[sample(1,.1),sample(-1,-.1),sample(0,0)]
    values[1].update(close=80,momentum=-.1)
    values[2].update(close=90,momentum=0)
    missing=sample(2,.2);missing['ma200']=None
    result=baseline_comparison(values+[missing],5)
    assert result['n']==3 and result['excluded']==1 and result['missing']['MA200/P_Close']==1
    for metric in result['metrics'].values():assert metric['n']==3
    assert result['metrics']['永远Hold']['ic']['mean'] is None
    assert result['metrics']['永远看多']['ic']['mean'] is None
    assert result['metrics']['200日均线趋势']['hits']['sign']==pytest.approx(2/3)
    assert result['metrics']['20日动量符号']['hits']['sign']==pytest.approx(2/3)


def fixture_outcome(day='2026-10-02',ratings=None,value=.1):
    return dict(run_id='fixture',symbol='QQQ',type='etf',trade_date=day,is_current=True,
        ratings=ratings or {'rm':'Buy','trader':'Hold','pm':'Underweight'},entry={'basis':'same_day_close'},
        primary_metric='raw_return',anchors={'P_Close':100,'atr':2,'close_200_sma':90},momentum_20d=.1,market_regime='偏强',
        windows={'5':{'status':'settled','primary_return':value,'excess_vs_sector':None}})


def test_attribution_distribution_and_ten_day_alert():
    values=[fixture_outcome(),fixture_outcome(ratings={'rm':'Sell','trader':'Hold','pm':'Buy'},value=-.2)]
    result=attribution(values,5)
    assert result['rm→trader']['下调']['mean']==.1 and result['rm→trader']['上调']['mean']==-.2
    assert result['trader→pm']['下调']['n']==1 and result['trader→pm']['上调']['n']==1
    calendar=xcals.get_calendar('XNYS');last=pd.Timestamp('2026-10-02')
    values=[fixture_outcome(calendar.session_offset(last,i).date().isoformat()) for i in range(-9,1)]
    assert bearish_warning(values)
    assert not bearish_warning(values[:-1])
    values[-1]['ratings']['pm']='Buy';assert not bearish_warning(values)
    data=analyze(values)
    assert sum(row['n'] for row in data['layers']['pm']['daily'])==10
    assert sum(row['n'] for row in data['layers']['pm']['weekly'])==10


def test_local_report_pending_small_sample_and_filters(tmp_path):
    value=fixture_outcome();value['windows']['5']['status']='pending'
    excluded=fixture_outcome('2026-10-01');excluded['is_current']=False;excluded['symbol']='SPY'
    path=tmp_path/'data/evaluation/outcomes.jsonl';path.parent.mkdir(parents=True)
    path.write_text('\n'.join(json.dumps(row) for row in (value,excluded))+'\n')
    result=evaluate(tmp_path,since='2026-10-02',window=5,layer='all',now=stamp('2026-10-03T10:00:00-04:00'))
    text=Path(result['path']).read_text()
    assert result['records']==1 and result['seconds']<30
    assert '样本不足，仅供参考' in text and 'NOT_TESTED' in text and '未定义/不可用' in text and 'pending n=1' in text
    assert '研究经理' in text and '交易员' in text and '组合经理' in text
    with pytest.raises(ValueError):evaluate(tmp_path,since='2026-99-01')


def test_corrupt_outcomes_not_overwritten(tmp_path):
    path=tmp_path/'data/evaluation/outcomes.jsonl';path.parent.mkdir(parents=True);path.write_text('{broken')
    with pytest.raises(ValueError):settle(tmp_path,now=stamp('2026-10-03T10:00:00-04:00'),services=FixtureServices(),settings=EvaluationSettings())
    assert path.read_text()=='{broken'


@pytest.mark.parametrize("later_source", ["Alpaca SIP adjustment=all", "yfinance auto_adjust=True"])
def test_split_or_source_switch_window_same_snapshot_keeps_reference(tmp_path, later_source):
    """首次100，后续复权50/50，真实收益为0而非负50%。"""
    write_run(tmp_path, raw('TECH', 'stock'))
    class Adjusted(FixtureServices):
        def __init__(self, split=False):
            super().__init__()
            self.split = split
        def bars(self, symbol, end):
            rows, _ = super().bars(symbol, end)
            level = 50 if self.split else 100
            for row in rows:
                row['open'] = row['close'] = level
            return rows, later_source if self.split else 'Alpaca SIP adjustment=all'
    settle(tmp_path, now=stamp('2026-10-03T10:00:00-04:00'), services=Adjusted(), settings=EvaluationSettings())
    assert rows(tmp_path)[0]['entry']['price'] == 100
    settle(tmp_path, now=stamp('2026-10-09T17:00:00-04:00'), services=Adjusted(split=True), settings=EvaluationSettings())
    record = rows(tmp_path)[0]
    outcome = record['windows']['5']
    assert record['entry']['price'] == 100 and record['entry']['source'] == 'Alpaca SIP adjustment=all'
    assert outcome['status'] == 'settled'
    assert outcome['raw_return'] == outcome['excess_vs_spy'] == outcome['excess_vs_sector'] == outcome['primary_return'] == 0
    for asset in ('asset', 'spy', 'sector'):
        assert outcome['pricing'][asset] == {'entry_price': 50, 'exit_price': 50, 'source': later_source, 'snapshot_through': '2026-10-08'}
    frozen = copy.deepcopy(outcome)
    settle(tmp_path, now=stamp('2026-11-02T17:00:00-05:00'), services=Adjusted(), settings=EvaluationSettings())
    assert rows(tmp_path)[0]['windows']['5'] == frozen

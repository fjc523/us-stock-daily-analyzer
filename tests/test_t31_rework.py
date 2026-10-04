"""第二轮点位、评级边界校准与成功live决策身份回归。"""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from daily_analyzer.evaluation.calibration import calibration,calibration_report,probability
from daily_analyzer.evaluation.price_plans import evaluate_plan,parse_plan,point_report
from daily_analyzer.evaluation.report import analyze,render_report,deduplicate
from daily_analyzer.analyzer import AnalyzerGraph
from tradingagents.agents.rating import PROBABILITY_BANDS,probability_rating
from tradingagents.memory.log import TradingMemoryLog


@pytest.mark.parametrize('p',[0,.3499,.35,.4499,.45,.5499,.55,.6499,.65,1])
def test_calibration_rating_same_boundaries(p):
    result=calibration([(p,True)])
    group=next(group for group in result['bins'] if group['n'])
    assert group['rating']==probability_rating(p)
    assert [(group['low'],group['high']) for group in result['bins']]==[(low,high) for _,low,high in PROBABILITY_BANDS]


def test_ece_known_rating_bins_and_missing_by_layer():
    # Sell:|.1-0|; UW:|.35-.5|; Hold:|.5-1|; Buy:|.65-0|，权重1/5,2/5,1/5,1/5。
    result=calibration([(.1,False),(.35,False),(.35,True),(.5,True),(.65,False)])
    assert result['ece']==pytest.approx(.31)
    assert result['brier']==pytest.approx((.01+.1225+.4225+.25+.4225)/5)
    rows=[{'windows':{'5':{'status':'settled','primary_return':.1}},'probabilities':{'rm':{'5':'未知'},'pm':{'5':.5}}},
          {'windows':{'5':{'status':'settled','primary_return':None}},'probabilities':{'rm':{'5':.6},'pm':{'5':None}}},
          {'windows':{'5':{'status':'pending'}},'probabilities':{'rm':{'5':None},'pm':{'5':.4}}}]
    text=calibration_report(rows)
    assert '成熟缺概率n=1，成熟缺主收益n=1' in text
    assert '概率缺失率=66.7%（全保留记录 2/3）' in text
    assert '概率缺失率=33.3%（全保留记录 1/3）' in text
    assert '[0.35,0.45)' in text
    assert probability('未知') is None


@pytest.mark.parametrize('close,expected',[(90,.1),(110,-.1)])
def test_reduce_terminal_direction_no_long_stop(close,expected):
    plan={**parse_plan('区间99–100美元'),'kind':'减仓','stop_loss':95,'first_target':120}
    out=evaluate_plan(plan,{'2026-10-01':{'open':100,'low':89,'high':111,'close':close}},start='2026-10-01',end='2026-10-01',basis='same_day_open')
    assert out['status']=='settled' and out['direction_adjusted_return']==pytest.approx(expected)
    assert out['mfe_pct']==pytest.approx(.11) and out['mae_pct']==pytest.approx(.11)
    assert out['realized_r'] is None and 'mfe_r' not in out
    text=point_report([{'symbol':'A','ratings':{'pm':'Sell'},'point_plans':{'reduce_plan':{'kind':'减仓','outcome':out}}}])
    assert '减仓独立检验' in text and '不进入上述平均R' in text
    assert '|类型|减仓|1|1|100.0%|' in text


def test_reduce_untriggered_and_immature():
    plan={**parse_plan('区间99–100美元'),'kind':'减仓'}
    bars={'2026-10-01':{'open':105,'low':102,'high':111,'close':110}}
    out=evaluate_plan(plan,bars,start='2026-10-01',end='2026-10-01',basis='same_day_open')
    assert out['status']=='settled' and out['triggered'] is False and out['realized_r'] is None
    assert evaluate_plan(plan,{},start='2026-10-01',end='2026-10-01',basis='same_day_open',mature=False)['status']=='pending'


@pytest.mark.parametrize('close,confirmed',[(110,False),(111,True)])
def test_wait_pullback_and_breakout_separately(close,confirmed):
    plan=parse_plan('不适用：等待回踩至90美元或突破110美元确认')
    assert plan['wait_price']==90 and plan['breakout_price']==110
    out=evaluate_plan(plan,{'2026-10-01':{'open':100,'low':89,'high':112,'close':close}},start='2026-10-01',end='2026-10-01',basis='same_day_open')
    assert out['wait_reached'] is True and out['breakout_confirmed'] is confirmed


def test_c3_c4_d2_share_index_priority(monkeypatch):
    rows=[{'symbol':'SPY','analysis_symbol':'SPY','trade_date':'2026-10-01','asset_type':'etf','finished_at':'2026-10-01T10:00:00-04:00','run_id':'later','ratings':{},'windows':{}},
          {'symbol':'^GSPC','analysis_symbol':'SPY','trade_date':'2026-10-01','asset_type':'index','finished_at':'2026-10-01T09:00:00-04:00','run_id':'earlier','ratings':{},'windows':{}}]
    # 使用既定真实字段type，index优先不引入权重。
    for row in rows:row['type']=row.pop('asset_type')
    captured=[]
    monkeypatch.setattr('daily_analyzer.evaluation.price_plans.point_report',lambda values:captured.append(values) or '点位')
    monkeypatch.setattr('daily_analyzer.evaluation.calibration.calibration_report',lambda values:captured.append(values) or '校准')
    result=analyze(rows)
    render_report(rows,result,datetime.fromisoformat('2026-10-04T10:00:00-04:00'))
    retained,_=deduplicate(rows)
    assert len(retained)==1 and retained[0]['symbol']=='^GSPC'
    assert captured==[retained,retained]


@pytest.mark.parametrize('mode,status,rating,changed',[('live','success','Sell',False),('live','failed','Sell',False),('live','unavailable','Sell',False),('live','success','REVIEW',False),('backfill','success','Sell',False)])
def test_analyzer_defers_memory_until_runner_current_persisted(tmp_path,mode,status,rating,changed):
    graph=object.__new__(AnalyzerGraph);graph.mode=mode;graph.item=SimpleNamespace(symbol='A');graph._log_state=Mock()
    path=tmp_path/'memory.md';graph.memory_log=TradingMemoryLog({'memory_log_path':str(path)})
    graph.memory_log.store_decision('A','2026-10-02','Rating: Buy\n旧决定')
    before=path.read_bytes()
    graph.record_decision('A','2026-10-02',{'final_trade_decision':f'Rating: {rating}\n新决定','status':status})
    assert (path.read_bytes()!=before) is changed
    assert len(graph.memory_log.load_entries())==1


@pytest.mark.parametrize('failure',[None,'save_reports','snapshot','consistency_input','batch_result','current_result'])
def test_actual_runner_late_failure_keeps_previous_memory_current(tmp_path,monkeypatch,failure):
    import daily_analyzer.runner as runner
    from test_runner import _project,_run,_FakeGraph
    monkeypatch.setattr(runner,'_codex_version',lambda _: '离线桩版本')
    monkeypatch.setattr(runner,'_fork_state',lambda _: {'tradingagents_commit':'离线桩','tradingagents_dirty':False})
    root=_project(tmp_path,('NVDA',))
    path=root/'data/tradingagents/memory/trading_memory.md'
    log=TradingMemoryLog({'memory_log_path':str(path)})
    log.store_decision('NVDA','2026-10-02','Rating: Buy\n原current')
    current=root/'data/runs/2026-10-02/current/NVDA.json';current.parent.mkdir(parents=True)
    previous={'symbol':'NVDA','run_id':'old','status':'success','mode':'live','final_rating':'Buy','final_trade_decision':'Rating: Buy\n原current'}
    runner.atomic_write_json(current,previous)
    old_memory=path.read_bytes();old_current=current.read_bytes()
    class Graph(_FakeGraph):
        def propagate(self,*args,**kwargs):
            state,_=super().propagate(*args,**kwargs)
            state['final_trade_decision']='Rating: Sell\n新current'
            graph=object.__new__(AnalyzerGraph);graph._log_state=Mock();graph.mode='live';graph.memory_log=log;graph.item=self.item
            graph.record_decision(self.item.symbol,'2026-10-02',state)
            if failure=='snapshot':self.tool_trace.snapshot=lambda:(_ for _ in ()).throw(OSError('晚期快照失败'))
            return state,'Sell'
        def consistency_snapshot(self,state):
            if failure=='consistency_input':raise OSError('一致性输入快照失败')
            return {'原始输入':'离线fixture'}
        def save_reports(self,*args,**kwargs):
            if failure=='save_reports':raise OSError('晚期报告保存失败')
            return super().save_reports(*args,**kwargs)
    real_write=runner.atomic_write_json
    def write(target,payload):
        if ((failure=='batch_result' and '/batches/' in str(target) and str(target).endswith('/results/NVDA.json')) or
                (failure=='current_result' and str(target).endswith('/current/NVDA.json'))) and payload.get('status')=='success':
            raise OSError('晚期批次结果保存失败')
        return real_write(target,payload)
    monkeypatch.setattr(runner,'atomic_write_json',write)
    _run(root,clock=lambda:datetime.fromisoformat('2026-10-02T10:15:00-04:00'),force=True,analyzer_factory=Graph)
    if failure:
        assert path.read_bytes()==old_memory and current.read_bytes()==old_current
        import json
        assert 'consistency_input' not in json.loads(current.read_text())
        for result_path in (root/'data/runs/2026-10-02/batches').glob('*/results/NVDA.json'):
            assert 'consistency_input' not in json.loads(result_path.read_text())
    else:
        import json,hashlib
        result=json.loads(current.read_text());entry=log.load_entries()[0]
        assert result['status']=='success' and entry['rating']==result['final_rating']=='Sell'
        assert hashlib.sha256(entry['decision'].encode()).hexdigest()==hashlib.sha256(result['final_trade_decision'].encode()).hexdigest()
    assert len(log.load_entries())==1

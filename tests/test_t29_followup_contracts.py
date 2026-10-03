"""T29旧反思口径、映射三态与独立开关/方向标记回归。"""
from types import SimpleNamespace
from unittest.mock import Mock
from datetime import datetime
import pytest
from tradingagents.agents.managers.portfolio_manager import create_portfolio_manager
from tradingagents.agents.rating import direction_flags
from tradingagents.graph.propagation import Propagator


@pytest.mark.parametrize('b3,d1',[(False,False),(False,True),(True,False),(True,True)])
def test_pm_switches_independent(b3,d1):
    llm=Mock();llm.with_structured_output.side_effect=NotImplementedError;llm.invoke.return_value=SimpleNamespace(content='**Rating**: Hold')
    state=Propagator().create_initial_state('COHR','2026-10-02');state.update(investment_plan='研究',trader_investment_plan='交易')
    create_portfolio_manager(llm,dict(risk_layer_direction_lock=b3,rating_timing_decoupled=d1))(state)
    prompt=llm.invoke.call_args[0][0]
    assert ('默认沿用研究经理recommendation' in prompt)==b3
    assert ('direction_change必填' in prompt)==b3
    assert ('Buy/Overweight没有合格入场点时保持评级' in prompt)==d1
    schema=llm.with_structured_output.call_args[0][0]
    assert ('direction_change' in schema.model_fields)==b3
    assert 'stop_loss' in schema.model_fields and 'prob_outperform_20d' in schema.model_fields
    if d1:assert '5–20' in schema.model_fields['time_horizon'].description


@pytest.mark.parametrize('current,change,flag',[('Hold','否',False),('Buy','否',True),('Buy',None,True),('Buy','是：新增事实',False)])
def test_direction_comparison_explicit(current,change,flag):
    state={'investment_plan':'**Recommendation**: Hold'}
    for layer,label in [('trader','action'),('pm','rating')]:
        assert direction_flags(state,{label:current,'direction_change':change},layer=layer)['direction_change_mismatch'] is flag
    assert direction_flags({},None,layer='pm')=={}


@pytest.mark.parametrize('symbol,kind,broad',[('SPY','etf',['SPY']),('^GSPC','index',[]),('QQQ','etf',['QQQ']),('CUSTOM','etf',['CUSTOM'])])
def test_absolute_reflection_and_unchanged_tag(monkeypatch,symbol,kind,broad,tmp_path):
    from tradingagents.memory import settlement
    from tradingagents.memory.log import TradingMemoryLog
    from tradingagents.memory.reflection import Reflector
    log=TradingMemoryLog({'memory_log_path':str(tmp_path/'memory.md')})
    decision='**Rating**: Hold\n原决策正文';log.store_decision(symbol,'2026-10-01',decision,rating='Hold')
    monkeypatch.setattr(settlement,'fetch_returns',lambda *a,**k:(.08,0.,5,'2026-10-08'))
    llm=Mock();llm.invoke.return_value=SimpleNamespace(content='固定反思')
    settlement.settle_pending(symbol,log,Reflector(llm),{'asset_type':kind,'broad_market_etfs':broad})
    messages=llm.invoke.call_args[0][0];text=str(messages)
    assert '绝对收益: +8.0%' in text and 'Alpha vs SPY: +0.0%' not in text and '5-day alpha' not in text
    entry=log.load_entries()[0]
    assert entry['decision']==decision and entry['alpha']=='+8.0%' and entry['raw']=='+8.0%'


def test_sector_failed_retry_and_success_freeze(tmp_path):
    from test_evaluation import raw,write_run,FixtureServices,rows
    from daily_analyzer.evaluation.settlement import _settle
    from daily_analyzer.config import EvaluationSettings
    class Services(FixtureServices):
        def __init__(self):super().__init__();self.lookup_calls=0
        def sector_lookup(self,symbol):
            self.lookup_calls+=1
            return {'status':'failed','benchmark':None} if self.lookup_calls==1 else {'status':'mapped','benchmark':'XLK'}
    record=raw(symbol='INTC',kind='stock');write_run(tmp_path,record)
    (tmp_path/'data/evaluation').mkdir(parents=True);services=Services()
    now=datetime.fromisoformat('2026-10-02T20:00:00-04:00')
    _settle(tmp_path,EvaluationSettings(),{},services,now)
    assert rows(tmp_path)[0]['sector_lookup']=='failed' and services.lookup_calls==1
    _settle(tmp_path,EvaluationSettings(),{},services,now)
    assert rows(tmp_path)[0]['sector_benchmark']=='XLK' and services.lookup_calls==2
    _settle(tmp_path,EvaluationSettings(),{},services,now)
    assert services.lookup_calls==2


def test_observed_http_method_keyword_passthrough():
    from tradingagents.dataflows.vendor_observer import observed_call,set_vendor_observer,reset_vendor_observer
    assert observed_call('yahoo_request','yfinance',lambda **kwargs:kwargs['method'],method='GET')=='GET'
    seen=[];token=set_vendor_observer(seen.append)
    try:
        assert observed_call('yahoo_request','yfinance',lambda **kwargs:kwargs['method'],method='GET')=='GET'
        assert seen[0]['method']=='yahoo_request' and seen[0]['outcome']=='success'
    finally:reset_vendor_observer(token)

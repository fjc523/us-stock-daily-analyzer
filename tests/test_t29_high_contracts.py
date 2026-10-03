"""T29高优先级返工：结构化容错、实际生成顺序与资产主口径。"""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from datetime import datetime,timezone

import pytest
from tradingagents.agents.schemas import (LegacyResearchPlan,ResearchPlan,CruxResearchPlan,EvidenceResearchPlan,TraderProposal,PortfolioDecision)
from tradingagents.agents.rating import output_flags
from tradingagents.agents.managers.research_manager import create_research_manager
from tradingagents.agents.trader.trader import create_trader
from tradingagents.agents.managers.portfolio_manager import create_portfolio_manager


@pytest.mark.parametrize('text,result',[('否','否'),('否。','否'),('否，沿用研究经理Overweight','否'),('是：新增事实','是：新增事实'),('是:新增事实','是：新增事实'),('是，新增数据Y','是：新增数据Y')])
def test_direction_normalization(text,result):
    assert TraderProposal(action='Hold',reasoning='理由',direction_change=text).direction_change==result
    assert PortfolioDecision(rating='Hold',executive_summary='摘要',investment_thesis='论点',direction_change=text).direction_change==result
    with pytest.raises(ValueError):TraderProposal(action='Hold',reasoning='理由',direction_change='是')


def test_generated_research_schema_evidence_first():
    assert list(ResearchPlan.model_json_schema()['properties'])[:2]==['cruxes','evidence_check']
    assert list(CruxResearchPlan.model_json_schema()['properties'])[:2]==['cruxes','recommendation']
    assert list(EvidenceResearchPlan.model_json_schema()['properties'])[:2]==['evidence_check','recommendation']
    assert 'evidence_check' not in CruxResearchPlan.model_fields and 'cruxes' not in EvidenceResearchPlan.model_fields


@pytest.mark.parametrize('count',[2,6])
def test_research_limits_are_soft_in_actual_node(count):
    evidence='证'*201;cruxes=[dict(bull_claim='多',bear_claim='空',evidence='事实',winner='未决',reason='理由')]*count
    llm=Mock();llm.with_structured_output.return_value=SimpleNamespace(invoke=lambda _:ResearchPlan(recommendation='Hold',rationale='论点',strategic_actions='行动',evidence_check=evidence,cruxes=cruxes))
    result=create_research_manager(llm,{})(dict(company_of_interest='SMTC',investment_debate_state=dict(history='历史',count=4)))
    assert result['structured_research_plan']['evidence_check']==evidence
    assert result['decision_flags']['rm']['evidence_check_overlength'] is True
    assert result['decision_flags']['rm']['cruxes_count']==count
    assert evidence in result['investment_plan']
    llm.invoke.assert_not_called()


def test_seven_symbols_structured_direction_no_fallback():
    from tradingagents.graph.propagation import Propagator
    for symbol in ['COHR','INTC','NVDA','SMTC','SPY','QQQ','TSLA']:
        state=Propagator().create_initial_state(symbol,'2026-10-02');state.update(investment_plan='研究',market_report='',trader_investment_plan='交易')
        for factory,schema,payload,key in [(create_trader,TraderProposal,dict(action='Hold',reasoning='理由',direction_change='否，沿用研究经理'),'structured_trader_proposal'),(create_portfolio_manager,PortfolioDecision,dict(rating='Hold',executive_summary='摘要',investment_thesis='论点',direction_change='是:新增事实'),'structured_pm_decision')]:
            llm=Mock();llm.with_structured_output.return_value=SimpleNamespace(invoke=lambda _,schema=schema,payload=payload:schema(**payload))
            result=factory(llm,{})(state)
            assert result[key] is not None
            llm.invoke.assert_not_called()


@pytest.mark.parametrize('symbol,kind,broad,label',[('SPY','etf',['SPY','QQQ'],'绝对收益'),('QQQ','etf',['SPY','QQQ'],'绝对收益'),('^GSPC','index',[],'绝对收益'),('COHR','stock',[],'相对 SPY 超额'),('XLK','etf',[],'相对 SPY 超额'),('CUSTOM','etf',['CUSTOM'],'绝对收益')])
def test_actual_framework_primary_metric(monkeypatch,tmp_path,symbol,kind,broad,label):
    from daily_analyzer.analyzer import AnalyzerGraph,TradingAgentsGraph
    def init(self,**kwargs):self.propagator=SimpleNamespace(get_graph_args=lambda **kwargs:{})
    monkeypatch.setattr(TradingAgentsGraph,'__init__',init)
    item=SimpleNamespace(type=kind,symbol=symbol,analysis_symbol='SPY' if kind=='index' else symbol,analysts=[])
    config=dict(context_compaction=False,broad_market_etfs=broad,rating_timing_decoupled=True)
    graph=AnalyzerGraph(item=item,mode='backfill',state_log_dir=tmp_path,context_blocks={},context_as_of=datetime.now(timezone.utc),config=config)
    assert label in graph.injected_context
    config['rating_timing_decoupled']=False
    old=AnalyzerGraph(item=item,mode='backfill',state_log_dir=tmp_path,context_blocks={},context_as_of=datetime.now(timezone.utc),config=config)
    assert '评级主口径：' not in old.injected_context


def test_multiline_direction_actual_nodes_no_fallback():
    from tradingagents.graph.propagation import Propagator
    state=Propagator().create_initial_state('COHR','2026-10-02');state.update(investment_plan='**Recommendation**: Hold',market_report='',trader_investment_plan='交易')
    for factory,schema,payload,key in [(create_trader,TraderProposal,dict(action='Buy',reasoning='理由',direction_change='是：新增数据Y\n来源：基本面报告'),'structured_trader_proposal'),(create_portfolio_manager,PortfolioDecision,dict(rating='Buy',executive_summary='摘要',investment_thesis='论点',direction_change='是：新增数据Y\n来源：基本面报告'),'structured_pm_decision')]:
        llm=Mock();llm.with_structured_output.return_value=SimpleNamespace(invoke=lambda _,schema=schema,payload=payload:schema(**payload))
        result=factory(llm,{})(state)
        assert result[key]['direction_change']=='是：新增数据Y\n来源：基本面报告'
        llm.invoke.assert_not_called()


def test_legacy_research_schema_unchanged_before_fix():
    import hashlib
    digest=hashlib.sha256(json.dumps(LegacyResearchPlan.model_json_schema(),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    assert digest=='df6a1c4b593d19d35d2106cd469076bdbc73a9ab5b226d2fa93a71e9fe713cc4'

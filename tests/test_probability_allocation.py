"""用户确认的概率/配置边界、校准手算及首页兼容。"""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tradingagents.agents.rating import probability_rating,output_flags
from tradingagents.agents.schemas import ResearchPlan,PortfolioDecision,decision_schema,render_research_plan,render_pm_decision
from tradingagents.agents.managers.research_manager import create_research_manager
from daily_analyzer.evaluation.calibration import calibration,calibration_report
from daily_analyzer.site import _marks
from daily_analyzer.config import TradingAgentsSettings


@pytest.mark.parametrize('probability,rating',[(0,'Sell'),(.3499,'Sell'),(.35,'Underweight'),(.4499,'Underweight'),(.45,'Hold'),(.5499,'Hold'),(.55,'Overweight'),(.6499,'Overweight'),(.65,'Buy'),(1,'Buy')])
def test_probability_boundaries(probability,rating):
    assert probability_rating(probability)==rating
    assert output_flags({'rating':rating,'prob_outperform_20d':probability},{'allocation_bands':None},layer='pm')['rating_prob_mismatch'] is False
    assert output_flags({'rating':'Hold' if rating!='Hold' else 'Sell','prob_outperform_20d':probability},{'allocation_bands':None},layer='pm')['rating_prob_mismatch'] is True


def test_manual_brier_ece():
    result=calibration([(.1,False),(.4,False),(.6,True),(.9,True)])
    assert result['brier']==pytest.approx(.085)
    assert result['ece']==pytest.approx(.25)
    assert result['base_rate']==.5 and result['baseline_brier']==.25
    assert calibration([])['brier'] is None
    text=calibration_report([{'windows':{'5':{'status':'pending','primary_return':1}},'probabilities':{'pm':{'5':.9}}}])
    assert '不可计算' in text and '样本不足' in text


def test_optional_probability_parse_render_and_disabled():
    model=ResearchPlan(recommendation='Overweight',rationale='论点',strategic_actions='行动',prob_outperform_5d='.57',prob_outperform_20d='.6',expected_return_20d_range='−2% ~ +5%')
    assert model.prob_outperform_20d==.6 and 'Prob Outperform 20d' in render_research_plan(model)
    with pytest.raises(ValueError):
        ResearchPlan(recommendation='Buy',rationale='论点',strategic_actions='行动',prob_outperform_20d=1.01)
    closed=decision_schema(ResearchPlan,{'rating_probability_fields':False},'rm')
    assert 'prob_outperform_20d' not in closed.model_fields
    old=closed(recommendation='Hold',rationale='论点',strategic_actions='行动')
    assert 'Prob Outperform' not in render_research_plan(old)


def test_schema_model_dump_persisted_in_actual_research_node():
    model=ResearchPlan(recommendation='Overweight',rationale='论点',strategic_actions='行动',prob_outperform_20d=.7,target_allocation_pct=60)
    structured=SimpleNamespace(invoke=lambda _:model)
    llm=Mock();llm.with_structured_output.return_value=structured
    state={'company_of_interest':'SMTC','investment_debate_state':{'history':'辩论','count':4}}
    result=create_research_manager(llm,{'lesson_min_settled_same_ticker':0,'cross_ticker_lessons':'text'})(state)
    assert result['structured_research_plan']==model.model_dump(mode='json')
    assert result['decision_flags']['rm']['rating_prob_mismatch'] is True
    assert model.recommendation.value=='Overweight' and model.target_allocation_pct==60


def test_probability_unknown_description_preserved():
    model=ResearchPlan(recommendation='Hold',rationale='论点',strategic_actions='行动',prob_outperform_20d='未知：缺少可核验样本')
    assert model.prob_outperform_20d=='未知：缺少可核验样本'
    from daily_analyzer.evaluation.calibration import probability as parse_probability
    assert parse_probability(model.prob_outperform_20d) is None

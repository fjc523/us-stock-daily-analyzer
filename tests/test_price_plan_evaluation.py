"""真实文本解析与日线点位执行约定。"""
import pytest
from daily_analyzer.evaluation.price_plans import parse_plan,evaluate_plan,extract_plans
from tradingagents.agents.schemas import PortfolioDecision,LegacyPortfolioDecision,decision_schema,render_pm_decision


def plan(short=False):
    return {'parse_status':'parsed','kind':'减仓' if short else '建仓','low':99.,'high':100.,'stop_loss':105. if short else 95.,'first_target':90. if short else 110.}


def check(bars,**kwargs):
    return evaluate_plan(kwargs.pop('plan',plan()),bars,start='2026-10-01',end='2026-10-01',basis='same_day_open',**kwargs)


def test_parser():
    assert parse_plan('区间 99–100 美元（依据：均线）')['high']==100
    assert parse_plan('不适用：等待回踩至 90 美元')['wait_price']==90
    assert parse_plan('看情况')['parse_status']=='unparsed'
    result={'final_trade_decision':'**建仓点位**: 区间 99–100 美元（依据：均线）\n\n**加仓点位**: 不适用：原因\n\n**减仓点位**: 不适用：原因\n\n**Stop Loss**: 95'}
    assert extract_plans(result)['entry_plan']['stop_loss']==95


@pytest.mark.parametrize('bar,reason,value',[
    ({'open':100,'low':98,'high':111,'close':108},'第一目标',2),
    ({'open':100,'low':94,'high':111,'close':108},'同日双触（保守止损）',-1),
    ({'open':94,'low':93,'high':101,'close':98},None,None),
    ({'open':100,'low':98,'high':107,'close':102},'有效期末',.4)])
def test_long_paths(bar,reason,value):
    result=check({'2026-10-01':bar})
    if reason is None:
        assert result['status']=='indeterminate' and '风险分母' in result['reason']
    else:
        assert result['exit_reason']==reason and result['realized_r']==pytest.approx(value)


def test_untriggered_pending_close_and_short():
    bars={'2026-10-01':{'open':105,'low':102,'high':108,'close':104}}
    assert check(bars)['triggered'] is False
    assert check(bars,mature=False)['status']=='pending'
    assert evaluate_plan(plan(),bars,start='2026-10-01',end='2026-10-01',basis='same_day_close')['status']=='indeterminate'
    short=check({'2026-10-01':{'open':100,'low':89,'high':102,'close':90}},plan=plan(True))
    assert short['exit_reason']=='减仓有效期末' and short['realized_r'] is None
    assert short['direction_adjusted_return']==pytest.approx(.1)


def test_gap_after_entry_and_unit_guard():
    bars={'2026-10-01':{'open':100,'low':99,'high':103,'close':102},'2026-10-02':{'open':93,'low':90,'high':94,'close':92}}
    result=evaluate_plan(plan(),bars,start='2026-10-01',end='2026-10-02',basis='same_day_open')
    assert result['exit_price']==93 and result['exit_reason']=='跳空止损'
    assert check(bars,units_verified=False)['status']=='indeterminate'


def test_optional_schema_and_closed_class():
    extended=decision_schema(PortfolioDecision,{},'pm')
    model=extended(rating='Hold',executive_summary='摘要',investment_thesis='论点',direction_change='否',stop_loss='N/A',first_target='110')
    assert model.stop_loss is None and model.first_target==110
    assert '**First Target**: 110.0' in render_pm_decision(model)
    closed=decision_schema(PortfolioDecision,{'price_plan_evaluation_enabled':False},'pm')
    assert 'first_target' not in closed.model_fields and 'prob_outperform_20d' in closed.model_fields
    all_closed=decision_schema(PortfolioDecision,{'price_plan_evaluation_enabled':False,'rating_probability_fields':False},'pm')
    assert 'first_target' not in all_closed.model_fields and 'prob_outperform_20d' not in all_closed.model_fields
    old=LegacyPortfolioDecision(rating='Hold',executive_summary='摘要',investment_thesis='论点')
    assert 'First Target' not in render_pm_decision(old)


@pytest.mark.parametrize('text,price',[
 ('不适用：等待回踩2026-10-01 P_Open 290.00美元，核验报价',290),
 ('不适用：等待回踩至90美元',90),
 ('不适用：等待突破90美元',None),
 ('不适用：等待回踩90–100美元',None),
 ('不适用：等待回踩90美元或100美元',None),
 ('不适用：等待2026-10-01',None)])
def test_wait_price_date_and_ambiguity(text,price):
    assert parse_plan(text)['wait_price']==price


def test_point_report_independent_metric_denominators():
    from daily_analyzer.evaluation.price_plans import point_report
    bars={'2026-10-01':{'open':100,'low':99,'high':101,'close':100}}
    missing={**plan(),'stop_loss':None,'first_target':None}
    yes=check(bars,plan=missing)
    no=check({'2026-10-01':{'open':105,'low':102,'high':108,'close':104}},plan=missing)
    assert yes['triggered'] is True and yes['status']=='indeterminate'
    assert no['triggered'] is False and no['status']=='settled'
    rows=[{'symbol':'COHR','ratings':{'pm':'Hold'},'point_plans':{'entry_plan':{'kind':'建仓','outcome':out}}} for out in [yes,no]]
    text=point_report(rows)
    assert '|类型|建仓|2|0|1|50.0%|不可计算|不可计算|不可计算|不可计算|不可计算|' in text


def test_analysis_validity_frozen_against_current_settings(tmp_path):
    from datetime import datetime
    from daily_analyzer.evaluation.settlement import _settle,load_outcomes,point_validity
    from daily_analyzer.config import EvaluationSettings
    from test_evaluation import raw,write_run,FixtureServices
    record=raw();record['decision_plan_validity_trading_days']=10
    record['final_trade_decision']='**建仓点位**: 区间99–100美元'
    write_run(tmp_path,record)
    (tmp_path/'data/evaluation').mkdir(parents=True)
    _settle(tmp_path,EvaluationSettings(),{},FixtureServices(),datetime.fromisoformat('2026-10-09T20:00:00-04:00'),validity=5)
    row=load_outcomes(tmp_path/'data/evaluation/outcomes.jsonl')[0]
    assert row['point_validity']=={'days':10,'source':'analysis_result_explicit'}
    assert row['point_plans']['entry_plan']['outcome']['status']=='pending'
    end=row['point_plans']['entry_plan']['outcome']['end']
    _settle(tmp_path,EvaluationSettings(),{},FixtureServices(),datetime.fromisoformat('2026-10-12T20:00:00-04:00'),validity=20)
    row=load_outcomes(tmp_path/'data/evaluation/outcomes.jsonl')[0]
    assert row['point_validity']['days']==10 and row['point_plans']['entry_plan']['outcome']['end']==end
    assert point_validity({'injected_context':'点位方案有效期：分析当日起10个交易日。'})['days']==10
    assert point_validity({})['source']=='legacy_default_5_unverified'


def test_full_current_cohr_trader_wait_price():
    # 固定2026-10-02/current COHR交易员完整点位正文；不依赖ignored历史文件。
    assert parse_plan('不适用：原方案止损不足1倍ATR且首目标盈亏比不足1.5。COHR等待回踩2026-10-01 P_Open 290.00美元，核验常规报价及连续两根30分钟K线止跌后复评；重新设置支撑外止损，满足1–2.5倍ATR及最近上方阻力盈亏比≥1.5才考虑建仓。跌破同日P_Low 286.4166则支撑观察失效；2026-10-08到期。')['wait_price']==290
    assert parse_plan('不适用：COHR当前无通过ATR和盈亏比检验的加仓区间。已有仓位等待回踩2026-10-01 P_Open 290.00美元并确认止跌，至少隔一交易日复评；核验常规报价、支撑外止损及最近上方阻力，满足1–2.5倍ATR和盈亏比≥1.5后才考虑加仓。跌破同日P_Low 286.4166则观察失效；2026-10-08到期。')['wait_price']==290

"""方案归因与角色回退证据离线契约。"""
from copy import deepcopy
import pytest
from daily_analyzer.config import TradingAgentsSettings
from daily_analyzer.model_scheme import result_scheme, record_scheme, overrides_fingerprint
from daily_analyzer.model_usage import role_execution_evidence, apply_execution_labels, mixed_usage
from daily_analyzer.site import _marks
from daily_analyzer.evaluation.report import scheme_report

def base(effort='xhigh'):
    return {'llm':{'deep':{'model':'sol','reasoning_effort':effort},'quick':{'model':'sol','reasoning_effort':'medium'}}}

def test_five_groups_and_stable_custom():
    configs=[{}, {'role_llm_scheme':'B'}, {'role_llm_scheme':'B'}, {'role_llm_overrides':{'trader':{'provider':'codex_exec','model':'sol','effort':'high'}}},{}]
    rows=[]
    for index,config in enumerate(configs):
        result=base('high' if index==4 else 'xhigh')
        if index==2:result['llm']['roles']={'research_manager':{'fallback':{'category':'quota'}}}
        label=result_scheme(result,config)
        rows.append({'llm':label,'trade_date':'2026-10-01'})
    assert len({(row['llm']['scheme'],row['llm']['model_fingerprint']) for row in rows})==5
    assert rows[2]['llm']['scheme']=='B+fallback' and rows[3]['llm']['scheme'].startswith('custom:')
    text=scheme_report(rows)
    assert text.count('|n=1；样本不足')==5 and 'default（推断' not in text
    assert overrides_fingerprint({'a':1,'b':2})==overrides_fingerprint({'b':2,'a':1})

def test_old_result_inference_and_record_unwritten():
    result=base();result['llm']['roles']={role:{'configured':{'provider':'claude_exec','model':'claude-opus-5-5','effort':'high'}} for role in ('research_manager','trader','portfolio_manager')}
    before=deepcopy(result)
    assert result_scheme(result)['scheme']=='B' and result_scheme(result)['source']=='inferred_from_result'
    assert result==before
    row={'trade_date':'2026-10-01'}
    assert record_scheme(row)['source']=='inferred_unwritten' and row=={'trade_date':'2026-10-01'}
    assert 'default（推断，未写入）' in scheme_report([row])

def test_fallback_evidence_flags_ui_and_counts():
    event={'ticker':'MOCK','role':'research_manager','provider':'claude_exec','result':'fallback','category':'quota','from':'claude_exec/claude-opus-5-5','to':'codex_exec/sol/xhigh','breaker':{'open':True}}
    result=base();result['llm']['roles']=role_execution_evidence({'research_manager':{'provider':'claude_exec'}},[event],'MOCK')
    apply_execution_labels(result,{'role_llm_scheme':'B'})
    assert result['llm']['roles']['research_manager']['status']=='FALLBACK'
    assert result['decision_flags']['rm']['llm_fallback']=='quota'
    assert '第二模型回退（研究经理）' in _marks(result)
    usage=mixed_usage([event])
    assert usage['fallback_count']==1 and usage['calls']==0

@pytest.mark.parametrize('field,value',[('claude_timeout',59),('claude_timeout',601),('claude_retries',-1),('claude_retries',3)])
def test_budget_rejects_outside_boundary(field,value):
    with pytest.raises(ValueError):TradingAgentsSettings(**{field:value})

@pytest.mark.parametrize('timeout,retries',[(60,0),(300,1),(600,2)])
def test_budget_valid_boundaries(timeout,retries):
    value=TradingAgentsSettings(claude_timeout=timeout,claude_retries=retries)
    assert value.claude_timeout==timeout and value.claude_retries==retries and value.role_llm_fallback

def test_consistency_budget_guard_and_disabled_override(tmp_path,monkeypatch):
    import daily_analyzer.evaluation.consistency as consistency
    snapshot={'config':{'role_llm_fallback':True,'claude_retries':2}}
    value=consistency.isolated_config(snapshot,tmp_path)
    assert value['role_llm_fallback'] is False and value['claude_retries']==0
    monkeypatch.setitem(consistency.CLAUDE_TEST_BUDGET,'role_llm_fallback',True)
    with pytest.raises(ValueError,match='关闭'):consistency.isolated_config(snapshot,tmp_path)

def test_report_each_actual_mature_denominator_warns_not_record_count():
    rows=[]
    for index in range(30):
        rows.append({'llm':result_scheme(base(),{'role_llm_scheme':'B'}),
            'trade_date':'2026-10-01','ratings':{'rm':'Buy','pm':'Buy'},
            'anchors':{'P_Close':100,'atr':1},
            'probabilities':{'rm':{'5':.7},'pm':{'5':.7}},
            'windows':{'5':{'status':'settled' if index==0 else 'pending','primary_return':.1}}})
    text=scheme_report(rows)
    assert '|n=30|' in text
    assert '命中100.00%(n=1；样本不足，仅供参考)' in text
    assert '收益10.00%(n=1；样本不足，仅供参考)' in text
    assert '0.0900(n=1；样本不足，仅供参考)' in text

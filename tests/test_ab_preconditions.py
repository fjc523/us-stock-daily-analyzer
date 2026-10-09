"""F2-P1分类同源trace与机械满足性，不读取投研预期标签。"""
import pytest
from daily_analyzer.evaluation.ab_ledger import preconditions,precondition_trace

@pytest.mark.parametrize('text,low,high',[
 ('核实实际配置达到或超过133%',132.99,133),
 ('实际配置超过目标123%至少10个百分点',132.99,133),
 ('实际配置较125%目标高出至少10个百分点',134.99,135),
 ('核对实际配置高于122%且偏离至少10个百分点',131.99,132),
 ('超配≥10个百分点且仍有未处理差额',134.99,135),
 ('仅现配置高于标准量80%时执行',80,80.01),
])
def test_P2_threshold_and_cross_clause_reference(text,low,high):
    assert precondition_trace(text)['overall']=='可判'
    assert preconditions(text,allocation=low,target=125,age=0)[0] is False
    assert preconditions(text,allocation=high,target=125,age=0)[0] is True

@pytest.mark.parametrize('text',['自2026-10-06起5交易日有效，届满更新','确认和成交均限分析日起5交易日；到期复评并更新保护方案'])
def test_P4_age_five_six_does_not_renew(text):
    assert preconditions(text,allocation=100,target=100,age=5)[0]
    assert not preconditions(text,allocation=100,target=100,age=6)[0]
    assert precondition_trace(text,age=6)['overall']=='可判'

@pytest.mark.parametrize('text',['核实持仓和现金','核实实际配置','仅常规收盘','仅减超额','与区间腿互斥','立即腿未执行、现配≥85%','仅实际持有SMTC','有效5交易日，CPI后重算','核实真实持仓与标准量及报价','偏离至少10个百分点','仍有未处理差额'])
def test_unknown_clause_is_OUT_not_keyword_match(text):
    assert precondition_trace(text,allocation=1000)['overall']=='受限不执行'
    assert not preconditions(text,allocation=1000,target=0,age=0)[0]


def test_trace_unicode_spans_and_empty():
    text='  核实真实持仓与标准量；实际配置≥135%，仅常规时段。'
    result=precondition_trace(text,allocation=135,target=125,age=5)
    assert [c['whitelist_class'] for c in result['clauses']]==['P1','P2','P3']
    assert all(text[c['start']:c['end']]==c['text'] for c in result['clauses'])
    assert precondition_trace('')=={'overall':'可判','clauses':[]}
    assert preconditions('',allocation=0,target=0,age=6)==(True,[])


@pytest.mark.parametrize('text',['分析日起3个交易日有效','有效3交易日','分析日起3交易日有效，届满更新'])
def test_P4_existing_N_is_preserved(text):
    assert preconditions(text,allocation=100,target=100,age=3)[0]
    assert not preconditions(text,allocation=100,target=100,age=4)[0]
    assert precondition_trace(text,age=4)['overall']=='可判'

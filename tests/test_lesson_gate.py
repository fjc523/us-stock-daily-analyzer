"""历史事实门槛、跨标模式及C2可见主收益。"""
import json
from tradingagents.memory.log import TradingMemoryLog


def log_with_entries(tmp_path, *, n=2, minimum=10, cross='stats'):
    log=TradingMemoryLog({'memory_log_path':str(tmp_path/'memory.md'),'lesson_min_settled_same_ticker':minimum,'cross_ticker_lessons':cross})
    for index in range(n):
        day=f'2026-09-{index+1:02d}'
        log.store_decision('SMTC',day,'Rating: Buy\n固定决策')
        log.update_with_outcome('SMTC',day,.02,.01,5,'REFLECTION_SECRET',resolution_date='2026-09-30')
    log.store_decision('INTC','2026-08-01','Rating: Sell')
    log.update_with_outcome('INTC','2026-08-01',-.02,-.01,5,'CROSS_SECRET',resolution_date='2026-09-30')
    return log


def test_lessons_use_full_count_before_display_cap(tmp_path):
    log=log_with_entries(tmp_path,n=10,minimum=10)
    text=log.get_past_context('SMTC',n_same=1,as_of='2026-10-02')
    assert '样本 10 条' in text and 'REFLECTION_SECRET' in text and '方向命中率' in text
    log._lesson_min=11
    text=log.get_past_context('SMTC',as_of='2026-10-02')
    assert '不足以形成规律' in text and 'REFLECTION_SECRET' not in text and 'CROSS_SECRET' not in text


def test_cross_modes_and_point_in_time(tmp_path):
    log=log_with_entries(tmp_path,cross='off')
    assert 'INTC' not in log.get_past_context('SMTC')
    log._cross_lessons='stats'
    assert 'CROSS_SECRET' not in log.get_past_context('SMTC') and '|Sell|' in log.get_past_context('SMTC')
    log._cross_lessons='text'
    assert 'CROSS_SECRET' in log.get_past_context('SMTC') and 'REFLECTION_SECRET' not in log.get_past_context('SMTC')
    assert log.get_past_context('SMTC',as_of='2026-09-01')==''


def test_c2_uses_asset_primary_not_legacy_alpha(tmp_path):
    log=log_with_entries(tmp_path)
    path=tmp_path/'outcomes.jsonl';log._outcomes_path=str(path)
    path.write_text(json.dumps({'is_current':True,'trade_date':'2026-09-01','symbol':'SMTC','ratings':{'pm':'Buy'},'primary_metric':'excess_vs_spy',
                               'windows':{'5':{'status':'settled','primary_return':.03,'settled_at':'2026-09-30T17:00:00-04:00'},'20':{'status':'pending','primary_return':.9}}})+'\n')
    text=log.get_past_context('SMTC',as_of='2026-10-02')
    assert '+3.00%' in text and 'C2 excess_vs_spy' in text and '+90.00%' not in text


def test_legacy_text_is_exact(tmp_path):
    log=log_with_entries(tmp_path,minimum=0,cross='text')
    entries=log.load_entries();same=[e for e in reversed(entries) if e['ticker']=='SMTC'];cross=[e for e in reversed(entries) if e['ticker']!='SMTC']
    expected='\n\n'.join(['Past analyses of SMTC (most recent first):',*[log._format_full(e) for e in same],'Recent cross-ticker lessons:',*[log._format_reflection_only(e) for e in cross]])
    assert log.get_past_context('SMTC')==expected


def test_c2_repeated_same_day_does_not_reuse_wrong_reflection(tmp_path):
    import hashlib
    log=log_with_entries(tmp_path,minimum=1)
    path=tmp_path/'outcomes.jsonl';log._outcomes_path=str(path)
    row={'is_current':True,'trade_date':'2026-09-01','symbol':'SMTC','ratings':{'pm':'Sell'},'primary_metric':'excess_vs_spy','decision_fingerprint':hashlib.sha256('Rating: Sell\n另次决策'.encode()).hexdigest(),
         'windows':{'5':{'status':'settled','primary_return':-.03,'settled_at':'2026-09-30T17:00:00-04:00'}}}
    path.write_text(json.dumps(row)+'\n')
    text=log.get_past_context('SMTC',as_of='2026-10-02')
    assert '[2026-09-01 | SMTC]\nREFLECTION:' not in text and '反思关联不可得' in text
    row['decision_fingerprint']=hashlib.sha256('Rating: Buy\n固定决策'.encode()).hexdigest()
    path.write_text(json.dumps(row)+'\n')
    assert '[2026-09-01 | SMTC]\nREFLECTION:' in log.get_past_context('SMTC',as_of='2026-10-02')


def test_cross_text_keeps_original_memory_identity(tmp_path):
    log=log_with_entries(tmp_path,minimum=1,cross='text')
    path=tmp_path/'outcomes.jsonl';log._outcomes_path=str(path)
    path.write_text(json.dumps({'is_current':True,'trade_date':'2026-08-01','symbol':'INTC','ratings':{'pm':'Buy'},'primary_metric':'excess_vs_spy','decision_fingerprint':'wrong',
                               'windows':{'5':{'status':'settled','primary_return':.5,'settled_at':'2026-09-30T17:00:00-04:00'}}})+'\n')
    text=log.get_past_context('SMTC',as_of='2026-10-02')
    assert '[2026-08-01 | INTC | Sell | -2.0%]' in text and 'CROSS_SECRET' in text
    assert '[2026-08-01 | INTC | Buy' not in text

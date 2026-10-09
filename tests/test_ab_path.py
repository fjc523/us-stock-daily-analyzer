"""T49 单次隔离入口、相对日历与结果适配的零模型夹具。"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from zoneinfo import ZoneInfo

import pytest

from daily_analyzer.evaluation.ab_path import calendar_after, adapt_result, fork_history
from daily_analyzer.evaluation.consistency import run_consistency, input_hash
from test_consistency import fixture_snapshot, final_state


def saved(tmp_path):
    path = tmp_path/'data/runs/2026-10-02/batches/test/results/SMTC.json'
    path.parent.mkdir(parents=True)
    snapshot = fixture_snapshot()
    path.write_text(json.dumps({'status': 'success', 'symbol': 'SMTC', 'trade_date':'2026-10-02', 'consistency_input': snapshot}))
    past = tmp_path/'past.txt'
    past.write_text('独立A历史')
    return snapshot, past


def test_path_only_changes_past_and_records_hashes(tmp_path):
    snapshot, past = saved(tmp_path)
    seen = []
    def executor(value, output, **kwargs):
        expected = deepcopy(snapshot); expected['state']['past_context'] = '独立A历史'
        assert value == expected
        seen.append(value)
        return final_state()
    run_consistency(tmp_path, 'test', repeats=1, test_mode=True, path_mode=True,
                    past_context_file=past, group='abpath-A', executor=executor)
    assert len(seen) == 1
    result = json.loads(next((tmp_path/'data/evaluation/consistency/test/abpath-A').glob('*/SMTC/1/result.json')).read_text())
    assert result['original_snapshot_hash'] == input_hash(snapshot)
    assert result['input_hash'] == input_hash(seen[0])
    assert result['past_context_file_sha256'] == hashlib.sha256(past.read_bytes()).hexdigest()
    assert result['reconstructed'] is False
    assert not list((tmp_path/'data/evaluation/consistency').glob('*.md'))


@pytest.mark.parametrize('change', [dict(test_mode=False), dict(path_mode=False), dict(group='strict'),
                                  dict(reconstructed=True), dict(from_stage='analysts'), dict(repeats=2)])
def test_single_path_protections(tmp_path, change):
    _, past = saved(tmp_path)
    options = dict(repeats=1, test_mode=True, path_mode=True, past_context_file=past, group='abpath-A')
    options.update(change)
    with pytest.raises(ValueError):
        run_consistency(tmp_path, 'test', executor=lambda *a, **k: pytest.fail('拒绝前不调用模型'), **options)


def test_executor_input_mutation_rejected(tmp_path):
    _, past = saved(tmp_path)
    def executor(value, output, **kwargs):
        value['reports']['market_report'] = '改变'
        return final_state()
    with pytest.raises(ValueError, match='冻结输入'):
        run_consistency(tmp_path, 'test', repeats=1, test_mode=True, path_mode=True,
                        past_context_file=past, group='abpath-A', executor=executor)


def test_calendar_relative_and_et_date():
    result = calendar_after('2026-10-09')
    assert result['t0'] == '2026-10-12'
    assert result['days'][:20] == ['2026-10-'+str(d) for d in (12,13,14,15,16,19,20,21,22,23,26,27,28,29,30)] + ['2026-11-'+str(d).zfill(2) for d in (2,3,4,5,6)]
    assert result['mature_reviews'] == ['2026-11-13','2026-11-20','2026-12-07']
    assert calendar_after('2026-10-10T08:00:00+08:00') == result
    assert '2026-11-26' not in result['days'] and '2026-11-27' in result['days']


def test_adapter_shares_production_fields_and_preserves_legs():
    from daily_analyzer.runner import final_state_result_fields
    state = final_state(); state['final_trade_decision'] = '原文'
    state['structured_pm_decision']['reduce_legs'] = [{'kind':'风险减配', 'post_allocation_pct':0}]
    record = {'symbol':'SPY', 'finished_at':'2026-10-09T09:00:00-04:00', 'structured':{}, 'data_queries':['原取数']}
    result = adapt_result(record, state, 'Hold')
    for key, value in final_state_result_fields(state, 'Hold').items():
        assert result[key] == value
    assert result['finished_at'] == record['finished_at'] and result['data_queries'] == []
    assert record['structured'] == {}


def test_fork_excludes_future_and_never_overwrites(tmp_path):
    memory = tmp_path/'data/tradingagents/memory/trading_memory.md'
    memory.parent.mkdir(parents=True)
    from tradingagents.memory.log import TradingMemoryLog
    memory.write_text(TradingMemoryLog._SEPARATOR.join(['[2026-10-09 | SPY | Hold | pending]\n\nDECISION:\n旧', '[2026-10-12 | SPY | Hold | pending]\n\nDECISION:\n新']))
    target = fork_history(tmp_path, '2026-10-12', now=datetime(2026,10,9,12,tzinfo=ZoneInfo('America/New_York')))
    assert '新' not in (target/'data/tradingagents/memory/trading_memory.md').read_text()
    with pytest.raises(ValueError, match='已存在'):
        fork_history(tmp_path, '2026-10-12', now=datetime(2026,10,9,12,tzinfo=ZoneInfo('America/New_York')))

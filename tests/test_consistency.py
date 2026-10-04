"""冻结输入、真实图入口复用及测试写面隔离；不调用真实模型。"""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from daily_analyzer.evaluation.consistency import (REPORT_FIELDS, snapshot_input, build_debate_state,
    isolated_config, decision_workflow, compare_states, run_consistency, input_hash, execute_saved)


def fixture_snapshot():
    initial = dict(company_of_interest='SMTC', company_name='测试公司', trade_date='2026-10-02',
                   asset_type='stock', instrument_context='原身份及上下文', instrument_context_full='完整原上下文',
                   instrument_context_brief='精简原上下文', past_context='原历史，不重算', portfolio_context='',
                   context_compaction=True, context_profiles={})
    final = dict.fromkeys(REPORT_FIELDS, '原保存报告')
    config = {'llm_provider': 'codex_exec', 'quick_think_llm': 'gpt-6.1-sol',
              'deep_think_llm': 'gpt-6.1-sol', 'max_tokens': 2000, 'late_news_refresh': True,
              'max_recur_limit': 100, 'debate_mode': 'structured', 'futu_host': '127.0.0.2', 'futu_port': 22222,
              'memory_log_path': '/生产/memory.md', 'data_cache_dir': '/生产/cache',
              '_late_macro_refresher': lambda: None, 'api_key': '不可落盘'}
    return snapshot_input(initial, final, config=config, injected_context='原注入文本',
                          selected_analysts=['market', 'social', 'news', 'fundamentals'], reference_price=100)


def final_state(rating='Hold', allocation=100, low=90):
    decision = {'rating': rating, 'target_allocation': allocation, 'entry_plan': f'区间{low}–110美元。'}
    return {'structured_research_plan': decision, 'structured_trader_proposal': decision,
            'structured_pm_decision': decision, 'final_rating': rating}


def test_snapshot_preserves_original_past_and_reports_without_sensitive_runtime_config():
    snapshot = fixture_snapshot()
    original = deepcopy(snapshot)
    state = build_debate_state(snapshot)
    assert state['past_context'] == '原历史，不重算'
    assert state['instrument_context_brief'] == '精简原上下文'
    assert state['investment_debate_state']['count'] == 0
    assert state['risk_debate_state']['count'] == 0
    assert 'structured_pm_decision' not in state
    assert all(state[key] == '原保存报告' for key in REPORT_FIELDS)
    assert 'api_key' not in snapshot['config'] and '_late_macro_refresher' not in snapshot['config']
    assert snapshot['config']['max_tokens'] == 2000
    assert snapshot == original
    empty = deepcopy(snapshot); empty['state']['past_context'] = ''; empty['reports']['sentiment_report'] = ''
    assert build_debate_state(empty)['past_context'] == ''


@pytest.mark.parametrize('missing', ['past_context', 'instrument_context_brief', 'config', 'news_report'])
def test_missing_original_field_is_rejected_not_rebuilt(missing):
    snapshot = fixture_snapshot()
    if missing == 'config':
        del snapshot[missing]
    elif missing in REPORT_FIELDS:
        del snapshot['reports'][missing]
    else:
        del snapshot['state'][missing]
    with pytest.raises(ValueError, match='保存输入缺失'):
        build_debate_state(snapshot)
    with pytest.raises(ValueError, match='旧运行'):
        build_debate_state(None)


def test_isolated_config_rebinds_all_writes_and_disables_refresh(tmp_path):
    snapshot = fixture_snapshot()
    original = deepcopy(snapshot)
    config = isolated_config(snapshot, tmp_path, overrides={'data_cache_dir': '/不可写', '_late_macro_refresher': lambda: None})
    for key in ('data_cache_dir', 'results_dir', 'memory_log_path', 'evaluation_outcomes_path', 'codex_usage_log_path'):
        assert str(tmp_path) in config[key]
    assert not config['late_news_refresh'] and not config['checkpoint_enabled']
    assert '_late_macro_refresher' not in config and config['codex_prompt_log_dir'] is None
    assert snapshot == original


def test_decision_graph_reuses_nodes_and_skips_all_analysts(monkeypatch, tmp_path):
    from langgraph.graph import StateGraph, START, END
    from tradingagents.agents.state import AgentState
    import tradingagents.graph.trading_graph as module
    workflow = StateGraph(AgentState)
    def forbidden(state):
        raise AssertionError('冻结测试不得执行分析师')
    workflow.add_node('Market Analyst', forbidden)
    workflow.add_node('Bull Opening', lambda state: {'bull_opening': state['market_report']})
    workflow.add_node('Bear Opening', lambda state: {'bear_opening': state['past_context']})
    workflow.add_node('Research Manager', lambda state: {'investment_plan': state['bull_opening'] + state['bear_opening']})
    workflow.add_node('Portfolio Manager', lambda state: {'final_trade_decision': state['investment_plan']})
    workflow.add_edge(START, 'Market Analyst')
    workflow.add_edge(['Market Analyst'], 'Bull Opening'); workflow.add_edge(['Market Analyst'], 'Bear Opening')
    workflow.add_edge(['Bull Opening', 'Bear Opening'], 'Research Manager')
    workflow.add_edge('Research Manager', 'Portfolio Manager'); workflow.add_edge('Portfolio Manager', END)
    captures = []
    def constructor(**kwargs):
        captures.append(kwargs)
        return SimpleNamespace(workflow=workflow)
    monkeypatch.setattr(module, 'TradingAgentsGraph', constructor)
    result = execute_saved(fixture_snapshot(), tmp_path)
    assert result['final_trade_decision'] == '原保存报告原历史，不重算'
    assert not captures[0]['config']['late_news_refresh']
    assert str(tmp_path) in captures[0]['config']['memory_log_path']


def test_legacy_conditional_edges_are_retained_and_no_old_count_reused():
    from langgraph.graph import StateGraph, START, END
    from tradingagents.agents.state import AgentState
    workflow = StateGraph(AgentState)
    workflow.add_node('Market Analyst', lambda state: {})
    workflow.add_node('Bull Researcher', lambda state: {'investment_plan': state['past_context']})
    workflow.add_node('Portfolio Manager', lambda state: {'final_trade_decision': state['investment_plan']})
    workflow.add_edge(START, 'Market Analyst'); workflow.add_edge('Market Analyst', 'Bull Researcher')
    workflow.add_conditional_edges('Bull Researcher', lambda state: 'done', {'done': 'Portfolio Manager'})
    workflow.add_edge('Portfolio Manager', END)
    result = decision_workflow(workflow).compile().invoke(build_debate_state(fixture_snapshot()))
    assert result['final_trade_decision'] == '原历史，不重算'


def test_three_layers_allocation_bounds_and_plan_types():
    comparison = compare_states(final_state(), final_state('Buy', 135, 95), 100)
    assert all(layer['rating_gap'] == 2 for layer in comparison['layers'].values())
    assert comparison['layers']['pm']['allocation_difference_pp'] == 35
    assert comparison['entry_bounds_difference_pct'] == [5, 0]
    assert comparison['same_entry_type']
    assert compare_states(final_state(), final_state(), None)['entry_bounds_difference_pct'] is None
    missing = compare_states({}, {})
    assert missing['layers']['rm']['same_rating'] is None and missing['same_entry_type'] is None
    not_applicable = final_state(); not_applicable['structured_pm_decision']['entry_plan'] = '不适用，等待。'
    assert compare_states(final_state(), not_applicable, 100)['same_entry_type'] is False


def create_saved_run(root, snapshot=True):
    result = root/'data/runs/2026-10-02/batches/saved-run/results/SMTC.json'
    result.parent.mkdir(parents=True)
    record = {'status': 'success', 'symbol': 'SMTC', 'consistency_input': fixture_snapshot() if snapshot else None}
    result.write_text(json.dumps(record, ensure_ascii=False))
    memory = root/'data/tradingagents/memory/trading_memory.md'; memory.parent.mkdir(parents=True)
    memory.write_text('正式记忆保护')
    return result, memory


def test_explicit_entry_writes_only_evaluation_and_records_mock_not_real_usage(tmp_path):
    formal, memory = create_saved_run(tmp_path)
    calls = []
    def executor(snapshot, output, **kwargs):
        calls.append((input_hash(snapshot), output, kwargs))
        return final_state()
    result = run_consistency(tmp_path, 'saved-run', test_mode=True, executor=executor)
    assert len(calls) == 2 and calls[0][0] == calls[1][0]
    assert memory.read_text() == '正式记忆保护'
    assert result['test_only'] and result['comparisons'][0]['layers']['pm']['rating_gap'] == 0
    assert all(str(tmp_path/'data/evaluation/consistency') in str(call[1]) for call in calls)
    report = Path(result['report']).read_text()
    assert '正式结果、记忆、缓存前后' in report
    records = list((tmp_path/'data/evaluation').rglob('result.json'))
    assert len(records) == 2
    assert all('NOT_TESTED' in json.loads(path.read_text())['usage_status'] for path in records)
    assert json.loads(formal.read_text())['status'] == 'success'


def test_guard_and_missing_snapshot_make_zero_calls_and_no_artifacts(tmp_path):
    create_saved_run(tmp_path, snapshot=False)
    def forbidden(*a, **kw):
        raise AssertionError('不得调用模型')
    with pytest.raises(ValueError, match='test-mode'):
        run_consistency(tmp_path, 'saved-run', executor=forbidden)
    with pytest.raises(ValueError, match='旧运行'):
        run_consistency(tmp_path, 'saved-run', test_mode=True, executor=forbidden)
    assert not (tmp_path/'data/evaluation').exists()


def test_analysts_mode_is_labeled_not_fully_frozen(tmp_path):
    create_saved_run(tmp_path)
    seen = []
    result = run_consistency(tmp_path, 'saved-run', test_mode=True, from_stage='analysts',
        executor=lambda *a, **kw: seen.append(kw['from_stage']) or final_state())
    assert seen == ['analysts', 'analysts']
    assert '非完全冻结' in Path(result['report']).read_text()


def test_success_only_snapshot_and_no_production_auto_test_entry():
    from daily_analyzer.cli import build_parser
    args = build_parser().parse_args(['consistency', '--run-id', 'saved-run', '--test-mode'])
    assert args.from_stage == 'debate' and args.repeats == 2 and args.test_mode
    for arguments in (['run'], ['run', '--scheduled'], ['run', '--tickers', 'SMTC']):
        assert not hasattr(build_parser().parse_args(arguments), 'test_mode')


def test_real_lock_occupation_blocks_but_stale_pid_does_not(tmp_path):
    import fcntl
    import os
    create_saved_run(tmp_path)
    lock = tmp_path/'data/run.lock'
    lock.write_text(str(os.getpid()))
    with lock.open('r') as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match='正式分析仍在运行'):
            run_consistency(tmp_path, 'saved-run', test_mode=True, executor=lambda *a, **kw: final_state())
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    run_consistency(tmp_path, 'saved-run', test_mode=True, executor=lambda *a, **kw: final_state())
    assert lock.read_text() == str(os.getpid())


def test_analysts_exec_is_new_process_with_private_paths(monkeypatch, tmp_path):
    import subprocess
    def fake_run(command, **kwargs):
        payload = json.loads(kwargs['input'])
        config = isolated_config(payload['snapshot'], payload['output'], from_stage='analysts')
        assert str(tmp_path) in config['data_cache_dir']
        assert command[1] == '-c' and "from_stage='analysts'" in command[2]
        Path(payload['target']).write_text(json.dumps(final_state()))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(subprocess, 'run', fake_run)
    assert execute_saved(fixture_snapshot(), tmp_path, from_stage='analysts', project_root=tmp_path) == final_state()


def test_fresh_analyst_child_reuses_saved_sources_credentials_and_yahoo_cache(tmp_path):
    """新进程真实初始化/本地缓存，来源与行情用桩，绝不请求网络或模型。"""
    import os
    import subprocess
    import sys
    import yfinance.cache as cache
    parent_locations = [cls._cache_dir for cls in (cache._TzDBManager, cache._CookieDBManager, cache._ISINDBManager)]
    project = tmp_path/'project'; (project/'config').mkdir(parents=True)
    secrets = project/'config/secrets.env'
    secrets.write_text('APCA_API_KEY_ID=fixture-only\nAPCA_API_SECRET_KEY=fixture-only\n')
    secrets.chmod(0o600)
    output = tmp_path/'evaluation'
    snapshot = fixture_snapshot()
    config = isolated_config(snapshot, output, from_stage='analysts')
    config['tool_vendors'] = {'get_fundamentals': 'futu,yfinance', 'get_macro_indicators': 'fred_public,futu,fred'}
    code = '''import json,sys,os
from types import SimpleNamespace
from pathlib import Path
import daily_analyzer.data_sources.futu as futu
import daily_analyzer.data_sources.treasury as treasury
methods={name:(lambda *a,**kw:'原futu来源') for name in ('daily_bars','fundamentals','insiders','news','macro','statements')}
source=SimpleNamespace(host=None,port=None,**methods)
futu.get_shared_data_source=lambda:source
treasury.TREASURY_SOURCE=SimpleNamespace(macro=lambda *a,**kw:'原公开利率来源')
from daily_analyzer.evaluation.consistency import prepare_analyst_child
p=json.load(sys.stdin)
prepare_analyst_child(p['config'],p['output'],p['project'])
from tradingagents.dataflows.config import run_config
from tradingagents.dataflows.router import route_to_vendor
from tradingagents.dataflows.ohlcv_sources import _LOADERS
with run_config(p['config']):
 assert route_to_vendor('get_fundamentals','SMTC','2026-10-02')=='原futu来源'
 assert route_to_vendor('get_macro_indicators','2026-10-02')=='原公开利率来源'
assert source.host=='127.0.0.2' and source.port==22222
assert _LOADERS['futu'] is source.daily_bars
assert os.environ['APCA_API_KEY_ID']=='fixture-only'
import yfinance.cache as cache
private=Path(p['output'])/'cache/yfinance'
assert all(Path(cls._cache_dir)==private for cls in (cache._TzDBManager,cache._CookieDBManager,cache._ISINDBManager))
cache.get_tz_cache().store('SMTC','America/New_York')
cache.get_cookie_cache().initialise()
cache.get_isin_cache().store('fixture-isin','SMTC')
assert {f.name for f in private.glob('*.db')}=={'tkr-tz.db','cookies.db','isin-tkr.db'}
print('离线来源绑定、原连接参数、凭据内存加载与三类缓存隔离通过')
'''
    env = dict(os.environ)
    for key in ('APCA_API_KEY_ID', 'APCA_API_SECRET_KEY', 'ALPHA_VANTAGE_API_KEY', 'FRED_API_KEY'):
        env.pop(key, None)
    result = subprocess.run([sys.executable, '-c', code], input=json.dumps(dict(config=config, output=str(output), project=str(project))),
                            text=True, capture_output=True, env=env, timeout=30)
    assert result.returncode == 0, result.stderr
    assert '隔离通过' in result.stdout
    assert parent_locations == [cls._cache_dir for cls in (cache._TzDBManager, cache._CookieDBManager, cache._ISINDBManager)]
    assert 'fixture-only' not in json.dumps(snapshot) and snapshot['config']['futu_port'] == 22222


def create_reconstructed_run(root):
    """构造旧原件和独立授权重建，不给正式结果添加成功snapshot。"""
    import hashlib
    snapshot = fixture_snapshot(); snapshot['state']['past_context'] = ''
    snapshot['config']['debate_mode'] = 'legacy'
    snapshot['config']['max_debate_rounds'] = snapshot['config']['max_risk_discuss_rounds'] = 1
    result = root/'data/runs/2026-10-02/batches/saved-run/results/SMTC.json'
    result.parent.mkdir(parents=True)
    original = {'status': 'success', 'symbol': 'SMTC', 'analyzed_symbol': 'SMTC', 'upstream_trade_date': '2026-10-02',
        'type': 'stock', 'name': snapshot['state']['company_name'], 'portfolio_context': None,
        'price_data_end_date': '2026-10-02', 'news_cutoff_utc': '2026-10-02T12:00:00+00:00',
        'reports': snapshot['reports'], 'injected_context': snapshot['injected_context'],
        'context_blocks': {'price_anchors': {'data': {'anchors': {'P_Close': {'value': 100}}}}},
        'llm': {'provider': 'codex_exec', 'quick': {'model': 'gpt-6.1-sol', 'reasoning_effort': 'medium'},
                'deep': {'model': 'gpt-6.1-sol', 'reasoning_effort': 'xhigh'}}}
    snapshot['config'].update(codex_quick_reasoning_effort='medium', codex_deep_reasoning_effort='xhigh',
                             trade_date='2026-10-02', price_data_end_date='2026-10-02', news_cutoff_utc='2026-10-02T12:00:00+00:00')
    result.write_text(json.dumps(original))
    settings = {key: snapshot['config'][key] for key in ('max_debate_rounds', 'max_risk_discuss_rounds')}
    settings['analysts'] = snapshot['selected_analysts']
    state = result.parent/'SMTC/state/full_states_log_2026-10-02.json';state.parent.mkdir(parents=True)
    state.write_text(json.dumps({'run_settings': settings}))
    sha = lambda text: hashlib.sha256(text.encode()).hexdigest()
    snapshot['reconstruction'] = {'reconstructed': True, 'explicitly_authorized': True, 'symbol': 'SMTC',
        'original_run_id': 'saved-run', 'original_missing': ['past_context'],
        'record_sha256': hashlib.sha256(result.read_bytes()).hexdigest(),
        'report_hashes': {k: sha(v) for k,v in snapshot['reports'].items()},
        'injected_hash': sha(snapshot['injected_context']), 'debate_mode_provenance': {'status': 'inferred'}}
    path = root/'data/evaluation/reconstructed/SMTC.json';path.parent.mkdir(parents=True);path.write_text(json.dumps(snapshot))
    return path, result, snapshot


def test_reconstructed_groups_preserve_strict_guard_datahash_and_original(tmp_path):
    path, original, snapshot = create_reconstructed_run(tmp_path)
    before = original.read_bytes()
    calls = []
    def executor(value, output, **kwargs):
        calls.append(value)
        assert value['state']['past_context'] == ''
        return final_state()
    with pytest.raises(ValueError, match='旧运行'):
        run_consistency(tmp_path, 'saved-run', test_mode=True, executor=executor)
    for group, repeats in [('baseline',2), ('A',1), ('B',1)]:
        result = run_consistency(tmp_path,'saved-run',test_mode=True,reconstructed=True,snapshot_paths=[path],group=group,repeats=repeats,executor=executor)
        assert '历史重建/缩样' in Path(result['report']).read_text()
        assert f'-{group}.md' in result['report']
    assert len(calls) == 4 and original.read_bytes() == before
    products = list((tmp_path/'data/evaluation/consistency').rglob('result.json'))
    hashes = {json.loads(p.read_text())['original_data_hash'] for p in products}
    assert len(products) == 4 and len(hashes) == 1
    assert all(json.loads(p.read_text())['reconstructed'] and not json.loads(p.read_text())['fully_frozen'] for p in products)
    assert all(json.loads(p.read_text())['input'] == snapshot for p in products)


@pytest.mark.parametrize('failure', ['test_mode','marker','group','path','authorization','record_hash','report','injected','price','model','rounds','credentials'])
def test_reconstructed_preflight_failure_has_zero_calls(tmp_path, failure):
    path, original, snapshot = create_reconstructed_run(tmp_path)
    kwargs = dict(test_mode=True,reconstructed=True,snapshot_paths=[path],group='baseline')
    if failure=='test_mode':kwargs['test_mode']=False
    elif failure=='marker':kwargs['reconstructed']=False
    elif failure=='group':kwargs['group']='../unsafe'
    elif failure=='path':
        other=tmp_path/'outside.json';other.write_text(path.read_text());kwargs['snapshot_paths']=[other]
    elif failure=='authorization':snapshot['reconstruction']['explicitly_authorized']=False
    elif failure=='record_hash':snapshot['reconstruction']['record_sha256']='wrong'
    elif failure=='report':snapshot['reports']['market_report']='改变原报告'
    elif failure=='injected':snapshot['injected_context']='改变原注入'
    elif failure=='price':snapshot['reference_price']=999
    elif failure=='model':snapshot['config']['deep_think_llm']='改变原模型'
    elif failure=='rounds':snapshot['config']['max_debate_rounds']=2
    elif failure=='credentials':snapshot['reconstruction']['api_key']='禁止落盘fixture'
    path.write_text(json.dumps(snapshot))
    with pytest.raises(ValueError):
        run_consistency(tmp_path,'saved-run',executor=lambda *a,**kw:pytest.fail('预检失败不得调用'),**kwargs)
    assert not (tmp_path/'data/evaluation/consistency').exists()


@pytest.mark.parametrize('overrides', [{'max_debate_rounds':99}, {'debate_mode':'structured'},
    {'deep_think_llm':'fake'}, {'role_llm_overrides':{'rm':{'provider':'claude_exec'}}},
    {'news_cutoff_utc':'2030-01-01T00:00:00+00:00'}])
def test_reconstructed_effective_overrides_cannot_bypass_frozen_config(tmp_path, overrides):
    path, _, _ = create_reconstructed_run(tmp_path)
    with pytest.raises(ValueError, match='禁止改变冻结配置'):
        run_consistency(tmp_path,'saved-run',test_mode=True,reconstructed=True,snapshot_paths=[path],group='baseline',
                        overrides=overrides,executor=lambda *a,**kw:pytest.fail('任何覆盖漂移必须0调用'))
    assert not (tmp_path/'data/evaluation/consistency').exists()


@pytest.mark.parametrize('field', ['asset_type','company_name','company_of_interest','portfolio_context',
    'trade_date','price_data_end_date','news_cutoff_utc'])
def test_reconstructed_original_identity_portfolio_dates_cannot_drift(tmp_path, field):
    path, _, snapshot = create_reconstructed_run(tmp_path)
    if field in ('asset_type','company_name','company_of_interest','portfolio_context'):
        snapshot['state'][field]='改变原输入'
    else:
        snapshot['config'][field]='2030-01-01'
    path.write_text(json.dumps(snapshot))
    with pytest.raises(ValueError):
        run_consistency(tmp_path,'saved-run',test_mode=True,reconstructed=True,snapshot_paths=[path],group='baseline',
                        executor=lambda *a,**kw:pytest.fail('身份/日期漂移必须0调用'))
    assert not (tmp_path/'data/evaluation/consistency').exists()


def test_reconstructed_later_snapshot_failure_preflights_whole_batch(tmp_path):
    import hashlib
    path, original, snapshot = create_reconstructed_run(tmp_path)
    second = deepcopy(snapshot);second['state'].update(company_of_interest='QQQ',asset_type='etf',company_name='原QQQ')
    second['reconstruction']['symbol']='QQQ'
    record=json.loads(original.read_text());record.update(symbol='QQQ',analyzed_symbol='QQQ',type='etf',name='原QQQ')
    source=original.with_name('QQQ.json');source.write_text(json.dumps(record))
    state=source.parent/'QQQ/state/full_states_log_2026-10-02.json';state.parent.mkdir(parents=True)
    state.write_bytes((source.parent/'SMTC/state/full_states_log_2026-10-02.json').read_bytes())
    second['reconstruction']['record_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
    second['config']['price_data_end_date']='2030-01-01'
    other=path.with_name('QQQ.json');other.write_text(json.dumps(second))
    with pytest.raises(ValueError,match='配置日期'):
        run_consistency(tmp_path,'saved-run',test_mode=True,reconstructed=True,snapshot_paths=[path,other],group='baseline',
                        executor=lambda *a,**kw:pytest.fail('后项失配不能先调用首项'))
    assert not (tmp_path/'data/evaluation/consistency').exists()


@pytest.mark.parametrize('key',['target_allocation','target_allocation_pct'])
def test_comparison_allocation_legacy_schema_and_unavailable_reason(key):
    left=final_state();right=final_state()
    for state,amount in ((left,100),(right,122)):
        for field in ('structured_research_plan','structured_trader_proposal','structured_pm_decision'):
            state[field].pop('target_allocation',None);state[field][key]=amount
        state['structured_pm_decision']['entry_plan']='不适用：等待回落190–195美元候选区间'
    result=compare_states(left,right,194.88)
    assert all(row['allocation_difference_pp']==22 for row in result['layers'].values())
    assert result['entry_bounds_difference_pct'] is None and result['entry_plan_types']==['not_applicable']*2
    assert all('候选' in reason for reason in result['entry_availability_reasons'])


def test_comparison_allocation_conflicting_keys_explicitly_unavailable():
    left=final_state();right=final_state()
    left['structured_pm_decision'].update(target_allocation=100,target_allocation_pct=122)
    row=compare_states(left,right,100)['layers']['pm']
    assert row['allocation_difference_pp'] is None and row['allocation_availability'][0]=='conflict'
    left['structured_pm_decision']['target_allocation_pct']=100
    assert compare_states(left,right,100)['layers']['pm']['allocation_availability'][0]=='available'
    assert compare_states({}, {})['layers']['pm']['allocation_availability']==['missing','missing']


@pytest.mark.parametrize('scheme',['A','B'])
def test_authorized_role_groups_keep_base_input_and_separate_effective_hash(tmp_path,scheme):
    path,original,snapshot=create_reconstructed_run(tmp_path)
    calls=[]
    result=run_consistency(tmp_path,'saved-run',test_mode=True,reconstructed=True,snapshot_paths=[path],group=scheme,repeats=1,
        overrides={'role_llm_scheme':scheme,'legacy_speaker_rotation':True},
        executor=lambda value,output,**kwargs:calls.append((value,kwargs)) or final_state())
    assert calls[0][0]==snapshot and calls[0][1]['overrides']['role_llm_scheme']==scheme
    execution=result['executions'][0]
    assert execution['input_hash']==input_hash(snapshot)
    assert execution['effective_config_hash']!=input_hash(snapshot['config'])
    assert json.loads(path.read_text())==snapshot


def test_later_snapshot_override_preflight_rejects_whole_batch_before_calls(tmp_path):
    from daily_analyzer.evaluation.consistency import validate_test_overrides
    _,_,snapshot=create_reconstructed_run(tmp_path)
    validate_test_overrides(snapshot,{'role_llm_scheme':'B'})
    with pytest.raises(ValueError):validate_test_overrides(snapshot,{'legacy_speaker_rotation':'true'})
    with pytest.raises(ValueError):validate_test_overrides(snapshot,{'role_llm_overrides':{'bull':{'provider':'codex_exec','model':'fake','effort':'medium'}}})


@pytest.mark.parametrize('day,first',[('2026-10-01','Bear Researcher'),('2026-10-02','Bull Researcher')])
def test_test_decision_entry_uses_explicit_legacy_rotation(day,first):
    from langgraph.graph import StateGraph,START,END
    from tradingagents.agents.state import AgentState
    workflow=StateGraph(AgentState)
    for name in ('Bull Researcher','Bear Researcher'):
        workflow.add_node(name,lambda state:{})
        workflow.add_edge(name,END)
    graph=decision_workflow(workflow,{'trade_date':day,'debate_mode':'legacy','legacy_speaker_rotation':True})
    assert (START,first) in graph.edges



def test_claude_test_budget_fixed_without_mutating_snapshot(tmp_path):
    snapshot=fixture_snapshot();snapshot['config']['claude_max_concurrency']=99
    digest=input_hash(snapshot)
    config=isolated_config(snapshot,tmp_path)
    assert (config['claude_retries'],config['claude_timeout'],config['claude_max_concurrency'])==(0,600,1)
    assert input_hash(snapshot)==digest and snapshot['config']['claude_max_concurrency']==99


def test_role_scheme_flags_only_explicit_consistency_parser():
    from daily_analyzer.cli import build_parser
    parser=build_parser()
    args=parser.parse_args(['consistency','--run-id','saved','--test-mode','--role-scheme','A','--legacy-speaker-rotation'])
    assert args.role_scheme=='A' and args.legacy_speaker_rotation
    default=parser.parse_args(['consistency','--run-id','saved'])
    assert default.role_scheme is None and not default.legacy_speaker_rotation and not default.test_mode

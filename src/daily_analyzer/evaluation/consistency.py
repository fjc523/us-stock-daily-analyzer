"""显式测试同输入决策一致性，独立工件不能成为生产决策。"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from itertools import combinations
import json
from pathlib import Path
import re
import time

from daily_analyzer.storage import atomic_write_json, jsonable

REPORT_FIELDS = ('market_report', 'sentiment_report', 'news_report', 'fundamentals_report')
INITIAL_FIELDS = ('company_of_interest', 'company_name', 'trade_date', 'asset_type',
                  'instrument_context', 'instrument_context_full', 'instrument_context_brief',
                  'past_context', 'portfolio_context', 'context_compaction', 'context_profiles')
REQUIRED_FIELDS = ('company_of_interest', 'trade_date', 'asset_type', 'instrument_context',
                   'instrument_context_full', 'instrument_context_brief', 'past_context', 'portfolio_context')
RATINGS = ('Sell', 'Underweight', 'Hold', 'Overweight', 'Buy')
ANALYST_NODES = {'Market Analyst', 'Sentiment Analyst', 'News Analyst', 'Fundamentals Analyst'}


def _public_config(value):
    """保存有效非凭据配置，不落盘临时闭包、认证或回调。"""
    if isinstance(value, dict):
        return {key: _public_config(item) for key, item in value.items()
                if not str(key).startswith('_') and not callable(item)
                and not re.search(r'api.?key|credential|password|secret|(?:access|refresh|auth|session)_token|callback', str(key), re.I)}
    if isinstance(value, (list, tuple)):
        return [_public_config(item) for item in value if not callable(item)]
    return jsonable(value)


def snapshot_input(initial_state, final_state, *, config, injected_context, selected_analysts, reference_price=None):
    """新成功运行保存原初始上下文和真实分析师报告，不含后来决策输出。"""
    snapshot = {'version': 1,
                'state': {key: deepcopy(initial_state[key]) for key in INITIAL_FIELDS if key in initial_state},
                'reports': {key: final_state.get(key, '') for key in REPORT_FIELDS},
                'config': _public_config(config), 'injected_context': injected_context,
                'selected_analysts': list(selected_analysts), 'reference_price': reference_price}
    build_debate_state(snapshot)
    return snapshot


def input_hash(snapshot):
    return hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def build_debate_state(snapshot):
    """缺历史字段即拒绝；真实保存的空历史合法，缺失不能伪造为空。"""
    if not isinstance(snapshot, dict) or snapshot.get('version') != 1:
        raise ValueError('保存输入缺失：旧运行没有完整冻结快照，不能重取分析师或当前记忆补齐')
    state, reports = snapshot.get('state', {}), snapshot.get('reports', {})
    missing = [key for key in REQUIRED_FIELDS if key not in state]
    missing += [key for key in REPORT_FIELDS if key not in reports]
    if 'injected_context' not in snapshot or not isinstance(snapshot.get('config'), dict):
        missing.append('injected_context/config')
    if not isinstance(snapshot.get('selected_analysts'), list):
        missing.append('selected_analysts')
    if missing:
        raise ValueError('保存输入缺失：' + '、'.join(missing))
    if not all(isinstance(state[key], str) for key in REQUIRED_FIELDS):
        raise ValueError('冻结上下文必须是原始字符串')
    if not all(isinstance(reports[key], str) for key in REPORT_FIELDS):
        raise ValueError('分析师报告槽必须保存字符串，原未启用槽允许空')
    from tradingagents.graph.propagation import Propagator
    initial = Propagator().create_initial_state(state['company_of_interest'], state['trade_date'],
        asset_type=state['asset_type'], past_context=state['past_context'],
        instrument_context=state['instrument_context'], portfolio_context=state['portfolio_context'])
    initial.update({key: deepcopy(state[key]) for key in INITIAL_FIELDS if key in state})
    initial.update(deepcopy(reports))
    return initial


def isolated_config(snapshot, output, *, from_stage='debate', overrides=None):
    """图构造和工具缓存都重定向；冻结模式切断新闻、宏观刷新。"""
    output = Path(output).resolve()
    config = deepcopy(snapshot['config'])
    if overrides:
        config.update(deepcopy(overrides))
    config.update(results_dir=str(output/'results'), data_cache_dir=str(output/'cache'),
                  memory_log_path=str(output/'memory'/'unused.md'),
                  evaluation_outcomes_path=str(output/'unused-outcomes.jsonl'),
                  checkpoint_enabled=False, late_news_refresh=False,
                  codex_usage_log_path=str(output/'llm_calls.jsonl'),
                  codex_prompt_log_dir=None, analysis_mode='consistency_test')
    config = {key: value for key, value in config.items() if not key.startswith('_')}
    return config


def decision_workflow(original):
    """复用真实图节点和条件边，移除分析师入口而不重复构造业务逻辑。"""
    from langgraph.graph import StateGraph, START
    from tradingagents.agents.state import AgentState
    workflow = StateGraph(AgentState)
    kept = set(original.nodes) - ANALYST_NODES
    for name in kept:
        workflow.add_node(name, original.nodes[name].runnable)
    for start, end in original.edges:
        if start in kept and (end in kept or end == '__end__'):
            workflow.add_edge(start, end)
    for starts, end in original.waiting_edges:
        if all(start in kept for start in starts) and end in kept:
            workflow.add_edge(list(starts), end)
    for name, branches in original.branches.items():
        if name in kept:
            for branch in branches.values():
                workflow.add_conditional_edges(name, branch.path, branch.ends)
    if 'Bull Opening' in kept:
        workflow.add_edge(START, 'Bull Opening')
        workflow.add_edge(START, 'Bear Opening')
    else:
        workflow.add_edge(START, 'Bull Researcher')
    return workflow


def _execute_local(snapshot, output, *, from_stage='debate', overrides=None):
    """只显式测试调用；不使用propagate/create_run_state或生产落盘生命周期。"""
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.dataflows.config import run_config
    from tradingagents.llm_clients.codex_exec.runner import codex_usage_context
    config = isolated_config(snapshot, output, from_stage=from_stage, overrides=overrides)
    graph = TradingAgentsGraph(selected_analysts=snapshot['selected_analysts'], config=config)
    state = build_debate_state(snapshot)
    if from_stage == 'analysts':
        state.update({key: '' for key in REPORT_FIELDS})
        compiled = graph.graph
    else:
        compiled = decision_workflow(graph.workflow).compile()
    with run_config(config), codex_usage_context(ticker=state['company_of_interest']):
        final = compiled.invoke(state, config={'recursion_limit': config.get('max_recur_limit', 100)})
    return jsonable(final)


def prepare_analyst_child(config, output, project_root):
    """仅新子进程加载凭据与绑定来源，Yahoo三类缓存先指向测试私有目录。"""
    import os
    from daily_analyzer.config import load_credentials
    import yfinance
    yfinance.set_tz_cache_location(str(Path(output)/'cache'/'yfinance'))
    credentials = load_credentials(project_root)
    for field, name in (('alpaca_key_id', 'APCA_API_KEY_ID'), ('alpaca_secret_key', 'APCA_API_SECRET_KEY'),
                        ('alpha_vantage_api_key', 'ALPHA_VANTAGE_API_KEY'), ('fred_api_key', 'FRED_API_KEY')):
        secret = getattr(credentials, field)
        if secret is not None:
            os.environ[name] = secret.get_secret_value()
    if 'futu_host' not in config or 'futu_port' not in config:
        raise ValueError('原保存来源连接参数缺失，不能使用今天配置替代')
    from daily_analyzer.analyzer import bind_project_sources
    bind_project_sources(config['futu_host'], config['futu_port'])


def execute_saved(snapshot, output, *, from_stage='debate', overrides=None, project_root=None):
    """分析师重新取数使用新进程，不共享生产全局来源配置、缓存实例或写入器。"""
    if from_stage != 'analysts':
        return _execute_local(snapshot, output, from_stage=from_stage, overrides=overrides)
    if project_root is None:
        raise ValueError('分析师隔离测试必须提供项目凭据根目录')
    import subprocess
    import sys
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    target = output/'isolated-state.json'
    code = ("import json,sys; from daily_analyzer.evaluation.consistency import _execute_local,prepare_analyst_child; "
            "from daily_analyzer.storage import atomic_write_json; p=json.load(sys.stdin); prepare_analyst_child(p['snapshot']['config'],p['output'],p['project_root']); "
            "atomic_write_json(p['target'],_execute_local(p['snapshot'],p['output'],"
            "from_stage='analysts',overrides=p['overrides']))")
    payload = dict(snapshot=snapshot, output=str(output), overrides=overrides, target=str(target), project_root=str(Path(project_root).resolve()))
    completed = subprocess.run([sys.executable, '-c', code], input=json.dumps(payload),
                               text=True, capture_output=True, timeout=3600)
    if completed.returncode:
        raise RuntimeError('隔离分析师测试进程失败，退出码：'+str(completed.returncode))
    return json.loads(target.read_text())


def compare_states(first, second, reference_price=None):
    """评级、配置与方案分别比较，缺值诚实保留不可计算。"""
    from .settlement import plan_rating, allocation, number
    from .price_plans import parse_plan
    from daily_analyzer.site import _decision_section
    layers = {}
    for layer, field, key, title in [('rm', 'investment_plan', 'structured_research_plan', 'Recommendation'),
                                    ('trader', 'trader_investment_plan', 'structured_trader_proposal', 'Action'),
                                    ('pm', 'final_trade_decision', 'structured_pm_decision', 'Recommendation')]:
        left = first.get(key) or first.get(field)
        right = second.get(key) or second.get(field)
        rating_a, rating_b = plan_rating(left, title), plan_rating(right, title)
        if layer == 'pm':
            from tradingagents.agents.rating import run_rating
            rating_a = rating_a or run_rating(first)
            rating_b = rating_b or run_rating(second)
        a, b = allocation(left), allocation(right)
        layers[layer] = {'ratings': [rating_a, rating_b],
                         'same_rating': rating_a == rating_b if rating_a in RATINGS and rating_b in RATINGS else None,
                         'rating_gap': abs(RATINGS.index(rating_a)-RATINGS.index(rating_b)) if rating_a in RATINGS and rating_b in RATINGS else None,
                         'allocation_difference_pp': b-a if a is not None and b is not None else None}
    plans = []
    for state in (first, second):
        structured = state.get('structured_pm_decision')
        value = structured.get('entry_plan') if isinstance(structured, dict) else _decision_section(state.get('final_trade_decision'), '建仓点位')
        plans.append(parse_plan(value))
    types = [plan['parse_status'] for plan in plans]
    reference = number(reference_price, positive=True)
    differences = None
    if reference is not None and all(plan['parse_status'] == 'parsed' for plan in plans):
        differences = [(plans[1][field]-plans[0][field])/reference*100 for field in ('low', 'high')]
    return {'layers': layers, 'entry_plan_types': types,
            'same_entry_type': types[0] == types[1] if 'unparsed' not in types else None,
            'entry_bounds_difference_pct': differences, 'reference_price': reference}


def protected_fingerprint(root):
    """正式结果、记忆与缓存的字节和文件清单，工件目录不在其内。"""
    root = Path(root)
    files = {}
    for relative in ('data/runs', 'data/tradingagents', 'data/cache', 'data/status.json', 'reports'):
        path = root/relative
        candidates = path.rglob('*') if path.is_dir() else [path]
        for candidate in candidates:
            if candidate.is_file():
                files[str(candidate.relative_to(root))] = hashlib.sha256(candidate.read_bytes()).hexdigest()
    return files


def run_consistency(root, run_id, *, repeats=2, from_stage='debate', test_mode=False, symbols=None,
                    executor=execute_saved, monotonic=time.monotonic, overrides=None):
    """必须显式test_mode；所有输入先检查后调用，避免部分消费才发现缺口。"""
    if not test_mode:
        raise ValueError('一致性重复仅允许显式测试入口：请指定--test-mode；生产默认关闭')
    if from_stage not in ('debate', 'analysts') or not 2 <= repeats <= 10:
        raise ValueError('测试起点须debate/analysts，重复次数须2–10')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', run_id):
        raise ValueError('非法run-id')
    root = Path(root).resolve()
    # 不接管生产锁或中断当前分析。
    lock = root/'data/run.lock'
    if lock.exists():
        import fcntl
        try:
            with lock.open('r') as stream:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        except BlockingIOError:
            raise ValueError('正式分析仍在运行，暂停一致性测试') from None
        except OSError:
            raise ValueError('运行锁状态不能确认，暂停一致性测试') from None
    batches = list((root/'data/runs').glob('*/batches/'+run_id))
    if len(batches) != 1:
        raise ValueError('run-id不存在或不唯一')
    records = [json.loads(path.read_text()) for path in sorted((batches[0]/'results').glob('*.json'))]
    records = [record for record in records if record.get('status') == 'success'
               and (symbols is None or record.get('symbol') in symbols)]
    if not records or (symbols is not None and set(symbols) != {r['symbol'] for r in records}):
        raise ValueError('找不到指定成功标的')
    for record in records:
        build_debate_state(record.get('consistency_input'))
        if not re.fullmatch(r'[A-Za-z0-9^][A-Za-z0-9.^_-]*', record.get('symbol', '')):
            raise ValueError('非法保存标的代码')
    destination = root/'data/evaluation/consistency'
    before = protected_fingerprint(root)
    stamp = str(time.time_ns())
    comparisons = []
    executions = []
    for record in records:
        snapshot = record['consistency_input']
        digest = input_hash(snapshot)
        symbol = record['symbol']
        if not re.fullmatch(r'[A-Za-z0-9^][A-Za-z0-9.^_-]*', symbol):
            raise ValueError('非法保存标的代码')
        states = []
        for repeat in range(repeats):
            output = destination/run_id/stamp/symbol/str(repeat+1)
            started = monotonic()
            final = executor(deepcopy(snapshot), output, from_stage=from_stage, overrides=overrides, project_root=root)
            duration = monotonic()-started
            if input_hash(snapshot) != digest:
                raise ValueError('冻结输入被修改')
            usage_path = output/'llm_calls.jsonl'
            calls = [json.loads(line) for line in usage_path.read_text().splitlines() if line.strip()] if usage_path.exists() else []
            atomic_write_json(output/'result.json', {'test_only': True, 'production_decision': False,
                'input_hash': digest, 'from_stage': from_stage, 'fully_frozen': from_stage == 'debate',
                'config': isolated_config(snapshot, output, from_stage=from_stage, overrides=overrides),
                'duration_seconds': duration, 'llm_usage': calls,
                'usage_status': '实际调用日志' if calls else 'NOT_TESTED：未取得实际用量，不作零成本', 'state': final})
            executions.append({'symbol': symbol, 'repeat': repeat+1, 'duration_seconds': duration,
                               'call_count': len(calls) if calls else None,
                               'tokens': [call.get('tokens', {}) for call in calls] if calls else 'NOT_TESTED'})
            states.append(final)
        for a, b in combinations(range(repeats), 2):
            comparisons.append({'symbol': symbol, 'runs': [a+1, b+1], 'input_hash': digest,
                                **compare_states(states[a], states[b], snapshot.get('reference_price'))})
    after = protected_fingerprint(root)
    if before != after:
        raise ValueError('测试前后正式结果/记忆/缓存发生变化，工件不得视为通过')
    report = ['# 同输入一致性测试', f'原运行：{run_id}；起点：{from_stage}；重复：{repeats}。',
              '仅测试工件，不是生产决策；正式结果、记忆、缓存前后字节/清单一致。',
              '冻结保存报告/injected/past及原配置。' if from_stage == 'debate' else '非完全冻结：保留原注入上下文，分析师工具会重新取数。',
              '区间差=(第二次边界−第一次边界)/原保存参考价×100%；配置差单位为百分点。',
              '实际用量见各重复llm_calls.jsonl，实际耗时与配置见result.json；缺失用量不能视为零成本。']
    report.extend(['\n## 实际执行耗时与用量', '```json', json.dumps(executions, ensure_ascii=False, indent=2), '```'])
    for row in comparisons:
        report.extend([f"\n## {row['symbol']} 第{row['runs'][0]}/{row['runs'][1]}次",
                       '```json', json.dumps(row, ensure_ascii=False, indent=2), '```'])
    destination.mkdir(parents=True, exist_ok=True)
    path = destination/(run_id+'.md')
    path.write_text('\n'.join(report)+'\n')
    atomic_write_json(destination/run_id/stamp/'summary.json', {'comparisons': comparisons, 'executions': executions,
                      'protected_before': before, 'protected_after': after, 'test_only': True})
    return {'report': str(path), 'comparisons': comparisons, 'test_only': True}

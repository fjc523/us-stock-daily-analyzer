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
from daily_analyzer.model_usage import call_evidence

REPORT_FIELDS = ('market_report', 'sentiment_report', 'news_report', 'fundamentals_report')
INITIAL_FIELDS = ('company_of_interest', 'company_name', 'trade_date', 'asset_type',
                  'instrument_context', 'instrument_context_full', 'instrument_context_brief',
                  'past_context', 'portfolio_context', 'context_compaction', 'context_profiles')
REQUIRED_FIELDS = ('company_of_interest', 'trade_date', 'asset_type', 'instrument_context',
                   'instrument_context_full', 'instrument_context_brief', 'past_context', 'portfolio_context')
RATINGS = ('Sell', 'Underweight', 'Hold', 'Overweight', 'Buy')
CLAUDE_TEST_BUDGET = {'role_llm_fallback':False,'claude_retries':0,'claude_timeout':600,'claude_max_concurrency':1}
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
    config.update(CLAUDE_TEST_BUDGET)
    if config.get('role_llm_fallback') is not False or config.get('claude_retries') != 0:
        raise ValueError('一致性入口必须关闭角色回退和重试')
    config.update(results_dir=str(output/'results'), data_cache_dir=str(output/'cache'),
                  memory_log_path=str(output/'memory'/'unused.md'),
                  evaluation_outcomes_path=str(output/'unused-outcomes.jsonl'),
                  checkpoint_enabled=False, late_news_refresh=False,
                  codex_usage_log_path=str(output/'llm_calls.jsonl'),
                  codex_prompt_log_dir=None, analysis_mode='consistency_test')
    config = {key: value for key, value in config.items() if not key.startswith('_')}
    return config


def decision_workflow(original, config=None):
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
        from tradingagents.graph.role_llms import legacy_first
        workflow.add_edge(START, legacy_first(config or {}))
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
        compiled = decision_workflow(graph.workflow, config).compile()
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


def validate_test_overrides(snapshot, overrides):
    """只允许角色模型及显式顺序；所有原数据/全局模型/轮数继续冻结。"""
    from tradingagents.graph.role_llms import resolve_overrides, DEEP_ROLES
    allowed={'role_llm_overrides','role_llm_scheme','legacy_speaker_rotation'}
    if set(overrides or {})-allowed:
        raise ValueError('受限测试禁止改变冻结配置')
    config={**snapshot['config'], **(overrides or {})}
    if type(config.get('legacy_speaker_rotation',False)) is not bool:
        raise ValueError('受限测试禁止改变冻结配置：顺序开关须布尔')
    try:roles=resolve_overrides(config)
    except (ValueError,TypeError,KeyError) as exc:
        raise ValueError('受限测试禁止改变冻结配置：角色配置无效') from exc
    for role,value in roles.items():
        if value['provider']=='codex_exec':
            tier='deep' if role in DEEP_ROLES else 'quick'
            original={'provider':snapshot['config']['llm_provider'], 'model':snapshot['config'][f'{tier}_think_llm'],
                      'effort':snapshot['config'].get(f'codex_{tier}_reasoning_effort')}
            if value!=original:raise ValueError('受限测试禁止改变冻结配置：Sol角色须原模型/档位')
    return config


def compared_allocation(value):
    """仅比较器兼容两种标准仓百分数键；不改变正式结算。"""
    from .settlement import allocation, number
    if isinstance(value,dict):
        a=number(value.get('target_allocation'));b=number(value.get('target_allocation_pct'))
        if a is not None and b is not None and a!=b:return None,'conflict'
        result=a if a is not None else b
    else:result=allocation(value)
    return result,'available' if result is not None else 'missing'


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
        (a, status_a), (b, status_b) = compared_allocation(left), compared_allocation(right)
        layers[layer] = {'ratings': [rating_a, rating_b],
                         'same_rating': rating_a == rating_b if rating_a in RATINGS and rating_b in RATINGS else None,
                         'rating_gap': abs(RATINGS.index(rating_a)-RATINGS.index(rating_b)) if rating_a in RATINGS and rating_b in RATINGS else None,
                         'allocation_availability': [status_a,status_b],
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
            'entry_availability_reasons': [None if plan['parse_status']=='parsed' else '不适用，候选点位不是可执行建仓区间' if plan['parse_status']=='not_applicable' else plan.get('reason','无法解析') for plan in plans],
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


def original_data_hash(snapshot):
    """跨baseline/A/B对齐原报告、注入、日期与价格；不把组配置混入数据hash。"""
    payload = {key: snapshot.get(key) for key in ('reports', 'injected_context', 'reference_price')}
    payload['trade_date'] = snapshot['state']['trade_date']
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def reconstructed_records(root, run_id, paths):
    """受限输入只读原件校验；无原件/hash/授权即拒绝，不能静默补历史。"""
    records = []
    for path in paths:
        path = Path(path).resolve()
        if not path.is_relative_to(root/'data/evaluation'):
            raise ValueError('重建snapshot必须位于独立data/evaluation目录')
        snapshot = json.loads(path.read_text())
        build_debate_state(snapshot)
        metadata = snapshot.get('reconstruction', {})
        if not isinstance(metadata, dict):
            raise ValueError('重建来源metadata必须是对象')
        if metadata.get('reconstructed') is not True or metadata.get('explicitly_authorized') is not True:
            raise ValueError('缺显式授权的历史重建标记')
        symbol = metadata.get('symbol', '')
        if not re.fullmatch(r'[A-Za-z0-9^][A-Za-z0-9.^_-]*', symbol) or metadata.get('original_run_id') != run_id:
            raise ValueError('重建原run-id/标的不匹配')
        if not metadata.get('original_missing') or snapshot['state']['past_context'] != '':
            raise ValueError('重建必须声明原缺失及显式空past，不能冒原历史')
        if _public_config(snapshot) != snapshot:
            raise ValueError('重建配置含凭据或运行闭包字段，禁止测试落盘')
        matches = list((root/'data/runs').glob('*/batches/'+run_id+'/results/'+symbol+'.json'))
        if len(matches) != 1:
            raise ValueError('重建原结果缺失或不唯一')
        original = matches[0].read_bytes()
        if hashlib.sha256(original).hexdigest() != metadata.get('record_sha256'):
            raise ValueError('重建原结果hash不匹配')
        record = json.loads(original)
        sha = lambda text: hashlib.sha256(text.encode()).hexdigest()
        for field in REPORT_FIELDS:
            text = snapshot['reports'][field]
            if text != record.get('reports', {}).get(field, '') or sha(text) != metadata.get('report_hashes', {}).get(field):
                raise ValueError('重建报告原文/hash不匹配')
        if snapshot['injected_context'] != record.get('injected_context') or sha(snapshot['injected_context']) != metadata.get('injected_hash'):
            raise ValueError('重建injected原文/hash不匹配')
        reference = record.get('context_blocks', {}).get('price_anchors', {}).get('data', {}).get('anchors', {}).get('P_Close', {}).get('value')
        if snapshot.get('reference_price') != reference or reference is None or snapshot['state']['trade_date'] != record.get('upstream_trade_date'):
            raise ValueError('重建日期/原P_Close不匹配')
        state, config = snapshot['state'], snapshot['config']
        if record.get('symbol') != symbol or state['asset_type'] != record.get('type'):
            raise ValueError('重建原标的/资产类型不匹配')
        if record.get('name') is not None and state.get('company_name') != record['name']:
            raise ValueError('重建原可得名称不匹配')
        portfolio = record.get('portfolio_context')
        if state['portfolio_context'] != ('' if portfolio is None else portfolio):
            raise ValueError('重建原组合上下文不匹配')
        dates = {'trade_date': record.get('upstream_trade_date'),
                 'price_data_end_date': record.get('price_data_end_date'),
                 'news_cutoff_utc': record.get('news_cutoff_utc')}
        if any(key not in config or config[key] != value for key, value in dates.items()):
            raise ValueError('重建原配置日期/信息截止不匹配')
        llm = record.get('llm', {})
        expected = {'llm_provider': llm.get('provider'), 'quick_think_llm': llm.get('quick', {}).get('model'),
                    'deep_think_llm': llm.get('deep', {}).get('model'),
                    'codex_quick_reasoning_effort': llm.get('quick', {}).get('reasoning_effort'),
                    'codex_deep_reasoning_effort': llm.get('deep', {}).get('reasoning_effort')}
        if any(snapshot['config'].get(key) != value for key, value in expected.items()):
            raise ValueError('重建原模型参数不匹配')
        saved_state = matches[0].parent/symbol/'state'/('full_states_log_'+snapshot['state']['trade_date']+'.json')
        if not saved_state.is_file():
            raise ValueError('原保存run_settings缺失')
        settings = json.loads(saved_state.read_text()).get('run_settings', {})
        if snapshot['selected_analysts'] != settings.get('analysts') or any(
                snapshot['config'].get(key) != value for key, value in settings.items() if key not in ('version', 'analysts')):
            raise ValueError('重建原轮数/分析师/语言/来源链不匹配')
        if snapshot['config'].get('debate_mode') != 'legacy' or metadata.get('debate_mode_provenance', {}).get('status') != 'inferred':
            raise ValueError('受限方案必须声明原兼容legacy推断')
        if record.get('status') != 'success' or snapshot['state']['company_of_interest'] != record.get('analyzed_symbol'):
            raise ValueError('重建标的身份/原成功状态不匹配')
        records.append({'symbol': symbol, 'status': 'success', 'consistency_input': snapshot,
                        'snapshot_path': str(path), 'snapshot_file_sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    if len({record['symbol'] for record in records}) != len(records):
        raise ValueError('重建标的重复')
    return records


def implementation_version():
    """记录测试源码指纹；旧baseline未采此字段，不能冒称相同执行版本。"""
    import subprocess
    root=Path(__file__).resolve().parents[3]
    relative=('src/daily_analyzer/evaluation/consistency.py','src/daily_analyzer/model_usage.py',
              'src/daily_analyzer/config.py','src/daily_analyzer/analyzer.py','src/daily_analyzer/runner.py',
              'TradingAgents/tradingagents/graph/role_llms.py','TradingAgents/tradingagents/graph/role_fallback.py',
              'src/daily_analyzer/model_scheme.py','TradingAgents/tradingagents/graph/setup.py',
              'TradingAgents/tradingagents/llm_clients/claude_exec/runner.py')
    hashes={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in relative if (root/name).exists()}
    heads={}
    for name,path in (('main',root),('TradingAgents',root/'TradingAgents')):
        result=subprocess.run(['git','-C',str(path),'rev-parse','HEAD'],capture_output=True,text=True)
        heads[name]=result.stdout.strip() if result.returncode==0 else 'NOT_REPORTED'
    return {'heads':heads,'source_sha256':hashes,'scope':'本次磁盘源码指纹，HEAD不代表未提交内容'}


def run_consistency(root, run_id, *, repeats=2, from_stage='debate', test_mode=False, symbols=None,
                    executor=execute_saved, monotonic=time.monotonic, overrides=None,
                    snapshot_paths=None, reconstructed=False, group=None):
    """必须显式test_mode；所有输入先检查后调用，避免部分消费才发现缺口。"""
    if not test_mode:
        raise ValueError('一致性重复仅允许显式测试入口：请指定--test-mode；生产默认关闭')
    if from_stage not in ('debate', 'analysts') or not (1 if reconstructed else 2) <= repeats <= 10:
        raise ValueError('测试起点须debate/analysts，重复次数须2–10')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', run_id):
        raise ValueError('非法run-id')
    if bool(snapshot_paths) != reconstructed:
        raise ValueError('独立snapshot与--reconstructed必须同时显式指定')
    if reconstructed and (from_stage != 'debate' or not group):
        raise ValueError('受限重建只允许debate起点并显式指定测试group')
    if group is not None and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', group):
        raise ValueError('非法测试group')
    if overrides and _public_config(overrides) != overrides:
        raise ValueError('测试覆盖配置含凭据或运行闭包字段')
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
    if reconstructed:
        records = reconstructed_records(root, run_id, snapshot_paths)
    else:
        batches = list((root/'data/runs').glob('*/batches/'+run_id))
        if len(batches) != 1:
            raise ValueError('run-id不存在或不唯一')
        records = [json.loads(path.read_text()) for path in sorted((batches[0]/'results').glob('*.json'))]
    records = [record for record in records if record.get('status') == 'success'
               and (symbols is None or record.get('symbol') in symbols)]
    if not records or (symbols is not None and set(symbols) != {r['symbol'] for r in records}):
        raise ValueError('找不到指定成功标的')
    for record in records:
        if str(record.get('consistency_input_status') or '').startswith('unavailable:'):
            raise ValueError('保存一致性快照不可用：'+record['consistency_input_status'])
        build_debate_state(record.get('consistency_input'))
        validate_test_overrides(record['consistency_input'], overrides)
        if not reconstructed and record['consistency_input'].get('reconstruction', {}).get('reconstructed'):
            raise ValueError('历史重建输入必须通过显式受限测试入口')
        if not re.fullmatch(r'[A-Za-z0-9^][A-Za-z0-9.^_-]*', record.get('symbol', '')):
            raise ValueError('非法保存标的代码')
    destination = root/'data/evaluation/consistency'
    before = protected_fingerprint(root)
    stamp = str(time.time_ns())
    comparisons = []
    executions = []
    version=implementation_version()
    for record in records:
        snapshot = record['consistency_input']
        digest = input_hash(snapshot)
        effective_hash = input_hash({**snapshot['config'], **(overrides or {}), **CLAUDE_TEST_BUDGET})
        symbol = record['symbol']
        if not re.fullmatch(r'[A-Za-z0-9^][A-Za-z0-9.^_-]*', symbol):
            raise ValueError('非法保存标的代码')
        states = []
        for repeat in range(repeats):
            output = destination/run_id/(group or 'strict')/stamp/symbol/str(repeat+1) if group else destination/run_id/stamp/symbol/str(repeat+1)
            started = monotonic()
            final = executor(deepcopy(snapshot), output, from_stage=from_stage, overrides=overrides, project_root=root)
            duration = monotonic()-started
            if input_hash(snapshot) != digest:
                raise ValueError('冻结输入被修改')
            usage_path = output/'llm_calls.jsonl'
            calls = [json.loads(line) for line in usage_path.read_text().splitlines() if line.strip()] if usage_path.exists() else []
            if any(row.get('result')=='fallback' for row in calls):
                raise ValueError('一致性结果含角色回退，拒绝混合模型')
            atomic_write_json(output/'result.json', {'test_only': True, 'production_decision': False,
                'input_hash': digest, 'effective_config_hash': effective_hash, 'from_stage': from_stage, 'fully_frozen': from_stage == 'debate' and not reconstructed,
                'reconstructed': reconstructed, 'reconstruction': snapshot.get('reconstruction'), 'group': group,
                'original_data_hash': original_data_hash(snapshot), 'input': snapshot,
                'snapshot_file_sha256': record.get('snapshot_file_sha256'), 'implementation_version':version,
                'test_resource_provenance':{'source':'用户显式测试资源限制，不改原snapshot/生产默认','config':CLAUDE_TEST_BUDGET},
                'config': isolated_config(snapshot, output, from_stage=from_stage, overrides=overrides),
                'duration_seconds': duration, 'llm_usage': calls,
                'role_call_evidence': call_evidence(calls),
                'usage_status': '实际调用日志' if calls else 'NOT_TESTED：未取得实际用量，不作零成本', 'state': final})
            executions.append({'symbol': symbol, 'repeat': repeat+1, 'duration_seconds': duration,
                               'group': group, 'input_hash': digest, 'effective_config_hash': effective_hash, 'original_data_hash': original_data_hash(snapshot),
                               'call_count': len(calls) if calls else None,
                               'tokens': [call.get('tokens') for call in calls] if calls else 'NOT_TESTED'})
            states.append(final)
        for a, b in combinations(range(repeats), 2):
            comparisons.append({'symbol': symbol, 'runs': [a+1, b+1], 'input_hash': digest,
                                **compare_states(states[a], states[b], snapshot.get('reference_price'))})
    after = protected_fingerprint(root)
    if before != after:
        raise ValueError('测试前后正式结果/记忆/缓存发生变化，工件不得视为通过')
    report = ['# 同输入一致性测试', f'原运行：{run_id}；起点：{from_stage}；重复：{repeats}。',
              '仅测试工件，不是生产决策；正式结果、记忆、缓存前后字节/清单一致。',
              '历史重建/缩样：原past缺失显式空，身份/档位/配置重建见各输入来源；不是原历史完全冻结。' if reconstructed else '冻结保存报告/injected/past及原配置。' if from_stage == 'debate' else '非完全冻结：保留原注入上下文，分析师工具会重新取数。',
              '区间差=(第二次边界−第一次边界)/原保存参考价×100%；配置差单位为百分点。',
              '实际用量见各重复llm_calls.jsonl，实际耗时与配置见result.json；缺失用量不能视为零成本。']
    report.extend(['\n## 实际执行耗时与用量', '```json', json.dumps(executions, ensure_ascii=False, indent=2), '```'])
    for row in comparisons:
        report.extend([f"\n## {row['symbol']} 第{row['runs'][0]}/{row['runs'][1]}次",
                       '```json', json.dumps(row, ensure_ascii=False, indent=2), '```'])
    destination.mkdir(parents=True, exist_ok=True)
    path = destination/(run_id+('-'+group if group else '')+'-'+stamp+'.md')
    path.write_text('\n'.join(report)+'\n')
    summary_dir = destination/run_id/group/stamp if group else destination/run_id/stamp
    atomic_write_json(summary_dir/'summary.json', {'comparisons': comparisons, 'executions': executions,
                      'reconstructed': reconstructed, 'group': group,
                      'protected_before': before, 'protected_after': after, 'test_only': True})
    return {'report': str(path), 'comparisons': comparisons, 'executions': executions, 'test_only': True}

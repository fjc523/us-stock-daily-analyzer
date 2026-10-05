"""跨订阅模型用量只按来源原字段解释，缺失不冒充零消费。"""
def call_evidence(rows):
    evidence=[]
    for row in rows:
        usage=row.get('tokens')
        usage=usage if isinstance(usage,dict) else None
        provider=row.get('provider','codex_exec')
        prompt=None
        if usage is not None:
            if provider=='claude_exec':
                parts=[usage.get(key) for key in ('input_tokens','cache_creation_input_tokens','cache_read_input_tokens')]
                if all(isinstance(value,(int,float)) for value in parts):prompt=sum(parts)
            else:
                # Sol cached_input是input的子集，不能重复相加。
                prompt=usage.get('input_tokens',usage.get('prompt_tokens'))
        evidence.append({'role':row.get('role'),'provider':provider,'model':row.get('model'),
                         'model_evidence':'实际CLI校验' if provider=='claude_exec' and row.get('model') else '配置模型，未返回实际模型' if provider=='codex_exec' else 'NOT_REPORTED',
                         'observed_api_providers':row.get('actual_api_providers'),
                         'configured_effort':row.get('configured_effort',row.get('reasoning_effort')),
                         'effective_effort':row.get('effective_effort','NOT_REPORTED'),
                         'tokens':usage,'total_prompt_tokens':prompt,
                         'prompt_token_basis':'Claude input+creation+read，缺一未知' if provider=='claude_exec' else 'Sol input含cached子集',
                         'estimated_cost_usd':row.get('estimated_cost_usd'),
                         'cost_basis':row.get('cost_basis','NOT_REPORTED：无实际费率不造美元'),
                         'result':row.get('result'),
                         **({key:row.get(key) for key in ('category','from','to','breaker')} if row.get('result')=='fallback' else {})})
    return evidence



def mixed_usage(rows):
    """混合调用每指标独立完整性；原input合计不冒称统一prompt合计。"""
    def numeric(value):return isinstance(value,(int,float)) and not isinstance(value,bool)
    def reported(row,names):
        usage=row.get('tokens')
        if not isinstance(usage,dict):return None
        for name in names:
            value=usage.get(name)
            if numeric(value):return value
        return None
    def complete(values):return sum(values) if values and all(numeric(value) for value in values) else None
    fallback_count=sum(row.get('result')=='fallback' for row in rows)
    rows=[row for row in rows if row.get('result')!='fallback']
    evidence=call_evidence(rows)
    metrics={
        'input_tokens':[reported(row,('input_tokens','prompt_tokens')) for row in rows],
        'cached_input_tokens':[reported(row,('cache_read_input_tokens',) if row.get('provider')=='claude_exec' else ('cached_input_tokens','cache_read_input_tokens')) for row in rows],
        'output_tokens':[reported(row,('output_tokens','completion_tokens')) for row in rows],
        'reasoning_output_tokens':[reported(row,('reasoning_output_tokens','reasoning_tokens')) for row in rows],
        'cache_creation_input_tokens':[reported(row,('cache_creation_input_tokens',)) for row in rows if row.get('provider')=='claude_exec'],
        'total_prompt_tokens':[row['total_prompt_tokens'] for row in evidence]}
    # Claude只有明确thinking明细时才计推理token；无字段继续未知。
    for index,row in enumerate(rows):
        if metrics['reasoning_output_tokens'][index] is None:
            usage=row.get('tokens')
            details=usage.get('output_tokens_details') if isinstance(usage,dict) else None
            value=details.get('thinking_tokens') if isinstance(details,dict) else None
            if numeric(value):metrics['reasoning_output_tokens'][index]=value
    totals={key:complete(values) for key,values in metrics.items()}
    return {'calls':len(rows),'fallback_count':fallback_count,**totals,'model_calls':evidence,
            'metric_status':{key:'REPORTED' if totals[key] is not None else 'NOT_REPORTED' for key in metrics},
            'input_token_basis':'原input字段合计；统一prompt见total_prompt_tokens（Sol不重复加缓存，Claude含creation/read）'}


def role_execution_evidence(configured,rows,ticker, auth_failed_role=None):
    """角色配置与控制日志观察分列，尚未执行不声称实际模型。"""
    aliases={'Bull Researcher':'bull','Bull Opening':'bull','Bull Rebuttal':'bull',
             'Bear Researcher':'bear','Bear Opening':'bear','Bear Rebuttal':'bear',
             'Research Manager':'research_manager','Trader':'trader',
             'Aggressive Analyst':'aggressive','Neutral Analyst':'neutral','Conservative Analyst':'conservative','Portfolio Manager':'portfolio_manager'}
    result={}
    for role,config in configured.items():
        calls=[row for row in rows if row.get('ticker')==ticker and aliases.get(row.get('role') or row.get('agent_name'),row.get('role') or row.get('agent_name'))==role]
        fallback=next((row for row in reversed(calls) if row.get('result')=='fallback'),None)
        actual=[row for row in calls if row.get('provider')=='claude_exec' and row.get('model')]
        result[role]={'configured':config,'call_count':sum(row.get('result')!='fallback' for row in calls),
                      'auth_preflight_rejected':role==auth_failed_role,
                      'status':'FALLBACK' if fallback else 'AUTH_REJECTED_ZERO_MODEL_REQUESTS' if role==auth_failed_role and not calls else 'NOT_EXECUTED_OR_NOT_RECORDED' if not calls else 'SUCCESS' if all(row.get('result')=='success' for row in calls) else 'FAILED' if all(row.get('result')!='success' for row in calls) else 'MIXED',
                      'observed':{'models':sorted({row['model'] for row in actual}) or None,
                                  'providers':sorted({provider for row in calls for provider in (row.get('actual_api_providers') or [])}) or None,
                                  'model_status':'CLI_CONTROL_REPORTED' if actual else 'NOT_REPORTED：Sol配置或未执行不作为实际模型证明'},
                      'calls':call_evidence(calls)}
        if fallback:result[role]['fallback']={key:fallback.get(key) for key in ('result','role','category','from','to','breaker')}
    return result


def apply_execution_labels(result, config):
    """角色回退写入决策标记，方案标签只标记当前新结果。"""
    from daily_analyzer.model_scheme import result_scheme
    llm=result.setdefault('llm',{})
    for role,layer in (('research_manager','rm'),('trader','trader'),('portfolio_manager','pm')):
        evidence=(llm.get('roles') or {}).get(role) or {}
        if evidence.get('fallback'):
            result.setdefault('decision_flags',{}).setdefault(layer,{})['llm_fallback']=evidence['fallback']['category']
    llm.update(result_scheme(result,config))

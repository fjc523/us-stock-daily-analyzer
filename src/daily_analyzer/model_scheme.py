"""模型方案来源与指纹；旧记录只读推断，不改去重键。"""
from collections import Counter
import hashlib
import json


def overrides_fingerprint(overrides):
    payload=json.dumps(overrides,sort_keys=True,ensure_ascii=False,separators=(',',':'))
    return hashlib.sha256(payload.encode()).hexdigest()[:8]


def model_fingerprint(llm):
    parts=[]
    for tier in ('deep','quick'):
        value=llm.get(tier) or {}
        parts.append(f"{tier}={value.get('model') or 'NOT_REPORTED'}/{value.get('reasoning_effort') or value.get('effort') or 'NOT_REPORTED'}")
    return ';'.join(parts)


def result_scheme(result, config=None):
    """新结果按显式配置写入；旧结果识别已记录角色配置，不猜当前默认值。"""
    llm=result.get('llm') or {}
    roles=llm.get('roles') or {}
    fallback_roles=sorted(role for role,value in roles.items() if isinstance(value,dict) and value.get('fallback'))
    if config is None and llm.get('scheme'):
        output={key:llm[key] for key in ('scheme','overrides_fingerprint','model_fingerprint','fallback_roles') if key in llm}
        output.setdefault('model_fingerprint',model_fingerprint(llm))
        output['source']='result_explicit'
        return output
    overrides=(config or {}).get('role_llm_overrides') or {}
    scheme=(config or {}).get('role_llm_scheme')
    if config is None:
        configured={role:value.get('configured',value) for role,value in roles.items() if isinstance(value,dict)}
        claude={role for role,value in configured.items() if value.get('provider')=='claude_exec' and value.get('model')=='claude-opus-5-5' and (value.get('effort') or value.get('configured_effort'))=='high'}
        others_valid=all(value.get('provider')=='codex_exec' for role,value in configured.items() if role not in claude)
        if claude=={'research_manager','trader','portfolio_manager'} and others_valid:scheme='B'
        elif claude in ({'bull','aggressive'},{'bear','conservative'}) and others_valid:scheme='A'
        elif configured:overrides=configured
    fingerprint=overrides_fingerprint(overrides) if overrides else None
    label='custom:'+fingerprint if fingerprint else 'A' if scheme=='A' else 'B+fallback' if scheme=='B' and fallback_roles else 'B' if scheme=='B' else 'default'
    output={'scheme':label,'model_fingerprint':model_fingerprint(llm),'source':'result_explicit' if config is not None else 'inferred_from_result'}
    if fingerprint:output['overrides_fingerprint']=fingerprint
    if fallback_roles:output['fallback_roles']=fallback_roles
    return output


def record_scheme(row):
    """结算旧键缺字段时仅用于报告显示。"""
    value=row.get('llm') or {}
    if value.get('scheme'):return value
    return {'scheme':'default','model_fingerprint':'deep=NOT_REPORTED/NOT_REPORTED;quick=NOT_REPORTED/NOT_REPORTED','source':'inferred_unwritten'}


def scheme_counts(rows):
    return Counter(record_scheme(row)['scheme'] for row in rows)

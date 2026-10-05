"""概率校准仅使用对应层/窗口成熟且有概率的同样本。"""
import math
import re

from tradingagents.agents.rating import PROBABILITY_BANDS, probability_rating


def probability(value):
    try:
        value=float(value.strip()[:-1])/100 if isinstance(value,str) and value.strip().endswith('%') else float(value)
    except (ValueError,TypeError):
        return None
    return value if math.isfinite(value) and 0<=value<=1 else None


def extract_probabilities(result):
    """优先真实model_dump，自由文本仅认显式概率标签。"""
    output={}
    for layer,key,text_key in [('rm','research_plan','investment_plan'),('pm','pm_decision','final_trade_decision')]:
        structured=(result.get('structured') or {}).get(key)
        values={}
        for window in (5,20):
            field=f'prob_outperform_{window}d'
            if isinstance(structured,dict):
                value=structured.get(field)
            else:
                match=re.search(r'(?mi)^\s*\*\*Prob Outperform '+str(window)+r'd\*\*\s*[:：]\s*([0-9]+(?:\.\d+)?%?)\s*$',str(result.get(text_key) or ''))
                value=match[1] if match else None
            values[str(window)]=probability(value)
        output[layer]=values
    return output


def calibration(pairs):
    """评级档箱左闭右开，最后含1；基准为样本内经验率。"""
    valid=[(parsed,int(bool(y))) for p,y in pairs if (parsed:=probability(p)) is not None]
    n=len(valid)
    if not n:
        return {'n':0,'brier':None,'ece':None,'base_rate':None,'baseline_brier':None,'bins':[]}
    base=sum(y for _,y in valid)/n;bins=[];ece=0.
    for index, (rating, low, high) in enumerate(PROBABILITY_BANDS):
        group=[(p,y) for p,y in valid if probability_rating(p)==rating]
        count=len(group);mean=sum(p for p,_ in group)/count if count else None;rate=sum(y for _,y in group)/count if count else None
        if count:ece+=count/n*abs(mean-rate)
        bins.append({'rating':rating,'low':low,'high':high,'n':count,'probability':mean,'actual_rate':rate})
    return {'n':n,'brier':sum((p-y)**2 for p,y in valid)/n,'ece':ece,'base_rate':base,
            'baseline_brier':sum((base-y)**2 for _,y in valid)/n,'bins':bins}


def calibration_report(rows):
    lines=['## 校准','','仅对应层与5/20日已settled且概率可用的同样本；跑赢定义为主口径收益>0。历史基准率为同样本经验率，仅样本内描述，不是OOS。']
    for layer,label in [('rm','研究经理'),('pm','组合经理')]:
        for window in ('5','20'):
            pairs=[];pending=0;missing_probability=0;missing_return=0
            total=len(rows)
            missing_all=sum(probability(row.get('probabilities',{}).get(layer,{}).get(window)) is None for row in rows)
            for row in rows:
                outcome=row.get('windows',{}).get(window,{})
                if outcome.get('status')!='settled':pending+=1;continue
                p=probability(row.get('probabilities',{}).get(layer,{}).get(window))
                value=outcome.get('primary_return')
                missing_probability += p is None
                return_missing = isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value)
                missing_return += return_missing
                if p is None or return_missing:continue
                pairs.append((p,value>0))
            missing_rate=f'{missing_all/total:.1%}' if total else '不可计算'
            result=calibration(pairs);note='样本不足，仅供参考' if result['n']<30 else '描述性指标，不证明未来有效性'
            lines += ['',f'### {label} {window}日：n={result["n"]}；{note}；未成熟/不可用n={pending}，成熟缺概率n={missing_probability}，成熟缺主收益n={missing_return}；概率缺失率={missing_rate}（全保留记录 {missing_all}/{total}）']
            if not result['n']:
                lines.append('Brier/ECE：不可计算；真实成熟校准NOT_TESTED。');continue
            lines.append(f'Brier={result["brier"]:.4f}；ECE={result["ece"]:.4f}；历史基准率={result["base_rate"]:.4f}；基准Brier={result["baseline_brier"]:.4f}。')
            lines += ['','|概率箱|n|平均概率|实际跑赢率|','|---|---|---|---|']
            for index,group in enumerate(result['bins']):
                fmt=lambda value:f'{value:.4f}' if value is not None else '不可计算'
                lines.append(f'|[{group["low"]:g},{group["high"]:g}'+(']' if index==4 else ')')+f'|{group["n"]}|{fmt(group["probability"])}|{fmt(group["actual_rate"])}|')
    return '\n'.join(lines)

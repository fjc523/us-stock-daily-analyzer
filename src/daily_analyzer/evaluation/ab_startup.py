"""F2首日只读操作验收：checked对应实际计划、成功/缺失与账户名额。"""
from __future__ import annotations
import argparse
import json
from pathlib import Path


def check_t0_checked(manifest):
    """本工具不启动实验或自动停机，调用者须对失败执行disable并保全。"""
    def read(key):return json.loads(Path(manifest[key]).read_text())
    batch=read('batch');allocation=read('allocation');verification=read('verification')
    records={}
    for path in manifest['B_results']:
        row=json.loads(Path(path).read_text())
        if row['symbol'] in records:raise ValueError('B结果清单重复标的')
        records[row['symbol']]=row
    planned=batch['planned_items'];errors=[];table=[];expected=[]
    if not batch.get('scheduled') or batch.get('mode')!='live' or batch.get('status')!='completed':errors.append('首日批次不是成功定时live')
    if batch['trade_date']!=manifest['t0']:errors.append('首日批次日期不等于实际T0')
    for symbol in planned:
        row=records.get(symbol,{})
        success=row.get('status')=='success';snapshot=bool(row.get('consistency_input'))
        required=success and snapshot
        if required:expected.append(symbol)
        status=allocation['audit'].get(symbol)
        if status is None:errors.append(symbol+'缺账户/名额审计')
        items=[x for x in batch.get('items',{}).values() if x.get('symbol')==symbol]
        if any(x.get('status')=='success' for x in items) and not success:errors.append(symbol+'批次成功但B原件缺失')
        if success and (len(items)!=1 or items[0].get('status')!='success'):errors.append(symbol+'B成功与批次item状态不一致')
        if row and (row.get('run_id')!=batch['run_id'] or row.get('upstream_trade_date')!=batch['trade_date']):errors.append(symbol+'结果run_id/日期冲突')
        table.append({'symbol':symbol,'B_success':success,'snapshot':snapshot,'symmetric_missing':not required,
                      'allocation_audit':status,'run_A':symbol in allocation['run_symbols'],'expected_checked':required})
    audit_running={s for s,status in allocation['audit'].items() if status=='运行A'}
    if len(allocation['run_symbols'])!=len(set(allocation['run_symbols'])) or set(allocation['run_symbols'])!=audit_running:
        errors.append('audit运行A与名额列表不一致或名额重复')
    actual=[x['symbol'] for x in verification['checked']]
    if verification.get('status')!='passed':errors.append('verification未通过')
    if not expected:errors.append('没有任何应验成功B，不得以空checked验收首日')
    if len(actual)!=len(set(actual)) or set(actual)!=set(expected):errors.append('checked与实际应验标的不符')
    if len(allocation['run_symbols'])>4 or not set(allocation['run_symbols'])<=set(expected):errors.append('A名额超限或不是应验成功标的')
    if allocation.get('planned_items')!=planned or allocation.get('day')!=batch['trade_date']:errors.append('账户计划/日期与首日批次不符')
    return {'run_id':batch['run_id'],'day':batch['trade_date'],'planned':planned,'table':table,
            'expected_checked':expected,'actual_checked':actual,'extra_B_results':sorted(set(records)-set(planned)),
            'run_A':allocation['run_symbols'],'errors':errors,'passed':not errors,
            'boundary':'离线核对应验范围，不替代同源gate、T0−1结算日志、D1–D5自然结构验收；失败须负责人disable并保全'}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--manifest',type=Path,required=True);args=parser.parse_args()
    result=check_t0_checked(json.loads(args.manifest.read_text()))
    print(json.dumps(result,ensure_ascii=False,indent=2));return int(not result['passed'])


if __name__=='__main__':raise SystemExit(main())

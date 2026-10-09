"""首日checked按实际计划对应，不硬编码四标或忽略应验缺件。"""
import pytest
from daily_analyzer.evaluation.ab_startup import check_t0_checked
from daily_analyzer.storage import atomic_write_json

@pytest.mark.parametrize('case',['valid','empty','short','extra_checked','missing_success','slot_over','audit_missing','slot_missing','batch_failure'])
def test_checked_actual_plan_and_slots(tmp_path,case):
    planned=['SPY','QQQ','TSLA','SPCX','X']
    batch={'scheduled':True,'mode':'live','status':'completed','run_id':'t0','trade_date':'2026-10-12','planned_items':planned,'items':{s:{'symbol':s,'status':'failed' if s=='SPCX' else 'success'} for s in planned}}
    allocation={'day':batch['trade_date'],'planned_items':planned,'run_symbols':['SPY','QQQ','TSLA','X'],
                'audit':{s:'缺失' if s=='SPCX' else '运行A' for s in planned}}
    symbols=['SPY','QQQ','TSLA','X'];paths=[]
    for symbol in symbols:
        path=tmp_path/f'{symbol}.json';atomic_write_json(path,{'symbol':symbol,'run_id':'t0','upstream_trade_date':'2026-10-12','status':'success','consistency_input':{'原件':True}});paths.append(str(path))
    checked=symbols.copy()
    if case=='empty':checked=[]
    if case=='short':checked.pop()
    if case=='extra_checked':checked.append('SPCX')
    if case=='missing_success':paths.pop();checked.pop()
    if case=='slot_over':allocation['run_symbols']=planned
    if case=='audit_missing':allocation['audit']['SPY']='缺失'
    if case=='slot_missing':allocation['run_symbols'].remove('SPY')
    if case=='batch_failure':batch['items']['SPY']['status']='failed'
    manifest={'B_results':paths,'t0':'2026-10-12'}
    for key,value in [('batch',batch),('allocation',allocation),('verification',{'status':'passed','checked':[{'symbol':s} for s in checked]})]:
        path=tmp_path/(key+'.json');atomic_write_json(path,value);manifest[key]=str(path)
    result=check_t0_checked(manifest)
    assert result['passed']==(case=='valid')
    if case=='valid':assert result['table'][3]['symmetric_missing'] and not result['table'][3]['expected_checked']

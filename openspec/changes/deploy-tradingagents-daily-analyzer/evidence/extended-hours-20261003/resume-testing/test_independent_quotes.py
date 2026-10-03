"""独立构造原始字段形状，不冒充旧批次录制的行情响应。"""
from datetime import datetime
import copy
import hashlib
import json
from pathlib import Path
import pytest
from daily_analyzer.context.analysis_quote import observation, raw_alpaca, raw_futu
from daily_analyzer.site import _summary_premarket
from test_context_providers import FakeFutu, FakeAlpaca, _extended_provider

@pytest.mark.parametrize('cutoff,session,stamp',[
 ('2026-10-01T08:31:00-04:00','pre','2026-10-01T08:30:00-04:00'),
 ('2026-10-01T12:10:00-04:00','regular','2026-10-01T12:09:00-04:00'),
 ('2026-10-01T18:00:00-04:00','after','2026-10-01T17:59:00-04:00'),
 ('2026-10-01T22:00:00-04:00','overnight','2026-10-01T21:59:00-04:00')])
def test_provider_alpaca_four_sessions(cutoff,session,stamp):
 feed='overnight' if session=='overnight' else 'iex'
 alpaca=FakeAlpaca(snapshots={feed:{'NVDA':{'latestTrade':{'p':111,'t':stamp}}}})
 provider,_=_extended_provider(FakeFutu(mode='unavailable'),alpaca)
 block=provider.build({'symbol':'NVDA','type':'stock'},cutoff)
 q=block.data['NVDA']['analysis_quote']
 assert (q['status'],q['session'],q['price'],q['quote_time'])==('可用',session,111,stamp)
 assert q['time_field']=='latestTrade.t'
 if feed=='iex': assert q['warning']=='IEX 覆盖不完整'

def test_provider_sdk_regular_and_no_extension_timestamp_invention():
 row={'last_price':200,'data_date':'2026-10-01','data_time':'12:09:00','pre_price':198,'after_price':199}
 provider,_=_extended_provider(FakeFutu(rows={'US.NVDA':row}))
 data=provider.build({'symbol':'NVDA','type':'stock'},'2026-10-01T12:10:00-04:00').data['NVDA']
 assert data['analysis_quote']['price']==200
 assert data['analysis_quote']['quote_time']=='2026-10-01T12:09:00-04:00'
 assert data['analysis_quote']['status']=='可用'
 assert data['after']['quote_time'] is None and data['after']['status']=='时段未核验（无分时段时间）'

@pytest.mark.parametrize('stamp,status',[
 ('2026-10-01T12:11:00-04:00','未来报价（超过分析截止）'),
 ('2026-10-01T11:39:59-04:00','过期'),
 ('2026-10-01T08:30:00-04:00','非本时段数据'),
 (None,'真实行情时间未核验')])
def test_provider_rejects_bad_raw_trade_timestamp(stamp,status):
 snapshot={'latestTrade':{'p':200,'t':stamp},'updated_at':'2026-10-01T12:09:00-04:00'}
 provider,_=_extended_provider(FakeFutu(mode='unavailable'),FakeAlpaca(snapshots={'iex':{'NVDA':snapshot}}))
 q=provider.build({'symbol':'NVDA','type':'stock'},'2026-10-01T12:10:00-04:00').data['NVDA']['analysis_quote']
 assert q['status']==status


def test_backfill_blocks_real_sources_and_future_minute():
 futu=FakeFutu(mode='unavailable'); alpaca=FakeAlpaca()
 provider,batch=_extended_provider(futu,alpaca); batch['mode']='backfill'
 def forbidden(*args): raise AssertionError('回放禁止实时行情')
 futu.get_quotes=futu.get_snapshots=alpaca.snapshots=forbidden
 alpaca.minute_rows['NVDA']=[{'t':'2026-10-01T12:30:00Z','c':110,'v':1}, {'t':'2026-10-01T12:31:00Z','c':999,'v':2}]
 q=provider.build({'symbol':'NVDA','type':'stock'},'2026-10-01T08:31:00-04:00').data['NVDA']['analysis_quote']
 assert q['status']=='可用' and q['price']==110 and q['time_field']=='minute.t'
 assert q['quote_time']=='2026-10-01T08:30:00-04:00'

def result_with_quote():
 cutoff=datetime.fromisoformat('2026-10-01T12:10:00-04:00')
 q=observation('NVDA',cutoff,raw_alpaca({'latestTrade':{'p':200,'t':'2026-10-01T12:09:00-04:00'}},'Alpaca feed=iex'))
 return {'symbol':'NVDA','context_as_of':cutoff.isoformat(),'context_blocks':{'extended_hours':{'as_of':cutoff.isoformat(),'data':{'NVDA':{'analysis_quote':q}}}}}

def test_site_no_benchmark_keeps_price_and_repeat_is_immutable():
 result=result_with_quote(); before=copy.deepcopy(result)
 first=_summary_premarket(result); second=_summary_premarket(result)
 assert first==second and result==before
 assert first['price']=='200.00 美元' and first['change']=='—'
 assert '美东' in first['time'] and '北京' in first['time'] and 'P收盘基准未核验' in first['title']

@pytest.mark.parametrize('field,value',[('symbol','COHR'),('cutoff','2026-10-01T12:11:00-04:00')])
def test_site_rejects_mismatched_report(field,value):
 result=result_with_quote(); result['context_blocks']['extended_hours']['data']['NVDA']['analysis_quote'][field]=value
 shown=_summary_premarket(result)
 assert shown['price']=='' and shown['reason']=='分析截止或标的不匹配'

@pytest.mark.parametrize('symbol',['SMTC','COHR'])
def test_saved_report_is_read_only_and_missing_not_fabricated(symbol):
 path=Path('data/runs/2026-10-02/batches/20261002T114709-33696/results')/(symbol+'.json')
 before=path.read_bytes(); report=json.loads(before)
 assert report['context_blocks']['extended_hours']['data'][symbol]['pre']['price'] is not None
 shown=_summary_premarket(report)
 assert shown['price']=='' and '未核验' in shown['reason']
 assert path.read_bytes()==before

@pytest.mark.parametrize('cutoff,valid',[
 ('2026-10-02T22:00:00-04:00',False),
 ('2026-10-04T22:00:00-04:00',True),
 ('2026-09-06T22:00:00-04:00',False)])
def test_night_quote_next_trading_day_boundary(cutoff,valid):
 stamp=datetime.fromisoformat(cutoff)
 q=observation('NVDA',stamp,{'price':200,'quote_time':cutoff,'time_field':'latestTrade.t','source':'Alpaca feed=overnight'})
 assert (q['status']=='可用') is valid

def test_render_context_analysis_quote_does_not_change_model_input():
 from daily_analyzer.context.base import render_context
 base={'extended_hours':{'title':'扩展时段','markdown':'保留原始上下文','data':{'NVDA':{'pre':{'status':'可用','source':'富途快照'}}}}}
 updated=copy.deepcopy(base)
 updated['extended_hours']['data']['NVDA']['analysis_quote']={'price':200,'status':'过期','warning':'独立展示告警','source':'Alpaca feed=iex'}
 assert render_context(base,'2026-10-01T12:10:00-04:00')==render_context(updated,'2026-10-01T12:10:00-04:00')

@pytest.mark.parametrize('mode',['live','backfill'])
def test_actual_runner_serialization_quote_binding(tmp_path,monkeypatch,mode):
 from datetime import timedelta
 import daily_analyzer.runner as runner
 from daily_analyzer.context.base import ContextBlock
 from test_runner import _ContextManager,_FakeGraph,_project
 class FixedQuoteContext(_ContextManager):
  def build(self,item,cutoff):
   q=observation(item.symbol,cutoff,{'price':200,'quote_time':(cutoff-timedelta(minutes=1)).isoformat(),'time_field':'latestTrade.t','source':'Alpaca feed=iex'})
   return {'extended_hours':ContextBlock('扩展时段','保持模型上下文', {item.symbol:{'analysis_quote':q}},cutoff,['固定源'])}
 monkeypatch.setattr(runner,'_codex_version',lambda settings:'测试固定版本')
 monkeypatch.setattr(runner,'_fork_state',lambda root:{})
 root=_project(tmp_path,symbols=('NVDA',),parallelism=1)
 now=datetime.fromisoformat('2026-10-02T12:10:00.654321-04:00')
 _FakeGraph.fail_symbols=set()
 outcome=runner.run_analysis(root,date_value='2026-10-01' if mode=='backfill' else None,tickers='NVDA',force=True,
  clock=lambda:now,monotonic=lambda:100.0,sleeper=lambda seconds:None,
  context_manager_factory=lambda *args:FixedQuoteContext(),analyzer_factory=_FakeGraph,
  site_builder=lambda *args,**kwargs:{'ok':True})
 assert outcome.exit_code==0
 reports=list((root/'data/runs').glob('*/batches/*/results/NVDA.json'))
 assert len(reports)==1
 result=json.loads(reports[0].read_text())
 assert result['mode']==mode
 assert _summary_premarket(result)['price']=='200.00 美元'

def test_half_day_actual_nyse_close_is_after_session():
 cutoff=datetime.fromisoformat('2026-11-27T13:10:00-05:00')
 q=observation('NVDA',cutoff,raw_alpaca({'latestTrade':{'p':200,'t':'2026-11-27T13:09:00-05:00'}},'Alpaca feed=iex'))
 assert q['status']=='可用' and q['session']=='after'

def test_active_night_stale_futu_analysis_requests_alpaca_without_changing_extension():
 futu=FakeFutu(rows={'US.NVDA':{'overnight_price':99,'overnight_update_time':'2026-10-01 01:00:00'}})
 alpaca=FakeAlpaca(snapshots={'overnight':{'NVDA':{'latestTrade':{'p':101,'t':'2026-10-01T02:30:00-04:00'}}}})
 provider,_=_extended_provider(futu,alpaca)
 data=provider.build({'symbol':'NVDA','type':'stock'},'2026-10-01T02:31:00-04:00').data['NVDA']
 assert data['overnight']['price']==99 and data['overnight']['status']=='可用'
 assert data['overnight']['source']=='富途订阅报价'
 assert any(call[0]=='snapshots' and call[2]=='overnight' and 'NVDA' in call[1] for call in alpaca.calls)
 assert data['analysis_quote']['status']=='可用'
 assert data['analysis_quote']['price']==101 and data['analysis_quote']['source']=='Alpaca feed=overnight'
 assert data['analysis_quote']['quote_time']=='2026-10-01T02:30:00-04:00'

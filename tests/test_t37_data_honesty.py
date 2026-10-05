"""数据诚实及可选产物失败隔离，不使用网络或模型。"""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo
import pytest
from daily_analyzer.context.compaction import _difference, _calendar_unit, calendar_markdown
from daily_analyzer.context.providers import MacroReleasesProvider
from daily_analyzer.context.base import ProviderServices
from tradingagents.dataflows.vendors.yahoo.expectations import eps_change
from tradingagents.agents.rating import chinese_length,output_flags
ET=ZoneInfo('America/New_York')

@pytest.mark.parametrize('actual,estimate',[('2K','1'),('2','1K'),('2M','1'),('2','1M'),('2%','1')])
def test_one_unknown_unit_is_not_comparable(actual,estimate):
    assert '不可比较' in _difference(actual,estimate)

@pytest.mark.parametrize('actual,estimate,expected',[('2','1','+1（原单位）'),('2K','1M','-998K'),('2M','1K','+1.999M')])
def test_both_bare_or_both_explicit_units(actual,estimate,expected):
    assert expected in _difference(actual,estimate)

@pytest.mark.parametrize('title',['美国就业参与率','美国工厂订单月率','美国价格年率','美国GDP季率','美国设备利用率'])
def test_title_percent_without_suffix(title):
    assert _calendar_unit({'title':title})=='%'


def test_past_release_short_priority_and_future_actual_masked():
    rows=[{'title':'未来数据','star':'HIGH','发布时间ET':'2026-10-06T10:00:00-04:00','actual':'9','consensus':'7'},
          {'title':'周一ISM','star':'MEDIUM','发布时间ET':'2026-10-05T10:00:00-04:00','actual':'52.1','consensus':'51.0'}]
    text=calendar_markdown({'economics':rows},datetime(2026,10,6,8,30,tzinfo=ET),short=True)
    assert '已发布；+1.1（原单位）（高于预期）' in text
    assert text.index('周一ISM')<text.index('未来数据') and '|9|' not in text and '+2' not in text


def test_monday_request_start_p_and_future_horizon_unchanged(monkeypatch):
    source=Mock();source.calendars.return_value={'economics':[],'earnings':[],'warnings':[]}
    provider=MacroReleasesProvider(ProviderServices(futu_data=source))
    from tradingagents.dataflows import router
    monkeypatch.setattr(router,'route_to_vendor',lambda *a,**k:'离线宏观')
    # 仅验证日历请求，其他准备来源使用既有空来源分支。
    monkeypatch.setattr(provider,'services',SimpleNamespace(futu_data=source,yahoo=None))
    provider.prepare({'trade_date':'2026-10-05','price_data_end_date':'2026-10-02','items':[],'context_as_of':'2026-10-05T08:30:00-04:00'})
    assert str(source.calendars.call_args.args[0])=='2026-10-02'

@pytest.mark.parametrize('actual,base,expected',[(.26,-.2,'+230.00%'),(.26,.049999,'基数过小'),(.26,-.049999,'基数过小'),(.26,0,'基数过小'),(.26,.05,'+420.00%'),(.26,-.05,'+620.00%')])
def test_eps_absolute_base_boundary(actual,base,expected):
    assert expected in eps_change(actual,base)


def test_chinese_count_preserves_200_threshold_and_raw_len():
    assert chinese_length('754.54')==1 and chinese_length('中文；Alpha 754.54')==5
    flags=output_flags({'evidence_check':'字'*200}, {},layer='rm')
    assert flags['evidence_check_count']==200 and flags['evidence_check_raw_length']==200 and not flags.get('evidence_check_overlength')
    flags=output_flags({'evidence_check':'字'*201}, {},layer='rm')
    assert flags['evidence_check_overlength']

@pytest.mark.parametrize('available',[False,True])
def test_reddit_failure_is_not_zero_and_skip_still_zero_llm(monkeypatch,available):
    from tradingagents.agents.analysts import sentiment_analyst
    from tradingagents.dataflows.social_result import SocialResult
    from tradingagents.dataflows.config import run_config
    monkeypatch.setattr(sentiment_analyst,'bind_structured',lambda *a:None)
    monkeypatch.setattr(sentiment_analyst.get_news,'func',lambda *a:'新闻')
    monkeypatch.setattr(sentiment_analyst,'jev_screen',lambda *a:None)
    value=SocialResult('HTTP 429' if not available else '正常（0 条）',available=available,effective_posts=0)
    monkeypatch.setattr(sentiment_analyst,'fetch_reddit_posts',lambda *a,**k:value)
    llm=Mock();monkeypatch.setattr(sentiment_analyst,'invoke_structured_or_freetext',llm)
    with run_config({}):
        node=sentiment_analyst.create_sentiment_analyst(Mock(),{'stocktwits_enabled':False,'sentiment_min_social_posts':3})
        text=node({'company_of_interest':'SMTC','trade_date':'2026-10-02','messages':[]})['sentiment_report']
    llm.assert_not_called()
    if available:assert '正常（0 条）' in text and '获取失败' not in text
    else:assert '获取失败' in text and 'HTTP 429' in text and '非无讨论' in text and '0 条' not in text


def test_reddit_zero_is_success_source_status(monkeypatch):
    from tradingagents.dataflows.vendors import reddit
    from tradingagents.dataflows.vendor_observer import observed_call,set_vendor_observer,reset_vendor_observer
    from daily_analyzer.source_status import SourceStatusCollector
    monkeypatch.setattr(reddit,'_fetch_subreddit_rss',lambda *a,**kw:[])
    collector=SourceStatusCollector();token=set_vendor_observer(collector.observe)
    try:observed_call('fetch_reddit','Reddit',reddit.fetch_reddit_posts,'SMTC',structured_result=True)
    finally:reset_vendor_observer(token)
    row=next(row for row in collector.snapshot({},{}) if row['category']=='Reddit')
    assert row['status']=='正常' and '正常（0 条）' in row['reason']


def test_sector_retries_pending_and_freezes_settled_window(tmp_path):
    from copy import deepcopy
    from test_evaluation import raw,write_run,FixtureServices,rows
    from daily_analyzer.evaluation.settlement import _settle,write_outcomes
    from daily_analyzer.config import EvaluationSettings
    class Services(FixtureServices):
        def __init__(self):super().__init__();self.lookups=0
        def sector_lookup(self,symbol):self.lookups+=1;return {'status':'mapped','benchmark':'XLK'}
    write_run(tmp_path,raw(symbol='TECH',kind='stock'))
    (tmp_path/'data/evaluation').mkdir(parents=True)
    services=Services();now=datetime.fromisoformat('2026-10-02T20:00:00-04:00')
    _settle(tmp_path,EvaluationSettings(),{},services,now)
    records=rows(tmp_path);record=records[0]
    record['sector_lookup']='failed';record['sector_benchmark']=None
    record['windows']['5']={'status':'settled','raw_return':.123,'pricing':{'source':'原冻结'}}
    frozen=deepcopy(record['windows']['5'])
    services.lookups=0
    write_outcomes(tmp_path/'data/evaluation/outcomes.jsonl',records)
    _settle(tmp_path,EvaluationSettings(),{},services,now)
    assert services.lookups==1 and rows(tmp_path)[0]['sector_benchmark']=='XLK'
    assert rows(tmp_path)[0]['windows']['5']==frozen

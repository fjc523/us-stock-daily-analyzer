"""一致预期、期权不可行分支与社交不足的离线契约。"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

from tradingagents.dataflows.config import run_config
from tradingagents.dataflows.social_result import SocialResult
from tradingagents.dataflows.vendors.yahoo import expectations
from tradingagents.dataflows.vendors import reddit
from tradingagents.agents.analysts import fundamentals_analyst, sentiment_analyst
from daily_analyzer.context.base import ProviderServices
from daily_analyzer.context.position_structure import PositionStructureProvider
from daily_analyzer.context.compaction import render_compacted_context
from daily_analyzer.source_status import SourceStatusCollector


def test_expectations_table_and_missing():
    frames={
        'earnings_estimate':pd.DataFrame({'avg':[1.,2.],'numberOfAnalysts':[8,9]},index=['0q','+1q']),
        'eps_trend':pd.DataFrame({'current':[1.2], '30daysAgo':[1.]},index=['0q']),
        'earnings_history':pd.DataFrame({'epsActual':[1.2],'epsEstimate':[1.],'surprisePercent':[.2]},index=['2026-07-31']),
    }
    text=expectations.render_expectations(frames,queried_at='2026-10-03T16:00:00+00:00',errors={'revenue_estimate':'来源为空'})
    assert '|EPS均值|1|2|' in text
    assert '变化+20.00%' in text and '+20.00%' in text
    assert '不可得' in text and 'revenue_estimate：来源为空' in text


def test_expectations_backfill_never_queries(monkeypatch):
    ticker=Mock(side_effect=AssertionError('不能查询当前值'));monkeypatch.setattr(expectations.yf,'Ticker',ticker)
    with run_config({'market_timezone':'America/New_York'}):
        assert expectations.get_earnings_expectations('SMTC','2020-01-01')=='回放不可用：来源只提供当前值'
    ticker.assert_not_called()
    assert fundamentals_analyst.available_tools({'earnings_expectations_enabled':False}) == fundamentals_analyst.TOOLS
    assert fundamentals_analyst.available_tools({},'etf') == fundamentals_analyst.TOOLS
    assert any(tool.name=='get_earnings_expectations' for tool in fundamentals_analyst.available_tools({}))


def test_position_structure_real_date_and_brief(monkeypatch):
    info={'shortPercentOfFloat':.0853,'sharesShort':6837610,'shortRatio':1.97,'dateShortInterest':1789430400}
    services=ProviderServices(yahoo=SimpleNamespace(_ticker=lambda _:SimpleNamespace(get_info=lambda:info)))
    block=PositionStructureProvider(services).build({'type':'stock','symbol':'SMTC'},datetime(2026,10,3,tzinfo=timezone.utc))
    assert block.data['short_date']=='2026-09-15' and '8.53%' in block.markdown
    assert '期权不可用' in render_compacted_context({'position_structure':block},block.as_of,profile='brief')
    collector=SourceStatusCollector(); rows=collector.snapshot({'position_structure':block.to_dict()},{})
    assert any(row['category']=='期权' and row['status']=='未开通/不可行' for row in rows)
    services.analysis_mode='backfill'; services.yahoo._ticker=Mock(side_effect=AssertionError)
    assert '回放不可用' in PositionStructureProvider(services).build({'type':'stock','symbol':'SMTC'},block.as_of).markdown
    services.yahoo._ticker.assert_not_called()


def test_reddit_structured_count_filters_window_and_mentions(monkeypatch):
    stamp=datetime(2026,10,2,12,tzinfo=timezone.utc).timestamp()
    posts=[{'title':'$SMTC margins','selftext':'','created_utc':stamp,'subreddit':'stocks'},
           {'title':'Semtech guidance','selftext':'','created_utc':stamp,'subreddit':'stocks'},
           {'title':'XSMTC is another ticker','selftext':'','created_utc':stamp,'subreddit':'stocks'},
           {'title':'SMTC old','selftext':'','created_utc':stamp-864000,'subreddit':'stocks'}]
    monkeypatch.setattr(reddit,'_fetch_subreddit_rss',lambda *a,**k:posts)
    with run_config({}):
        result=reddit.fetch_reddit_posts('SMTC',start_date='2026-10-01',end_date='2026-10-02',structured_result=True,company_name='Semtech')
    assert isinstance(result,str) and result.effective_posts==2
    assert 'XSMTC' not in result and 'SMTC old' not in result


@pytest.mark.parametrize('minimum,count,expected_calls',[(3,0,0),(3,3,1),(0,0,1)])
def test_sentiment_skips_before_llm(monkeypatch,minimum,count,expected_calls):
    monkeypatch.setattr(sentiment_analyst,'bind_structured',lambda *a:None)
    monkeypatch.setattr(sentiment_analyst.get_news,'func',lambda *a:'新闻')
    monkeypatch.setattr(sentiment_analyst,'jev_screen',lambda *a:None)
    monkeypatch.setattr(sentiment_analyst,'fetch_reddit_posts',lambda *a,**k:SocialResult('帖子',available=True,effective_posts=count))
    call=Mock(return_value='模型报告');monkeypatch.setattr(sentiment_analyst,'invoke_structured_or_freetext',call)
    node=sentiment_analyst.create_sentiment_analyst(Mock(),{'stocktwits_enabled':False,'sentiment_min_social_posts':minimum})
    state={'company_of_interest':'SMTC','trade_date':'2026-10-02','messages':[]}
    result=node(state)
    assert call.call_count==expected_calls
    if not expected_calls:
        assert result['sentiment_report'].startswith('**Overall Sentiment:** 未评估（社交数据不足）')
        assert 'score' not in result['sentiment_report'] and 'band' not in result['sentiment_report']


def test_today_backfill_zero_current_query(monkeypatch):
    from tradingagents.dataflows.date_window import get_current_date
    ticker=Mock(side_effect=AssertionError('不可读取今天预期'));monkeypatch.setattr(expectations.yf,'Ticker',ticker)
    with run_config({'analysis_mode':'backfill','news_cutoff_utc':'2026-10-04T12:31:00+00:00'}):
        assert '回放不可用' in expectations.get_earnings_expectations('SMTC',get_current_date())
    ticker.assert_not_called()


@pytest.mark.parametrize('available',[True,False])
def test_stocktwits_empty_cannot_bypass_gate(monkeypatch,available):
    monkeypatch.setattr(sentiment_analyst,'bind_structured',lambda *a:None)
    monkeypatch.setattr(sentiment_analyst.get_news,'func',lambda *a:'新闻')
    monkeypatch.setattr(sentiment_analyst,'jev_screen',lambda *a:None)
    monkeypatch.setattr(sentiment_analyst,'fetch_reddit_posts',lambda *a,**k:SocialResult('空',available=True,effective_posts=0))
    monkeypatch.setattr(sentiment_analyst,'fetch_stocktwits_messages',lambda *a,**k:SocialResult('成功但空/全筛除',available=available,effective_posts=0))
    call=Mock(side_effect=AssertionError('双空不能评分'));monkeypatch.setattr(sentiment_analyst,'invoke_structured_or_freetext',call)
    result=sentiment_analyst.create_sentiment_analyst(Mock(),{'stocktwits_enabled':True,'sentiment_min_social_posts':3})({'company_of_interest':'SMTC','trade_date':'2026-10-02','messages':[]})
    assert '未评估' in result['sentiment_report'];call.assert_not_called()


def test_reddit_missing_timestamp_not_effective_today(monkeypatch):
    from tradingagents.dataflows.date_window import get_current_date
    posts=[{'title':'SMTC','selftext':'','subreddit':'stocks'} for _ in range(3)] + [{'title':'SMTC epoch','created_utc':0,'subreddit':'stocks'}]
    monkeypatch.setattr(reddit,'_fetch_subreddit_rss',lambda *a,**k:posts)
    with run_config({'news_cutoff_utc':None}):
        day=get_current_date(); result=reddit.fetch_reddit_posts('SMTC',start_date=day,end_date=day,structured_result=True)
    assert result.effective_posts==0

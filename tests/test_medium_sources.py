"""一致预期、期权不可行分支与社交不足的离线契约。"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

from tradingagents.dataflows.config import run_config
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
    assert any(row['category']=='期权' and row['status']=='失败' for row in rows)
    services.analysis_mode='backfill'; services.yahoo._ticker=Mock(side_effect=AssertionError)
    assert '回放不可用' in PositionStructureProvider(services).build({'type':'stock','symbol':'SMTC'},block.as_of).markdown
    services.yahoo._ticker.assert_not_called()


def test_today_backfill_zero_current_query(monkeypatch):
    from tradingagents.dataflows.date_window import get_current_date
    ticker=Mock(side_effect=AssertionError('不可读取今天预期'));monkeypatch.setattr(expectations.yf,'Ticker',ticker)
    with run_config({'analysis_mode':'backfill','news_cutoff_utc':'2026-10-04T12:31:00+00:00'}):
        assert '回放不可用' in expectations.get_earnings_expectations('SMTC',get_current_date())
    ticker.assert_not_called()

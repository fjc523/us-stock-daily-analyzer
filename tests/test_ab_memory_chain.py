"""M1：共同尾后同日四标、连续多日追加同步及生产同函数结算。"""
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import exchange_calendars as xcals
import pandas as pd
import pytest
from tradingagents.memory.log import TradingMemoryLog
from tradingagents.memory.settlement import settle_pending
from tradingagents.dataflows.config import run_config,get_config
from daily_analyzer.evaluation.ab_path import fork_history,copy_common_settlements,shadow_config,_memory_blocks

NY=ZoneInfo('America/New_York')
SYMBOLS=('SPY','QQQ','TSLA','SPCX')


@pytest.mark.parametrize('common',[False,True])
def test_multi_symbol_multi_day_append_sync_and_each_settlement(tmp_path,monkeypatch,common):
    import tradingagents.memory.settlement as settlement
    formal_path=tmp_path/'data/tradingagents/memory/trading_memory.md'
    if common:
        formal=TradingMemoryLog({'memory_log_path':str(formal_path)})
        formal.store_decision('SPY','2026-10-09','共同尾原文\n第二行','Hold')
    fork_history(tmp_path,'2026-10-12',now=datetime(2026,10,9,17,tzinfo=NY))
    cfg=shadow_config(tmp_path,{},'2026-10-12')
    log=TradingMemoryLog(cfg);cal=xcals.get_calendar('XNYS')
    dates=[cal.session_offset(pd.Timestamp('2026-10-12'),i).date().isoformat() for i in range(3)]
    expected=[]
    for day in dates:
        for symbol in SYMBOLS:
            body=f'{day}/{symbol} 自有正文\n逐条保留'
            log.store_decision(symbol,day,body,'Hold');expected.append((day,symbol,body))
            copy_common_settlements(tmp_path)
            own=[e for e in log.load_entries() if e['date']>='2026-10-12']
            assert [(e['date'],e['ticker'],e['decision']) for e in own]==expected
    if common:
        formal.batch_update_with_outcomes([dict(ticker='SPY',trade_date='2026-10-09',raw_return=.02,alpha_return=.01,holding_days=5,resolution_date='2026-10-16',reflection='共同反思原文')])
        copy_common_settlements(tmp_path)
        assert _memory_blocks(formal_path)[0]==_memory_blocks(log._log_path)[0]
    def closes(symbol,start,end):
        cutoff=min(get_config()['price_data_end_date'],end)
        sessions=cal.sessions_in_range(pd.Timestamp(start),pd.Timestamp(cutoff))
        return pd.Series([100+i for i in range(len(sessions))],index=sessions)
    monkeypatch.setattr(settlement,'get_closes',closes)
    calls=[]
    def reflect(**kwargs):calls.append(deepcopy(kwargs));return '仅合成反思：'+kwargs['final_decision']
    reflector=SimpleNamespace(reflect_on_final_decision=reflect)
    # D6管线截止D5只有五根bar，任何一条D1自有记录均不能反思；D7截止D6才首次可见。
    for current_index in range(5,9):
        current=cal.session_offset(pd.Timestamp(dates[0]),current_index).date().isoformat()
        cutoff=cal.previous_session(pd.Timestamp(current)).date().isoformat()
        cfg=shadow_config(tmp_path,{},current)
        with run_config(cfg):
            for symbol in SYMBOLS:
                # 共同历史由同步取得，不交A重新反思。
                own=SimpleNamespace(get_pending_entries=lambda:[e for e in log.get_pending_entries() if e['date']>=dates[0]],batch_update_with_outcomes=log.batch_update_with_outcomes)
                settle_pending(symbol,own,reflector,{**cfg,'asset_type':'etf' if symbol in ('SPY','QQQ') else 'stock'})
        copy_common_settlements(tmp_path)
        entries=[e for e in log.load_entries() if e['date']>=dates[0]]
        assert [(e['date'],e['ticker'],e['decision']) for e in entries]==expected
        for e in entries:
            resolution=cal.session_offset(pd.Timestamp(e['date']),5).date().isoformat()
            should_settle=resolution<=cutoff
            assert e['pending'] is not should_settle
            if should_settle:
                assert e['resolved']==resolution and e['reflection']=='仅合成反思：'+e['decision']
        assert len(calls)==4*max(0,current_index-5)
        if current_index==5:assert not [e for e in entries if not e['pending']]
    assert len(calls)==len(expected)==12
    assert log._log_path.read_text().endswith(TradingMemoryLog._SEPARATOR)

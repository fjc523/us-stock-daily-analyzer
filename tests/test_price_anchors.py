"""锚点数值、历史覆盖与代理标的契约。"""
from datetime import date
from types import SimpleNamespace
import pandas as pd
import pytest
from stockstats import wrap
from daily_analyzer.config import WatchlistItem
from daily_analyzer.context.price_anchors import PriceAnchorsProvider


def bars(count=220):
    days=pd.bdate_range(end='2026-10-01',periods=count)
    return pd.DataFrame({'Date':days,'Open':[100+i for i in range(count)],'High':[102+i for i in range(count)],
                         'Low':[99+i for i in range(count)],'Close':[101+i for i in range(count)],'Volume':[1000]*count})


def provider(data,source='Alpaca SIP adjustment=all'):
    calls=[]
    prices=SimpleNamespace(bars=lambda symbol,end:(calls.append((symbol,end)) or data.to_dict(orient='records'),source))
    instance=PriceAnchorsProvider(SimpleNamespace(prices=prices))
    instance.prepare({'price_data_end_date':date(2026,10,1)})
    return instance,calls


def test_anchors_match_stockstats_and_extreme_dates():
    data=bars(); future=bars(1);future['Date']=pd.Timestamp('2026-10-02');future['High']=9999
    instance,calls=provider(pd.concat([data,future]))
    block=instance.build(WatchlistItem(symbol='TSLA',type='stock'),'2026-10-02')
    expected=wrap(data.copy())
    for name in ('close_10_ema','close_20_sma','close_50_sma','close_200_sma','atr'):
        assert block.data['anchors'][name]['value']==pytest.approx(expected[name].iloc[-1])
    assert block.data['anchors']['20d_High']['value']==321
    assert block.data['anchors']['20d_High']['date']=='2026-10-01'
    assert block.data['anchors']['60d_Low']['date']==data.Date.iloc[-60].date().isoformat()
    assert block.data['source']=='Alpaca SIP adjustment=all'


def test_short_history_does_not_extrapolate_and_index_uses_proxy():
    instance,calls=provider(bars(10))
    block=instance.build(WatchlistItem(symbol='^GSPC',type='index'),'2026-10-02')
    assert calls[0][0]=='SPY'
    assert block.data['anchors']['close_200_sma']['value'] is None
    assert block.data['anchors']['atr']['value'] is None and '数据不足' in block.markdown


def test_empty_or_missing_p_row_is_unavailable():
    for data in (pd.DataFrame(),bars().iloc[:-1]):
        instance,calls=provider(data,'不可用')
        block=instance.build(WatchlistItem(symbol='TSLA',type='stock'),'2026-10-02')
        assert '锚点不可用' in block.markdown and block.data['anchors']=={}

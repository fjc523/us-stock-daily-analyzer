"""用固定发行方持仓核对行业、指数优先级和未知成员，不连接网络。"""

from io import BytesIO
from types import SimpleNamespace

import pytest
from openpyxl import Workbook

from daily_analyzer.data_sources.index_metadata import IndexMetadataSource, HOLDINGS_URLS


def _xlsx(symbols):
    book = Workbook()
    sheet = book.active
    sheet.append(["Holdings:", "As of 30-Sep-2026"])
    sheet.append(["Name", "Ticker", "Sector"])
    for symbol in symbols:
        sheet.append(["测试公司", symbol, "-"])
    stream = BytesIO()
    book.save(stream)
    return stream.getvalue()


def _source(qqq, spy, dia, *, fail=(), sector=None):
    calls = []
    def get(url, **kwargs):
        fund = next(f for f, u in HOLDINGS_URLS.items() if u == url)
        calls.append(fund)
        if fund in fail:
            raise OSError("固定网络失败")
        payload = {"holdings": [{"ticker": s, "sectorName": sector} for s in qqq],
                   "totalNumberOfHoldings": len(qqq), "effectiveDate": "2026-09-30"}
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload,
                               content=_xlsx(spy if fund == "SPY" else dia))
    return IndexMetadataSource(get=get), calls


@pytest.mark.parametrize("qqq,spy,dia,expected", [
    (["TSLA"], ["TSLA"], ["TSLA"], "QQQ"),
    (["AAPL"], ["TSLA"], ["TSLA"], "SPY"),
    (["AAPL"], ["MSFT"], ["TSLA"], "DIA"),
])
def test_verified_index_priority_and_one_lookup_per_fund(qqq, spy, dia, expected):
    source, calls = _source(qqq, spy, dia)
    row = source.lookup(["TSLA"])["TSLA"]
    assert row["benchmark_symbol"] == expected and row["benchmark_kind"] == "index"
    assert row["index_symbol"] == expected
    assert row["membership_as_of"] == "2026-09-30"
    source.lookup(["TSLA"])
    assert calls == ["QQQ", "SPY", "DIA"][:["QQQ", "SPY", "DIA"].index(expected) + 1]


def test_official_sector_precedes_index_and_stops_unneeded_queries():
    source, calls = _source(["TSLA"], ["TSLA"], [], sector="Consumer Discretionary")
    row = source.lookup(["TSLA"])["TSLA"]
    assert row["benchmark_symbol"] == "XLY" and row["benchmark_kind"] == "sector"
    assert row["index_symbol"] == "QQQ"
    assert calls == ["QQQ"]


def test_unavailable_membership_differs_from_verified_absence():
    source, _ = _source(["AAPL"], ["MSFT"], ["IBM"])
    row = source.lookup(["TSLA"])["TSLA"]
    assert row["benchmark_symbol"] == "SPY" and "未核验" in row["benchmark_reason"]
    source, _ = _source([], [], [], fail=["QQQ", "SPY", "DIA"])
    row = source.lookup(["TSLA"])["TSLA"]
    assert row["benchmark_kind"] == "default" and "未核验" in row["benchmark_reason"]


def test_partial_holdings_are_not_treated_as_verified_absence():
    payload = {"holdings": [{"ticker": "AAPL"}], "totalNumberOfHoldings": 100, "effectiveDate": "2026-09-30"}
    source = IndexMetadataSource(get=lambda *a, **kw: SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload))
    assert "未核验" in source.lookup(["TSLA"])["TSLA"]["benchmark_reason"]


def test_iwm_official_csv_supplies_sector_without_changing_three_index_priority():
    text='iShares Russell 2000 ETF\nFund Holdings as of,"Sep 30, 2026"\nTicker,Name,Sector,Asset Class\nTWST,TWIST,Health Care,Equity\n'
    source=IndexMetadataSource(get=lambda *args,**kwargs:SimpleNamespace(raise_for_status=lambda:None,text=text))
    source.cache.update({'QQQ':None,'SPY':None,'DIA':None})
    row=source.lookup(['TWST'])['TWST']
    assert row['benchmark_symbol']=='XLV' and row['index_symbol'] is None and 'IWM' in row['benchmark_reason']

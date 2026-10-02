"""使用固定资料验证身份查询，不连接外部行情源。"""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from daily_analyzer.config import ConfigurationError
from daily_analyzer.instruments import InstrumentResolver, InstrumentUnavailableError


@pytest.mark.parametrize("quote_type,kind", [("EQUITY", "stock"), ("ETF", "etf"), ("INDEX", "index"), ("UNKNOWN", None)])
def test_yahoo_identity_classification(tmp_path, monkeypatch, quote_type, kind):
    monkeypatch.setattr("daily_analyzer.instruments.socket.create_connection", lambda *a, **k: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr("tradingagents.dataflows.vendors.yahoo.fundamentals.get_company_profile",
                        lambda symbol: {"longName": "固定标的", "quoteType": quote_type})
    result = InstrumentResolver(tmp_path)("^gspc" if kind == "index" else "qqq")
    assert result["type"] == kind
    if kind == "index":
        assert result["proxy"] == "SPY"


def test_empty_identity_differs_from_source_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("tradingagents.dataflows.vendors.yahoo.fundamentals.get_company_profile", lambda symbol: {})
    with pytest.raises(ConfigurationError, match="未找到"):
        InstrumentResolver(tmp_path)("^INVALID")
    def fail(symbol):
        raise RuntimeError("固定网络错误")
    monkeypatch.setattr("tradingagents.dataflows.vendors.yahoo.fundamentals.get_company_profile", fail)
    with pytest.raises(InstrumentUnavailableError, match="暂时"):
        InstrumentResolver(tmp_path)("^INVALID")


def test_futu_basic_identity_closes_without_subscription(tmp_path, monkeypatch):
    calls = []
    context = SimpleNamespace(
        set_sync_query_connect_timeout=lambda seconds: calls.append(("timeout", seconds)),
        get_stock_basicinfo=lambda market, code_list: (0, [{"name": "固定ETF", "stock_type": "ETF"}]),
        close=lambda: calls.append("close"),
    )
    monkeypatch.setattr("daily_analyzer.instruments.socket.create_connection", lambda *a, **k: nullcontext())
    monkeypatch.setattr("futu.OpenQuoteContext", lambda **kwargs: context)
    monkeypatch.setattr("tradingagents.dataflows.vendors.yahoo.fundamentals.get_company_profile",
                        lambda *args: pytest.fail("富途成功时无需 Yahoo 查询"))
    assert InstrumentResolver(tmp_path)("qqq")["type"] == "etf"
    assert calls[-1] == "close"

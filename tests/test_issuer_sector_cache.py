"""发行方真实缺字段响应、31自然日边界及实时股票范围；禁止联网。"""

from datetime import date, datetime
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from daily_analyzer.context.base import ProviderServices
from daily_analyzer.context.providers import SectorStrengthProvider
from daily_analyzer.data_sources.index_metadata import HOLDINGS_URLS, IndexMetadataSource
from daily_analyzer.source_status import SourceStatusCollector

# 来自 /Users/zhoulei/Documents/us-stock-daily-analyzer/data/cache/etf_holdings/QQQ.json
# 2026-10-13 原缓存 raw_response_base64 解码，原始字节未改。
FIXTURE = Path(__file__).parent / "fixtures/invesco_qqq_missing_sector_20261013.json"
BATCH = {"trade_date": date(2026, 10, 13), "price_data_end_date": date(2026, 10, 12)}


class Prices:
    def metrics(self, symbols, end, windows):
        return {}

    def bars(self, symbol, end):
        return [], "不可用"


def source(payload=None):
    payload = payload or json.loads(FIXTURE.read_text())
    def get(url, **kwargs):
        assert url == HOLDINGS_URLS["QQQ"], "用例不得触发其他发行方或真实网络"
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)
    return IndexMetadataSource(get=get)


def provider(tmp_path, metadata=None):
    yahoo = SimpleNamespace(sector_etf=lambda symbol: {"SPCX": "XLI", "TSLA": "XLY"}.get(symbol))
    services = ProviderServices(project_root=str(tmp_path), index_metadata=metadata or source(),
        prices=Prices(), yahoo=yahoo, alpaca=object(), futu=object(), futu_enabled=False,
        clock=lambda: datetime.fromisoformat("2026-10-13T08:31:00-04:00"))
    return SectorStrengthProvider(services)


def seed(tmp_path, membership="2026-10-12", **extra):
    path = tmp_path / "data/cache/issuer_sector_map.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({symbol: {"sector_etf": sector, "fund": "QQQ", "membership_as_of": membership,
        "recorded_at": "2026-10-13T08:31:00-04:00", **extra} for symbol, sector in (("SPCX", "XLC"), ("TSLA", "XLY"))}))
    return path


def build(p, symbols=("SPCX", "TSLA"), **batch):
    items = [{"symbol": s, "type": "stock"} for s in symbols]
    p.prepare({**BATCH, "items": items, **batch})
    return [p.build(item, "2026-10-13T08:31:00-04:00").to_dict() for item in items]


def mapping_status(block):
    return next(row for row in SourceStatusCollector().snapshot({"sector_strength": block}, {}) if row["category"] == "板块映射")


def test_fixture_is_original_complete_response():
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == "d3cb4af212bc047daf5fc90084998efed4a5f931d75f14708fc3c8d21d6d893f"
    payload = json.loads(FIXTURE.read_text())
    assert payload["effectiveDate"] == "2026-10-12"
    assert len(payload["holdings"]) == payload["totalNumberOfHoldings"] == 106
    assert all("sectorName" not in row for row in payload["holdings"])


@pytest.mark.parametrize("membership,expected", [("2026-10-12", "XLC"), ("2026-09-12", "XLC"),
    ("2026-09-11", "XLI"), ("2026-10-14", "XLI"), ("未知", "XLI"), (None, "XLI")])
def test_missing_fields_age_uses_membership_not_recorded_at(tmp_path, membership, expected):
    path = seed(tmp_path, membership)
    before = path.read_bytes()
    blocks = build(provider(tmp_path))
    assert blocks[0]["data"]["benchmark_symbol"] == expected
    assert blocks[1]["data"]["benchmark_symbol"] == "XLY"
    for block in blocks:
        status = mapping_status(block)
        assert status["status"] == "降级" and status["reason"]
        if expected == "XLC":
            assert f"沿用 {membership} 名单" in block["data"]["benchmark_reason"]
            assert status["reason"] == block["data"]["benchmark_reason"]
        else:
            assert status["reason"] == "发行方名单缺行业字段，改用 Yahoo"
    assert path.read_bytes() == before


def test_missing_cache_preserves_yahoo_and_explains_reason(tmp_path):
    block = build(provider(tmp_path), ("SPCX",))[0]
    assert block["data"]["benchmark_symbol"] == "XLI"
    assert block["data"]["benchmark_reason"] == "Yahoo板块映射"
    assert mapping_status(block)["reason"] == "发行方名单缺行业字段，改用 Yahoo"
    assert not (tmp_path / "data/cache/issuer_sector_map.json").exists()


def test_normal_fields_refresh_cache_without_changing_output(tmp_path):
    payload = json.loads(FIXTURE.read_text())
    for row in payload["holdings"]:
        row["sectorName"] = "Communication Services" if row["ticker"] == "SPCX" else "Consumer Discretionary"
    p = provider(tmp_path, source(payload))
    blocks = build(p)
    for block, expected in zip(blocks, ("XLC", "XLY")):
        assert block["data"]["benchmark_symbol"] == expected
        assert block["data"]["benchmark_reason"] == "发行方行业映射（QQQ持仓）"
        assert "issuer_sector_reason" not in block["data"]
        assert mapping_status(block)["status"] == "正常"
        assert mapping_status(block)["reason"] == ""
    cached = json.loads((tmp_path / "data/cache/issuer_sector_map.json").read_text())
    assert cached["SPCX"] == {"sector_etf": "XLC", "fund": "QQQ", "membership_as_of": "2026-10-12", "recorded_at": "2026-10-13T08:31:00-04:00"}


def test_unmappable_field_is_same_as_missing(tmp_path):
    payload = json.loads(FIXTURE.read_text())
    for row in payload["holdings"]:
        row["sectorName"] = "无法映射的行业"
    seed(tmp_path)
    assert build(provider(tmp_path, source(payload)), ("SPCX",))[0]["data"]["benchmark_symbol"] == "XLC"


@pytest.mark.parametrize("mode,kind,override", [("backfill", "stock", None), ("live", "etf", None),
    ("live", "index", None), ("live", "stock", "SMH")])
def test_no_cache_access_outside_applicable_stock(tmp_path, monkeypatch, mode, kind, override):
    import daily_analyzer.context.providers as module
    monkeypatch.setattr(module, "issuer_sector_mapping", lambda *a: pytest.fail("禁止读写发行方行业缓存"))
    p = provider(tmp_path)
    item = {"symbol": "SPCX", "type": kind, "sector_etf": override}
    p.prepare({**BATCH, "mode": mode, "items": [item]})
    block = p.build(item, "2026-10-13T08:31:00-04:00")
    if mode == "backfill":
        assert block.data["benchmark_reason"] == "Yahoo板块映射"
    if kind != "stock":
        assert "benchmark_symbol" not in block.data
    if override:
        assert block.data["benchmark_reason"] == "手工指定板块"


@pytest.mark.parametrize("reason", ["行业未识别；指数成员未核验，默认SPY", "行业未识别；三大指数名单无记录，默认SPY"])
def test_unavailable_unknown_and_nonmember_cannot_reuse(tmp_path, reason):
    seed(tmp_path)
    metadata = SimpleNamespace(lookup=lambda symbols: {s: {"benchmark_symbol": "SPY", "benchmark_kind": "default", "benchmark_reason": reason, "index_symbol": None} for s in symbols})
    block = build(provider(tmp_path, metadata), ("SPCX",))[0]
    assert block["data"]["benchmark_symbol"] == "XLI"
    assert "issuer_sector_reason" not in block["data"]


def test_cache_from_different_fund_cannot_reuse(tmp_path):
    seed(tmp_path, fund="SPY")
    block = build(provider(tmp_path), ("SPCX",))[0]
    assert block["data"]["benchmark_symbol"] == "XLI"

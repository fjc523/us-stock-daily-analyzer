"""仅保存发行方已核验的行业映射，与 Yahoo 缓存隔离。"""

from datetime import date, datetime
import json
from pathlib import Path
import threading

from ..data_sources.index_metadata import HOLDINGS_URLS
from ..data_sources.yfinance import SECTOR_TO_ETF, YahooDataSource

_LOCK = threading.Lock()


def issuer_sector_mapping(root, symbol, metadata, today: date, recorded_at: datetime):
    """返回可沿用的映射和降级原因；调用方只在实时股票且无手工覆盖时使用。"""
    fund = next((fund for fund, url in HOLDINGS_URLS.items() if url == metadata.get("metadata_source")), None)
    if not fund or metadata.get("benchmark_kind") not in {"sector", "index"}:
        return None, None
    path = Path(root) / "data" / "cache" / "issuer_sector_map.json"
    with _LOCK:
        cache = YahooDataSource._read_sector_cache(path)
        if metadata["benchmark_kind"] == "sector":
            cache[symbol] = {"sector_etf": metadata["benchmark_symbol"], "fund": fund,
                             "membership_as_of": metadata.get("membership_as_of"),
                             "recorded_at": recorded_at.isoformat()}
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            except OSError:
                # 缓存写入失败不改变本次已核验映射。
                pass
            return None, None
        cached = cache.get(symbol)
        if isinstance(cached, dict) and cached.get("fund") == fund:
            try:
                membership_day = date.fromisoformat(cached["membership_as_of"])
                valid = 0 <= (today - membership_day).days <= 31
            except (KeyError, TypeError, ValueError):
                valid = False
            if valid and cached.get("sector_etf") in SECTOR_TO_ETF.values():
                reason = f"发行方行业映射（{fund}持仓，沿用 {membership_day.isoformat()} 名单；最新名单缺行业字段）"
                return cached["sector_etf"], reason
        return None, "发行方名单缺行业字段，改用 Yahoo"

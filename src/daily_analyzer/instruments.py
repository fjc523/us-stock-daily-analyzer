"""查询代码身份，区分不可用与无效；不订阅行情或调用模型。"""

from __future__ import annotations

import re
import socket
from pathlib import Path
from typing import Any

from daily_analyzer.config import ConfigurationError, DEFAULT_INDEX_PROXIES, load_settings
from daily_analyzer.data_sources.futu import _records, futu_code


class InstrumentUnavailableError(RuntimeError):
    """身份查询失败，不据此判定代码无效。"""


def normalize_code(value: Any) -> str:
    code = str(value or "").strip().upper()
    if not re.fullmatch(r"[A-Z^][A-Z0-9.^-]{0,19}", code):
        raise ConfigurationError("代码只能包含字母、数字、点号、连字符和指数前缀 ^")
    return code


class InstrumentResolver:
    def __init__(self, root: Path):
        self.root = root

    def __call__(self, value: str) -> dict[str, Any]:
        symbol = normalize_code(value)
        settings = load_settings(self.root)
        # 富途提供明确的股票/ETF 类型；基本资料查询无需行情订阅。
        if settings.futu.enabled and not symbol.startswith("^"):
            context = None
            try:
                with socket.create_connection((settings.futu.host, settings.futu.port), timeout=1):
                    pass
                from futu import OpenQuoteContext, RET_OK, Market
                context = OpenQuoteContext(host=settings.futu.host, port=settings.futu.port)
                context.set_sync_query_connect_timeout(5)
                ret, data = context.get_stock_basicinfo(Market.US, code_list=[futu_code(symbol)])
                rows = _records(data) if ret == RET_OK else []
                if rows:
                    row = rows[0]
                    kind = {"STOCK": "stock", "ETF": "etf", "IDX": "index"}.get(row.get("stock_type"))
                    return self._result(symbol, row.get("name") or symbol, kind, "富途基本资料")
            except Exception:
                # 网络/SDK 失败交给既有 Yahoo 资料入口，不把异常当作无效代码。
                pass
            finally:
                if context is not None:
                    context.close()
        from tradingagents.dataflows.vendors.yahoo.fundamentals import get_company_profile
        try:
            profile = get_company_profile(symbol)
        except Exception as exc:
            raise InstrumentUnavailableError("数据源暂时无法验证代码，请稍后重试") from exc
        name = profile.get("longName") or profile.get("shortName")
        if not name or not profile.get("quoteType"):
            raise ConfigurationError(f"未找到有效标的：{symbol}")
        kind = {"EQUITY": "stock", "ETF": "etf", "INDEX": "index"}.get(profile.get("quoteType"))
        return self._result(symbol, name, kind, "Yahoo 基本资料")

    @staticmethod
    def _result(symbol: str, name: str, kind: str | None, source: str) -> dict[str, Any]:
        return {"symbol": symbol, "name": name, "type": kind, "source": source,
                "proxy": DEFAULT_INDEX_PROXIES.get(symbol) if kind == "index" else None}

"""从指数ETF发行方完整持仓补充行业和比较基准。"""

from __future__ import annotations

from datetime import datetime
import csv
from io import BytesIO, StringIO
from typing import Any

import requests
from openpyxl import load_workbook

from .yfinance import SECTOR_TO_ETF


HOLDINGS_URLS = {
    "IWM": "https://www.ishares.com/us/products/239710/ishares-russell-2000-etf/latest-holdings.csv",
    "QQQ": "https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/QQQ/holdings/fund?idType=ticker&interval=monthly&productType=ETF",
    "SPY": "https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx",
    "DIA": "https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-dia.xlsx",
}
_SECTOR_ETFS = {**SECTOR_TO_ETF, "Consumer Discretionary": "XLY", "Consumer Staples": "XLP",
                "Financials": "XLF", "Health Care": "XLV", "Telecommunications": "XLC",
                "Basic Materials": "XLB", "Information Technology": "XLK"}


def _symbol(value: Any) -> str:
    return str(value or "").strip().upper().replace("-", ".")


class IndexMetadataSource:
    """只在缺行业时读取名单，批次内复用；没有完整名单就不判定非成员。"""

    def __init__(self, *, get=requests.get):
        self.get = get
        self.cache: dict[str, dict | None] = {}

    def _load(self, fund: str) -> dict | None:
        if fund in self.cache:
            return self.cache[fund]
        try:
            response = self.get(HOLDINGS_URLS[fund], timeout=15)
            response.raise_for_status()
            if fund == "QQQ":
                payload = response.json()
                rows = payload["holdings"]
                # 部分加载结果不能据此断言标的不在完整指数名单里。
                if not rows or len(rows) != int(payload["totalNumberOfHoldings"]):
                    raise ValueError("发行方持仓名单不完整")
                data = {"as_of": payload["effectiveDate"],
                        "holdings": {_symbol(row["ticker"]): row.get("sectorName") for row in rows if row.get("ticker")}}
            elif fund == "IWM":
                values = list(csv.reader(StringIO(response.text.lstrip("\ufeff"))))
                header_index = next(i for i, row in enumerate(values) if "Ticker" in row and "Sector" in row)
                header = values[header_index]
                tick, sector = header.index("Ticker"), header.index("Sector")
                holdings = {_symbol(row[tick]): row[sector] for row in values[header_index+1:] if len(row) == len(header) and row[tick] not in {"", "-"}}
                if not holdings:
                    raise ValueError("IWM持仓为空")
                as_of = next(row[1] for row in values[:header_index] if row and "Holdings as of" in row[0])
                data = {"as_of": datetime.strptime(as_of, "%b %d, %Y").date().isoformat(), "holdings": holdings}
            else:
                book = load_workbook(BytesIO(response.content), read_only=True, data_only=True)
                try:
                    values = list(book.active.values)
                    as_of = next(str(row[1]).removeprefix("As of ") for row in values if row[0] == "Holdings:")
                    header_index = next(i for i, row in enumerate(values) if "Ticker" in row and "Name" in row)
                    header = values[header_index]
                    ticker_index, sector_index = header.index("Ticker"), header.index("Sector")
                    holdings = {_symbol(row[ticker_index]): row[sector_index] for row in values[header_index + 1:]
                                if row[ticker_index] and row[ticker_index] != "-"}
                    if not holdings:
                        raise ValueError("发行方持仓名单为空")
                    data = {"as_of": datetime.strptime(as_of, "%d-%b-%Y").date().isoformat(), "holdings": holdings}
                finally:
                    book.close()
            self.cache[fund] = data
        except Exception:
            self.cache[fund] = None
        return self.cache[fund]

    def lookup(self, symbols: list[str]) -> dict[str, dict]:
        pending = list(dict.fromkeys(symbols))
        result = {}
        unavailable = []
        for fund in ("QQQ", "SPY", "DIA", "IWM"):
            if not pending:
                break
            data = self._load(fund)
            if data is None:
                unavailable.append(fund)
                continue
            for symbol in pending[:]:
                normalized = _symbol(symbol)
                if normalized not in data["holdings"]:
                    continue
                sector = _SECTOR_ETFS.get(data["holdings"][normalized])
                reason = f"发行方行业映射（{fund}持仓）" if sector else f"指数成员已核验（{fund}持仓）"
                if unavailable and not sector:
                    reason += "；高优先级名单暂不可用"
                result[symbol] = {"benchmark_symbol": sector or (fund if fund != "IWM" else "SPY"), "benchmark_kind": "sector" if sector else "index",
                                  "index_symbol": fund if fund != "IWM" else None,
                                  "index_warning": "高优先级名单暂不可用" if unavailable else "",
                                  "benchmark_reason": reason, "membership_as_of": data["as_of"],
                                  "metadata_source": HOLDINGS_URLS[fund]}
                pending.remove(symbol)
        for symbol in pending:
            result[symbol] = {"benchmark_symbol": "SPY", "benchmark_kind": "default",
                              "index_symbol": None,
                              "benchmark_reason": "行业未识别；指数成员未核验，默认SPY" if unavailable
                              else "行业未识别；三大指数名单无记录，默认SPY"}
        return result

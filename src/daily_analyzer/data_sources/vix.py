"""CBOE官方VIX日线及可选FRED兜底。"""
import os
from io import StringIO
import pandas as pd
import requests
from tradingagents.dataflows.errors import VendorNotConfiguredError

CBOE_VIX_URL = "https://cdn-api.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"


class VixDataSource:
    def __init__(self, get=requests.get):
        self.get = get

    def cboe(self, start, end):
        response = self.get(CBOE_VIX_URL, timeout=10)
        response.raise_for_status()
        data = pd.read_csv(StringIO(response.text))
        data = data.rename(columns={"DATE":"Date", "CLOSE":"Close", "OPEN":"Open", "HIGH":"High", "LOW":"Low"})
        data["Date"] = pd.to_datetime(data.Date).dt.strftime("%Y-%m-%d")
        return data[(data.Date >= str(start)) & (data.Date <= str(end))].to_dict(orient="records")

    def fred(self, start, end):
        key = os.environ.get("FRED_API_KEY")
        if not key:
            raise VendorNotConfiguredError("FRED未配置")
        from tradingagents.dataflows.net import get_scrubbed
        response = get_scrubbed("https://api.stlouisfed.org/fred/series/observations", params={
            "api_key":key, "series_id":"VIXCLS", "file_type":"json", "observation_start":str(start), "observation_end":str(end)
        }, timeout=10, secret=key)
        response.raise_for_status()
        return [{"Date":row["date"], "Close":float(row["value"])} for row in response.json().get("observations", []) if row["value"] != "."]

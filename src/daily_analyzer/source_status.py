"""汇总真实来源尝试，状态记录与各标的分析隔离。"""
from collections.abc import Mapping
from datetime import datetime, timezone
import re
import threading

CATEGORIES = ("日线", "扩展时段报价", "新闻", "财报报表", "估值", "内部人交易",
              "财报日历", "经济日历", "宏观指标", "VIX", "板块映射", "StockTwits", "Reddit", "预测市场")
METHOD_CATEGORY = {
    "load_ohlcv": "日线", "get_stock_data": "日线", "get_indicators": "日线", "daily_bars": "日线",
    "vix": "VIX", "get_news": "新闻", "get_global_news": "新闻",
    "get_fundamentals": "估值", "get_insider_transactions": "内部人交易",
    "get_balance_sheet": "财报报表", "get_cashflow": "财报报表", "get_income_statement": "财报报表",
    "get_earnings_calendar": "财报日历", "get_economic_calendar": "经济日历",
    "get_macro_indicators": "宏观指标", "fetch_stocktwits": "StockTwits", "fetch_reddit": "Reddit",
    "get_prediction_markets": "预测市场", "sector_mapping": "板块映射",
}


def clean_reason(value, secrets=()):
    text = str(value or "")
    for secret in secrets:
        if secret:
            text = text.replace(str(secret), "[已隐藏]")
    text = re.sub(r"https?://\S+", "[链接已隐藏]", text)
    text = re.sub(r"(?i)(api[_-]?key|token|authorization|password)(\s*[:=]\s*)[^\s,;]+", r"\1\2[已隐藏]", text)
    return text[:240]


def _clean_statement_metadata(value, secrets):
    """元数据亦走既有脱敏；日期字符串、bool和数值不改变语义。"""
    if isinstance(value, str):
        return clean_reason(value, secrets)
    if isinstance(value, Mapping):
        return {key: _clean_statement_metadata(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean_statement_metadata(item, secrets) for item in value]
    return value


def _canonical_source(source):
    lower = source.lower()
    for token in ("alpaca", "fred", "cboe", "sec_edgar", "stocktwits", "reddit", "polymarket"):
        if token in lower:
            return token
    if "futu" in lower or "富途" in source:
        return "futu"
    if "yahoo" in lower or "yfinance" in lower:
        return "yfinance"
    return lower


def _primary_source(category, config):
    method = {"新闻":"get_news", "估值":"get_fundamentals", "内部人交易":"get_insider_transactions",
              "财报报表":"get_income_statement", "宏观指标":"get_macro_indicators"}.get(category)
    defaults = {"新闻":"alpaca", "估值":"futu", "内部人交易":"futu", "财报报表":"sec_edgar", "宏观指标":"futu"}
    if method:
        return config.get("tool_vendors", {}).get(method, defaults[category]).split(",")[0].strip()
    if category == "日线":
        return config.get("data_vendors", {}).get("core_stock_apis", "alpaca").split(",")[0].strip()
    return {"VIX":"cboe", "财报日历":"futu", "经济日历":"futu",
            "扩展时段报价":"futu" if config.get("futu_enabled", True) else "alpaca",
            "StockTwits":"stocktwits", "Reddit":"reddit", "预测市场":"polymarket"}.get(category)


# 公开美债来源只覆盖这些指标；其余宏观指标的主源仍是富途。
TREASURY_INDICATORS = frozenset({"10y_treasury", "DGS10", "2y_treasury", "DGS2", "10y_2y_spread", "yield_curve"})


def _fallback_used(category, attempts, used, config):
    """判断是否用了兜底来源；扩展时段与宏观指标按时段或指标确定主源。"""
    if category == "扩展时段报价" and config.get("futu_enabled", True):
        # 夜盘富途常缺分时段时间，Alpaca 夜盘是该时段的既定来源；IEX 盘前覆盖不完整，仍算降级。
        return any(_canonical_source(source) != "futu" and source != "Alpaca feed=overnight" for source in used)
    if category == "宏观指标":
        chain = [name.strip() for name in config.get("tool_vendors", {}).get("get_macro_indicators", "futu").split(",") if name.strip()]
        general = next((name for name in chain if name != "fred_public"), "futu")
        for event in attempts:
            if event.get("outcome") != "success":
                continue
            expected = "fred_public" if event.get("symbol") in TREASURY_INDICATORS and "fred_public" in chain else general
            if str(event.get("source", "")).lower() != expected:
                return True
        return False
    primary = _primary_source(category, config)
    if primary:
        return any(_canonical_source(source) != primary for source in used)
    return any(_canonical_source(source) == "yfinance" for source in used)


class SourceStatusCollector:
    def __init__(self, secrets=(), seed=()):
        self.secrets = secrets
        self.events = list(seed)
        self.lock = threading.Lock()

    def observe(self, event):
        category = event.get("category") or METHOD_CATEGORY.get(event.get("method"))
        if category is None:
            return
        if str(event.get("error") or "").startswith("IndicatorNotApplicableError"):
            # 来源不覆盖该指标属于路由跳过，不是失败。
            return
        row = {"category": category, "method": str(event.get("method", "")),
               "source": clean_reason(event.get("source"), self.secrets),
               "outcome": event.get("outcome", "failed"),
               "error": clean_reason(event.get("error"), self.secrets),
               "duration_seconds": event.get("duration_seconds", 0),
               "symbol": event.get("symbol"),
               "recorded_at": event.get("recorded_at") or datetime.now(timezone.utc).isoformat()}
        if isinstance(event.get('statement_metadata'), Mapping):
            row['statement_metadata'] = _clean_statement_metadata(event['statement_metadata'], self.secrets)
        with self.lock:
            self.events.append(row)

    def _context(self, blocks):
        def record(category, source, outcome="success", error=None):
            self.observe({"category": category, "method": "context", "source": source,
                          "outcome": outcome, "error": error})
        for name, block in blocks.items():
            data = block.get("data") if isinstance(block, Mapping) else None
            if not isinstance(data, Mapping):
                continue
            if name == "extended_hours":
                for segments in data.values():
                    if not isinstance(segments, Mapping):
                        continue
                    for segment_name in ("after", "overnight", "pre"):
                        segment = segments.get(segment_name)
                        if isinstance(segment, Mapping) and segment.get("status"):
                            valid = segment.get("status") in ("可用", "时段未核验（无分时段时间）")
                            record("扩展时段报价", segment.get("source") or "扩展时段来源", "success" if valid else "failed", segment.get("warning") or (None if valid else segment.get("status")))
            if name == "sector_strength" and data.get("benchmark_reason"):
                record("板块映射", data.get("benchmark_reason"))
            category = {"price_anchors": "日线", "macro_releases": "新闻"}.get(name)
            if category and data.get("error"):
                record(category, "上下文来源", "failed", data["error"])
            if name == "price_anchors" and not data.get("anchors"):
                record("日线", data.get("source", "日线来源"), "failed", "锚点不可用")

    def snapshot(self, blocks, config, *, fred_configured=False):
        self._context(blocks)
        rows = []
        with self.lock:
            events = [dict(event, statement_metadata=_clean_statement_metadata(event['statement_metadata'], self.secrets))
                      if isinstance(event.get('statement_metadata'), Mapping) else dict(event)
                      for event in self.events]
        # 旧seed未经过observe时，财报事件原字段仍须沿用同一脱敏。
        for event in events:
            if event.get('category') == '财报报表':
                for key in ('error', 'source'):
                    if isinstance(event.get(key), str):
                        event[key] = clean_reason(event[key], self.secrets)
        for category in CATEGORIES:
            attempts = [dict(event) for event in events if event["category"] == category]
            if category in ("宏观指标", "VIX") and not fred_configured:
                if not any(event["source"].lower() in ('fred','fred api') for event in attempts):
                    attempts.append({"source": "FRED", "outcome": "unconfigured", "error": "未配置FRED_API_KEY", "recorded_at": datetime.now(timezone.utc).isoformat()})
            used = list(dict.fromkeys(event["source"] for event in attempts if event["outcome"] == "success"))
            failed = [event for event in attempts if event["outcome"] in ("failed", "no_data")]
            configured_attempts = [event for event in attempts if event["outcome"] != "unconfigured"]
            if used:
                status = "降级" if _fallback_used(category, attempts, used, config) else "正常"
            elif configured_attempts:
                status = "失败"
            elif category == "宏观指标" and "futu" in config.get("tool_vendors", {}).get("get_macro_indicators", ""):
                status = "未使用"
            elif attempts:
                status = "未配置"
            else:
                status = "未使用"
            reason = "；".join(dict.fromkeys(event.get("error", "") for event in attempts if event.get("error")))
            if status == "正常" and failed:
                reason = "部分请求失败，主源仍可用；" + reason
            statement_meta = {}
            if category == '财报报表':
                statement_events = [event for event in attempts if event.get('statement_metadata')]
                if statement_events:
                    statement_meta['statements'] = [dict(event['statement_metadata'], method=event.get('method')) for event in statement_events]
                    last = statement_events[-1]['statement_metadata']
                    statement_meta.update(latest_period=last.get('latest_period'), actual_source=last.get('actual_source'),
                                          stale=any(event['statement_metadata'].get('stale') for event in statement_events))
                    details = [f"{event.get('method')}表体期末{event['statement_metadata'].get('latest_period') or '未核验'}，实际来源{event['statement_metadata'].get('actual_source')}" + (f"；{event['statement_metadata']['reason']}" if event['statement_metadata'].get('reason') else '') for event in statement_events]
                    reason = '；'.join(filter(None, [reason, *dict.fromkeys(details)]))
                    if statement_meta['stale']:
                        status = '降级'
            rows.append({"category": category, "source": "、".join(used) or "—", "status": status,
                         **statement_meta,
                         "reason": reason,
                         "attempts": attempts, "recorded_at": attempts[-1].get("recorded_at") if attempts else None})
        return rows

"""从本地批次结果生成离线 HTML 报告站点。"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import uuid
from collections.abc import Iterable, Mapping
from datetime import date, datetime, time, timedelta, timezone
from html import escape, unescape
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import markdown
import nh3
from markupsafe import Markup

from daily_analyzer.storage import read_json
from daily_analyzer.config import load_settings, load_watchlist
from daily_analyzer.site.templates import BASE, DETAIL, HISTORY, HOME, OVERVIEW
from daily_analyzer.context.providers import BENCHMARK_NAMES

DISCLAIMER = "仅供个人研究参考，不构成投资建议。"
_MARKET_TZ = "America/New_York"
_BEIJING_TZ = ZoneInfo("Asia/Shanghai")
_MARKDOWN_TAGS = {
    "a", "abbr", "blockquote", "br", "code", "del", "em", "h1", "h2",
    "h3", "h4", "h5", "h6", "hr", "li", "ol", "p", "pre", "strong",
    "table", "tbody", "td", "th", "thead", "tr", "ul",
}
_MARKDOWN_ATTRIBUTES = {"a": {"href", "title"}, "td": {"align"}, "th": {"align"}}
_RATING = {
    "BUY": ("买入", "rating-buy"),
    "OVERWEIGHT": ("增持", "rating-overweight"),
    "HOLD": ("持有", "rating-hold"),
    "UNDERWEIGHT": ("减持", "rating-underweight"),
    "SELL": ("卖出", "rating-sell"),
    "REVIEW": ("待复核", "rating-review"),
}
_STATUS = {
    "success": "已完成", "completed": "已完成", "running": "运行中",
    "partial": "部分失败", "failed": "失败", "interrupted": "已中断",
    "skipped_quota": "额度限制跳过", "skipped_fatal": "致命错误后跳过",
    "skipped_timeout": "超时跳过", "skipped": "已跳过", "pending": "待分析",
}


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _display(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def symbol_slug(value: str) -> str:
    normalized = re.sub(r"[^A-Z0-9._^-]+", "-", value.upper()).strip(".-")
    return normalized or "UNKNOWN"


def _markdown(value: Any) -> Markup:
    if value is None or value == "":
        return Markup("<p class=\"muted\">暂无内容。</p>")
    # 提供器的表格可能紧接元数据说明，Markdown 表格需要空行分隔。
    text = re.sub(r"(?<=\S)\n(?=\|[^\n]+\|\n\|[-:| ]+\|)", "\n\n", str(value))
    text = re.sub(
        r"(?m)^\*\*Action\*\*\s*[:：]\s*(Buy|Overweight|Hold|Underweight|Sell)\b",
        lambda match: f"**动作**: {_RATING[match[1].upper()][0]}（{match[1]}）", text,
    )
    rendered = markdown.markdown(text, extensions=["tables", "fenced_code"])
    cleaned = nh3.clean(
        rendered,
        tags=_MARKDOWN_TAGS,
        attributes=_MARKDOWN_ATTRIBUTES,
        url_schemes={"http", "https", "mailto"},
    )
    return Markup(cleaned)


def _provider_text(block: Any) -> str:
    if isinstance(block, str):
        return block
    if isinstance(block, list):
        return "\n\n".join(text for text in (_provider_text(item) for item in block) if text)
    data = _as_mapping(block)
    for name in ("markdown", "content", "text", "summary", "rendered"):
        value = data.get(name)
        if isinstance(value, str) and value.strip():
            return value
    nested = data.get("data")
    if isinstance(nested, (str, list)):
        return _provider_text(nested)
    if isinstance(nested, Mapping):
        nested_text = _provider_text(nested)
        if nested_text:
            return nested_text
    if not data:
        return ""
    lines = []
    for key, value in data.items():
        if key in {"source", "as_of", "data_timestamp", "provider", "status"}:
            continue
        if isinstance(value, (str, int, float, bool)):
            lines.append(f"- {key}: {_display(value)}")
    return "\n".join(lines)


def _records(value: Any, keys: tuple[str, ...]) -> list[Mapping[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    data = _as_mapping(value)
    for key in keys:
        child = data.get(key)
        if isinstance(child, list):
            return [item for item in child if isinstance(item, Mapping)]
        if isinstance(child, Mapping):
            nested = _records(child, keys)
            if nested:
                return nested
    for key in ("data", "payload", "result"):
        child = data.get(key)
        if isinstance(child, (Mapping, list)):
            nested = _records(child, keys)
            if nested:
                return nested
    return []


def _first(record: Mapping[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if record.get(name) is not None:
            return record[name]
    return None


def _percentage(value: Any) -> str:
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("%"):
            return text
    try:
        return f"{float(value):+.2f}%"
    except (TypeError, ValueError, OverflowError):
        return _display(value)


def _latest_result_block(results: list[Mapping[str, Any]], name: str) -> Any:
    eligible = [
        result
        for result in results
        if str(result.get("status") or "").casefold() in {"success", "completed"}
    ]
    eligible.sort(
        key=lambda result: str(result.get("context_as_of") or result.get("started_at") or "")
    )
    for result in reversed(eligible):
        block = _provider_block(result, name)
        if block is not None:
            return block
    return None


def _block_data(block: Any) -> Mapping[str, Any]:
    return _as_mapping(_as_mapping(block).get("data"))


def _rows(value: Any, kind: str) -> list[dict[str, str]]:
    keys = ("releases", "items", "rows", "data", "events") if kind == "macro" else (
        "ranking", "rankings", "sectors", "items", "rows", "data"
    )
    records = _records(value, keys)
    rows: list[dict[str, str]] = []
    for index, item in enumerate(records, start=1):
        if kind == "macro":
            rows.append(
                {
                    "metric": _display(_first(item, ("metric", "indicator", "name", "title"))),
                    "actual": _display(_first(item, ("actual", "value"))),
                    "expected": _display(_first(item, ("expected", "estimate", "consensus"))),
                    "prior": _display(_first(item, ("prior", "previous", "prior_value", "prior_revised"))),
                    "published_at": _display(_first(item, ("published_at", "release_time", "time", "created_at"))),
                }
            )
        else:
            sector_symbol = _first(item, ("sector", "name", "industry", "sector_etf", "symbol"))
            performance = _first(item, ("performance", "return", "change_pct"))
            if performance is None and item.get("excess_return_20d") is not None:
                try:
                    performance = f"{float(item['excess_return_20d']):+.2%}"
                except (TypeError, ValueError, OverflowError):
                    performance = item["excess_return_20d"]
            rows.append(
                {
                    "rank": _display(_first(item, ("rank", "position"))),
                    "sector": _display(sector_symbol),
                    "symbol": _display(_first(item, ("stock_symbol", "ticker"))),
                    "performance": _display(performance if performance is not None else item.get("score")),
                    "performance_5d": _relative_metric(item.get("excess_return_5d"))["text"],
                    "performance_60d": _relative_metric(item.get("excess_return_60d"))["text"],
                    "note": _display(_first(item, ("note", "description", "status", "source"))),
                }
            )
    return rows


def _walk(value: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield str(key), child
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _find(value: Any, names: tuple[str, ...]) -> Any:
    name_set = {name.casefold() for name in names}
    for key, child in _walk(value):
        if key.casefold() in name_set and not isinstance(child, (dict, list)):
            return child
    return None


def _rating(result: Mapping[str, Any]) -> tuple[str, str]:
    raw = str(result.get("final_rating") or "").strip()
    if not raw:
        return "无", "rating-review"
    return _RATING.get(raw.upper(), (raw, "rating-review"))


def _pretty_timestamp(value: Any) -> str:
    if value is None or value == "":
        return "—"
    text = str(value)
    try:
        instant = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if instant.tzinfo is None:
            return text
        beijing = instant.astimezone(_BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")
        new_york = instant.astimezone(ZoneInfo(_MARKET_TZ)).strftime("%Y-%m-%d %H:%M:%S")
        return f"{beijing} 北京 / {new_york} 美东"
    except (ValueError, OverflowError):
        return text


def _status(result: Mapping[str, Any]) -> str:
    raw = str(result.get("status") or "未知")
    return _STATUS.get(raw.casefold(), raw)


def _marks(result: Mapping[str, Any], retry_failure: Any = None) -> list[str]:
    marks: list[str] = []
    if result.get("finished_after_open"):
        marks.append("开盘后生成")
    if result.get("started_after_open"):
        marks.append("开盘后开始")
    if result.get("mode") == "backfill":
        marks.append("回放")
    if retry_failure:
        marks.append("最近一次重跑失败")
    for key, value in _walk(result):
        normalized = key.casefold()
        if normalized in {"data_expired", "expired", "stale"} and value is True:
            marks.append("数据过期")
            break
    extended = _block_data(_provider_block(result, "extended_hours"))
    symbols = [str(result.get("symbol") or ""), str(result.get("analyzed_symbol") or "")]
    for symbol in dict.fromkeys(value for value in symbols if value):
        quote = _as_mapping(extended.get(symbol))
        for session in ("after", "overnight", "pre"):
            segment = _as_mapping(quote.get(session))
            status = str(segment.get("status") or "")
            if status == "过期" and "数据过期" not in marks:
                marks.append("数据过期")
            elif status == "非本时段数据" and "非本时段数据" not in marks:
                marks.append("非本时段数据")
            elif status.startswith("时段未核验") and "时段未核验" not in marks:
                marks.append("时段未核验")
    macro_truncated = _block_data(_provider_block(result, "macro_releases")).get("truncated") is True
    if result.get("news_truncated") is True or macro_truncated:
        marks.append("新闻已截断")
    marks.extend(str(error) for error in result.get("late_news_errors", []))
    return marks


def _read_results(runs_root: Path) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    if not runs_root.is_dir():
        return grouped
    for day_dir in sorted(runs_root.iterdir()):
        if not day_dir.is_dir() or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day_dir.name):
            continue
        current = day_dir / "current"
        if not current.is_dir():
            continue
        for result_path in sorted(current.glob("*.json")):
            result = _as_mapping(_load_json(result_path))
            if not result:
                continue
            result = dict(result)
            result.setdefault("symbol", result_path.stem)
            result.setdefault("upstream_trade_date", day_dir.name)
            result["_slug"] = symbol_slug(str(result["symbol"]))
            result["_date"] = day_dir.name
            grouped.setdefault(day_dir.name, []).append(result)
    return grouped


def _manifest(day_dir: Path) -> Mapping[str, Any]:
    path = day_dir / "manifest.json"
    return _as_mapping(_load_json(path)) if path.is_file() else {}


def _retry_failure(manifest: Mapping[str, Any], result: Mapping[str, Any]) -> Any:
    items = _as_mapping(manifest.get("items"))
    entry = _as_mapping(items.get(str(result.get("_slug"))))
    if not entry:
        entry = _as_mapping(items.get(str(result.get("symbol"))))
    return entry.get("recent_retry_failure")


def _latest_context(day_dir: Path) -> Mapping[str, Any]:
    batches = day_dir / "batches"
    if not batches.is_dir():
        return {}
    for batch_dir in sorted((path for path in batches.iterdir() if path.is_dir()), reverse=True):
        path = batch_dir / "context.json"
        if path.is_file():
            return _as_mapping(_load_json(path))
    return {}


def _provider_block(value: Mapping[str, Any], name: str) -> Any:
    blocks = _as_mapping(value.get("context_blocks"))
    return blocks.get(name)


def _context_cards(context: Mapping[str, Any], results: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    cards = []
    for name, title in (("market_regime", "市场环境"),):
        block = context.get(name)
        if block is None:
            block = _latest_result_block(results, name)
        text = _provider_text(block)
        if text:
            cards.append({"title": title, "body": _markdown(text)})
    return cards


def _macro_data(results: list[Mapping[str, Any]]) -> tuple[list[dict[str, str]], Markup | None]:
    # 宏观块是 ticker 级，使用最近成功结果，避免依赖不存在的 batch 级宏观数据。
    block = _latest_result_block(results, "macro_releases")
    if block is None:
        return [], None
    rows = _rows(block, "macro")
    text = _provider_text(block)
    return rows, _markdown(text) if text else None


def _sector_data(
    context: Mapping[str, Any], results: list[Mapping[str, Any]] | None = None
) -> tuple[list[dict[str, str]], Markup | None]:
    block = context.get("sector_strength")
    if block is None:
        block = _latest_result_block(results or [], "sector_strength")
    if block is None:
        return [], None
    rows = _rows(block, "sector")
    text = _provider_text(block)
    html = str(_markdown(text)) if text else ""
    table = re.search(r"<table\b[^>]*>.*?</table>", html, re.DOTALL)
    return rows, Markup(table.group(0)) if table else None


def _summary_premarket(result: Mapping[str, Any]) -> dict[str, str]:
    """盘前价格与涨跌幅取自同一时段；没有涨跌幅（过期、非本时段）时不显示价格。"""
    direct = _first(
        result,
        ("premarket_change_pct", "pre_market_change_pct", "premarket_pct_change", "premarket_return"),
    )
    if direct is not None:
        return {"change": _percentage(direct), "price": "", "title": ""}
    block = _provider_block(result, "extended_hours")
    data = _block_data(block)
    symbols = [str(result.get("symbol") or ""), str(result.get("analyzed_symbol") or "")]
    for symbol in dict.fromkeys(symbol for symbol in symbols if symbol):
        quote = _as_mapping(data.get(symbol))
        premarket = _as_mapping(quote.get("pre"))
        value = premarket.get("change_pct")
        if value is not None:
            price = premarket.get("price")
            try:
                price_text = f"{float(price):.2f} 美元" if price is not None else ""
            except (TypeError, ValueError):
                price_text = ""
            title = "；".join(filter(None, [
                f"{symbol} 盘前" if symbol != symbols[0] else "",
                f"来源 {premarket['source']}" if premarket.get("source") else "",
                f"报价时间 {_pretty_timestamp(premarket['quote_time'])}" if premarket.get("quote_time") else "",
            ]))
            return {"change": _percentage(value), "price": price_text, "title": title}
    return {"change": "—", "price": "", "title": ""}


def _start_clock(value: Any) -> str:
    """开始分析时间只取时分，沿用北京/美东双时区。"""
    try:
        instant = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return ""
    if instant.tzinfo is None:
        return ""
    beijing = instant.astimezone(_BEIJING_TZ).strftime("%H:%M")
    new_york = instant.astimezone(ZoneInfo(_MARKET_TZ)).strftime("%H:%M")
    return f"开始 {beijing} 北京 / {new_york} 美东"


def _summary_sector_rank(result: Mapping[str, Any]) -> Any:
    direct = _first(result, ("sector_rank", "sector_position"))
    if direct is not None:
        return direct
    return _block_data(_provider_block(result, "sector_strength")).get("sector_rank")


def _safe_retry_error(value: Any) -> Any:
    data = _as_mapping(value)
    return data.get("error") if data else None


def _advice_summary(value: Any, limit: int = 140) -> str:
    """摘取报告的执行摘要，首页不生成新的模型建议。"""
    if isinstance(value, Mapping):
        value = _first(value, ("summary", "decision", "action", "plan"))
    if not value:
        return "暂无建议，等待分析完成。"
    text = str(value)
    match = re.search(
        r"(?:\*\*|#{1,6}\s*)?(?:Executive Summary|执行摘要|总体建议|操作建议|摘要)"
        r"(?:\*\*)?\s*[:：]\s*(.*?)(?=\n\s*(?:\*\*[^*\n]+\*\*\s*[:：]|#{1,6}\s)|\Z)",
        text, flags=re.IGNORECASE | re.DOTALL,
    )
    if match:
        text = match.group(1)
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = unescape(re.sub(r"<[^>]+>", " ", str(_markdown(text))))
    text = re.sub(r"\s+", " ", text).strip()
    sentence = re.search(r"^.*?[。！？](?=\s|[^。！？]|$)", text)
    if sentence:
        text = sentence.group(0)
    return text[:limit].rstrip() + ("…" if len(text) > limit else "")


def _relative_metric(value: Any) -> dict[str, str]:
    try:
        number = float(value) if value is not None else float("nan")
    except (TypeError, ValueError, OverflowError):
        number = float("nan")
    if not math.isfinite(number):
        return {"text": "—", "tone": "muted"}
    return {"text": f"{number * 100:+.2f}", "tone": "positive" if number > 0 else "negative" if number < 0 else "muted"}


def _decision_section(value: Any, label: str) -> str:
    """只摘取固定报告章节，保留组合经理优先的来源顺序。"""
    if not isinstance(value, str):
        return ""
    match = re.search(
        rf"(?:\*\*|#{{1,6}}\s*){re.escape(label)}(?:\*\*)?\s*[:：]\s*(.*?)"
        r"(?=\n\s*(?:\*\*[^*\n]+\*\*\s*[:：]|#{1,6}\s|FINAL TRANSACTION PROPOSAL)|\Z)",
        value, flags=re.DOTALL,
    )
    return match.group(1).strip() if match else ""


def _allocation_summary(result: Mapping[str, Any]) -> str:
    """只认明确的标准仓位口径，不把账户资产比例或普通百分数当成配置。"""
    for key in ("final_trade_decision", "trader_investment_plan", "investment_plan"):
        text = result.get(key)
        if not isinstance(text, str):
            continue
        fixed = _decision_section(text, "目标配置（标准仓位=100%）")
        match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*%\s*", fixed)
        if not fixed:
            match = re.search(r"标准(?:配置|仓位|敞口)\s*(?:的|为|=|：|:)\s*(\d+(?:\.\d+)?)\s*%", text)
        if match:
            return f"目标配置 {float(match.group(1)):g}% · 标准仓位=100%"
        # 最终决策明确未提供目标时，不用上游目标覆盖最终结论。
        if fixed:
            return "目标配置未提供 · 标准仓位=100%"
    return "目标配置未提供 · 标准仓位=100%"


def _strength_data(result: Mapping[str, Any], root: Path | None) -> Mapping[str, Any]:
    sector = _block_data(_provider_block(result, "sector_strength"))
    symbol = result.get("symbol")
    if result.get("type") != "stock" or (sector.get("symbol") and sector.get("symbol") != symbol):
        return {}
    has_values = any(sector.get(f"{prefix}_excess_{days}d") is not None
                     for prefix in ("sector", "benchmark") for days in (5, 20, 60))
    if root is not None and (not has_values or not sector.get("comparisons")):
        end = str(result.get("price_data_end_date") or "")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", end):
            path = root / "data/cache/relative_strength" / end / f"{symbol_slug(str(symbol))}.json"
            if path.is_file():
                supplement = _as_mapping(_load_json(path))
                if supplement.get("symbol") == symbol and supplement.get("as_of") == end:
                    if not has_values:
                        return {**supplement, "display_supplement": True}
                    if supplement.get("comparisons"):
                        return {**sector, "comparisons": supplement["comparisons"], "comparisons_supplement": True}
    return sector


def _comparison_chart(chart: Any, symbol: str, benchmark: str) -> dict[str, Any] | None:
    """把已存归一化序列排到SVG坐标，不重新计算行情。"""
    if not isinstance(chart, Mapping):
        return None
    dates = chart.get("dates") or []
    stock, baseline = chart.get("stock") or [], chart.get("benchmark") or []
    if len(dates) < 2 or len(stock) != len(dates) or len(baseline) != len(dates):
        return None
    values = [float(v) for v in [*stock, *baseline]]
    if not all(math.isfinite(v) for v in values):
        return None
    low, high = min(values), max(values)
    padding = max((high - low) * 0.1, 1)
    low, high = low - padding, high + padding
    def y(value):
        return round(255 - (value - low) / (high - low) * 225, 2)
    series = []
    for label, prices, color in ((symbol, stock, "stock-line"), (benchmark, baseline, "benchmark-line")):
        dots = [{"x": round(58 + i / (len(dates) - 1) * 560, 2), "y": y(price),
                 "tip": f"{dates[i]} · {label} {float(price):.2f}"} for i, price in enumerate(prices)]
        series.append({"label": label, "color": color, "points": " ".join(f"{p['x']},{p['y']}" for p in dots), "dots": dots})
    return {"series": series, "ticks": [{"y": y(v), "text": f"{v:.1f}"} for v in (low, (low + high) / 2, high)],
            "baseline_y": y(100), "start": dates[0], "end": dates[-1], "count": len(dates),
            "sources": "；".join(dict.fromkeys(chart.get("sources") or []))}


def _summary_row(result: Mapping[str, Any], retry: Any, detail_path: str, root: Path | None = None) -> dict[str, Any]:
    rating, rating_class = _rating(result)
    advice = result.get("final_trade_decision") or result.get("trader_investment_plan")
    symbol_type = str(result.get("type") or "")
    sector = _strength_data(result, root)
    benchmark = sector.get("benchmark_symbol") or sector.get("sector_etf")
    benchmark_kind = sector.get("benchmark_kind") or ("sector" if sector.get("sector_etf") else "")
    benchmark_label = "板块" if benchmark_kind == "sector" else "指数"
    prefix = "benchmark" if sector.get("benchmark_symbol") else "sector"
    relative = {str(days): _relative_metric(sector.get(f"{prefix}_excess_{days}d")) for days in (5, 20, 60)}
    strength = "不适用" if symbol_type != "stock" else "数据不足"
    tone = relative["20"]["tone"]
    if relative["20"]["text"] != "—" and symbol_type == "stock":
        strength = {"positive": f"强于{benchmark_label}", "negative": f"弱于{benchmark_label}", "muted": f"与{benchmark_label}持平"}[tone]
    comparisons = []
    raw_comparisons = sector.get("comparisons") or ([{
        "symbol": benchmark, "kind": benchmark_kind, "reason": sector.get("benchmark_reason", ""),
        **{f"excess_{days}d": sector.get(f"{prefix}_excess_{days}d") for days in (5, 20, 60)},
    }] if benchmark else [])
    for comparison in raw_comparisons:
        name = comparison["symbol"]
        kind_label = "板块" if comparison.get("kind") == "sector" else "指数"
        metrics = {str(days): _relative_metric(comparison.get(f"excess_{days}d")) for days in (5, 20, 60)}
        strength_text = "数据不足" if metrics["20"]["text"] == "—" else {
            "positive": f"强于{kind_label}", "negative": f"弱于{kind_label}", "muted": f"与{kind_label}持平"}[metrics["20"]["tone"]]
        comparisons.append({"symbol": name, "name": BENCHMARK_NAMES.get(name, name), "kind": kind_label,
                            "reason": comparison.get("reason", ""), "relative": metrics, "strength": strength_text,
                            "tone": metrics["20"]["tone"], "chart": _comparison_chart(comparison.get("chart"), str(result.get("symbol")), name)})
    plans = []
    for label in ("建仓点位", "加仓点位", "减仓点位"):
        full_text = next((section for key in ("final_trade_decision", "trader_investment_plan")
                          if (section := _decision_section(result.get(key), label))), "")
        first = re.match(r"区间[^\n。]+?（依据：[^）]*）", full_text)
        summary = _advice_summary(first.group(0), len(first.group(0)) + 1) if first else _advice_summary(full_text, 200 if full_text.startswith("不适用：") else 100)
        plans.append({"label": label, "text": summary if full_text else "本报告未提供",
                      "full_text": full_text})
    error = result.get("error") or _safe_retry_error(retry)
    premarket = _summary_premarket(result)
    duration = result.get("duration_seconds")
    duration_text = "耗时未记录"
    if isinstance(duration, (int, float)) and math.isfinite(duration) and duration >= 0:
        minutes, seconds = divmod(int(duration), 60)
        duration_text = f"耗时 {minutes} 分 {seconds} 秒"
    return {
        "symbol": str(result.get("symbol") or "未知"),
        "name": str(result.get("name") or ""),
        "type": {"stock": "个股", "etf": "ETF", "index": "指数"}.get(symbol_type, symbol_type or "—"),
        "proxy": result.get("analyzed_symbol") if symbol_type == "index" else None,
        "rating": rating, "rating_class": rating_class,
        "advice": _advice_summary(advice),
        "plans": plans, "allocation": _allocation_summary(result),
        "premarket": premarket["change"], "premarket_price": premarket["price"],
        "premarket_title": premarket["title"],
        "sector_rank": _display(sector.get("sector_rank") if sector.get("sector_rank") is not None
                                else _summary_sector_rank(result)) if benchmark_kind == "sector" else "—",
        "sector_etf": sector.get("sector_etf") or "—",
        "benchmark": benchmark or "—", "benchmark_reason": sector.get("benchmark_reason") or "",
        "strength_supplement": sector.get("display_supplement", False),
        "relative": relative, "strength": strength, "strength_tone": tone,
        "comparisons": comparisons, "comparisons_supplement": sector.get("display_supplement") or sector.get("comparisons_supplement", False),
        "price_date": result.get("price_data_end_date") or "—",
        "date": result.get("_date") or result.get("upstream_trade_date") or "—",
        "information_through": _pretty_timestamp(result.get("information_through")),
        "status": _status(result), "error": _display(error) if error else None,
        "duration": duration_text,
        "late_news_count": len(result.get("late_news") or []),
        "source_status": _source_status(result),
        "started_at": _pretty_timestamp(result.get("started_at")),
        "start_clock": _start_clock(result.get("started_at")) if result.get("started_at") else "",
        "finished_at": _pretty_timestamp(result.get("finished_at")),
        "marks": _marks(result, retry), "path": detail_path,
    }


def _source_status(result):
    records = result.get("data_source_status")
    tones = {"正常": "normal", "降级": "degraded", "失败": "failed", "未配置": "inactive", "未使用": "inactive"}
    if not isinstance(records, list):
        return {"legacy": True, "tone": "inactive", "rows": []}
    rows = [{**row, "tone": tones.get(row.get("status"), "inactive")} for row in records if isinstance(row, Mapping)]
    statuses = {row.get("status") for row in rows}
    tone = "failed" if "失败" in statuses else "degraded" if "降级" in statuses else "normal" if "正常" in statuses else "inactive"
    return {"legacy": False, "tone": tone, "rows": rows, "normal": sum(row.get("status") == "正常" for row in rows), "total": len(rows)}


def _timestamp_rows(result: Mapping[str, Any]) -> list[dict[str, str]]:
    timestamps = result.get("source_timestamps")
    rows: list[dict[str, str]] = []
    if isinstance(timestamps, Mapping):
        for name, item in timestamps.items():
            record = _as_mapping(item)
            rows.append({
                "name": str(name),
                "time": _pretty_timestamp(record.get("as_of") or record.get("timestamp") or (item if isinstance(item, str) else None)),
                "source": _display(record.get("source") or record.get("sources")),
            })
    elif isinstance(timestamps, list):
        for item in timestamps:
            record = _as_mapping(item)
            rows.append({
                "name": _display(record.get("name") or record.get("provider")),
                "time": _pretty_timestamp(record.get("as_of") or record.get("timestamp")),
                "source": _display(record.get("source") or record.get("sources")),
            })
    for name, block_name in (("经济数据标题", "macro_releases"), ("扩展时段报价", "extended_hours")):
        block = _provider_block(result, block_name)
        data = _as_mapping(block)
        if block is not None:
            rows.append({"name": name, "time": _pretty_timestamp(data.get("as_of") or data.get("data_timestamp")), "source": _display(data.get("source") or data.get("sources"))})
    return rows


def _debate_text(value: Any) -> str:
    if isinstance(value, Mapping):
        if value.get("history"):
            value = str(value["history"])
        else:
            labels = {"bull_history": "多方观点", "bear_history": "空方观点",
                      "aggressive_history": "积极观点", "conservative_history": "保守观点",
                      "neutral_history": "中性观点"}
            return "\n\n".join(f"### {title}\n\n{value[key]}" for key, title in labels.items() if value.get(key))
    roles = {"Bull Analyst": "多方观点", "Bear Analyst": "空方观点",
             "Aggressive Analyst": "积极观点", "Conservative Analyst": "保守观点",
             "Neutral Analyst": "中性观点"}
    return re.sub(r"(Bull|Bear|Aggressive|Conservative|Neutral) Analyst:",
                  lambda match: f"\n\n### {roles[match.group(0)[:-1]]}\n\n", str(value or ""))


def _detail_values(
    result: Mapping[str, Any],
    all_results: list[Mapping[str, Any]],
    retry: Any,
) -> dict[str, Any]:
    rating, rating_class = _rating(result)
    symbol = str(result.get("symbol") or "未知")
    previous = next((item for item in all_results if item.get("_date") < result.get("_date")), None)
    next_result = next((item for item in reversed(all_results) if item.get("_date") > result.get("_date")), None)
    same_symbol = [item for item in all_results if str(item.get("symbol", "")).upper() == symbol.upper()]
    same_symbol.sort(key=lambda item: str(item.get("_date")), reverse=True)
    previous = next((item for item in same_symbol if item.get("_date") < result.get("_date")), None)
    next_result = next((item for item in reversed(same_symbol) if item.get("_date") > result.get("_date")), None)
    slug = str(result.get("_slug") or symbol_slug(symbol))
    day_prefix = "../../"
    reports = []
    for name, value in _as_mapping(result.get("reports")).items():
        if value is None or value == "":
            continue
        text = _provider_text(value) if isinstance(value, (Mapping, list)) else str(value)
        if text.strip():
            reports.append({"title": {"market_report": "技术与市场分析", "sentiment_report": "情绪分析",
                                      "news_report": "新闻分析", "fundamentals_report": "基本面分析"}.get(name, str(name)),
                            "body": _markdown(text)})
    llm = _as_mapping(result.get("llm"))
    metadata = [
        {"label": "批次", "value": result.get("run_id")},
        {"label": "Provider", "value": llm.get("provider")},
        {"label": "Deep 模型 / 强度", "value": _role_summary(llm.get("deep"))},
        {"label": "Quick 模型 / 强度", "value": _role_summary(llm.get("quick"))},
        {"label": "耗时（秒）", "value": result.get("duration_seconds")},
        {"label": "调用次数", "value": _find(result.get("llm_usage"), ("calls", "call_count", "total_calls"))},
        {"label": "Token 用量", "value": _find(result.get("llm_usage"), ("total_tokens", "tokens", "input_tokens"))},
    ]
    marks = _marks(result, retry)
    if retry and not any("最近一次重跑失败" == mark for mark in marks):
        marks.append("最近一次重跑失败")
    return {
        "rating": rating,
        "rating_class": rating_class,
        "symbol": symbol,
        "proxy": result.get("analyzed_symbol") if result.get("type") == "index" else None,
        "type_label": {"stock": "个股", "etf": "ETF", "index": "指数"}.get(str(result.get("type")), _display(result.get("type"))),
        "mode_label": "回放" if result.get("mode") == "backfill" else "实时",
        "times": [
            {"label": "开始分析", "value": _pretty_timestamp(result.get("started_at"))},
            {"label": "附加上下文时刻", "value": _pretty_timestamp(result.get("context_as_of"))},
            {"label": "日线截止交易日", "value": _display(result.get("price_data_end_date"))},
            {"label": "新闻截止时刻", "value": _pretty_timestamp(result.get("news_cutoff_utc"))},
            {"label": "工具数据最晚查询", "value": _pretty_timestamp(result.get("last_data_query_at"))},
            {"label": "信息截止", "value": _pretty_timestamp(result.get("information_through"))},
            {"label": "分析完成", "value": _pretty_timestamp(result.get("finished_at"))},
            {"label": "适用时段", "value": _display(result.get("target_session"))},
        ],
        "context_as_of": _pretty_timestamp(result.get("context_as_of")),
        "price_data_end_date": _display(result.get("price_data_end_date")),
        "last_data_query_at": _pretty_timestamp(result.get("last_data_query_at")),
        "decision": _markdown(result.get("final_trade_decision")),
        "trader_plan": _markdown(result.get("trader_investment_plan")),
        "investment_plan": _markdown(result.get("investment_plan")),
        "reports": reports,
        "investment_debate": _markdown(_debate_text(result.get("investment_debate"))),
        "risk_debate": _markdown(_debate_text(result.get("risk_debate"))),
        "injected_context": _markdown(result.get("injected_context")),
        "timestamps": _timestamp_rows(result),
        "source_status": _source_status(result),
        "data_queries": [
            {
                "name": _display(_as_mapping(query).get("name") or _as_mapping(query).get("tool")),
                "started_at": _pretty_timestamp(_as_mapping(query).get("started_at")),
                "finished_at": _pretty_timestamp(_as_mapping(query).get("finished_at")),
            }
            for query in result.get("data_queries", [])
            if isinstance(query, Mapping)
        ],
        "metadata": [{"label": item["label"], "value": _display(item["value"])} for item in metadata],
        "marks": marks,
        "error": _display(result.get("error") or _safe_retry_error(retry)) if result.get("error") or _safe_retry_error(retry) else None,
        "history": f"{day_prefix}symbols/{slug}.html",
        "previous": f"{day_prefix}days/{previous['_date']}/{slug}.html" if previous else "",
        "next": f"{day_prefix}days/{next_result['_date']}/{slug}.html" if next_result else "",
    }


def _role_summary(value: Any) -> str:
    role = _as_mapping(value)
    model = role.get("model")
    effort = role.get("reasoning_effort") or role.get("effort")
    if model or effort:
        return f"{model or '—'} / {effort or '—'}"
    return _display(value)


def _anchor(anchor: str, trading_day: date) -> datetime:
    match = re.fullmatch(r"(\d{2}):(\d{2})\s+(\S+)", anchor)
    if not match:
        match = re.fullmatch(r"(\d{2}):(\d{2})\s+(\S+)", "08:30 America/New_York")
    zone = ZoneInfo(match.group(3))
    return datetime.combine(trading_day, time(int(match.group(1)), int(match.group(2))), zone)


def _calendar_payload(today: date, anchor: str) -> dict[str, Any]:
    calendar = xcals.get_calendar("XNYS")
    end = today + timedelta(days=90)
    sessions = calendar.sessions_in_range(today.isoformat(), end.isoformat())
    values = [session.date().isoformat() for session in sessions[:30]]
    return {
        "calendar_start": today.isoformat(),
        "calendar_end": values[-1] if values else today.isoformat(),
        "trading_days": values,
        "anchors_beijing": {
            value: _anchor(anchor, date.fromisoformat(value)).astimezone(_BEIJING_TZ).isoformat()
            for value in values
        },
    }


def _read_status(path: Path) -> Mapping[str, Any]:
    return _as_mapping(_load_json(path)) if path.is_file() else {}


def _index_data(grouped: Mapping[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    values = []
    for day, results in sorted(grouped.items(), reverse=True):
        items = []
        for result in sorted(results, key=lambda item: str(item.get("symbol", ""))):
            symbol = str(result.get("symbol") or "未知")
            slug = str(result.get("_slug") or symbol_slug(symbol))
            items.append({"symbol": symbol, "label": f"{symbol}（{_rating(result)[0]}）", "path": f"days/{day}/{slug}.html"})
        values.append({"date": day, "items": items, "overview_path": f"days/{day}/index.html"})
    return values


def _page(
    *,
    title: str,
    body: Markup,
    root_prefix: str,
    index: list[dict[str, Any]],
    selected_date: str | None,
    selected_symbol: str | None,
    banner: Mapping[str, Any],
    refresh_seconds: int,
    managed: bool = False,
) -> str:
    return BASE.render(
        title=title,
        body=body,
        managed=managed,
        root_prefix=root_prefix,
        ui_data={
            "root_prefix": root_prefix,
            "index": index,
            "selected_date": selected_date,
            "selected_symbol": selected_symbol,
            "banner": banner,
            "refresh_seconds": refresh_seconds,
        },
        refresh_seconds=refresh_seconds,
    )


def render_home(project_root: str | Path, *, now: datetime | None = None, managed: bool = False,
                grouped: dict[str, list[dict[str, Any]]] | None = None) -> str:
    """读取当前订阅与落盘结果，HTTP 首页不写分析状态或发布目录。"""
    root = Path(project_root).resolve()
    now = now or datetime.now(ZoneInfo(_MARKET_TZ))
    grouped = grouped if grouped is not None else _read_results(root / "data" / "runs")
    index = _index_data(grouped)
    status = _read_status(root / "data" / "status.json")
    anchor = load_settings(root).schedule.anchor
    local_today = now.astimezone(ZoneInfo(_MARKET_TZ)).date()
    calendar = _calendar_payload(local_today, anchor)
    anchor_match = re.fullmatch(r"(\d{2}):(\d{2})\s+(\S+)", anchor)
    banner_data = {
        **calendar,
        "market_timezone": anchor_match.group(3) if anchor_match else _MARKET_TZ,
        "anchor_time": f"{anchor_match.group(1)}:{anchor_match.group(2)}" if anchor_match else "08:30",
        "last_run": status.get("last_run") or {},
        "last_schedule_event": status.get("last_schedule_event") or {},
    }
    running = _as_mapping(banner_data["last_run"]).get("status") == "running"
    latest_day = next(iter(sorted(grouped, reverse=True)), None)
    latest_results = grouped.get(latest_day, []) if latest_day else []
    latest_context = _latest_context(root / "data" / "runs" / latest_day) if latest_day else {}
    watchlist_path = root / "config" / "watchlist.yaml"
    watchlist = load_watchlist(root) if watchlist_path.is_file() else None
    latest_by_symbol = {}
    for day in sorted(grouped, reverse=True):
        for result in grouped[day]:
            latest_by_symbol.setdefault(result.get("symbol"), result)
    items = watchlist.active_items if watchlist is not None else []
    last_run = _as_mapping(banner_data["last_run"])
    batch_items = {}
    if running and last_run.get("run_id") and last_run.get("trade_date"):
        batch_path = root / "data/runs" / str(last_run["trade_date"]) / "batches" / str(last_run["run_id"]) / "batch.json"
        if batch_path.is_file():
            batch_items = _as_mapping(_load_json(batch_path).get("items"))
    news_watch = read_json(root / "data/news_watch.json", {})
    rows = []
    for item in items:
        result = latest_by_symbol.get(item.symbol)
        if result is None:
            result = {"symbol": item.symbol, "type": item.type, "status": "pending", "analyzed_symbol": item.analysis_symbol}
            row = _summary_row(result, None, "")
        else:
            day = result["_date"]
            row = _summary_row(result, _retry_failure(_manifest(root / "data" / "runs" / day), result),
                               f"days/{day}/{result['_slug']}.html", root)
        watch = news_watch.get('items', {}).get(item.symbol, {})
        if (watch.get('run_id') == result.get('run_id') and
            watch.get('information_through') == result.get('information_through') and
            news_watch.get('trade_date') == local_today.isoformat() and watch.get('count')):
            row['news_watch'] = {**watch, 'checked_at':_pretty_timestamp(news_watch.get('checked_at')),
                                 'articles':[{**article, 'time':_pretty_timestamp(article['published_at'])}
                                             for article in watch.get('articles', [])]}
        row["name"] = item.name or row["name"]
        attempt_status = _as_mapping(batch_items.get(symbol_slug(item.symbol))).get("status")
        if attempt_status in {"running", "pending"}:
            row["status"] = "今日分析中" if attempt_status == "running" else "今日排队中"
        rows.append(row)
    if watchlist is None:
        rows = [_summary_row(result, _retry_failure(_manifest(root / "data" / "runs" / latest_day), result),
                             f"days/{latest_day}/{result['_slug']}.html", root) for result in latest_results]
    macro_rows, macro_html = _macro_data(latest_results)
    sector_rows, sector_html = _sector_data(latest_context, latest_results)
    regime = latest_context.get("market_regime") or _latest_result_block(latest_results, "market_regime")
    market = _block_data(regime)
    try:
        vix_text = f"{float(market['vix_close']):.2f}"
    except (TypeError, ValueError, KeyError):
        vix_text = "—"
    summary = {"positive": 0, "neutral": 0, "negative": 0, "pending": 0}
    for row in rows:
        if row["rating_class"] in {"rating-buy", "rating-overweight"}:
            summary["positive"] += 1
        elif row["rating_class"] in {"rating-sell", "rating-underweight"}:
            summary["negative"] += 1
        elif row["rating_class"] == "rating-hold":
            summary["neutral"] += 1
        else:
            summary["pending"] += 1
    body = Markup(HOME.render(
        latest_date=latest_day, rows=rows, summary=summary,
        watchlist=watchlist.items if watchlist else [], managed=managed,
        market_label=market.get("label") or "暂无数据", vix=vix_text,
        market_cards=_context_cards(latest_context, latest_results),
        macro_rows=macro_rows, macro_html=macro_html, sector_rows=sector_rows, sector_html=sector_html,
        model_label=("分析师/辩论 quick：" + _role_summary(load_settings(root).llm.quick.model_dump())
                     + "；研究经理/交易员/组合经理 deep：" + _role_summary(load_settings(root).llm.deep.model_dump())),
    ))
    return _page(title="自选研判", body=body, root_prefix="", index=index,
                 selected_date=latest_day, selected_symbol=None, banner=banner_data,
                 refresh_seconds=60 if running else 300, managed=managed)


def _build_pages(build_root: Path, grouped: dict[str, list[dict[str, Any]]], root: Path, now: datetime) -> int:
    index = _index_data(grouped)
    status = _read_status(root / "data" / "status.json")
    anchor = load_settings(root).schedule.anchor
    local_today = now.astimezone(ZoneInfo(_MARKET_TZ)).date()
    calendar = _calendar_payload(local_today, anchor)
    anchor_match = re.fullmatch(r"(\d{2}):(\d{2})\s+(\S+)", anchor)
    banner_data = {
        **calendar,
        "market_timezone": anchor_match.group(3) if anchor_match else _MARKET_TZ,
        "anchor_time": f"{anchor_match.group(1)}:{anchor_match.group(2)}" if anchor_match else "08:30",
        "last_run": status.get("last_run") or {},
        "last_schedule_event": status.get("last_schedule_event") or {},
    }
    running = _as_mapping(banner_data["last_run"]).get("status") == "running"
    pages = 1
    (build_root / "index.html").write_text(render_home(root, now=now, grouped=grouped), encoding="utf-8")

    all_symbols: dict[str, list[dict[str, Any]]] = {}
    all_results: list[dict[str, Any]] = []
    for day in sorted(grouped, reverse=True):
        day_results = grouped[day]
        day_dir = root / "data" / "runs" / day
        manifest = _manifest(day_dir)
        context = _latest_context(day_dir)
        rows = [
            _summary_row(item, _retry_failure(manifest, item), f"{item['_slug']}.html", root)
            for item in day_results
        ]
        cards = _context_cards(context, day_results)
        day_macro_rows, day_macro_html = _macro_data(day_results)
        day_sector_rows, day_sector_html = _sector_data(context, day_results)
        day_path = build_root / "days" / day
        day_path.mkdir(parents=True, exist_ok=True)
        overview_body = Markup(OVERVIEW.render(
            trade_date=day,
            market_cards=cards,
            macro_rows=day_macro_rows,
            macro_html=day_macro_html,
            sector_rows=day_sector_rows,
            sector_html=day_sector_html,
            rows=rows,
        ))
        day_index = _index_data(grouped)
        (day_path / "index.html").write_text(
            _page(title=f"{day} 总览", body=overview_body, root_prefix="../../",
                  index=day_index, selected_date=day, selected_symbol=None,
                  banner=banner_data, refresh_seconds=60 if running else 0),
            encoding="utf-8",
        )
        pages += 1
        for result in day_results:
            all_results.append(result)
            all_symbols.setdefault(str(result.get("symbol") or "未知"), []).append(result)
            retry = _retry_failure(manifest, result)
            detail_values = _detail_values(result, all_results + [item for item in grouped.get(day, []) if item is not result], retry)
            # 同一标的前后交易日链接需要完整日期序列，稍后补齐。
            same_symbol = [item for values in grouped.values() for item in values if str(item.get("symbol", "")).upper() == str(result.get("symbol", "")).upper()]
            same_symbol.sort(key=lambda item: str(item.get("_date")), reverse=True)
            previous = next((item for item in same_symbol if item.get("_date") < day), None)
            next_result = next((item for item in reversed(same_symbol) if item.get("_date") > day), None)
            slug = str(result.get("_slug") or "UNKNOWN")
            detail_values["previous"] = f"../../days/{previous['_date']}/{slug}.html" if previous else ""
            detail_values["next"] = f"../../days/{next_result['_date']}/{slug}.html" if next_result else ""
            detail_body = Markup(DETAIL.render(**detail_values))
            (day_path / f"{slug}.html").write_text(
                _page(title=f"{day} · {result.get('symbol', '未知')}", body=detail_body,
                      root_prefix="../../", index=day_index, selected_date=day,
                      selected_symbol=str(result.get("symbol")), banner=banner_data,
                      refresh_seconds=60 if running else 0),
                encoding="utf-8",
            )
            pages += 1

    for symbol, values in all_symbols.items():
        values.sort(key=lambda item: str(item.get("_date")), reverse=True)
        slug = symbol_slug(symbol)
        history_rows = []
        for result in values:
            rating, rating_class = _rating(result)
            advice = result.get("final_trade_decision") or result.get("trader_investment_plan")
            if isinstance(advice, Mapping):
                advice = advice.get("action") or advice.get("summary") or advice.get("plan")
            history_rows.append({
                "date": result.get("_date"),
                "rating": rating,
                "rating_class": rating_class,
                "advice": _advice_summary(advice),
                "status": _status(result),
                "mode": "回放" if result.get("mode") == "backfill" else "实时",
                "path": f"../days/{result.get('_date')}/{slug}.html",
            })
        history_body = Markup(HISTORY.render(symbol=symbol, rows=history_rows))
        history_path = build_root / "symbols"
        history_path.mkdir(parents=True, exist_ok=True)
        selected_date = values[0].get("_date") if values else None
        (history_path / f"{slug}.html").write_text(
            _page(title=f"{symbol} 历史", body=history_body, root_prefix="../",
                  index=index, selected_date=selected_date, selected_symbol=symbol,
                  banner=banner_data, refresh_seconds=60 if running else 0),
            encoding="utf-8",
        )
        pages += 1
    return pages


def build_site(project_root: str | Path, *, now: datetime | None = None) -> dict[str, Any]:
    """构建并原子发布站点，失败时返回错误且保留当前 `site` 链接。"""
    root = Path(project_root).expanduser().resolve()
    build_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:6]
    builds = root / "site-builds"
    stage = builds / f".{build_id}.tmp"
    final = builds / build_id
    link_temp = root / f".site-{build_id}"
    site_link = root / "site"
    pages = 0
    published = False
    try:
        if site_link.exists() and not site_link.is_symlink():
            raise OSError("site 已存在但不是符号链接，未覆盖该路径")
        grouped = _read_results(root / "data" / "runs")
        current_time = now or datetime.now(ZoneInfo(_MARKET_TZ))
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=ZoneInfo(_MARKET_TZ))
        builds.mkdir(parents=True, exist_ok=True)
        stage.mkdir()
        pages = _build_pages(stage, grouped, root, current_time)
        os.replace(stage, final)
        os.symlink(Path("site-builds") / build_id, link_temp)
        os.replace(link_temp, site_link)
        published = True
        active_target = (root / os.readlink(site_link)).resolve()
        build_dirs = sorted(
            (path for path in builds.iterdir() if path.is_dir() and not path.name.startswith(".")),
            key=lambda path: path.name,
            reverse=True,
        )
        keep = [active_target]
        for path in build_dirs:
            if path.resolve() != active_target and len(keep) < 3:
                keep.append(path.resolve())
        for path in build_dirs:
            if path.resolve() not in keep:
                shutil.rmtree(path, ignore_errors=True)
        return {
            "ok": True,
            "build_id": build_id,
            "site_path": str(site_link),
            "build_path": str(final),
            "pages": pages,
            "error": None,
        }
    except Exception as exc:
        shutil.rmtree(stage, ignore_errors=True)
        if final.exists() and not published:
            shutil.rmtree(final, ignore_errors=True)
        try:
            link_temp.unlink(missing_ok=True)
        except OSError:
            pass
        return {
            "ok": False,
            "build_id": build_id,
            "site_path": str(site_link),
            "build_path": str(final),
            "pages": pages,
            "error": f"{type(exc).__name__}: {exc}",
        }


__all__ = ["DISCLAIMER", "build_site", "symbol_slug"]

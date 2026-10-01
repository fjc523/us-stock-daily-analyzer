"""从本地批次结果生成离线 HTML 报告站点。"""

from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from collections.abc import Iterable, Mapping
from datetime import date, datetime, time, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import markdown
import nh3
from markupsafe import Markup

from daily_analyzer.config import load_settings
from daily_analyzer.site.templates import BASE, DETAIL, HISTORY, HOME, OVERVIEW

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
    "skipped_timeout": "超时跳过", "skipped": "已跳过",
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
    rendered = markdown.markdown(str(value), extensions=["tables", "fenced_code"])
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
                    "rank": _display(_first(item, ("rank", "position")) or index),
                    "sector": _display(sector_symbol),
                    "symbol": _display(_first(item, ("stock_symbol", "ticker"))),
                    "performance": _display(performance if performance is not None else item.get("score")),
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
    for name, title in (("market_regime", "市场环境"), ("extended_hours", "扩展时段")):
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
    return rows, _markdown(text) if text else None


def _summary_premarket(result: Mapping[str, Any]) -> str:
    direct = _find(
        result,
        ("premarket_change_pct", "pre_market_change_pct", "premarket_pct_change", "premarket_return"),
    )
    if direct is not None:
        return _percentage(direct)
    block = _provider_block(result, "extended_hours")
    data = _block_data(block)
    symbols = [str(result.get("symbol") or ""), str(result.get("analyzed_symbol") or "")]
    for symbol in dict.fromkeys(symbol for symbol in symbols if symbol):
        quote = _as_mapping(data.get(symbol))
        premarket = _as_mapping(quote.get("pre"))
        value = premarket.get("change_pct")
        if value is not None:
            return _percentage(value)
    return "—"


def _summary_sector_rank(result: Mapping[str, Any]) -> Any:
    direct = _find(result, ("sector_rank", "sector_position"))
    if direct is not None:
        return direct
    return _block_data(_provider_block(result, "sector_strength")).get("sector_rank")


def _safe_retry_error(value: Any) -> Any:
    data = _as_mapping(value)
    return data.get("error") if data else None


def _summary_row(result: Mapping[str, Any], retry: Any, detail_path: str) -> dict[str, Any]:
    rating, rating_class = _rating(result)
    advice = result.get("final_trade_decision")
    if isinstance(advice, Mapping):
        advice = advice.get("action") or advice.get("summary") or advice.get("decision")
    if not advice:
        advice = result.get("trader_investment_plan")
    if isinstance(advice, Mapping):
        advice = advice.get("plan") or advice.get("summary") or advice.get("action")
    premarket = _summary_premarket(result)
    sector_rank = _summary_sector_rank(result)
    symbol_type = str(result.get("type") or "")
    proxy = result.get("analyzed_symbol") if symbol_type == "index" else None
    status = _status(result)
    error = result.get("error") or _safe_retry_error(retry)
    return {
        "symbol": str(result.get("symbol") or "未知"),
        "name": str(result.get("name") or "—"),
        "type": {"stock": "个股", "etf": "ETF", "index": "指数"}.get(symbol_type, symbol_type or "—"),
        "proxy": proxy,
        "rating": rating,
        "rating_class": rating_class,
        "advice": _display(advice),
        "premarket": _display(premarket),
        "sector_rank": _display(sector_rank),
        "information_through": _pretty_timestamp(result.get("information_through")),
        "status": status,
        "error": _display(error) if error else None,
        "started_at": _pretty_timestamp(result.get("started_at")),
        "finished_at": _pretty_timestamp(result.get("finished_at")),
        "marks": _marks(result, retry),
        "path": detail_path,
    }


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
            reports.append({"title": str(name), "body": _markdown(text)})
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
        "investment_debate": _markdown(result.get("investment_debate")),
        "risk_debate": _markdown(result.get("risk_debate")),
        "injected_context": _markdown(result.get("injected_context")),
        "timestamps": _timestamp_rows(result),
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
) -> str:
    return BASE.render(
        title=title,
        body=body,
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


def _build_pages(
    build_root: Path,
    grouped: dict[str, list[dict[str, Any]]],
    root: Path,
    now: datetime,
) -> int:
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
    home_refresh = 60 if running else 300
    pages = 0

    latest_day = next(iter(sorted(grouped, reverse=True)), None)
    latest_results = grouped.get(latest_day, []) if latest_day else []
    latest_context = _latest_context(root / "data" / "runs" / latest_day) if latest_day else {}
    latest_manifest = _manifest(root / "data" / "runs" / latest_day) if latest_day else {}
    latest_rows = [
        _summary_row(item, _retry_failure(latest_manifest, item), f"days/{latest_day}/{item['_slug']}.html")
        for item in latest_results
    ]
    macro_rows, macro_html = _macro_data(latest_results)
    sector_rows, sector_html = _sector_data(latest_context, latest_results)
    home_cards = _context_cards(latest_context, latest_results)
    home_body = Markup(HOME.render(
        latest_date=latest_day,
        market_cards=home_cards,
        macro_rows=macro_rows,
        macro_html=macro_html,
        sector_rows=sector_rows,
        sector_html=sector_html,
        rows=latest_rows,
    ))
    (build_root / "index.html").write_text(
        _page(title="首页", body=home_body, root_prefix="", index=index,
              selected_date=latest_day, selected_symbol=None, banner=banner_data,
              refresh_seconds=home_refresh),
        encoding="utf-8",
    )
    pages += 1

    all_symbols: dict[str, list[dict[str, Any]]] = {}
    all_results: list[dict[str, Any]] = []
    for day in sorted(grouped, reverse=True):
        day_results = grouped[day]
        day_dir = root / "data" / "runs" / day
        manifest = _manifest(day_dir)
        context = _latest_context(day_dir)
        rows = [
            _summary_row(item, _retry_failure(manifest, item), f"{item['_slug']}.html")
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
                "advice": _display(advice),
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

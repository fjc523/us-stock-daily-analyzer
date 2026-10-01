"""美东交易日、运行模式与锚点判断。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd


NEW_YORK = ZoneInfo("America/New_York")


class NoTradingSessionError(ValueError):
    """当前没有可分析的交易日。"""


@dataclass(frozen=True)
class RunWindow:
    trade_date: date
    price_data_end_date: date
    mode: str
    news_cutoff_utc: datetime | None


def as_new_york(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=NEW_YORK)
    return value.astimezone(NEW_YORK)


def is_trading_day(value: date) -> bool:
    return bool(xcals.get_calendar("XNYS").is_session(pd.Timestamp(value)))


def previous_trading_day(value: date) -> date:
    calendar = xcals.get_calendar("XNYS")
    session = calendar.date_to_session(pd.Timestamp(value), direction="previous")
    if session.date() >= value:
        session = calendar.previous_session(session)
    return session.date()


def session_bounds(value: date) -> tuple[datetime, datetime]:
    calendar = xcals.get_calendar("XNYS")
    session = pd.Timestamp(value)
    if not calendar.is_session(session):
        raise ValueError(f"{value.isoformat()} 不是 NYSE 交易日")
    opened = calendar.session_open(session).to_pydatetime().astimezone(NEW_YORK)
    closed = calendar.session_close(session).to_pydatetime().astimezone(NEW_YORK)
    return opened, closed


def parse_trade_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("--date 必须使用 YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise ValueError("--date 必须使用 YYYY-MM-DD")
    return parsed


def select_run_window(date_value: str | None, now: datetime) -> RunWindow:
    current = as_new_york(now)
    today = current.date()
    if date_value is None:
        if not is_trading_day(today) or current >= session_bounds(today)[1]:
            raise NoTradingSessionError("当前没有可分析的交易日；下一个交易日将在锚点时刻自动分析")
        trade_day = today
    else:
        trade_day = parse_trade_date(date_value)
        if trade_day > today:
            raise ValueError("未来交易日将于当天锚点时刻自动分析")
        if not is_trading_day(trade_day):
            raise ValueError(f"{trade_day.isoformat()} 不是 NYSE 交易日")

    previous = previous_trading_day(trade_day)
    backfill = trade_day < today or (
        trade_day == today and current >= session_bounds(trade_day)[1]
    )
    cutoff = (
        datetime.combine(trade_day, time(8, 31), NEW_YORK).astimezone(timezone.utc)
        if backfill
        else None
    )
    return RunWindow(
        trade_date=trade_day,
        price_data_end_date=previous,
        mode="backfill" if backfill else "live",
        news_cutoff_utc=cutoff,
    )


def scheduled_decision(
    anchor: str,
    now: datetime,
    *,
    already_completed: bool,
    recover_interrupted: bool,
) -> tuple[str, str] | None:
    """返回应记录的跳过/启动事件；可启动时返回 None。"""
    current = as_new_york(now)
    today = current.date()
    if not is_trading_day(today):
        return "skipped_not_trading_day", "NYSE 今日休市"
    hour_minute, zone_name = anchor.split(maxsplit=1)
    hour, minute = map(int, hour_minute.split(":"))
    anchor_at = datetime.combine(today, time(hour, minute), ZoneInfo(zone_name))
    if current < anchor_at:
        return "skipped_before_anchor", f"尚未到锚点 {hour_minute} {zone_name}"
    if current >= session_bounds(today)[1]:
        return "skipped_after_close", "已过当日收盘时刻"
    if already_completed:
        return "skipped_already_done", "今日已有已结束的定时批次"
    if recover_interrupted:
        return "recovery_started", "恢复当天尚未成功的标的"
    return None


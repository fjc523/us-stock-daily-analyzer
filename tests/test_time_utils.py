from __future__ import annotations

from datetime import datetime, timezone
import pytest

from daily_analyzer.time_utils import (
    NEW_YORK,
    NoTradingSessionError,
    scheduled_decision,
    select_run_window,
)


def test_live_and_backfill_windows_use_previous_complete_session() -> None:
    live_now = datetime(2026, 10, 2, 10, 15, tzinfo=NEW_YORK)
    live = select_run_window(None, live_now)
    assert live.mode == "live"
    assert live.trade_date.isoformat() == "2026-10-02"
    assert live.price_data_end_date.isoformat() == "2026-10-01"
    assert live.news_cutoff_utc is None

    replay_now = datetime(2026, 10, 2, 17, 0, tzinfo=NEW_YORK)
    replay = select_run_window("2026-10-02", replay_now)
    assert replay.mode == "backfill"
    assert replay.price_data_end_date.isoformat() == "2026-10-01"
    assert replay.news_cutoff_utc == datetime(2026, 10, 2, 12, 31, tzinfo=timezone.utc)


def test_historical_replay_and_future_rejection() -> None:
    now = datetime(2026, 10, 2, 10, 0, tzinfo=NEW_YORK)
    replay = select_run_window("2026-09-14", now)
    assert replay.mode == "backfill"
    assert replay.trade_date.isoformat() == "2026-09-14"
    assert replay.price_data_end_date.isoformat() == "2026-09-11"

    with pytest.raises(ValueError, match="未来交易日"):
        select_run_window("2026-10-05", now)
    with pytest.raises(ValueError, match="不是 NYSE 交易日"):
        select_run_window("2026-09-26", now)


def test_manual_run_without_session_is_rejected_but_schedule_skips() -> None:
    saturday = datetime(2026, 10, 3, 9, 0, tzinfo=NEW_YORK)
    with pytest.raises(NoTradingSessionError):
        select_run_window(None, saturday)
    assert scheduled_decision(
        "08:30 America/New_York",
        saturday,
        already_completed=False,
        recover_interrupted=False,
    ) == ("skipped_not_trading_day", "NYSE 今日休市")


@pytest.mark.parametrize(
    ("now", "completed", "expected"),
    [
        (datetime(2026, 12, 3, 7, 30, tzinfo=NEW_YORK), False, "skipped_before_anchor"),
        (datetime(2026, 12, 3, 8, 45, tzinfo=NEW_YORK), True, "skipped_already_done"),
        (datetime(2026, 12, 3, 16, 1, tzinfo=NEW_YORK), False, "skipped_after_close"),
    ],
)
def test_scheduled_gate_reasons(now: datetime, completed: bool, expected: str) -> None:
    decision = scheduled_decision(
        "08:30 America/New_York",
        now,
        already_completed=completed,
        recover_interrupted=False,
    )
    assert decision is not None
    assert decision[0] == expected

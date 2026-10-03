"""从业务边界独立验证日期窗口；全部使用固定美东时钟。"""
from datetime import datetime, timezone

import pytest

from daily_analyzer.time_utils import NEW_YORK, scheduled_decision, select_run_window


@pytest.mark.parametrize('stamp,price_end', [
    ('2026-10-03T09:17:43-04:00', '2026-10-02'),
    ('2026-10-04T19:12:19-04:00', '2026-10-02'),
    ('2026-09-07T10:02:30-04:00', '2026-09-04'),
    ('2026-11-27T13:01:00-05:00', '2026-11-27'),
    ('2026-11-27T20:14:00-05:00', '2026-11-27'),
    ('2026-10-02T20:17:00-04:00', '2026-10-02'),
    ('2026-10-02T15:59:59-04:00', '2026-10-01'),
])
def test_当前手动窗口不拒绝且不套历史新闻截止(stamp, price_end):
    now = datetime.fromisoformat(stamp)
    window = select_run_window(None, now)
    assert window.mode == 'live'
    assert window.trade_date == now.astimezone(NEW_YORK).date()
    assert window.price_data_end_date.isoformat() == price_end
    assert window.news_cutoff_utc is None


@pytest.mark.parametrize('stamp,expected', [
    ('2026-10-03T09:17:43-04:00', 'skipped_not_trading_day'),
    ('2026-09-07T10:02:30-04:00', 'skipped_not_trading_day'),
    ('2026-11-27T13:01:00-05:00', 'skipped_after_close'),
    ('2026-10-02T20:17:00-04:00', 'skipped_after_close'),
])
def test_定时入口仍按原交易日锚点跳过(stamp, expected):
    decision = scheduled_decision('08:30 America/New_York', datetime.fromisoformat(stamp),
                                  already_completed=False, recover_interrupted=False)
    assert decision[0] == expected


@pytest.mark.parametrize('date_value,price_end,cutoff', [
    ('2026-10-02', '2026-10-01', '2026-10-02T12:31:00+00:00'),
    ('2026-09-04', '2026-09-03', '2026-09-04T12:31:00+00:00'),
    ('2026-11-27', '2026-11-25', '2026-11-27T13:31:00+00:00'),
])
def test_显式回放始终保留当日盘前截止(date_value, price_end, cutoff):
    now = datetime(2026, 11, 28, 11, 22, tzinfo=NEW_YORK)
    window = select_run_window(date_value, now)
    assert window.mode == 'backfill'
    assert window.price_data_end_date.isoformat() == price_end
    assert window.news_cutoff_utc == datetime.fromisoformat(cutoff)


def test_未来与显式非交易日不偷偷转成最新分析():
    now = datetime(2026, 10, 3, 11, 17, tzinfo=NEW_YORK)
    with pytest.raises(ValueError, match='未来'):
        select_run_window('2026-10-05', now)
    with pytest.raises(ValueError, match='不是 NYSE 交易日'):
        select_run_window('2026-10-03', now)

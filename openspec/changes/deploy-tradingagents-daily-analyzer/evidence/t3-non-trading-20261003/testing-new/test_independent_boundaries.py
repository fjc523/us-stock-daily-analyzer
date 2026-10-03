"""独立时区与实际收盘边界断言，全部固定时钟。"""
from datetime import datetime

import pytest

from daily_analyzer.time_utils import select_run_window


@pytest.mark.parametrize('stamp,request_day,daily_end', [
    ('2026-10-03T01:30:00+08:00', '2026-10-02', '2026-10-01'),
    ('2026-10-03T04:00:00+08:00', '2026-10-02', '2026-10-02'),
    ('2026-10-03T12:00:00+08:00', '2026-10-03', '2026-10-02'),
    ('2026-11-27T12:59:59-05:00', '2026-11-27', '2026-11-25'),
    ('2026-11-27T13:00:00-05:00', '2026-11-27', '2026-11-27'),
    ('2026-09-07T00:00:00-04:00', '2026-09-07', '2026-09-04'),
])
def test_请求自然日与最近完整日线按美东实际收盘区分(stamp, request_day, daily_end):
    window = select_run_window(None, datetime.fromisoformat(stamp))
    assert window.mode == 'live'
    assert window.trade_date.isoformat() == request_day
    assert window.price_data_end_date.isoformat() == daily_end
    assert window.news_cutoff_utc is None

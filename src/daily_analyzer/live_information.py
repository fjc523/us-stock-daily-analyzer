"""父仓库的实时信息适配：单次查询截止、运行作用域与上游回放隔离。"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
import json
import threading

_LOCK = threading.Lock()
_ACTIVE_CLOCK = ContextVar('daily_live_information_clock', default=None)


@contextmanager
def live_information_scope(clock):
    """仅当前图传播拥有实时过滤权限；退出或异常均恢复此前作用域。"""
    token = _ACTIVE_CLOCK.set(clock)
    try:
        yield
    finally:
        _ACTIVE_CLOCK.reset(token)


def _alpha_response(value, cutoff):
    """只过滤有结构化发布时间的feed；错误响应及原返回类型保持。"""
    was_text = isinstance(value, str)
    if was_text:
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return value
    else:
        parsed = value
    if not isinstance(parsed, dict) or not isinstance(parsed.get('feed'), list):
        return value
    rows = []
    unverified = 0
    future = 0
    for row in parsed['feed']:
        try:
            stamp = datetime.strptime(str(row.get('time_published')), '%Y%m%dT%H%M%S').replace(tzinfo=timezone.utc)
        except (ValueError, TypeError, AttributeError):
            unverified += 1
            continue
        if stamp < cutoff:
            rows.append(row)
        else:
            future += 1
    filtered = {**parsed, 'feed': rows, 'items': str(len(rows)),
                '信息检索说明': f"检索截止 {cutoff.isoformat()}；发布时间无法核验 {unverified} 条，未来消息 {future} 条已排除；未返回结果不等于没有消息。"}
    return json.dumps(filtered, ensure_ascii=False) if was_text else filtered


def _wrap(function, *, alpha=False):
    if getattr(function, '_daily_live_information', False):
        return function

    @wraps(function)
    def read(*args, **kwargs):
        from tradingagents.dataflows.config import get_config, run_config
        config = get_config()
        clock = _ACTIVE_CLOCK.get()
        configured_clock = config.get('_daily_live_information_clock')
        if not callable(clock) or not callable(configured_clock) or config.get('news_cutoff_utc'):
            return function(*args, **kwargs)
        # 一次调用固定一个截止，不能随每条过滤滚动，也不冻结整个分析。
        stamp = clock()
        if stamp.tzinfo is None:
            raise ValueError('实时信息查询时钟必须带时区')
        stamp = stamp.astimezone(timezone.utc)
        with run_config({**config, 'news_cutoff_utc': stamp.isoformat()}):
            value = function(*args, **kwargs)
            if alpha:
                return _alpha_response(value, stamp)
            if isinstance(value, str):
                value += f"\n\n本次信息检索截止 {stamp.isoformat()}；缺发布时间的条目无法核验，不进入本次证据；未返回结果不等于没有消息。"
            return value

    read._daily_live_information = True
    return read


def install_live_information_adapter():
    """幂等包装实际信息入口；未带本图私有配置的调用保留原路径。"""
    from tradingagents.dataflows import router
    from tradingagents.agents.analysts import sentiment_analyst
    with _LOCK:
        for name in ('get_news', 'get_global_news'):
            for vendor in ('alpaca', 'yfinance', 'alpha_vantage'):
                original = router.VENDOR_METHODS[name].get(vendor)
                if original is not None:
                    router.VENDOR_METHODS[name][vendor] = _wrap(original, alpha=vendor == 'alpha_vantage')
        for name in ('fetch_stocktwits_messages', 'fetch_reddit_posts'):
            setattr(sentiment_analyst, name, _wrap(getattr(sentiment_analyst, name)))

"""仅供展示的分析时报价：同源价格、真实时间与冻结截止验证。"""
from datetime import datetime, time, timedelta
from collections.abc import Mapping
from math import isfinite
from zoneinfo import ZoneInfo

from ..time_utils import session_bounds, is_trading_day, previous_trading_day

EASTERN = ZoneInfo('America/New_York')


def active_window(cutoff):
    """按报告交易日和 NYSE 实际开收盘确定活跃时段。"""
    four = datetime.combine(cutoff.date(), time(4), EASTERN)
    twenty = datetime.combine(cutoff.date(), time(20), EASTERN)
    if cutoff >= twenty:
        # 夜盘属于下一自然日交易日；周五晚和假日前晚不能伪称开市。
        session_bounds(cutoff.date() + timedelta(days=1))
        return 'overnight', twenty, four + timedelta(days=1)
    opened, closed = session_bounds(cutoff.date())
    if cutoff < four:
        return 'overnight', twenty - timedelta(days=1), four
    if cutoff < opened:
        return 'pre', four, opened
    if cutoff < closed:
        return 'regular', opened, closed
    if cutoff < twenty:
        return 'after', closed, twenty
    raise ValueError('无有效交易时段')


def recent_after_window(cutoff):
    """当前休市/收盘后请求采用最近完整交易日的实际盘后窗口。"""
    cutoff = cutoff.astimezone(EASTERN)
    day = cutoff.date()
    if is_trading_day(day):
        _, closed = session_bounds(day)
        if cutoff < closed:
            return None
    else:
        day = previous_trading_day(day)
        _, closed = session_bounds(day)
    return closed, datetime.combine(day, time(20), EASTERN)


def observation(symbol, cutoff, candidate=None, close=None, *, recent_after=False):
    """候选必须携带明确原始字段证据；价格有效不依赖涨幅基准。"""
    candidate = dict(candidate or {})
    try:
        close = float(close)
        if not isfinite(close) or close <= 0:
            close = None
    except (TypeError, ValueError):
        close = None
    result = dict(candidate, symbol=symbol, cutoff=cutoff.isoformat(),
                  official_previous_close=close, benchmark_verified=close is not None,
                  change_pct=None)
    try:
        window = recent_after_window(cutoff) if recent_after else None
        session, start, end = ('after', *window) if window else active_window(cutoff)
    except ValueError:
        result.update(session=None, status='时段未核验（非交易日）')
        return result
    result['session'] = session
    try:
        price = float(candidate.get('price'))
        if not isfinite(price) or price <= 0:
            raise ValueError
    except (TypeError, ValueError):
        result.update(price=None, status='数据不可用')
        return result
    try:
        stamp = datetime.fromisoformat(str(candidate.get('quote_time')).replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError
    except (TypeError, ValueError):
        result['status'] = '真实行情时间未核验'
        return result
    evidence = candidate.get('time_field')
    allowed = {'latestTrade.t', 'minute.t', 'data_date+data_time', 'pre_update_time',
               'after_update_time', 'overnight_update_time', 'futu_kline.time_key', 'sip_minute.t'}
    if recent_after:
        # 最近盘后只认独立after或同源成交/分钟时间，不能借盘前、夜盘或当前价时间。
        allowed = {'after_update_time', 'latestTrade.t', 'minute.t', 'futu_kline.time_key', 'sip_minute.t'}
    if evidence not in allowed:
        result['status'] = '真实行情时间未核验'
    elif stamp > cutoff:
        result['status'] = '未来报价（超过分析截止）'
    elif (not start < stamp <= end if evidence in {'futu_kline.time_key', 'sip_minute.t'} else not start <= stamp < end) or (recent_after and stamp == start and evidence != 'after_update_time'):
        result['status'] = '非本时段数据'
    elif recent_after and evidence == 'minute.t' and (stamp.second or stamp.microsecond or stamp + timedelta(minutes=1) > min(cutoff, end)):
        result['status'] = '分钟尚未完整（超过分析截止）'
    elif not (recent_after and cutoff >= end) and (cutoff - stamp).total_seconds() > (2700 if evidence == 'sip_minute.t' and 'feed=sip' in str(candidate.get('source')) else 1800):
        result['status'] = '过期'
    else:
        result['status'] = '可用'
        if recent_after:
            result['age_seconds'] = max(0.0, (cutoff - stamp).total_seconds())
            warnings = str(candidate.get('warning') or '').split('；')
            warnings += ['最近可检索盘后', '陈旧（已结束时段）' if cutoff >= end and result['age_seconds'] > 1800 else None]
            result['warning'] = '；'.join(dict.fromkeys(filter(None, warnings)))
        if close is not None and close > 0:
            result['change_pct'] = (price / close - 1) * 100
    return result


def raw_futu(row, session, source):
    """当前价时间仅用于常规 last_price，不移植到独立扩展价。"""
    if not isinstance(row, Mapping):
        return None
    if session == 'regular':
        stamp = f"{row.get('data_date')} {row.get('data_time')}"
        field, price = 'data_date+data_time', row.get('last_price')
    else:
        field, price = f'{session}_update_time', row.get(f'{session}_price')
        stamp = row.get(field)
    try:
        parsed = datetime.fromisoformat(str(stamp))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=EASTERN)
    except ValueError:
        parsed = None
    return {'price': price, 'quote_time': parsed.isoformat() if parsed else None,
            'time_field': field, 'source': source}


def raw_alpaca(snapshot, source):
    """只认 latestTrade 的 p/t；快照刷新时间不是成交时间。"""
    if not isinstance(snapshot, Mapping):
        return None
    trade = snapshot.get('latestTrade') or snapshot.get('latest_trade')
    if not isinstance(trade, Mapping):
        return None
    return {'price': trade.get('p', trade.get('price')),
            'quote_time': trade.get('t', trade.get('timestamp')),
            'time_field': 'latestTrade.t', 'source': source,
            'warning': 'IEX 覆盖不完整' if 'iex' in source else None}

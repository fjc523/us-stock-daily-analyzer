"""只收敛模型上下文，保留提供器原始 Markdown 与全部结果数据。"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import re

import exchange_calendars as xcals

from daily_analyzer.context.base import ContextBlock, render_context
from daily_analyzer.data_sources.treasury import TREASURY_SOURCE

EASTERN = ZoneInfo('America/New_York')
CORE_BLOCKS = {'market_regime', 'sector_strength', 'extended_hours', 'price_anchors', 'position_structure', 'etf_structure'}


def _time(row):
    """只读取结构化时刻，不从事件标题猜测日期。"""
    value = row.get('发布时间ET') or row.get('release_time')
    try:
        stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return stamp.astimezone(EASTERN) if stamp.tzinfo else None
    except (ValueError, TypeError):
        try:
            return datetime.fromtimestamp(float(row['timestamp']), EASTERN)
        except (KeyError, ValueError, TypeError, OverflowError):
            return None


def _cell(value):
    text = str(value if value not in (None, '') else '—').replace('|', '／').replace('\n', ' ')
    if re.fullmatch(r'[+-]?\d+\.\d+', text):
        text = text.rstrip('0').rstrip('.')
    return text


def _calendar_number(value, unit=None):
    """仅识别明确数值和单位，不从事件标题推测尺度。"""
    text = str(value).strip().replace('％', '%').replace(',', '')
    match = re.fullmatch(r'([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(%|千人|万人|人|千|万|K|M)?', text, re.I)
    if not match:
        return None
    suffix = match.group(2) or str(unit or '').strip()
    if not suffix:
        return None
    units = {'number': ('number', Decimal(1), ''), '%': ('percent', Decimal(1), '百分点'),
             '人': ('people', Decimal(1), '人'), '千人': ('people', Decimal(1000), '千人'),
             '万人': ('people', Decimal(10000), '万人'), '千': ('number', Decimal(1000), '千'),
             '万': ('number', Decimal(10000), '万'), 'K': ('number', Decimal(1000), 'K'),
             'M': ('number', Decimal(1000000), 'M')}
    spec = units.get(suffix.upper() if suffix.upper() in ('K', 'M') else suffix)
    if spec is None:
        return None
    number = Decimal(match.group(1))
    return number, spec


def _difference(actual, estimate, unit=None):
    """可比较实际减预期，显式尺度换算，方向只描述数值不判断利多利空。"""
    if estimate in (None, ''):
        return '无预期'
    a, e = _calendar_number(actual, unit), _calendar_number(estimate, unit)
    if a is None or e is None or a[1][0] != e[1][0]:
        return '不可比较（单位或数值未核验）'
    diff = (a[0] * a[1][1] - e[0] * e[1][1]) / a[1][1]
    direction = '高于预期' if diff > 0 else '低于预期' if diff < 0 else '持平'
    return f'{diff:+g}{a[1][2]}（{direction}）'


def _calendar_unit(row):
    """渲染单位优先原字段，其次标题明示单位，再用BLS具体事件单位。"""
    if row.get('unit'):
        return row['unit']
    title = str(row.get('title') or row.get('event') or '')
    explicit = re.search(r'[（(](%|千人|万人|人|千|万|K|M)[）)]', title, re.I)
    if explicit:
        return explicit.group(1)
    # BLS失业率表以percent计；平均每小时工资月/年率为percent change。
    # https://www.bls.gov/eag/eag.us.htm 与 https://www.bls.gov/news.release/empsit.htm
    if re.fullmatch(r'美国(?:\d+年)?\d+月(?:(?:U6)?失业率|平均每小时工资[月年]率)', title):
        return '%'
    return None


def calendar_markdown(calendars, as_of, *, short=False, validity=5):
    """完整HIGH优先；有效期采用从请求日起的五个实际XNYS交易日。"""
    as_of = as_of.astimezone(EASTERN)
    calendar = xcals.get_calendar('XNYS')
    first = calendar.date_to_session(as_of.date().isoformat(), direction='next')
    last = calendar.session_offset(first, validity - 1).date()
    start = first.date()
    rows, omitted = [], 0
    for index, row in enumerate(calendars.get('economics', [])):
        level = str(row.get('star') or row.get('importance') or '').upper()
        stamp = _time(row)
        in_window = stamp is not None and start <= stamp.date() <= last
        keep = level == 'HIGH' and (not short or (in_window and stamp >= as_of))
        keep = keep or (not short and level == 'MEDIUM' and in_window)
        if keep:
            rows.append((stamp, index, row, level))
        else:
            omitted += 1
    rows.sort(key=lambda entry: (entry[0] or datetime.max.replace(tzinfo=EASTERN), entry[1]))
    lines = ['重要度：高=HIGH、中=MEDIUM；时间为ET，未列月日沿用本组首行，↳同上。事件均为美国；年份同上下文。',
             '|发布时间ET|事件|重要度|前值|预期|实际|意外差|',
             '|---|---|---|---|---|---|---|']
    previous_stamp = None
    for stamp, _, row, level in rows:
        actual = row.get('actual')
        estimate = row.get('consensus')
        if estimate in (None, ''):
            estimate = row.get('estimate')
        published = stamp is not None and stamp <= as_of and actual not in (None, '', '尚未发布', '未发布')
        if not published:
            actual = '未发布'
        if stamp and stamp == previous_stamp:
            time_text = '↳'
        elif stamp:
            time_text = stamp.strftime('%H:%M' if previous_stamp and stamp.date() == previous_stamp.date() else '%Y-%m-%d %H:%M' if stamp.year != as_of.year else '%m-%d %H:%M')
        else:
            time_text = '时间未核验'
        title = str(row.get('title') or row.get('event') or '事件未注明').removeprefix('美国')
        lines.append('|' + '|'.join(map(_cell, [
            time_text, title,
            '高' if level == 'HIGH' else '中', row.get('previous'), estimate, actual,
            _difference(actual, estimate, _calendar_unit(row)) if published else ('未发布；无预期' if estimate in (None, '') else '未发布'),
        ])) + '|')
        previous_stamp = stamp
    if not rows:
        lines.append('当前窗口无可核验的适用经济事件。')
    if omitted:
        lines.append(f'另有 {omitted} 条不属于本档位的重要度或有效期事件已省略，完整数据见结果文件 `context_blocks.macro_releases.data.calendars`。')
    return '\n'.join(lines)


def earnings_markdown(calendars):
    """提供器已按本标的筛选，不注入其他订阅财报日。"""
    rows = calendars.get('earnings', [])
    if not rows:
        return '日历中未找到已确认的财报日'
    lines = ['本标的已确认财报日：']
    for row in rows:
        # 富途和Yahoo日历字段不同，保留已有字段而不编造发布时间。
        fields = [f'{key}：{_cell(value)}' for key, value in row.items() if value not in (None, '')]
        lines.append('- ' + '；'.join(fields))
    return '\n'.join(lines)


def compact_macro(payload, as_of, *, short=False, validity=5):
    data = payload.get('data', {})
    calendars = data.get('calendars', {})
    if short:
        return ('#### 本标的财报日\n' + earnings_markdown(calendars) +
                '\n\n#### 未来有效期HIGH经济事件\n' + calendar_markdown(calendars, as_of, short=True, validity=validity))
    text = str(payload.get('markdown') or '')
    # 定位旧版固定日历段，只替换prompt文本；其他新闻/经济发布正文不改。
    text = text.split('\n#### 决策周期日历（富途）', 1)[0].rstrip()
    def local_time(match):
        stamp = datetime.fromisoformat(match.group()).astimezone(EASTERN)
        return stamp.strftime('%H:%M:%S') if stamp.date() == as_of.astimezone(EASTERN).date() else stamp.strftime('%Y-%m-%d %H:%M:%S' if stamp.year != as_of.year else '%m-%d %H:%M:%S')
    text = re.sub(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:\d{2}|Z)', local_time, text)
    text = '新闻及当日发布时刻均为ET，当日仅列时分秒，其他日期列月日时刻。\n' + text
    treasury = data.get('treasury_yield')
    if treasury:
        text = text.replace(str(treasury), TREASURY_SOURCE.compact(str(treasury)))
    if calendars:
        text += ('\n\n#### 决策周期日历（富途）\n' + earnings_markdown(calendars) +
                 '\n美国经济事件：\n' + calendar_markdown(calendars, as_of, validity=validity))
    return text


def render_compacted_context(blocks, as_of, *, profile='full', validity=5):
    """保留来源与质量标记，构造副本供现有渲染器消费。"""
    if isinstance(as_of, str):
        as_of = datetime.fromisoformat(as_of.replace('Z', '+00:00'))
    payloads = {}
    for name, block in blocks.items():
        if profile == 'brief' and name not in CORE_BLOCKS | {'macro_releases'}:
            continue
        payload = block.to_dict() if isinstance(block, ContextBlock) else dict(block)
        if name == 'macro_releases':
            payload['markdown'] = compact_macro(payload, as_of, short=profile == 'brief', validity=validity)
        payload['markdown'] = '\n'.join('|' + '|'.join(cell.strip() for cell in line.split('|')[1:-1]) + '|' if line.startswith('|') and line.endswith('|') else line for line in str(payload.get('markdown') or '').splitlines())
        payloads[name] = payload
    return render_context(payloads, as_of)

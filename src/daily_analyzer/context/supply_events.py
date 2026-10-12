"""人工录入供给条款的逐行校验、严格可见时点过滤与共享来源上下文。"""
from datetime import date as Date, datetime, timedelta
from pathlib import Path
from typing import Literal
import math

import exchange_calendars as xcals
from pydantic import BaseModel, ConfigDict, Field, model_validator
import yaml

from tradingagents.dataflows.errors import VendorError
from .base import ContextBlock, _value
from .market_data import _bar_date, _expected_sessions


class SupplySource(BaseModel):
    form: str
    accession: str
    url: str
    visible_at: datetime

    @model_validator(mode='after')
    def aware(self):
        if self.visible_at.tzinfo is None:
            raise ValueError('来源可见时刻必须带时区')
        return self


class SupplyEvent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    symbol: str
    kind: Literal['lockup_release']
    date_rule: Literal['fixed', 'after_earnings']
    date: Date | None = None
    earnings_period_end: Date | None = None
    trading_days_after: int | None = Field(default=None, gt=0)
    shares_max: int = Field(gt=0, strict=True)
    shares_text: str
    condition: str | None = None
    source: SupplySource
    entered_at: datetime

    @model_validator(mode='after')
    def dates(self):
        if self.entered_at.tzinfo is None:
            raise ValueError('录入时刻必须带时区')
        if self.date_rule == 'fixed' and self.date is None:
            raise ValueError('固定事件必须有原文日期')
        if self.date_rule == 'after_earnings' and (self.earnings_period_end is None or self.trading_days_after is None):
            raise ValueError('财报后事件必须有报告期和完整交易日数')
        return self


def _stamp(value):
    stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00')) if not isinstance(value, datetime) else value
    if stamp.tzinfo is None:
        raise ValueError('截止和申报可见时刻必须带时区')
    return stamp


def _prospectuses(symbol, cutoff):
    """复用 SEC 的身份映射、24小时缓存和列式校验；缺时刻不当作无申报。"""
    from tradingagents.dataflows.vendors import sec_edgar as sec
    cik = sec.cik_for(symbol)
    if cik is None:
        raise ValueError('SEC 身份不可得')
    payload = sec._cached_json(sec._SUBMISSIONS_URL.format(cik=cik), f'submissions_CIK{cik}.json')
    filings = payload['filings']
    tables = [filings['recent']]
    lower = cutoff.date() - timedelta(days=400)
    for archive in filings.get('files', []):
        if archive['filingTo'] >= lower.isoformat() and archive['filingFrom'] <= cutoff.date().isoformat():
            name = archive['name']
            tables.append(sec._cached_json(sec._SUBMISSIONS_ARCHIVE_URL.format(name=name), f'submissions_{name}'))
    result = []
    for table in tables:
        for row in sec._submission_rows(table, cutoff.date().isoformat()):
            if row['form'] not in ('424B4', '424B1') or row['filingDate'] < lower.isoformat():
                continue
            if _stamp(row.get('acceptanceDateTime')) <= cutoff:
                result.append(row)
    return result


class SupplyEventsProvider:
    name = 'supply_events'
    scope = 'ticker'

    def __init__(self, services):
        self.services = services
        self.events, self.invalid = [], []
        self.error = None

    def prepare(self, batch):
        self.end = Date.fromisoformat(str(_value(batch, 'price_data_end_date'))[:10])
        try:
            payload = yaml.safe_load((Path(self.services.project_root) / 'config/supply_events.yaml').read_text())
            if not isinstance(payload, dict) or not isinstance(payload.get('events'), list):
                raise ValueError('事件文件缺少 events 列表')
            self.events, self.invalid = [], []
            for row in payload['events']:
                try:
                    self.events.append(SupplyEvent.model_validate(row))
                except (ValueError, TypeError) as exc:
                    self.invalid.append({'status': '无效条目（原文保留）', 'raw': row, 'error': str(exc)})
            self.error = None
        except (OSError, ValueError, yaml.YAMLError) as exc:
            self.error = f'事件文件不可得：{type(exc).__name__}'

    def build(self, item, cutoff):
        if _value(item, 'type') != 'stock':
            return None
        symbol, cutoff = _value(item, 'symbol'), _stamp(cutoff)
        # 无法确定归属的坏条目保守影响全部股票；有效条目继续保留并渲染。
        invalid = [row for row in self.invalid if not isinstance(row['raw'], dict) or row['raw'].get('symbol') in (None, symbol)]
        data = {'symbol': symbol, 'events': [], 'invalid_entries': invalid, 'warnings': []}
        events = [event for event in self.events if event.symbol == symbol and event.source.visible_at <= cutoff]
        calendar = xcals.get_calendar('XNYS')
        p = calendar.date_to_session(self.end.isoformat(), direction='previous')
        first, last = calendar.session_offset(p, -10).date(), calendar.session_offset(p, 30).date()
        previous = calendar.session_offset(p, -11).date()
        rows, source = self.services.prices.bars(symbol, self.end) if events else ([], '不可用')
        volumes = {}
        sessions = _expected_sessions(self.end, 20)
        for row in rows:
            day = _bar_date(row)
            try:
                volume = float(row.get('Volume', row.get('volume', row.get('v'))))
                if day in sessions and math.isfinite(volume) and volume > 0:
                    volumes[day] = volume
            except (TypeError, ValueError):
                continue
        average = sum(volumes.values()) / 20 if len(volumes) == 20 else None
        lines, urls = [], []
        for event in events:
            # 原文日期不晚于前一交易日或晚于窗口终点，顺延后也不可能落入窗口。
            # 先过滤，避免合法的远期/旧条款越过日历可用范围而影响其他记录。
            if event.date_rule == 'fixed' and (event.date <= previous or event.date > last):
                continue
            effective = calendar.date_to_session(event.date.isoformat(), direction='next').date() if event.date_rule == 'fixed' else None
            if effective is not None and not first <= effective <= last:
                continue
            timing = (f'原文日期 {event.date}／首个可交易日 {effective}（' + ('已发生' if effective <= self.end else '待发生') + '）') if effective else f'{event.earnings_period_end}季度财报公布后第{event.trading_days_after}个完整交易日；财报日未经公司确认，日期未定'
            ratio = f'≈{event.shares_max / average:.1f}个20日均量日' if average else '20日均量日：未知（日线不足20个完整交易日）'
            lines.append(f'- {timing}；最多{event.shares_max:,}股；{ratio}；占流通盘：未知（无可核实流通股来源）。原文：{event.shares_text}；条件：{event.condition or "原文未附加条件"}；来源 {event.source.form} {event.source.accession}，可见于 {event.source.visible_at.isoformat()}，{event.source.url}')
            data['events'].append({**event.model_dump(mode='json'), 'first_tradable_date': str(effective) if effective else None, 'volume_days': event.shares_max / average if average else None})
            urls.append(event.source.url)
        try:
            # 提供器先于图初始化；显式绑定同一项目缓存，保留已有图配置与 User-Agent。
            from tradingagents.dataflows.config import get_config, run_config
            config = get_config()
            config['data_cache_dir'] = str(Path(self.services.project_root) / 'data/tradingagents/cache')
            with run_config(config):
                filings = _prospectuses(symbol, cutoff)
            data['prospectuses'] = filings
            state = '有事件' if lines else ('未知·未录入' if filings and not events else '已核查无')
            reason = '展示窗口内已录入可见锁定期条款；不代表实际出售' if lines else ('有最终招股书：' + '；'.join(f"{row['filingDate']} {row.get('accessionNumber')}" for row in filings) + '；锁定期条款未录入') if filings and not events else ('已录入可见条款，展示窗口内无事件' if events else '近400日SEC申报无最终招股书(424B4/424B1)；未录入其他供给事件（增发、可转债等不在本块范围）')
        except (ValueError, TypeError, KeyError, OSError, RuntimeError, VendorError) as exc:
            state, reason = '未知·来源不可得', f'SEC 来源不可得：{type(exc).__name__}'
        if self.error or invalid:
            state, reason = '未知·来源不可得', self.error or '存在无效条目（原文保留）；有效条目继续展示'
        data.update(status=state, reason=reason, volume_source=source, average_volume_20d=average)
        if state.startswith('未知'):
            data['warnings'].append(reason)
        return ContextBlock('供给事件', '\n'.join([state + '：' + reason, *lines]), data, cutoff, list(dict.fromkeys(urls)) or ['SEC EDGAR'])

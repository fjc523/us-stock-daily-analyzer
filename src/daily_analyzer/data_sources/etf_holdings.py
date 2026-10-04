"""读取发行方原持仓权重，一天缓存，不将当前快照用于历史回放。"""
from __future__ import annotations

import base64
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
import json
import math
from pathlib import Path
import tempfile

from openpyxl import load_workbook
import requests

from .index_metadata import HOLDINGS_URLS, _symbol


def _weight(value):
    """发行方已明确为百分比单位，拒绝缺失、非有限或越界数值。"""
    try:
        number = float(str(value).strip().removesuffix('%'))
    except (TypeError, ValueError):
        raise ValueError('发行方权重不可解析') from None
    if not math.isfinite(number) or not -100 <= number <= 100:
        raise ValueError('发行方权重不在百分比范围')
    return number


def parse_holdings(fund, raw):
    """解析公开JSON或XLSX；保留日期、单位与完整性，不猜测未知列。"""
    if fund == 'QQQ':
        payload = json.loads(raw)
        records = payload['holdings']
        if not records or len(records) != int(payload['totalNumberOfHoldings']):
            raise ValueError('发行方持仓名单不完整')
        rows = [{'symbol': _symbol(row.get('ticker')), 'weight_pct': _weight(row['percentageOfTotalNetAssets']) if row.get('percentageOfTotalNetAssets') is not None else None,
                 'security_type': row.get('securityTypeName')}
                for row in records]
        as_of = date.fromisoformat(str(payload['effectiveDate'])[:10]).isoformat()
        business_date = payload.get('effectiveBusinessDate')
        frequency = '月度（公开端点interval=monthly）'
    else:
        book = load_workbook(BytesIO(raw), read_only=True, data_only=True)
        try:
            values = list(book.active.values)
            stamp = next(str(row[1]).removeprefix('As of ') for row in values if row[0] == 'Holdings:')
            as_of = datetime.strptime(stamp, '%d-%b-%Y').date().isoformat()
            index = next(i for i, row in enumerate(values) if 'Ticker' in row and ('Weight' in row or 'Weight (%)' in row))
            header = values[index]
            tick, weight = header.index('Ticker'), header.index('Weight') if 'Weight' in header else header.index('Weight (%)')
            rows = [{'symbol': _symbol(row[tick]) if row[tick] != '-' else '', 'weight_pct': _weight(row[weight])}
                    for row in values[index + 1:] if len(row) > weight and row[weight] is not None]
            frequency = '日度（发行方持仓文件）'
            business_date = None
        finally:
            book.close()
    if not rows or sum(row['weight_pct'] for row in rows if row['weight_pct'] is not None) <= 0:
        raise ValueError('发行方持仓权重为空')
    return {'holdings': rows, 'holdings_as_of': as_of, 'published_at': None,
            'effective_business_date': business_date,
            'publication_status': '发布日期未提供；获取时刻不代表发布日期',
            'weight_unit': '%', 'update_frequency': frequency,
            'source_url': HOLDINGS_URLS[fund], 'shares_history': [],
            'shares_reason': '公开持仓响应无可核验份额历史，近5/20交易日份额变化不可得'}


class ETFHoldingsSource:
    """持仓原响应随快照缓存；过期请求失败不将旧数据冒充当前。"""
    def __init__(self, cache_dir, *, get=requests.get, clock=lambda: datetime.now(timezone.utc)):
        self.cache_dir = Path(cache_dir)
        self.get, self.clock = get, clock
        self.cache = {}

    def holdings(self, fund, *, mode='live'):
        fund = fund.upper()
        if mode != 'live':
            return {'status': 'unavailable', 'reason': '回放不可用：没有可核验当时已发布的历史持仓；不请求当前快照'}
        if fund not in ('QQQ', 'SPY', 'DIA'):
            return {'status': 'unavailable', 'reason': '发行方权重来源尚未接入；复杂杠杆/反向ETF不支持'}
        now = self.clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        path = self.cache_dir / (fund + '.json')
        cached = self.cache.get(fund)
        if cached is None:
            try:
                cached = json.loads(path.read_text())
            except (OSError, ValueError):
                cached = None
        if cached:
            try:
                fetched = datetime.fromisoformat(cached['fetched_at'])
                if timedelta(0) <= now - fetched < timedelta(days=1):
                    self.cache[fund] = cached
                    return {**cached['data'], 'status': 'available', 'fetched_at': cached['fetched_at'],
                            'cache_hit': True, 'raw_evidence': str(path)}
            except (KeyError, TypeError, ValueError):
                pass
        try:
            response = self.get(HOLDINGS_URLS[fund], timeout=15)
            response.raise_for_status()
            raw = response.content
            data = parse_holdings(fund, raw)
            if date.fromisoformat(data['holdings_as_of']) > now.date():
                raise ValueError('持仓生效日在获取日期之后')
            entry = {'fetched_at': now.isoformat(), 'data': data,
                     'raw_response_base64': base64.b64encode(raw).decode('ascii')}
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', dir=self.cache_dir, delete=False, encoding='utf-8') as out:
                json.dump(entry, out, ensure_ascii=False)
                temporary = Path(out.name)
            temporary.replace(path)
            self.cache[fund] = entry
            return {**data, 'status': 'available', 'fetched_at': entry['fetched_at'],
                    'cache_hit': False, 'raw_evidence': str(path)}
        except (requests.RequestException, OSError, ValueError, KeyError, StopIteration, TypeError) as exc:
            return {'status': 'unavailable', 'source_url': HOLDINGS_URLS[fund],
                    'reason': '发行方权重不可用：' + type(exc).__name__}

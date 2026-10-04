"""ETF集中度、前50成分广度与有来源的份额变化。"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from .base import ContextBlock
from .market_data import normalize_closes, _expected_sessions
from statistics import fmean


def share_changes(history, end):
    """只用同单位真实份额，交易日端点缺失不插值。"""
    from .market_data import _expected_sessions
    values = {}
    units = set()
    for row in history:
        try:
            day = date.fromisoformat(str(row['date'])[:10])
            shares = float(row['shares'])
            import math
            if day <= end and math.isfinite(shares) and shares > 0 and row.get('unit'):
                values[day] = shares
                units.add(row['unit'])
        except (KeyError, TypeError, ValueError):
            continue
    output = {}
    for days in (5, 20):
        sessions = _expected_sessions(end, days + 1)
        first = sessions[0] if len(sessions) == days + 1 else None
        output[f'change_{days}d_pct'] = ((values[end] / values[first] - 1) * 100
            if len(units) == 1 and end in values and first in values else None)
    return output


def breadth_averages(rows, end):
    """均线只需N个连续交易日，不借用收益率所需的N+1端点。"""
    closes = normalize_closes(rows, end)
    output = {'close': closes.get(end)}
    for days in (50, 200):
        sessions = _expected_sessions(end, days)
        values = [closes.get(day) for day in sessions]
        output[f'sma_{days}d'] = fmean(values) if len(sessions) == days and all(v is not None for v in values) else None
    return output


def concentration(holdings):
    """权重已为百分比，直接相加不归一为另一种分母。"""
    weights = sorted((row['weight_pct'] for row in holdings if row['weight_pct'] is not None), reverse=True)
    return {'top10_weight_pct': sum(weights[:10]), 'max_weight_pct': max(weights),
            'total_holdings': len(holdings), 'total_weight_pct': sum(weights),
            'missing_weight_count': sum(row['weight_pct'] is None for row in holdings)}


class ETFStructureProvider:
    name = 'etf_structure'
    scope = 'ticker'

    def __init__(self, services):
        self.services = services
        self.end = None
        self.source = getattr(services, 'etf_holdings', None)
        if self.source is None:
            from daily_analyzer.data_sources.etf_holdings import ETFHoldingsSource
            self.source = ETFHoldingsSource(Path(services.project_root) / 'data/cache/etf_holdings',
                                           clock=services.clock)

    def prepare(self, batch):
        value = batch.get('price_data_end_date') if isinstance(batch, dict) else batch.price_data_end_date
        self.end = date.fromisoformat(str(value)[:10])

    def build(self, item, cutoff):
        def value(key, default=None):
            return item.get(key, default) if isinstance(item, dict) else getattr(item, key, default)
        if value('type') not in ('etf', 'index'):
            return None
        symbol = value('symbol')
        if value('type') == 'index':
            from daily_analyzer.config import DEFAULT_INDEX_PROXIES
            symbol = value('proxy') or getattr(item, 'analysis_symbol', None) or DEFAULT_INDEX_PROXIES.get(symbol, symbol)
        mode = self.services.analysis_mode
        snapshot = self.source.holdings(symbol, mode=mode)
        data = {**snapshot, 'symbol': symbol, 'price_as_of': self.end.isoformat()}
        url = snapshot.get('source_url')
        if snapshot.get('status') != 'available':
            return ContextBlock('ETF 结构', snapshot.get('reason', 'ETF结构不可得'), data, cutoff, [url] if url else [])
        holdings = snapshot['holdings']
        data.update(concentration(holdings))
        eligible = [row for row in holdings if row.get('symbol') and row['weight_pct'] is not None and row['weight_pct'] > 0
                    and row.get('security_type') not in ('Currency', 'Synthetic Cash', 'Currency Collateral')]
        selected = sorted(eligible, key=lambda row: row['weight_pct'], reverse=True)[:50]
        data['selected_count'] = len(selected)
        data['eligible_count'] = len(eligible)
        data['excluded_weight_pct'] = sum(row['weight_pct'] for row in holdings if row not in eligible and row['weight_pct'] is not None)
        data['selected_weight_pct'] = sum(row['weight_pct'] for row in selected)
        breadth = {str(days): {'above_count': 0, 'valid_count': 0, 'valid_weight_pct': 0.0,
                              'above_pct': None, 'price_sources': [], 'missing_symbols': []}
                   for days in (50, 200)}
        for row in selected:
            symbol = row['symbol']
            if symbol:
                bars, source = self.services.prices.bars(symbol, self.end)
                metrics = breadth_averages(bars, self.end)
            else:
                metrics, source = {}, '不可用'
            for days in (50, 200):
                result = breadth[str(days)]
                close, sma = metrics.get('close'), metrics.get(f'sma_{days}d')
                if close is None or sma is None:
                    result['missing_symbols'].append(symbol or '无可交易代码持仓')
                    continue
                result['valid_count'] += 1
                result['valid_weight_pct'] += row['weight_pct']
                result['above_count'] += int(close > sma)
                if source not in result['price_sources']:
                    result['price_sources'].append(source)
        for result in breadth.values():
            if result['valid_count']:
                result['above_pct'] = result['above_count'] / result['valid_count'] * 100
        data['breadth'] = breadth
        data['share_changes'] = share_changes(snapshot.get('shares_history', []), self.end)
        lines = [f"成分持仓日期：{snapshot['holdings_as_of']}；发布日期：{snapshot.get('published_at') or '未提供'}；"
                 f"获取时刻：{snapshot['fetched_at']}；更新频率：{snapshot['update_frequency']}；权重单位：%。",
                 f"前10权重合计 {data['top10_weight_pct']:.2f}%；最大单一权重 {data['max_weight_pct']:.2f}%。",
                 f"权重前{len(selected)}成分／总{len(holdings)}持仓；选定权重覆盖 {data['selected_weight_pct']:.2f}%基金资产；原持仓可读权重合计 {data['total_weight_pct']:.4f}%（空权重{data['missing_weight_count']}条）。",
                 f"正权重可交易成分{len(eligible)}个；排除现金/无代码/空权重，已知排除权重{data['excluded_weight_pct']:+.4f}%；不将股票权重归一到100%。",
                 '|广度截至P|站上比例（有效成分分母）|有效数量／选定|有效权重覆盖基金资产|',
                 '|---|---:|---:|---:|']
        for days in (50, 200):
            row = breadth[str(days)]
            proportion = f"{row['above_pct']:.2f}%（{row['above_count']}/{row['valid_count']}）" if row['above_pct'] is not None else '不可得'
            lines.append(f"|{self.end} MA{days}|{proportion}|{row['valid_count']}/{len(selected)}|{row['valid_weight_pct']:.2f}%|")
        for days in (5, 20):
            change = data['share_changes'][f'change_{days}d_pct']
            lines.append(f'近{days}交易日份额变化：' + (f'{change:+.2f}%' if change is not None else '不可得'))
        if any(v is None for v in data['share_changes'].values()):
            lines.append(snapshot.get('shares_reason') or '份额历史同单位交易日端点不足，不能代表净申赎。')
        data['warnings'] = []
        if data['missing_weight_count']:
            data['warnings'].append('存在空权重；集中度基于发行方可读权重，完整权重覆盖未核验')
        if any(row['valid_count'] < len(selected) for row in breadth.values()):
            data['warnings'].append('成分日线覆盖不足；广度只以各均线有效成分为分母，不把缺值当未站上')
        lines.extend(data['warnings'])
        return ContextBlock('ETF 结构', '\n'.join(lines), data, cutoff, [url])

"""复用复权日线和stockstats计算可追溯的价位锚点。"""
from datetime import date
import math
import pandas as pd
from stockstats import wrap
from .base import ContextBlock


def _abnormal_bars(frame):
    """仅识别相对同日开收盘明显错位的高低价，不按跨日涨跌过滤。"""
    fields = ['Open', 'High', 'Low', 'Close']
    if not set(fields) <= set(frame):
        return pd.Series(False, index=frame.index)
    prices = frame[fields].apply(pd.to_numeric, errors='coerce')
    finite = prices.apply(lambda column: column.map(math.isfinite)).all(axis=1)
    return finite & ((prices.Low < 0.5 * prices[['Open', 'Close']].min(axis=1)) |
                     (prices.High > 2 * prices[['Open', 'Close']].max(axis=1)))


class PriceAnchorsProvider:
    name = 'price_anchors'
    scope = 'ticker'

    def __init__(self, services):
        self.services = services
        self.end = None

    def prepare(self, batch):
        value = batch.get('price_data_end_date') if isinstance(batch, dict) else batch.price_data_end_date
        self.end = date.fromisoformat(str(value)[:10])

    def build(self, item, cutoff):
        symbol = item.get('proxy') or item['symbol'] if isinstance(item, dict) else item.analysis_symbol
        rows, source = self.services.prices.bars(symbol, self.end)
        data = {'symbol':symbol, 'as_of':self.end.isoformat(), 'source':source, 'anchors':{}, 'warnings':[]}
        frame = pd.DataFrame(rows).rename(columns={'t':'Date','date':'Date','timestamp':'Date','o':'Open','open':'Open',
            'h':'High','high':'High','l':'Low','low':'Low','c':'Close','close':'Close','v':'Volume','volume':'Volume'})
        if not frame.empty and 'Date' in frame and 'Close' in frame:
            def local_date(value):
                stamp = pd.Timestamp(value)
                return stamp.tz_convert('America/New_York').date() if stamp.tzinfo else stamp.date()
            frame['Date'] = frame.Date.map(local_date)
            frame = frame[frame.Date <= self.end].sort_values('Date').drop_duplicates('Date',keep='last')
        else:
            frame = pd.DataFrame()
        if frame.empty or frame.Date.iloc[-1] != self.end:
            data['warnings'] = ['锚点不可用：没有P日完整日线']
            return ContextBlock(self.name, data['warnings'][0], data, cutoff, [source] if source != '不可用' else [])
        abnormal = _abnormal_bars(frame)
        if abnormal.any():
            days = '、'.join(frame.loc[abnormal, 'Date'].astype(str))
            data['warnings'].append(f'剔除异常日线{int(abnormal.sum())}条（{days}）')
        if abnormal.iloc[-1]:
            data['warnings'].append('锚点不可用：P日OHLC异常')
            return ContextBlock(self.name, '\n'.join(data['warnings']), data, cutoff, [source])
        anchors = data['anchors']
        def put(name, value, kind, day=None):
            try:
                number = float(value)
                if not math.isfinite(number): number = None
            except (ValueError,TypeError): number = None
            anchors[name] = {'value':number, 'date':str(day or self.end), 'type':kind}
            if number is None:
                data['warnings'].append(name+'数据不足')
        for field in ('Open','High','Low','Close'):
            put('P_'+field, frame.iloc[-1].get(field), 'P日'+{'Open':'开盘','High':'高点','Low':'低点','Close':'收盘'}[field])
        stock = wrap(frame.copy())
        atr_frame = frame.loc[~abnormal].copy()
        atr_stock = wrap(atr_frame)
        for name, minimum in [('close_10_ema',10),('close_20_sma',20),('close_50_sma',50),('close_200_sma',200),('atr',15)]:
            calculation, sample = (atr_stock, atr_frame) if name == 'atr' else (stock, frame)
            try: value = calculation[name].iloc[-1] if len(sample) >= minimum else None
            except (KeyError,ValueError): value = None
            put(name,value,'ATR14' if name=='atr' else '均线')
        for window in (20,60):
            for field,operation in [('High','idxmax'),('Low','idxmin')]:
                selected = frame.tail(window)
                enough = len(selected) == window
                selected = selected.loc[~abnormal.loc[selected.index]]
                if not enough or selected.empty or field not in selected or selected[field].isna().any():
                    put(f'{window}d_{field}',None,f'{window}日极值')
                else:
                    index = getattr(selected[field],operation)()
                    put(f'{window}d_{field}',selected.loc[index,field],f'{window}日极值',selected.loc[index,'Date'])
        # 一年窗口使用同源有效OHLC；样本不足不推断上市日期。
        selected = frame.tail(252).copy()
        window_excluded = int(abnormal.loc[selected.index].sum())
        selected = selected.loc[~abnormal.loc[selected.index]]
        for field in ('High', 'Low'):
            if field in selected:
                selected[field] = pd.to_numeric(selected[field], errors='coerce')
        valid = selected.dropna(subset=['High', 'Low']) if {'High', 'Low'} <= set(selected) else selected.iloc[:0]
        if not valid.empty:
            valid = valid[valid.High.map(math.isfinite) & valid.Low.map(math.isfinite)]
        data['window_252d_count'] = len(valid)
        for field, operation in [('High', 'idxmax'), ('Low', 'idxmin')]:
            name = '252d_' + field
            if valid.empty:
                put(name, None, '252日极值（有效日线不足）')
            else:
                index = getattr(valid[field], operation)()
                if window_excluded:
                    label = f'252交易日极值（剔除异常{window_excluded}条）'
                    if len(valid)<252:label += f'；已有{len(valid)}有效交易日（不足252日）'
                else:
                    label = '252交易日极值' if len(valid)==252 else f'已有{len(valid)}交易日极值（不足252日）'
                put(name, valid.loc[index, field], label, valid.loc[index, 'Date'])
            row = anchors[name]
            close, atr = anchors['P_Close']['value'], anchors['atr']['value']
            row['sample_days'] = len(valid)
            row['distance_pct'] = (row['value'] - close) / close * 100 if row['value'] is not None and close else None
            row['distance_atr'] = (row['value'] - close) / atr if row['value'] is not None and close is not None and atr and atr > 0 else None
        if len(valid) < len(selected):
            data['warnings'].append('一年窗口存在无效OHLC；已注明有效交易日数，极值覆盖不足')
        lines = [f'标的{symbol}；完整日线截至P={self.end}；实际来源{source}。',
                 '| 锚点 | 美元 | 类型 | 来源日期 |', '|---|---:|---|---|']
        lines.extend(f"| {name} | {row['value']:.4f} | {row['type']} | {row['date']} |" if row['value'] is not None else f"| {name} | 数据不足 | {row['type']} | {row['date']} |" for name,row in anchors.items())
        lines.extend(['|一年锚点|距P_Close（%）|距P_Close（ATR14）|', '|---|---:|---:|'])
        for name in ('252d_High', '252d_Low'):
            row = anchors[name]
            pct = f"{row['distance_pct']:+.2f}%" if row['distance_pct'] is not None else '不可计算'
            atr = f"{row['distance_atr']:+.2f}" if row['distance_atr'] is not None else '不可计算'
            lines.append(f'|{name}|{pct}|{atr}|')
        lines.extend(data['warnings'])
        return ContextBlock(self.name,'\n'.join(lines),data,cutoff,[source])

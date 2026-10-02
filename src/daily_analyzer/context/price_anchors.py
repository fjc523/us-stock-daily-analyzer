"""复用复权日线和stockstats计算可追溯的价位锚点。"""
from datetime import date
import math
import pandas as pd
from stockstats import wrap
from .base import ContextBlock


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
        for name, minimum in [('close_10_ema',10),('close_20_sma',20),('close_50_sma',50),('close_200_sma',200),('atr',15)]:
            try: value = stock[name].iloc[-1] if len(frame) >= minimum else None
            except (KeyError,ValueError): value = None
            put(name,value,'ATR14' if name=='atr' else '均线')
        for window in (20,60):
            for field,operation in [('High','idxmax'),('Low','idxmin')]:
                selected = frame.tail(window)
                if len(selected) < window or field not in selected or selected[field].isna().any():
                    put(f'{window}d_{field}',None,f'{window}日极值')
                else:
                    index = getattr(selected[field],operation)()
                    put(f'{window}d_{field}',selected.loc[index,field],f'{window}日极值',selected.loc[index,'Date'])
        lines = [f'标的{symbol}；完整日线截至P={self.end}；实际来源{source}。',
                 '| 锚点 | 美元 | 类型 | 来源日期 |', '|---|---:|---|---|']
        lines.extend(f"| {name} | {row['value']:.4f} | {row['type']} | {row['date']} |" if row['value'] is not None else f"| {name} | 数据不足 | {row['type']} | {row['date']} |" for name,row in anchors.items())
        return ContextBlock(self.name,'\n'.join(lines),data,cutoff,[source])

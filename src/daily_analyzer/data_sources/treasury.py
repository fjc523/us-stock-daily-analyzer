"""FRED公开日度美债收益率，无需API密钥，保留实际观测日。"""
from datetime import date, timedelta
from io import StringIO
import json
import threading
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar
from tradingagents.dataflows.net import get_scrubbed
from tradingagents.dataflows.errors import VendorUnavailableError, NoMarketDataError

FRED_PUBLIC_URL = 'https://fred.stlouisfed.org/graph/fredgraph.csv'


class IndicatorNotApplicableError(VendorUnavailableError):
    """公开美债来源不覆盖该指标，来源链直接转下一来源，不计为失败。"""


class TreasuryYieldSource:
    def __init__(self, get=get_scrubbed):
        self.get = get
        self.cache = {}
        self.summaries = {}
        self.lock = threading.RLock()

    def clear_cache(self):
        with self.lock:
            self.cache.clear()
            self.summaries.clear()

    def macro(self, indicator, curr_date, look_back_days=365):
        from tradingagents.dataflows.config import get_config
        from daily_analyzer.context.market_data import previous_trading_day
        fields = {'10y_treasury':'DGS10', 'DGS10':'DGS10', '2y_treasury':'DGS2', 'DGS2':'DGS2',
                  '10y_2y_spread':'10Y-2Y', 'yield_curve':'10Y-2Y'}
        if indicator not in fields:
            raise IndicatorNotApplicableError('公开美债来源仅提供DGS10、DGS2与10Y-2Y')
        config = get_config()
        if config.get('news_cutoff_utc'):
            raise VendorUnavailableError('公开CSV历史版本未核验，回放使用FRED API')
        configured = config.get('price_data_end_date')
        end = min(date.fromisoformat(curr_date), date.fromisoformat(configured) if configured else previous_trading_day(curr_date))
        start = end - timedelta(days=look_back_days)
        with self.lock:
            if end not in self.cache:
                response = self.get(FRED_PUBLIC_URL, params={'id':'DGS2,DGS10'}, timeout=10, secret='')
                response.raise_for_status()
                frame = pd.read_csv(StringIO(response.text), na_values=['.'])
                frame = frame.rename(columns={'DATE':'observation_date'})
                if not {'observation_date','DGS2','DGS10'} <= set(frame.columns):
                    raise VendorUnavailableError('FRED公开CSV缺少收益率字段')
                frame['10Y-2Y'] = frame.DGS10 - frame.DGS2
                self.cache[end] = frame[frame.observation_date <= end.isoformat()]
            frame = self.cache[end]
        field = fields[indicator]
        rows = frame[(frame.observation_date >= start.isoformat()) & frame[field].notna()].tail(40)
        if rows.empty:
            raise NoMarketDataError(indicator, indicator, 'FRED公开CSV没有窗口内有效观测')
        values = [{'观测日':row.observation_date, '数值':float(row[field])} for _,row in rows.iterrows()]
        unit = '百分点' if field == '10Y-2Y' else '%'
        latest = values[-1]
        text = (f'## 美债收益率（FRED公开CSV {field}）\n'
                f'来源：美联储H.15，经FRED发布；单位{unit}；日度，非实时。截止P={end}；'
                f'最新实际观测日{latest["观测日"]}，数值{latest["数值"]}{unit}。'
                '公开序列可能修订，不填补节假日或尚未发布数据，不等同10Y期货主连。\n'
                + json.dumps(values, ensure_ascii=False))
        full = frame[(frame.observation_date >= (end - timedelta(days=90)).isoformat()) & frame[field].notna()]
        observations = [{'观测日': row.observation_date, '数值': float(row[field])} for _, row in full.iterrows()]
        spread = None
        if not full.empty:
            latest_row = full.iloc[-1]
            spread = float(latest_row['10Y-2Y']) if pd.notna(latest_row['10Y-2Y']) else None
        with self.lock:
            self.summaries[text] = summarize_yields(observations, field, end, spread=spread, complete=True)
        return text

    def compact(self, text):
        """只读本次获取的完整序列摘要；历史40点不冒充完整90日。"""
        with self.lock:
            summary = self.summaries.get(text)
        if summary is not None:
            return summary
        try:
            head, raw = text.rsplit('\n', 1)
            observations = json.loads(raw)
            if not observations or not all('观测日' in row and '数值' in row for row in observations):
                raise ValueError('没有结构化收益率观测')
            import re
            match = re.search(r'截止P=(\d{4}-\d{2}-\d{2})', head)
            end = date.fromisoformat(match.group(1) if match else observations[-1]['观测日'])
            field = 'DGS2' if 'DGS2' in head else '10Y-2Y' if '10Y-2Y' in head else 'DGS10'
            return summarize_yields(observations, field, end, complete=False)
        except (ValueError, TypeError, KeyError):
            return '；'.join(text.splitlines()[:2]) + '；历史观测结构未核验，5/20变化和90日区间不可计算。'


def summarize_yields(observations, field, end, *, spread=None, complete=False):
    """收益率单位为百分数，差值乘100为bp；不填缺失观测。"""
    rows = sorted((row for row in observations
                   if (end - timedelta(days=90)).isoformat() <= row['观测日'] <= end.isoformat()),
                  key=lambda row: row['观测日'])
    if not rows:
        return '美债收益率：90日内无有效观测。'
    latest = float(rows[-1]['数值'])
    unit = '百分点' if field == '10Y-2Y' else '%'
    parts = [f'美债{field}：{latest:g}{unit}（观测日{rows[-1]["观测日"]}，日度非实时；截止P={end}，观测年龄{(end-date.fromisoformat(rows[-1]["观测日"])).days}天）']
    for n in (5, 20):
        parts.append(f'较{n}个观测日前{(latest - float(rows[-1-n]["数值"])) * 100:+.2f}bp'
                     if len(rows) > n else f'较{n}个观测日前变化：历史不足')
    low, high = min(float(row['数值']) for row in rows), max(float(row['数值']) for row in rows)
    # 使用成熟美国联邦工作日边界，周末及联邦假日不被误作缺失；
    # 仅取得窗口开头或结尾都不算完整，不引入额外陈旧天数阈值。
    business_day = pd.offsets.CustomBusinessDay(calendar=USFederalHolidayCalendar())
    first_expected = business_day.rollforward(pd.Timestamp(end - timedelta(days=90))).date()
    last_expected = business_day.rollback(pd.Timestamp(end)).date()
    expected_dates = {stamp.date() for stamp in pd.date_range(first_expected, last_expected, freq=business_day)}
    observed_dates = {date.fromisoformat(row['观测日']) for row in rows}
    complete = (complete and date.fromisoformat(rows[0]['观测日']) <= first_expected
                and date.fromisoformat(rows[-1]['观测日']) >= last_expected
                and expected_dates <= observed_dates)
    label = '90日' if complete else f'已有{len(rows)}点（90日覆盖不足）'
    parts.append(f'{label}区间{low:g}–{high:g}{unit}')
    parts.append(f'当前位置{(latest-low)/(high-low)*100:.1f}%' if high > low else '区间恒定，位置不可计算')
    parts.append(f'10Y-2Y利差{spread:+.2f}百分点' if spread is not None else '10Y-2Y利差未取得')
    parts.append('来源：FRED公开CSV；序列可能修订，不等同10Y期货主连')
    return '；'.join(parts) + '。'


TREASURY_SOURCE = TreasuryYieldSource()

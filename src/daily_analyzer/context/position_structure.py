"""期权权限不可行分支：仅提供带真实数据日期的空头持仓结构。"""
from datetime import datetime, timezone

from daily_analyzer.context.base import ContextBlock
from tradingagents.dataflows.vendors.yahoo.expectations import number


class PositionStructureProvider:
    name = 'position_structure'
    scope = 'ticker'

    def __init__(self, services):
        self.services = services

    def prepare(self, batch):
        """不订阅行情、不请求期权或账户。"""

    def build(self, item, cutoff):
        from daily_analyzer.context.base import _value
        if _value(item, 'type', 'stock') != 'stock':
            return None
        if self.services.analysis_mode == 'backfill':
            reason='回放不可用：期权与空头来源只提供当前快照'
            return ContextBlock('期权与持仓结构', reason, {'option_status':'unavailable','short_status':'unavailable','reason':reason},cutoff,('yfinance',))
        reason='期权不可用：已核验NVDA/TSLA美国期权行情无权限；不提供IV、Greeks、PCR或隐含幅度'
        data={'option_status':'unavailable','option_reason':reason,'short_status':'unavailable'}
        lines=[reason]
        try:
            import yfinance as yf
            source=self.services.yahoo
            obj=source._ticker(_value(item,'symbol')) if source is not None else yf.Ticker(_value(item,'symbol'))
            info=obj.get_info(); stamp=number(info.get('dateShortInterest'))
            data.update({key:number(info.get(key)) for key in ('shortPercentOfFloat','sharesShort','shortRatio')})
            data['short_date']=datetime.fromtimestamp(stamp,timezone.utc).date().isoformat() if stamp is not None else None
            data['short_status']='available' if any(data.get(key) is not None for key in ('shortPercentOfFloat','sharesShort','shortRatio')) else 'unavailable'
            lines += ['空头数据日期：'+(data['short_date'] or '不可得，日期未核验')+'；通常半月更新，不能称实时。',
                      '|字段|值|','|---|---|']
            for label,key,multiplier in [('空头占流通股比例','shortPercentOfFloat',100),('空头股数','sharesShort',1),('回补天数','shortRatio',1)]:
                value=data.get(key);text=(f'{value*multiplier:g}'+('%' if multiplier==100 else '')) if value is not None else '不可得（来源缺字段）'
                lines.append(f'|{label}|{text}|')
        except Exception as exc:
            data['short_reason']='空头来源不可用：'+type(exc).__name__;lines.append(data['short_reason'])
        return ContextBlock('期权与持仓结构','\n'.join(lines),data,cutoff,('yfinance',))

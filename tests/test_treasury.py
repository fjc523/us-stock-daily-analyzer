"""公开美债来源的日期、口径、缓存与降级验证。"""
from types import SimpleNamespace
import pytest
from daily_analyzer.data_sources.treasury import TreasuryYieldSource


def test_public_yields_filter_missing_future_and_share_cache(monkeypatch):
    import tradingagents.dataflows.config as config
    monkeypatch.setattr(config,'get_config',lambda:{'price_data_end_date':'2026-10-01'})
    calls=[]
    def get(*args,**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(raise_for_status=lambda:None,text='observation_date,DGS2,DGS10\n2026-09-29,4.89,5.26\n2026-09-30,4.88,5.29\n2026-10-01,.,.\n2026-10-02,4.9,5.3\n')
    source=TreasuryYieldSource(get)
    text=source.macro('10y_treasury','2026-10-02',30)
    assert '最新实际观测日2026-09-30，数值5.29%' in text
    assert '2026-10-02' not in text and '非实时' in text and '公开序列可能修订' in text
    spread=source.macro('10y_2y_spread','2026-10-02',30)
    assert '百分点' in spread and '0.410' in spread
    assert len(calls)==1 and calls[0]['timeout']==10
    source.clear_cache();source.macro('DGS2','2026-10-02')
    assert len(calls)==2


def test_public_yields_reject_unverified_replay(monkeypatch):
    import tradingagents.dataflows.config as config
    from tradingagents.dataflows.errors import VendorUnavailableError
    monkeypatch.setattr(config,'get_config',lambda:{'news_cutoff_utc':'2026-10-01T12:31:00Z'})
    source=TreasuryYieldSource(lambda *args,**kw:pytest.fail('回放不读取公开CSV'))
    with pytest.raises(VendorUnavailableError,match='历史版本未核验'):
        source.macro('10y_treasury','2026-10-01')


def test_public_yields_use_existing_http_wrapper(monkeypatch):
    import tradingagents.dataflows.net as net
    import tradingagents.dataflows.config as config
    monkeypatch.setattr(config,'get_config',lambda:{'price_data_end_date':'2026-10-01'})
    monkeypatch.setattr(net.requests,'get',lambda *args,**kwargs:SimpleNamespace(status_code=200,
        raise_for_status=lambda:None,text='observation_date,DGS2,DGS10\n2026-09-30,4.88,5.29\n'))
    assert '数值5.29%' in TreasuryYieldSource().macro('10y_treasury','2026-10-02')


def _route_macro(monkeypatch, impls, indicator):
    from tradingagents.dataflows import router
    from tradingagents.dataflows.config import run_config
    from tradingagents.dataflows.vendor_observer import set_vendor_observer,reset_vendor_observer
    from daily_analyzer.source_status import SourceStatusCollector
    monkeypatch.setitem(router.VENDOR_METHODS,'get_macro_indicators',impls)
    collector=SourceStatusCollector();token=set_vendor_observer(collector.observe)
    config={'tool_vendors':{'get_macro_indicators':'fred_public,futu,fred'}}
    try:
        with run_config(config):
            text=router.route_to_vendor('get_macro_indicators',indicator,'2026-10-02')
    finally:reset_vendor_observer(token)
    return text,next(row for row in collector.snapshot({}, config) if row["category"] == "宏观指标")


def test_public_yields_are_primary_for_treasury(monkeypatch):
    def futu(*args):pytest.fail('公开美债可用时不请求富途')
    text,row=_route_macro(monkeypatch,{'fred_public':lambda *args:'DGS10 5.29% 2026-09-30','futu':futu},'10y_treasury')
    assert '5.29%' in text
    assert row['status']=='正常' and row['source']=='fred_public'


def test_other_macro_skips_public_yields_without_failure(monkeypatch):
    from daily_analyzer.data_sources.treasury import TreasuryYieldSource
    import tradingagents.dataflows.config as config
    monkeypatch.setattr(config,'get_config',lambda:{})
    public=TreasuryYieldSource(lambda *args,**kw:pytest.fail('不适用指标不请求公开CSV'))
    text,row=_route_macro(monkeypatch,{'fred_public':public.macro,'futu':lambda *args:'CPI同比 2.9%'},'cpi')
    assert '2.9%' in text
    assert row['status']=='正常' and row['source']=='futu'
    assert not any(event['source']=='fred_public' for event in row['attempts'])


def test_treasury_falls_back_to_futu_when_public_csv_fails(monkeypatch):
    from tradingagents.dataflows.errors import VendorUnavailableError
    def public(*args):raise VendorUnavailableError('FRED公开CSV超时')
    text,row=_route_macro(monkeypatch,{'fred_public':public,'futu':lambda *args:'US.10Ymain 4.24'},'10y_treasury')
    assert '4.24' in text
    assert row['status']=='降级' and row['source']=='futu' and '超时' in row['reason']

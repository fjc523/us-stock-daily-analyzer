"""替代来源、日历、凭据与身份的离线契约。"""
from datetime import date, datetime
from zoneinfo import ZoneInfo
from types import SimpleNamespace
import pandas as pd
import pytest
from daily_analyzer.data_sources.futu import FutuDataSource
from daily_analyzer.data_sources.vix import VixDataSource
from daily_analyzer.context.market_data import DailyPriceService
from daily_analyzer.config import load_credentials


def test_futu_cache_and_form144_are_distinct():
    calls = []
    class Quote:
        def __init__(self, **kwargs): pass
        def get_insider_trade_list(self, **kwargs):
            calls.append(kwargs)
            return 0, pd.DataFrame([{"max_trade_date_str":"2026-10-01", "is_proposed_sale_of_securities":True},
                                    {"max_trade_date_str":"2026-10-01", "is_proposed_sale_of_securities":False}])
        def close(self): pass
    source = FutuDataSource(context_factory=Quote)
    text = source.insiders("TSLA", "2026-10-02")
    source.insiders("TSLA", "2026-10-02")
    assert len(calls) == 1 and "Form 144拟售" in text and "实际交易" in text
    source.clear_cache(); source.insiders("TSLA", "2026-10-02")
    assert len(calls) == 2


def test_calendar_week_segments_paging_filter_and_future_values(monkeypatch):
    source = FutuDataSource()
    calls = []
    def call(method, **kwargs):
        calls.append((method, kwargs))
        if method == "get_earnings_calendar":
            return ([{"security":"US.TSLA"}, {"security":"US.OTHER"}],)
        if kwargs["next_page"] is None:
            return ([{"country":"日本"}, {"country":"美国", "timestamp":1790967600, "actual":"999"}], "second", True)
        return ([], None, False)
    monkeypatch.setattr(source, "_call", call)
    result = source.calendars(date(2026,10,2), date(2026,10,21), ["TSLA"], datetime(2026,10,2,5,tzinfo=ZoneInfo("America/New_York")))
    segments = [kwargs for name, kwargs in calls if name == "get_earnings_calendar"]
    assert len(segments) == 3 and segments[-1]["end_date"] == "2026-10-21"
    assert all((date.fromisoformat(row['end_date'])-date.fromisoformat(row['begin_date'])).days <= 6 for row in segments)
    assert all(row['security']=='US.TSLA' for row in result['earnings'])
    assert all(row['country']=='美国' and row['actual']=='尚未发布' for row in result['economics'])
    assert all(kwargs['count'] == 100 for name, kwargs in calls if name == 'get_economic_calendar')


def test_cpi_matching_does_not_confuse_core_and_units(monkeypatch):
    source = FutuDataSource(); called=[]
    def call(method, **kwargs):
        if method == 'get_macro_indicator_list':
            return ([{'name':'美国核心CPI同比','indicator_id':1}, {'name':'美国CPI同比','indicator_id':2}],)
        called.append(kwargs)
        return ([{'release_time':'2026-09-11 20:30:00','value':0.025,'unit_type':'PERCENT'}],)
    monkeypatch.setattr(source, '_call', call)
    text = source.macro('cpi', '2026-10-02')
    assert called[0]['indicator_id']==2 and '0.025=2.5%' in text and '时区未核验' in text


def test_valuation_price_is_separate_from_current_quote(monkeypatch):
    import tradingagents.dataflows.date_window as window
    monkeypatch.setattr(window,'is_historical',lambda value:False)
    source=FutuDataSource()
    monkeypatch.setattr(source,'_call', lambda method,**kw: ([{'prev_close_price':100,'last_price':102,'equity_pe_ratio':30,'update_time':'2026-10-02'}],) if method=='get_market_snapshot' else ({'valuation_type':'PE','trend':{'valuation_percentile':70}},))
    text=source.fundamentals('TSLA','2026-10-02')
    assert '官方前收盘' in text and '快照现价（独立列示）' in text and 'prev_close_price' in text and '估值分位%' in text


def test_vix_official_rows_are_filtered_and_chain_uses_fred(monkeypatch):
    response=SimpleNamespace(raise_for_status=lambda:None, text='DATE,OPEN,HIGH,LOW,CLOSE\n09/30/2026,14,16,13,15\n10/01/2026,15,18,14,16\n10/02/2026,16,19,15,17\n')
    source=VixDataSource(get=lambda *args,**kw:response)
    assert source.cboe(date(2026,10,1),date(2026,10,1))[0]['Close']==16
    calls=[]
    def broken(*args): calls.append('cboe');raise ConnectionError()
    fake=SimpleNamespace(cboe=broken,fred=lambda *args:[{'Date':'2026-10-01','Close':16}])
    prices=DailyPriceService(None,SimpleNamespace(daily_bars=lambda *args:pytest.fail('不应调用Yahoo')),vix=fake)
    assert prices.bars('^VIX',date(2026,10,1))[1]=='FRED VIXCLS'


def test_vix_fred_uses_secret_scrubbing_http_contract(monkeypatch):
    import tradingagents.dataflows.net as net
    monkeypatch.setenv('FRED_API_KEY','fixture-fred-key')
    monkeypatch.setattr(net.requests,'get',lambda *args,**kw:SimpleNamespace(status_code=200,raise_for_status=lambda:None,
        json=lambda:{'observations':[{'date':'2026-09-30','value':'16.39'}]}))
    assert VixDataSource().fred(date(2026,9,30),date(2026,10,1)) == [{'Date':'2026-09-30','Close':16.39}]


def test_fred_key_is_loaded_as_secret_and_in_environment(tmp_path):
    from daily_analyzer.runner import _environment_credentials,_secret_values
    (tmp_path/'config').mkdir()
    path=tmp_path/'config/secrets.env';path.write_text('FRED_API_KEY=fred-secret-fixture\n');path.chmod(0o600)
    credentials=load_credentials(tmp_path,environ={})
    project=SimpleNamespace(credentials=credentials)
    assert _environment_credentials(project)['FRED_API_KEY']=='fred-secret-fixture'
    assert 'fred-secret-fixture' in _secret_values(project)
    assert 'fred-secret-fixture' not in repr(credentials)


def test_watchlist_name_survives_yahoo_and_futu_failure(monkeypatch):
    from daily_analyzer.analyzer import AnalyzerGraph
    from daily_analyzer.data_sources.futu import get_shared_data_source
    source=get_shared_data_source()
    def unavailable(*args):raise ConnectionError()
    monkeypatch.setattr(source,'identity',unavailable)
    graph=object.__new__(AnalyzerGraph);graph.item=SimpleNamespace(name='特斯拉');graph.injected_context='测试框架'
    text=graph.resolve_instrument_context('TSLA','stock','2026-10-02')
    assert 'Company: 特斯拉' in text and '测试框架' in text


def test_treasury_yield_futures_use_completed_days_and_cache(monkeypatch):
    import tradingagents.dataflows.config as config
    from futu import KLType, AuType
    monkeypatch.setattr(config, 'get_config', lambda: {'price_data_end_date':'2026-10-01'})
    calls = []
    class Quote:
        def __init__(self, **kwargs): pass
        def subscribe(self, codes, subtypes, **kwargs):
            calls.append(('subscribe', codes, subtypes))
            return 0, None
        def get_cur_kline(self, **kwargs):
            calls.append(('kline', kwargs))
            return 0, pd.DataFrame([
                {'time_key':'2026-10-01 00:00:00','close':4.240},
                {'time_key':'2026-10-02 00:00:00','close':4.250},
            ])
        def close(self): pass
    source = FutuDataSource(context_factory=Quote)
    text = source.macro('10y_treasury', '2026-10-02')
    alias_text = source.macro('DGS10', '2026-10-02')
    assert text.split('\n')[-1] == alias_text.split('\n')[-1]
    assert len(calls) == 2 and calls[0] == ('subscribe', ['US.10Ymain'], [KLType.K_DAY])
    assert calls[1][1]['autype'] == AuType.NONE
    assert '"收益率%": 4.24' in text and '4.240表示4.240%' in text
    assert '"日期": "2026-10-02"' not in text and '期货主连为代理' in text and '换月' in text


def test_treasury_yield_futures_permission_failure(monkeypatch):
    import tradingagents.dataflows.config as config
    from tradingagents.dataflows.errors import VendorUnavailableError
    monkeypatch.setattr(config, 'get_config', lambda: {'price_data_end_date':'2026-10-01'})
    subscribes = []
    class Quote:
        def __init__(self, **kwargs): pass
        def subscribe(self, *args, **kwargs):
            subscribes.append(args)
            return -1, '没有CME行情权限'
        def get_cur_kline(self, **kwargs): pytest.fail('订阅失败后不取K线')
        def close(self): pass
    source = FutuDataSource(context_factory=Quote)
    with pytest.raises(VendorUnavailableError, match='权限'):
        source.macro('10y_treasury', '2026-10-02')
    with pytest.raises(VendorUnavailableError, match='本批次不再重试'):
        source.macro('DGS10', '2026-10-02')
    assert len(subscribes) == 1
    source.clear_cache()
    with pytest.raises(VendorUnavailableError, match='权限'):
        source.macro('10y_treasury', '2026-10-02')
    assert len(subscribes) == 2


def test_yahoo_earnings_fallback_filters_window(monkeypatch):
    from daily_analyzer.data_sources.yfinance import YahooDataSource
    import tradingagents.dataflows.vendors.yahoo.common as common
    monkeypatch.setattr(common,'yf_retry',lambda impl:impl())
    frame=pd.DataFrame({'EPS Estimate':[1,2]},index=pd.to_datetime(['2026-10-21','2026-11-21']))
    frame.index.name='Earnings Date'
    source=YahooDataSource(ticker_factory=lambda symbol:SimpleNamespace(get_earnings_dates=lambda **kw:frame))
    rows=source.earnings_calendar('TSLA',date(2026,10,2),date(2026,10,30))
    assert len(rows)==1 and rows[0]['日期']=='2026-10-21'


def test_futu_initial_claims_matches_actual_indicator_name():
    from daily_analyzer.data_sources.futu import FutuDataSource
    source = FutuDataSource()
    calls = []
    def call(method, **kwargs):
        calls.append((method, kwargs))
        if method == 'get_macro_indicator_list':
            return ([{'name':'美国初次申请失业救济金人数','indicator_id':1003000008}],)
        return ([{'release_time':'2026-10-01','value':220000}],)
    source._call = call
    assert '220000' in source.macro('initial_claims','2026-10-02')
    assert calls[-1][1]['indicator_id'] == 1003000008


def test_macro_context_injects_yields_and_attempts_calendar_fallback(monkeypatch):
    from daily_analyzer.context.providers import MacroReleasesProvider
    from daily_analyzer.context.base import ProviderServices,render_context
    import tradingagents.dataflows.router as router
    monkeypatch.setattr(router,'route_to_vendor',lambda *args:'美债样本DGS10：5.29%，2026-09-30')
    source=SimpleNamespace(calendars=lambda *args:{'earnings':[],'economics':[],'warnings':['财报日历不可用：权限','经济日历不可用：权限']})
    yahoo=SimpleNamespace(earnings_calendar=lambda *args:[{'security':'US.TSLA','日期':'2026-10-21'}],economic_calendar=lambda *args:[{'title':'美国经济样本'}])
    services=ProviderServices(futu=SimpleNamespace(),futu_data=source,yahoo=yahoo,prices=SimpleNamespace(),index_metadata=SimpleNamespace(),
        alpaca=SimpleNamespace(news=lambda *args,**kw:{'articles':[]}))
    provider=MacroReleasesProvider(services)
    now=datetime(2026,10,2,6,tzinfo=ZoneInfo('America/New_York'))
    provider.prepare({'trade_date':date(2026,10,2),'price_data_end_date':date(2026,10,1),'context_as_of':now,
        'items':[{'symbol':'TSLA','type':'stock'}]})
    block=provider.build({'symbol':'TSLA','type':'stock'},now)
    text=render_context({'macro_releases':block},now)
    assert '美债样本DGS10：5.29%' in text
    assert block.data['calendars']['earnings'][0]['security']=='US.TSLA'
    assert 'Yahoo日历兜底' in block.sources

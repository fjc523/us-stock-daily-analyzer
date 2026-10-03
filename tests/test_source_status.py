"""来源汇总的降级、隐私与并行隔离契约。"""
import threading
from concurrent.futures import ThreadPoolExecutor
from daily_analyzer.source_status import SourceStatusCollector, clean_reason
from tradingagents.dataflows.vendor_observer import observed_call, set_vendor_observer, reset_vendor_observer


def test_source_status_fallback_and_unconfigured_fred():
    collector = SourceStatusCollector()
    for method, vendor, outcome in [("daily_bars", "Alpaca", "success"), ("vix", "CBOE", "failed"),
                                    ("vix", "Yahoo", "success"), ("fetch_stocktwits", "StockTwits", "failed"),
                                    ("get_macro_indicators", "futu", "success")]:
        collector.observe({"method": method, "source": vendor, "outcome": outcome})
    rows = {row["category"]: row for row in collector.snapshot({}, {})}
    assert rows["日线"]["status"] == "正常"
    assert rows["VIX"]["status"] == "降级"
    assert rows["VIX"]["source"] == "Yahoo"
    assert rows["StockTwits"]["status"] == "失败"
    assert rows["宏观指标"]["status"] == "正常"
    assert rows["宏观指标"]["attempts"][-1]["outcome"] == "unconfigured"
    assert rows["财报报表"]["status"] == "未使用"


def test_partial_primary_failure_does_not_claim_fallback():
    collector = SourceStatusCollector()
    collector.observe({'method':'daily_bars','source':'Alpaca SIP','outcome':'success'})
    collector.observe({'method':'load_ohlcv','source':'alpaca','outcome':'failed','error':'单次请求失败'})
    row = collector.snapshot({}, {})[0]
    assert row['status'] == '正常' and '部分请求失败，主源仍可用' in row['reason']
    collector.observe({'method':'load_ohlcv','source':'futu','outcome':'success'})
    assert collector.snapshot({}, {})[0]['status'] == '降级'


def test_extended_hours_fallback_is_visible():
    collector = SourceStatusCollector()
    blocks = {'extended_hours':{'data':{'TSLA':{'pre':{'status':'可用','source':'Alpaca feed=iex'},
        'overnight':{'status':'可用','source':'富途快照'}}}}}
    row = collector.snapshot(blocks, {'futu_enabled':True})[1]
    assert row['status'] == '降级' and 'Alpaca feed=iex' in row['source']


def test_extended_hours_alpaca_overnight_is_session_primary():
    collector = SourceStatusCollector()
    blocks = {'extended_hours':{'data':{'TSLA':{'pre':{'status':'可用','source':'富途快照'},
        'after':{'status':'时段未核验（无分时段时间）','source':'富途订阅报价'},
        'overnight':{'status':'可用','source':'Alpaca feed=overnight'}}}}}
    row = collector.snapshot(blocks, {'futu_enabled':True})[1]
    assert row['status'] == '正常' and 'Alpaca feed=overnight' in row['source']


def test_source_failures_never_expose_credentials():
    value = clean_reason("auth abcsecret https://user:password@example.org/?token=xyz api_key=unknown", ["abcsecret"])
    assert not any(secret in value for secret in ("abcsecret", "password", "xyz", "unknown", "example.org"))
    collector = SourceStatusCollector(["fredsecret"])
    collector.observe({"method": "vix", "source": "FRED", "outcome": "failed", "error": "FRED_API_KEY=fredsecret"})
    assert "fredsecret" not in str(collector.snapshot({}, {}))


def test_observer_isolated_between_threads():
    def analyze(symbol):
        collector = SourceStatusCollector()
        token = set_vendor_observer(collector.observe)
        try:
            observed_call("get_news", symbol, lambda: "已获取资讯")
            return collector.snapshot({}, {})[2]["source"]
        finally:
            reset_vendor_observer(token)
    with ThreadPoolExecutor(2) as pool:
        assert list(pool.map(analyze, ["TSLA", "NVDA"])) == ["TSLA", "NVDA"]


def test_fred_key_environment_result_and_html_are_separated(tmp_path):
    from datetime import date, datetime
    from types import SimpleNamespace
    from zoneinfo import ZoneInfo
    from daily_analyzer.runner import _analyze_item, _environment_credentials, _secret_values
    from daily_analyzer.config import WatchlistItem, DataCredentials
    from daily_analyzer.runner import RunWindow
    from daily_analyzer.site import build_site
    from tradingagents.dataflows.vendor_observer import report_vendor
    project = SimpleNamespace(credentials=DataCredentials(fred_api_key='fixture-fred-private'))
    assert _environment_credentials(project)['FRED_API_KEY'] == 'fixture-fred-private'
    now = datetime(2026,10,2,8,30,tzinfo=ZoneInfo('America/New_York'))
    batch = tmp_path/'data'/'runs'/'2026-10-02'/'batches'/'test'
    class Context:
        def build(self, *args): return {}
    def failing_graph(**kwargs):
        report_vendor('get_macro_indicators','FRED','failed',error='https://fred.invalid/?api_key=fixture-fred-private')
        raise RuntimeError('FRED failed fixture-fred-private')
    outcome = _analyze_item(item=WatchlistItem(symbol='TSLA',type='stock'),run_id='test',root=tmp_path,
        batch_dir=batch,window=RunWindow(date(2026,10,2),date(2026,10,1),'live',None),
        shared_config={},context_manager=Context(),context_build_lock=threading.Lock(),portfolio=None,
        clock=lambda:now,monotonic=lambda:0,secrets=_secret_values(project),analyzer_factory=failing_graph)
    data = (batch/'results'/'TSLA.json').read_text()
    assert 'fixture-fred-private' not in data
    assert 'fred.invalid' not in data
    current = tmp_path/'data'/'runs'/'2026-10-02'/'current'
    current.mkdir(parents=True)
    (current/'TSLA.json').write_text(data)
    assert build_site(tmp_path)['ok']
    assert 'fixture-fred-private' not in (tmp_path/'site'/'index.html').read_text()
    assert 'fixture-fred-private' not in (tmp_path/'site'/'days'/'2026-10-02'/'TSLA.html').read_text()


def test_disabled_stocktwits_is_grey_with_reason():
    collector = SourceStatusCollector()
    collector.observe({'method':'fetch_stocktwits','source':'StockTwits','outcome':'unconfigured',
                       'error':'已停用：StockTwits 公共接口被 Cloudflare 拦截'})
    row = {row['category']: row for row in collector.snapshot({}, {})}['StockTwits']
    assert row['status'] == '未配置' and 'Cloudflare' in row['reason']


def test_analysis_observation_never_counts_as_extended_coverage():
    collector = SourceStatusCollector()
    block = {'extended_hours': {'data': {'SMTC': {'pre': {'status': '数据不可用'},
        'analysis_quote': {'status': '可用', 'source': '富途订阅报价'}}}}}
    row = collector.snapshot(block, {'futu_enabled': True})[1]
    assert row['status'] != '正常'
    assert '富途订阅报价' not in row['source']

import json
import importlib
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from daily_analyzer.site import build_site, symbol_slug


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _result(symbol: str, day: str, rating: str = "Buy") -> dict:
    return {
        "schema_version": 1,
        "run_id": f"{day.replace('-', '')}T123100-100",
        "mode": "live",
        "symbol": symbol,
        "analyzed_symbol": "QQQ" if symbol == "^NDX" else symbol,
        "type": "index" if symbol == "^NDX" else "stock",
        "target_session": "regular",
        "upstream_trade_date": day,
        "status": "completed",
        "error": None,
        "final_rating": rating,
        "rating_cn": "买入",
        "final_trade_decision": "建议持有；仅供研究。\n\n<script>alert(1)</script>\n\n[恶意链接](javascript:alert(1))",
        "trader_investment_plan": "分批观察。",
        "investment_plan": "研究经理结论。",
        "reports": {"market": "# 市场报告\n\n|项|值|\n|---|---|\n|趋势|上行|"},
        "investment_debate": "多空观点摘要。",
        "risk_debate": "风险观点摘要。",
        "injected_context": "扩展时段与宏观上下文。",
        "started_at": f"{day}T12:31:00Z",
        "context_as_of": f"{day}T12:31:00Z",
        "price_data_end_date": "2026-09-30",
        "news_cutoff_utc": None,
        "data_queries": [{"name": "get_news", "started_at": f"{day}T12:40:00Z", "finished_at": f"{day}T12:40:02Z"}],
        "last_data_query_at": f"{day}T12:40:02Z",
        "information_through": f"{day}T12:40:02Z",
        "finished_at": f"{day}T13:10:00Z",
        "started_after_open": False,
        "finished_after_open": False,
        "source_timestamps": {"news": {"as_of": f"{day}T12:40:02Z", "source": "Alpaca"}},
        "news_truncated": True,
        "premarket_change_pct": 1.25,
        "sector_rank": 2,
        "context_blocks": {
            "macro_releases": {
                "source": "Alpaca",
                "as_of": f"{day}T12:31:00Z",
                "items": [
                    {
                        "metric": "初请失业金",
                        "actual": "197K",
                        "expected": "201K",
                        "prior": "201K",
                        "published_at": "08:30 ET",
                    }
                ],
            },
            "sector_strength": {
                "title": "sector_strength",
                "markdown": "Technology 相对 SPY 强于大盘。",
                "data": {"ranking": [{"rank": 2, "symbol": "XLK", "excess_return_20d": 0.012, "status": "可用"}]},
                "as_of": f"{day}T12:31:00Z",
                "sources": ["Alpaca"],
            },
            "extended_hours": {"source": "Futu", "as_of": f"{day}T12:30:00Z", "content": "SPY 夜盘与盘前数据。"},
        },
        "portfolio_context": None,
        "llm": {"provider": "codex_exec", "deep": {"model": "gpt-6.1-sol", "reasoning_effort": "high"}, "quick": {"model": "gpt-6.1-sol", "reasoning_effort": "high"}},
        "duration_seconds": 234,
        "llm_usage": {"calls": 8, "input_tokens": 700},
    }


def _fixture(root: Path) -> None:
    current = root / "data" / "runs" / "2026-10-01" / "current"
    _write_json(current / "NVDA.json", _result("NVDA", "2026-10-01"))
    _write_json(current / "^NDX.json", _result("^NDX", "2026-10-01"))
    _write_json(
        root / "data" / "runs" / "2026-09-30" / "current" / "NVDA.json",
        _result("NVDA", "2026-09-30", "Hold"),
    )
    _write_json(
        root / "data" / "runs" / "2026-10-01" / "manifest.json",
        {"trade_date": "2026-10-01", "items": {"NVDA": {"recent_retry_failure": {"run_id": "retry-2", "status": "failed", "error": "quota exhausted"}}}},
    )
    _write_json(
        root / "data" / "runs" / "2026-10-01" / "batches" / "20261001T123100-100" / "context.json",
        {
            "market_regime": {"source": "Alpaca", "as_of": "2026-10-01T12:30:00Z", "content": "SPY 趋势温和向上。"},
            "sector_strength": {"source": "Alpaca", "items": [{"rank": 1, "sector": "Technology", "performance": "+1.8%", "note": "强于大盘"}]},
        },
    )
    _write_json(
        root / "data" / "status.json",
        {
            "last_run": {
                "run_id": "20261001T123100-100",
                "trade_date": "2026-10-01",
                "mode": "live",
                "status": "partial",
                "progress": {"completed": 2, "total": 3},
                "started_at": "2026-10-01T12:31:00Z",
                "average_duration_seconds": 234,
                "estimated_finish_at": "2026-10-01T13:40:00Z",
                "last_error": "一个标的失败",
            },
            "last_schedule_event": {"at": "2026-10-01T13:30:00Z", "trade_date": "2026-10-01", "result": "skipped_already_done", "reason": "今日已运行"},
        },
    )


def test_site_builds_local_pages_and_sanitizes_report(tmp_path: Path) -> None:
    _fixture(tmp_path)
    result = build_site(tmp_path, now=datetime(2026, 10, 2, 8, 0, tzinfo=ZoneInfo("America/New_York")))

    assert result["ok"] is True
    site = tmp_path / "site"
    assert site.is_symlink()
    assert (site / "index.html").is_file()
    assert (site / "days" / "2026-10-01" / "index.html").is_file()
    assert (site / "days" / "2026-10-01" / "NVDA.html").is_file()
    assert (site / "days" / "2026-10-01" / "^NDX.html").is_file()
    assert (site / "symbols" / "NVDA.html").is_file()
    assert symbol_slug("^NDX") == "^NDX"

    home = (site / "index.html").read_text(encoding="utf-8")
    detail = (site / "days" / "2026-10-01" / "NVDA.html").read_text(encoding="utf-8")
    overview = (site / "days" / "2026-10-01" / "index.html").read_text(encoding="utf-8")
    history = (site / "symbols" / "NVDA.html").read_text(encoding="utf-8")
    assert "days/2026-10-01/NVDA.html" in home
    assert "初请失业金" in home and "197K" in home
    assert "Technology" in overview and "Technology" in home
    assert "最近一次重跑失败" in overview and "quota exhausted" in overview
    assert "上一交易日结果" in detail and "../../days/2026-09-30/NVDA.html" in detail
    assert "数据查询记录" in detail and "get_news" in detail
    assert "研究经理结论" in detail and "Deep 模型 / 强度" in detail
    assert "href=\"../days/2026-10-01/NVDA.html\"" in history
    assert 'href="../../symbols/NVDA.html"' in detail
    assert "alert(1)" not in detail
    assert "javascript:" not in detail
    assert "<script>alert" not in detail
    assert "仅供个人研究参考，不构成投资建议。" in detail
    assert "fetch(" not in home and "XMLHttpRequest" not in home
    assert "https://" not in home
    assert "content=\"300\"" in home


def test_site_build_failure_preserves_previous_symlink_and_retains_three(tmp_path: Path) -> None:
    _fixture(tmp_path)
    for _ in range(4):
        result = build_site(tmp_path)
        assert result["ok"] is True
    builds = [path for path in (tmp_path / "site-builds").iterdir() if path.is_dir()]
    assert len(builds) == 3
    old_target = (tmp_path / "site").resolve()

    site_module = importlib.import_module("daily_analyzer.site")
    original_page = site_module._page
    calls = 0

    def fail_mid_build(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise RuntimeError("模拟模板错误")
        return original_page(**kwargs)

    old_page = site_module._page
    site_module._page = fail_mid_build
    try:
        failed = build_site(tmp_path)
    finally:
        site_module._page = old_page
    assert failed["ok"] is False
    assert (tmp_path / "site").resolve() == old_target
    assert (tmp_path / "site" / "index.html").is_file()


def test_sector_ranking_uses_ticker_context_when_batch_context_has_no_sector(tmp_path: Path) -> None:
    _fixture(tmp_path)
    context = tmp_path / "data" / "runs" / "2026-10-01" / "batches" / "20261001T123100-100" / "context.json"
    _write_json(context, {"market_regime": {"markdown": "SPY 稳定。"}})
    current = tmp_path / "data" / "runs" / "2026-10-01" / "current" / "NVDA.json"
    value = json.loads(current.read_text(encoding="utf-8"))
    value.pop("sector_rank", None)
    value.pop("premarket_change_pct", None)
    value["context_as_of"] = "2026-10-01T12:32:00Z"
    value["context_blocks"]["macro_releases"] = {
        "title": "macro_releases",
        "markdown": "#### 前值修订\n\n- 08:30：非农数据前值修订\n\n#### 市场要闻\n\n- 盘前要闻 A",
        "data": {
            "trade_date": "2026-10-01",
            "releases": [{"name": "初请失业金", "actual": "197K", "estimate": "201K", "prior": "201K", "created_at": "2026-10-01T08:30:30-04:00"}],
            "prior_revised": [{"title": "非农数据前值修订"}],
        },
        "as_of": "2026-10-01T12:31:00Z",
        "sources": ["Alpaca Benzinga 新闻"],
    }
    value["context_blocks"]["sector_strength"] = {
        "title": "sector_strength",
        "markdown": "NVDA 相对板块：20日 +2.00%。",
        "data": {
            "ranking": [
                {"rank": 1, "symbol": "XLK", "excess_return_20d": 0.018, "status": "可用"},
                {"rank": 2, "symbol": "XLY", "excess_return_20d": 0.012, "status": "可用"},
            ],
        },
        "as_of": "2026-10-01T12:31:00Z",
        "sources": ["Alpaca"],
    }
    value["context_blocks"]["extended_hours"] = {
        "title": "extended_hours",
        "markdown": "NVDA 盘前报价。",
        "data": {"NVDA": {"pre": {"change_pct": 1.25}}, "SPY": {"pre": {"change_pct": 0.5}}},
        "as_of": "2026-10-01T12:30:00Z",
        "sources": ["Futu"],
    }
    _write_json(current, value)
    failed = _result("ZZZ", "2026-10-01")
    failed["status"] = "failed"
    failed["context_as_of"] = "2026-10-01T13:00:00Z"
    failed["context_blocks"]["macro_releases"] = {
        "title": "macro_releases",
        "markdown": "错误样本宏观数据不得覆盖成功结果。",
        "data": {"releases": [{"name": "错误样本宏观数据", "actual": "0"}]},
        "as_of": "2026-10-01T13:00:00Z",
        "sources": ["测试"],
    }
    _write_json(tmp_path / "data" / "runs" / "2026-10-01" / "current" / "ZZZ.json", failed)
    result = build_site(tmp_path)
    assert result["ok"] is True
    overview = (tmp_path / "site" / "days" / "2026-10-01" / "index.html").read_text(encoding="utf-8")
    home = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert "XLK" in overview
    assert "可用" in overview
    assert "+1.80%" in overview and "+1.20%" in overview
    assert "NVDA 相对板块：20日 +2.00%" in overview
    assert "初请失业金" in home and "非农数据前值修订" in home and "盘前要闻 A" in home
    assert "错误样本宏观数据" not in home
    assert "+1.25%" in overview and "信息截止" in overview


def test_summary_marks_read_extended_and_macro_context_block_statuses() -> None:
    site_module = importlib.import_module("daily_analyzer.site")
    result = {
        "symbol": "NVDA",
        "context_blocks": {
            "extended_hours": {
                "title": "extended_hours",
                "markdown": "",
                "data": {
                    "NVDA": {
                        "after": {"status": "数据不可用", "session_verified": False},
                        "overnight": {"status": "时段未核验（无分时段时间）", "session_verified": False},
                        "pre": {"status": "过期", "session_verified": True},
                    }
                },
                "as_of": "2026-10-01T12:31:00Z",
                "sources": ["Futu"],
            },
            "macro_releases": {
                "title": "macro_releases",
                "markdown": "新闻结果已截断。",
                "data": {"truncated": True},
                "as_of": "2026-10-01T12:31:00Z",
                "sources": ["Alpaca"],
            },
            "market_regime": {"data": {"session_verified": False}},
        },
    }
    marks = site_module._marks(result)
    assert "时段未核验" in marks
    assert "数据过期" in marks
    assert "新闻已截断" in marks
    assert "非本时段数据" not in marks

    result["context_blocks"]["extended_hours"]["data"]["NVDA"]["overnight"]["status"] = "非本时段数据"
    result["news_truncated"] = True
    marks = site_module._marks(result)
    assert "非本时段数据" in marks
    assert marks.count("新闻已截断") == 1


def test_banner_javascript_uses_fixed_time_for_missing_run_and_schedule_state(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("当前环境没有 node，无法执行内联横幅判定函数")
    _fixture(tmp_path)
    build_site(tmp_path, now=datetime(2026, 10, 1, 8, 0, tzinfo=ZoneInfo("America/New_York")))
    html = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    scripts = re.findall(r"<script>(.*?)</script>", html, flags=re.DOTALL)
    assert scripts
    payload = {
        "market_timezone": "America/New_York",
        "anchor_time": "08:30",
        "calendar_start": "2026-10-01",
        "calendar_end": "2026-12-30",
        "trading_days": ["2026-10-01", "2026-10-02", "2026-10-05"],
        "last_run": {},
        "last_schedule_event": {},
    }
    harness = (
        "const window = {};\n"
        + scripts[-1]
        + "\nconst payload = "
        + json.dumps(payload)
        + ";\n"
        + "const date = new Date('2026-10-01T12:45:00Z');\n"
        + "const missed = window.dailyAnalyzerBannerState(payload, date);\n"
        + "const event = window.dailyAnalyzerBannerState({...payload,last_schedule_event:{trade_date:'2026-10-01',result:'skipped_before_anchor'}}, date);\n"
        + "const partial = window.dailyAnalyzerBannerState({...payload,last_run:{trade_date:'2026-10-01',status:'partial',last_error:'quota'},last_schedule_event:{trade_date:'2026-10-01',result:'skipped_already_done'}}, date);\n"
        + "const running = window.dailyAnalyzerBannerState({...payload,last_run:{trade_date:'2026-10-01',status:'running',progress:{completed:4,total:9},started_at:'2026-10-01T12:31:00Z',estimated_finish_at:'2026-10-01T13:10:00Z'}}, date);\n"
        + "const failed = window.dailyAnalyzerBannerState({...payload,last_run:{trade_date:'2026-10-01',status:'failed',last_error:{category:'fatal_config',message:'模型不受支持'}}}, date);\n"
        + "const holiday = window.dailyAnalyzerBannerState(payload, new Date('2026-10-03T16:00:00Z'));\n"
        + "console.log(JSON.stringify({missed,event,partial,running,failed,holiday}));\n"
    )
    script_path = tmp_path / "banner-check.js"
    script_path.write_text(harness, encoding="utf-8")
    completed = subprocess.run([node, str(script_path)], capture_output=True, text=True, check=True)
    result = json.loads(completed.stdout)
    assert result["missed"]["title"] == "今日尚未运行"
    assert "请检查电脑是否开机、已登录且已唤醒" in result["missed"]["detail"]
    assert "已有调度记录" in result["event"]["detail"]
    assert result["partial"]["title"] == "今日部分失败"
    assert result["partial"]["detail"] == "quota"
    assert "4/9" in result["running"]["title"] and "预计完成" in result["running"]["detail"]
    assert result["failed"]["title"] == "今日失败"
    assert "fatal_config：模型不受支持" in result["failed"]["detail"]
    assert "npm install -g @openai/codex@latest" in result["failed"]["detail"]
    assert result["holiday"]["title"] == "今日非交易日"


def test_manual_button_script_tracks_only_active_row_and_busy_click(tmp_path):
    from daily_analyzer.site import render_home
    node = shutil.which("node")
    if node is None:
        pytest.skip("当前环境没有 node，无法执行按钮交互脚本")
    _fixture(tmp_path)
    html = render_home(tmp_path, managed=True)
    script = re.search(r"(  const analysisMessage=.*?  analysisStatus\(\);)", html, re.DOTALL).group(1)
    harness = r'''
const assert=require("node:assert/strict");
const message={textContent:""};
function makeButton(symbol){
  const bar={value:null,removeAttribute(){this.value=null;}};
  const fields={"[data-stage]":{textContent:""},"[data-remaining]":{textContent:""},"[data-estimate-note]":{textContent:""},"progress":bar};
  const box={hidden:true,querySelector(key){return fields[key];}};
  const summary={hidden:false};
  return {dataset:{analyze:symbol},disabled:false,textContent:"分析一次",box,summary,fields,
    closest(){return {querySelector(key){return key==="[data-analysis-progress]"?box:summary;}};},
    addEventListener(event,handler){this.click=handler;}};
}
const buttons=[makeButton("NVDA"),makeButton("TSLA")];
let value={busy:false,items:{},active_symbols:[]};
let reloads=0;
const delays=[];
const global={document:{getElementById(){return message;},querySelectorAll(){return buttons;}},
  clearTimeout(){},setTimeout(fn,delay){delays.push(delay);return delays.length;},location:{reload(){reloads++;}}};
async function api(data){
  if(data){
    if(value.busy)throw new Error("已有分析批次运行中");
    value={busy:true,symbol:data.symbol,active_symbols:[data.symbol],message:"正在分析",
      items:{NVDA:{stage:"新闻分析",estimated_percent:50,elapsed_seconds:300,remaining_seconds:300,estimate_samples:3,estimate_source:"其他配置参考"}}};
  }
  return value;
}
'''+script+r'''
(async()=>{
  await new Promise(setImmediate);
  const clicking=buttons[0].click();
  assert.equal(buttons[0].disabled,true);
  assert.equal(buttons[1].disabled,false);
  await clicking;
  await new Promise(setImmediate);
  assert.equal(buttons[0].disabled,true);
  assert.equal(buttons[1].disabled,false);
  assert.equal(buttons[0].fields["[data-stage]"].textContent,"新闻分析 · 预计 50%");
  assert.match(buttons[0].fields["[data-remaining]"].textContent,/剩余约 5分/);
  assert.match(buttons[0].fields["[data-estimate-note]"].textContent,/配置不同/);
  assert.equal(buttons[0].summary.hidden,true);
  assert.equal(buttons[1].summary.hidden,false);
  await buttons[1].click();
  assert.equal(buttons[0].disabled,true);
  assert.equal(buttons[1].disabled,false);
  assert.match(message.textContent,/已有分析批次/);
  value={busy:false,active_symbols:[],items:{}};
  await analysisStatus();
  assert.ok(buttons.every(button=>!button.disabled && button.box.hidden && !button.summary.hidden));
  assert.equal(reloads,1);
  assert.ok(delays.every(delay=>delay===3000));
  console.log("按钮和进度验证通过");
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
    path = tmp_path / "analysis-buttons.js"
    path.write_text(harness)
    result = subprocess.run([node, str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_report_status_shows_only_duration_and_keeps_times_collapsed(tmp_path):
    from daily_analyzer.site import render_home
    _fixture(tmp_path)
    html = render_home(tmp_path, managed=True)
    summary = re.findall(r"<span data-report-summary>(.*?)</span></span>", html, re.DOTALL)
    assert summary and "耗时 3 分 54 秒" in summary[0]
    assert all("开始" not in value and "完成 2026" not in value and "北京" not in value for value in summary)
    assert re.search(r'<details class="row-details">.*?开始 .*?完成 .*?</details>', html, re.DOTALL)


def test_date_selection_navigates_to_overview_and_symbol_to_detail(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("当前环境没有 node，无法执行内联页面交互")
    _fixture(tmp_path)
    result = build_site(tmp_path)
    assert result["ok"] is True
    html = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    scripts = re.findall(r"<script>(.*?)</script>", html, flags=re.DOTALL)
    assert scripts
    harness = (
        "const listeners = {};\n"
        "function makeSelect(){let html='';return {value:'',options:[],set innerHTML(value){html=value;this.options=[];},get innerHTML(){return html;},appendChild(value){this.options.push(value);},addEventListener(name,fn){listeners[name]=fn;}};}\n"
        "const dateSelect=makeSelect();const symbolSelect=makeSelect();\n"
        "const document={getElementById(id){return id==='date-select'?dateSelect:(id==='symbol-select'?symbolSelect:null);},createElement(){return {value:'',textContent:''};}};\n"
        "const window={document,location:{href:''},setTimeout(){}};\n"
        + scripts[-1]
        + "\ndateSelect.value='2026-09-30';listeners.change();const overview=window.location.href;\n"
        + "symbolSelect.value='NVDA';listeners.change();console.log(JSON.stringify({overview,detail:window.location.href}));\n"
    )
    script_path = tmp_path / "selector-check.js"
    script_path.write_text(harness, encoding="utf-8")
    completed = subprocess.run([node, str(script_path)], capture_output=True, text=True, check=True)
    navigation = json.loads(completed.stdout)
    assert navigation["overview"] == "days/2026-09-30/index.html"
    assert navigation["detail"] == "days/2026-09-30/NVDA.html"


def test_site_source_is_trackable_while_root_release_link_is_ignored() -> None:
    repository = Path(__file__).resolve().parents[1]
    source = subprocess.run(
        ["git", "check-ignore", "-q", "src/daily_analyzer/site/__init__.py"],
        cwd=repository,
        check=False,
    )
    release = subprocess.run(
        ["git", "check-ignore", "-q", "site"],
        cwd=repository,
        check=False,
    )
    assert source.returncode == 1
    assert release.returncode == 0


def test_home_tracks_enabled_subscriptions_and_relative_units(tmp_path):
    from daily_analyzer.site import render_home
    _fixture(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/watchlist.yaml").write_text(
        "items:\n  - {symbol: NVDA, type: stock, name: 英伟达}\n"
        "  - {symbol: AAPL, type: stock}\n  - {symbol: MSFT, type: stock, enabled: false}\n", encoding="utf-8")
    path = tmp_path / "data/runs/2026-10-01/current/NVDA.json"
    result = json.loads(path.read_text())
    result["final_trade_decision"] = "**Rating**: Hold\n\n**Executive Summary**: 先维持已有仓位，不追涨。条件和风险稍后复核。\n\n**Investment Thesis**: 这里是很长的论证。"
    result["context_blocks"]["sector_strength"]["data"].update(
        symbol="NVDA", sector_etf="XLK", sector_excess_5d=-0.011,
        sector_excess_20d=0.025, sector_excess_60d=None)
    _write_json(path, result)
    html = render_home(tmp_path, managed=True)
    table = html.split('aria-label="自选建议与相对板块强弱"')[1].split("</table>")[0]
    assert "英伟达" in table and "AAPL" in table and "待分析" in table
    assert "^NDX" not in table and "MSFT" not in table
    assert "+2.50" in table and "-1.10" in table and "强于板块" in table
    assert "先维持已有仓位，不追涨。" in table and "Investment Thesis" not in table
    assert "2026-10-01 报告" in table
    assert html.index('aria-label="自选建议') < html.index("市场背景与数据")
    assert "XMLHttpRequest" not in html
    build_site(tmp_path)
    offline = (tmp_path / "site/index.html").read_text()
    assert "fetch(" not in offline and "http://127.0.0.1:8765/" in offline
    assert (tmp_path / "site/days/2026-10-01/^NDX.html").is_file()


def test_missing_relative_values_are_not_zero_or_cross_symbol():
    from daily_analyzer.site import _summary_row, _rows
    result = _result("NVDA", "2026-10-01")
    result.pop("premarket_change_pct")
    result["context_blocks"]["extended_hours"] = {"data": {"SPY": {"pre": {"change_pct": 2.5}}}}
    result["context_blocks"]["sector_strength"] = {"data": {"symbol": "AAPL", "sector_excess_20d": 0.02}}
    row = _summary_row(result, None, "")
    assert row["premarket"] == "—" and row["relative"]["20"]["text"] == "—"
    assert row["strength"] == "数据不足"
    assert _rows({"ranking": [{"symbol": "XLK", "rank": None}]}, "sector")[0]["rank"] == "—"
    result["type"] = "etf"
    result["context_blocks"]["sector_strength"] = {"data": {"symbol": "NVDA", "sector_excess_20d": 0.02}}
    row = _summary_row(result, None, "")
    assert row["strength"] == "不适用" and row["relative"]["20"]["text"] == "—"


def test_summary_is_bounded_and_does_not_render_scripts():
    from daily_analyzer.site import _advice_summary
    assert _advice_summary("**Executive Summary**: 持有。\n\n**Risk**: 后续长报告") == "持有。"
    assert len(_advice_summary("建议" * 100)) == 141
    assert "alert" not in _advice_summary("<script>alert(1)</script>继续观察。")


def test_context_tables_and_structured_debates_render_readable_html():
    from daily_analyzer.site import _markdown, _debate_text
    html = str(_markdown("数据来源：Alpaca\n| 标的 | 收盘 |\n|---|---:|\n| NVDA | 100 |"))
    assert "<table>" in html and "<td>NVDA</td>" in html
    text = _debate_text({"history": "**观点**：保持持有。", "bull_history": "重复段落", "count": 1})
    assert text == "**观点**：保持持有。" and "重复段落" not in text
    html = str(_markdown(_debate_text({"history": "Aggressive Analyst: 持有。Conservative Analyst: 控制仓位。"})))
    assert "<h3>积极观点</h3>" in html and "<h3>保守观点</h3>" in html


def test_home_distinguishes_running_today_from_prior_report(tmp_path):
    from daily_analyzer.site import render_home
    _fixture(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/watchlist.yaml").write_text("items:\n  - {symbol: NVDA, type: stock}\n")
    _write_json(tmp_path / "data/status.json", {"last_run": {"run_id": "active", "trade_date": "2026-10-02", "status": "running"}})
    _write_json(tmp_path / "data/runs/2026-10-02/batches/active/batch.json", {"items": {"NVDA": {"status": "running"}}})
    html = render_home(tmp_path, managed=True)
    assert "今日分析中" in html and "2026-10-01 报告" in html

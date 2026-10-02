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
    assert "NVDA 相对板块：20日 +2.00%" not in overview
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
  const error={hidden:true,textContent:""};
  return {dataset:{analyze:symbol},disabled:false,textContent:"分析一次",box,summary,fields,error,
    closest(){return {querySelector(key){return key==="[data-analysis-progress]"?box:key==="[data-analysis-error]"?error:summary;}};},
    addEventListener(event,handler){this.click=handler;}};
}
const buttons=[makeButton("NVDA"),makeButton("TSLA")];
const allButton={disabled:false,textContent:"全部分析一次",addEventListener(event,handler){this.click=handler;}};
let value={busy:false,items:{},active_symbols:[]};
let reloads=0;
const delays=[];
const watchManager={open:false};
const global={document:{getElementById(id){return id==="analyze-all"?allButton:id==="watchlist-manager"?watchManager:message;},querySelectorAll(){return buttons;}},
  clearTimeout(){},setTimeout(fn,delay){delays.push(delay);return delays.length;},location:{reload(){reloads++;}}};
async function api(data){
  if(data){
    if(value.busy)throw new Error("已有分析批次运行中");
    value={busy:true,symbol:data.symbol,active_symbols:data.scope==="all"?["NVDA","TSLA"]:[data.symbol],message:"正在分析",
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
  assert.equal(allButton.disabled,false);
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
  assert.match(buttons[1].error.textContent,/已有分析批次/);
  await analysisStatus();
  assert.match(buttons[1].error.textContent,/已有分析批次/);
  value.items.TSLA={status:"pending",stage:"排队中",elapsed_seconds:0};
  value.active_symbols.push("TSLA");
  await analysisStatus();
  assert.equal(buttons[1].textContent,"排队中");
  assert.equal(buttons[1].disabled,true);
  value={busy:false,active_symbols:[],items:{}};
  watchManager.open=true;
  await analysisStatus();
  assert.equal(reloads,0);
  watchManager.open=false;
  await analysisStatus();
  assert.ok(buttons.every(button=>!button.disabled && button.box.hidden && !button.summary.hidden));
  assert.equal(reloads,1);
  assert.equal(allButton.disabled,false);
  await allButton.click();
  await new Promise(setImmediate);
  assert.equal(allButton.disabled,false);
  assert.ok(buttons.every(button=>button.disabled && !button.box.hidden));
  value={busy:true,active_symbols:["TSLA"],items:{TSLA:{stage:"新闻分析",elapsed_seconds:10}}};
  await analysisStatus();
  assert.equal(buttons[0].disabled,false);
  assert.equal(buttons[1].disabled,true);
  assert.equal(allButton.disabled,false);
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
        "const document={querySelectorAll(){return [];},getElementById(id){return id==='date-select'?dateSelect:(id==='symbol-select'?symbolSelect:null);},createElement(){return {value:'',textContent:''};}};\n"
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
    table = html.split('aria-label="自选建议与相对基准强弱"')[1].split("</table>")[0]
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


def test_home_price_plans_and_standard_allocation_are_explicit(tmp_path):
    from daily_analyzer.site import _summary_row, render_home
    result = _result("TSLA", "2026-10-01")
    result["final_trade_decision"] = (
        "**Executive Summary**: 减配。目标为标准配置的60%，只减超额部分。\n\n"
        "**建仓点位**: 不新建仓；价格区间不适用。\n\n"
        "**加仓点位**: 暂不加仓；等待技术数据。\n\n"
    )
    result["trader_investment_plan"] = "**减仓点位**: 98–100 USD；跌破97后减仓；依据支撑。"
    row = _summary_row(result, None, "")
    assert "目标配置 60%" in row["allocation"]
    assert "不新建仓" in row["plans"][0]["text"] and "98–100" in row["plans"][2]["text"]
    _write_json(tmp_path / "data/runs/2026-10-01/current/TSLA.json", result)
    html = render_home(tmp_path, managed=True)
    assert "标准仓位 100% 是什么" in html and "6000 元" in html
    assert "不是卖出现有持仓" in html and 'id="analyze-all"' in html
    result["final_trade_decision"] = "目标为账户总资产60%。\n\n**目标配置（标准仓位=100%）**: 0%"
    assert "目标配置 0%" in _summary_row(result, None, "")["allocation"]
    result["final_trade_decision"] = "目标为账户总资产60%。"
    result["trader_investment_plan"] = ""
    assert "未提供" in _summary_row(result, None, "")["allocation"]
    assert _summary_row(result, None, "")["plans"][2]["text"] == "本报告未提供"


def test_strength_supplement_matches_symbol_date_and_preserves_report(tmp_path):
    from daily_analyzer.site import _summary_row
    result = _result("TSLA", "2026-10-01")
    path = tmp_path / "data/cache/relative_strength/2026-09-30/TSLA.json"
    supplement = {"symbol": "TSLA", "as_of": "2026-09-30", "benchmark_symbol": "QQQ",
                  "benchmark_kind": "index", "benchmark_reason": "指数成员已核验", "benchmark_excess_20d": 0.03}
    before = json.dumps(result)
    _write_json(path, supplement)
    row = _summary_row(result, None, "", tmp_path)
    assert row["strength"] == "强于指数" and row["benchmark"] == "QQQ"
    assert row["relative"]["20"]["text"] == "+3.00" and row["strength_supplement"] is True
    assert row["sector_rank"] == "—" and json.dumps(result) == before
    _write_json(path, {**supplement, "symbol": "NVDA"})
    assert _summary_row(result, None, "", tmp_path)["strength"] == "数据不足"
    _write_json(path, {**supplement, "as_of": "2026-09-29"})
    assert _summary_row(result, None, "", tmp_path)["strength"] == "数据不足"
    _write_json(path, supplement)
    result["context_blocks"]["sector_strength"]["data"] = {"symbol": "TSLA", "sector_etf": "XLY", "sector_excess_20d": -0.02}
    row = _summary_row(result, None, "", tmp_path)
    assert row["benchmark"] == "XLY" and row["strength_supplement"] is False
    result["context_blocks"]["sector_strength"]["data"] = {}
    _write_json(path, {**supplement, "benchmark_kind": "sector", "benchmark_symbol": "XLY", "sector_rank": 6})
    assert _summary_row(result, None, "", tmp_path)["sector_rank"] == "6"


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


def test_dual_comparison_charts_render_offline_and_keep_common_origin(tmp_path):
    from daily_analyzer.site import _summary_row, _comparison_chart, render_home
    result = _result("TSLA", "2026-10-01")
    chart = {"dates": ["2026-09-28", "2026-09-29", "2026-09-30"],
             "stock": [100, 120, 90], "benchmark": [100, 95, 110], "sources": ["固定复权样本"]}
    comparisons = [{"symbol": code, "kind": kind, "excess_20d": 0.02, "chart": chart} for code, kind in [("XLY", "sector"), ("QQQ", "index")]]
    result["context_blocks"]["sector_strength"]["data"] = {"symbol": "TSLA", "sector_etf": "XLY", "comparisons": comparisons}
    row = _summary_row(result, None, "")
    assert [c["name"] for c in row["comparisons"]] == ["消费可选", "纳斯达克100"]
    plot = row["comparisons"][0]["chart"]
    assert plot["series"][0]["dots"][0]["y"] == plot["series"][1]["dots"][0]["y"]
    assert _comparison_chart(None, "TSLA", "QQQ") is None
    _write_json(tmp_path / "data/runs/2026-10-01/current/TSLA.json", result)
    html = render_home(tmp_path)
    assert html.count('<polyline class=') == 4
    assert 'aria-label="查看TSLA相对XLY归一化走势"' in html
    assert 'aria-label="查看TSLA相对QQQ归一化走势"' in html
    assert "共同首日100" in html and "固定复权样本" in html
    assert "fetch(" not in html and "cdn" not in html.lower()


def test_comparison_dialog_click_script_needs_no_network(tmp_path):
    from daily_analyzer.site import render_home
    node = shutil.which("node")
    if node is None:
        pytest.skip("当前环境没有node")
    _fixture(tmp_path)
    html = render_home(tmp_path)
    script = re.search(r'(  global.document.querySelectorAll\("\[data-comparison\]"\).*?)(?=\n\s*if \(site.refresh_seconds)', html, re.DOTALL).group(1)
    harness = '''
const assert=require("node:assert/strict");
const dialog={open:false,showModal(){this.open=true;},close(){this.open=false;}};
const trigger={addEventListener(event,fn){this.click=fn;},closest(){return {querySelector(){return dialog;}};}};
const closer={addEventListener(event,fn){this.click=fn;},closest(){return dialog;}};
const global={document:{querySelectorAll(selector){return selector==="[data-comparison]"?[trigger]:[closer];}}};
'''+script+'''
trigger.click();assert.equal(dialog.open,true);closer.click();assert.equal(dialog.open,false);
'''
    path = tmp_path / "comparison-dialog.js"
    path.write_text(harness)
    result = subprocess.run([node, str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_new_price_summary_keeps_full_anchor_and_legacy_format():
    from daily_analyzer.site import _summary_row
    result = _result("TSLA", "2026-10-02")
    first = "区间 348.0–352.0 美元（依据：SMA20 与前低" + "，明确来源日期" * 15 + "）"
    result["final_trade_decision"] = "**建仓点位**: " + first + "。等待回踩企稳后执行。\n\n**加仓点位**: 不适用：缺少确认。等待信号。"
    result["trader_investment_plan"] = "**减仓点位**: 98–100 USD；依据支撑。"
    plans = _summary_row(result, None, "")["plans"]
    assert plans[0]["text"] == first
    assert plans[1]["text"] == "不适用：缺少确认。"
    assert "98–100 USD" in plans[2]["text"]


@pytest.mark.parametrize("action,name", [("Buy", "买入"), ("Overweight", "增持"), ("Hold", "持有"), ("Underweight", "减持"), ("Sell", "卖出")])
def test_trader_actions_share_chinese_rating_mapping(action, name):
    from daily_analyzer.site import _markdown, _decision_section
    text = "**Action**: " + action + "\n\n**建仓点位**: 区间 100–101 美元（依据：SMA20）\n\nFINAL TRANSACTION PROPOSAL: **" + action.upper() + "**"
    assert name + "（" + action + "）" in str(_markdown(text))
    assert _decision_section(text, "建仓点位") == "区间 100–101 美元（依据：SMA20）"


def test_source_status_shared_home_detail_and_legacy():
    from daily_analyzer.site import _source_status
    from daily_analyzer.site.templates import HOME, DETAIL, BASE
    record = {"data_source_status": [
        {"category": "日线", "source": "Alpaca", "status": "正常", "reason": ""},
        {"category": "VIX", "source": "Yahoo", "status": "降级", "reason": "CBOE失败"},
        {"category": "StockTwits", "source": "—", "status": "失败", "reason": "HTTP错误"},
        {"category": "Reddit", "source": "—", "status": "未使用", "reason": ""},
    ]}
    value = _source_status(record)
    assert value["tone"] == "failed"
    for html in (HOME.render(rows=[{"source_status": value}], summary={}), DETAIL.render(source_status=value)):
        assert "数据源 1/4 正常" in html
        assert 'aria-haspopup="dialog"' in html and 'class="source-dialog"' in html
        assert 'data-source-close' in html
        if 'class="watch-table"' in html:
            assert html.index('class="source-dialog"') > html.index('</tbody></table>')
        import re
        time_section = re.search(r'<details[^>]*><summary>时间与质量.*?</details>', html, re.S).group()
        assert 'source-table' not in time_section and '数据源 1/4 正常' not in time_section
        for text in ("source-normal", "source-degraded", "source-failed", "source-inactive", "CBOE失败"):
            assert text in html
    assert "旧报告未记录数据源状态" in DETAIL.render(source_status=_source_status({}))
    assert "--warn:#a36b08" in BASE.render(ui_data={})
    assert "--warn:#e6ba68" in BASE.render(ui_data={})
    assert '.source-dialog[open]' in BASE.render(ui_data={})


def test_sector_rank_keeps_only_complete_markdown_table():
    from daily_analyzer.site.templates import HOME
    complete = "<table><tr><th>行业 ETF</th><th>相对 SPY 5日</th><th>20日</th><th>60日</th></tr></table>"
    html = HOME.render(rows=[], summary={}, sector_rows=[{"sector":"XLK","rank":1}], sector_html=complete)
    assert complete in html
    assert html.count(complete) == 1
    assert "<th>20 日超额收益</th>" not in html



def test_sector_display_omits_ticker_caption_and_twenty_day_title():
    from daily_analyzer.site import _sector_data
    from daily_analyzer.site.templates import HOME
    rows, html = _sector_data({"sector_strength":{"markdown":"| 名次 | 行业 ETF | 相对 SPY 5日 | 20日 | 60日 | 状态 |\n|---|---|---|---|---|---|\n| 1 | XLK | +2% | +7% | +6% | 可用 |\n\nTSLA 比较基准：XLY，重复说明。","data":{}}})
    rendered = HOME.render(rows=[],summary={},sector_rows=rows,sector_html=html)
    assert "板块强弱排名 · 相对 SPY" in rendered
    assert "相对 SPY 的 20 日收益" not in rendered
    assert "TSLA 比较基准" not in rendered
    assert "相对 SPY 5日" in rendered and "60日" in rendered


def test_market_panel_hides_extended_hours_without_changing_context():
    from daily_analyzer.site import _context_cards
    from daily_analyzer.site.templates import HOME
    context={'market_regime':{'markdown':'市场偏强'},'extended_hours':{'markdown':'扩展时段明细样本'}}
    cards=_context_cards(context, [])
    rendered=HOME.render(rows=[],summary={},market_cards=cards)
    assert '大盘环境与扩展时段' not in rendered and '大盘环境' in rendered
    assert '市场偏强' in rendered and '扩展时段明细样本' not in rendered
    assert context['extended_hours']['markdown']=='扩展时段明细样本'


def test_premarket_cell_shows_price_with_change_and_quote_source():
    from daily_analyzer.site import _summary_row
    result = _result("TSLA", "2026-10-02")
    result.pop("premarket_change_pct")
    result["context_blocks"]["extended_hours"] = {"data": {"TSLA": {"pre": {
        "price": 357.13, "change_pct": 0.8528, "status": "可用", "source": "富途快照",
        "quote_time": "2026-10-02T06:39:39-04:00"}}}}
    row = _summary_row(result, None, "")
    assert row["premarket_price"] == "357.13 美元" and row["premarket"] == "+0.85%"
    assert "富途快照" in row["premarket_title"] and "06:39:39 美东" in row["premarket_title"]


def test_stale_premarket_quote_hides_price_and_legacy_change_only():
    from daily_analyzer.site import _summary_row
    result = _result("TSLA", "2026-10-02")
    legacy = _summary_row(result, None, "")
    assert legacy["premarket"] == "+1.25%" and legacy["premarket_price"] == ""
    result.pop("premarket_change_pct")
    result["context_blocks"]["extended_hours"] = {"data": {"TSLA": {"pre": {
        "price": 350.0, "change_pct": None, "status": "过期"}}}}
    row = _summary_row(result, None, "")
    assert row["premarket"] == "—" and row["premarket_price"] == ""


def test_report_status_shows_start_clock_after_date(tmp_path):
    from daily_analyzer.site import _summary_row
    result = _result("TSLA", "2026-10-02")
    result["_date"] = "2026-10-02"
    result["started_at"] = "2026-10-02T08:31:02-04:00"
    row = _summary_row(result, None, "")
    assert row["start_clock"] == "开始 20:31 北京 / 08:31 美东"
    result.pop("started_at")
    assert _summary_row(result, None, "")["start_clock"] == ""


def test_home_row_renders_premarket_price_and_start_clock(tmp_path):
    from daily_analyzer.site import render_home
    _fixture(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/watchlist.yaml").write_text("items:\n  - {symbol: NVDA, type: stock}\n", encoding="utf-8")
    path = tmp_path / "data/runs/2026-10-01/current/NVDA.json"
    result = json.loads(path.read_text())
    result.pop("premarket_change_pct")
    result["context_blocks"]["extended_hours"] = {"data": {"NVDA": {"pre": {
        "price": 101.0, "change_pct": 1.0, "status": "可用", "source": "富途快照",
        "quote_time": "2026-10-01T08:29:00-04:00"}}}}
    _write_json(path, result)
    table = render_home(tmp_path).split('aria-label="自选建议与相对基准强弱"')[1].split("</table>")[0]
    assert '<span class="premarket-price">101.00 美元</span>+1.00%' in table
    assert "2026-10-01 报告 · 开始 20:31 北京 / 08:31 美东" in table
    assert 'title="来源 富途快照；报价时间' in table


def test_home_late_news_and_bound_cutoff_watch_render_and_hide_stale(tmp_path):
    from daily_analyzer.site import render_home
    _fixture(tmp_path)
    now = datetime(2026,10,2,10,tzinfo=ZoneInfo('America/New_York'))
    result = _result('TSLA','2026-10-02')
    result['late_news'] = [{'title':'分析期间交付数据'}]
    (tmp_path/'config').mkdir(exist_ok=True)
    (tmp_path/'config/watchlist.yaml').write_text('items:\n  - symbol: TSLA\n    type: stock\n')
    _write_json(tmp_path/'data/runs/2026-10-02/current/TSLA.json',result)
    articles = [{'title':f'季度交付{i}', 'published_at':'2026-10-02T13:04:19Z',
                 'url':'https://example.test/news', 'major':True} for i in range(5)]
    watch = {'trade_date':'2026-10-02', 'checked_at':'2026-10-02T13:10:00Z',
             'items':{'TSLA':{'run_id':result['run_id'], 'information_through':result['information_through'],
                              'count':5,'major':True,'articles':articles}}}
    _write_json(tmp_path/'data/news_watch.json',watch)
    html=render_home(tmp_path,now=now)
    assert '分析期间纳入 1 条新增消息' in html
    assert '截止后新增 5 条消息' in html
    assert 'data-news-watch' in html and '未自动重跑' in html
    assert len(re.findall(r'<span class="subline source-degraded">',html))==3
    assert all(article['title'] in html for article in articles)
    build_site(tmp_path,now=now)
    assert '截止后新增 5 条消息' in (tmp_path/'site/index.html').read_text()
    watch['items']['TSLA']['run_id']='旧报告'
    _write_json(tmp_path/'data/news_watch.json',watch)
    assert 'data-news-watch' not in render_home(tmp_path,now=now)
    watch['items']['TSLA']['run_id']=result['run_id']
    watch['items']['TSLA']['count']=0
    _write_json(tmp_path/'data/news_watch.json',watch)
    assert 'data-news-watch' not in render_home(tmp_path,now=now)


def test_home_shows_late_macro_count_and_errors(tmp_path):
    from daily_analyzer.site import render_home
    _fixture(tmp_path)
    now = datetime(2026,10,2,10,tzinfo=ZoneInfo('America/New_York'))
    result = _result('TSLA','2026-10-02')
    result['late_macro'] = [{'title':'USA Nonfarm Payrolls For Sept. 29K Vs 89K Est.','stage':'research'},
                            {'title':'USA Unemployment Rate For September 4.2% Vs 4.1% Est.','stage':'portfolio'}]
    result['late_macro_errors'] = ['portfolio阶段补抓经济数据失败：TimeoutError']
    (tmp_path/'config').mkdir(exist_ok=True)
    (tmp_path/'config/watchlist.yaml').write_text('items:\n  - symbol: TSLA\n    type: stock\n')
    _write_json(tmp_path/'data/runs/2026-10-02/current/TSLA.json',result)
    html=render_home(tmp_path,now=now)
    assert '分析期间补抓 2 条经济数据' in html
    del result['late_macro'], result['late_macro_errors']
    _write_json(tmp_path/'data/runs/2026-10-02/current/TSLA.json',result)
    assert '条经济数据' not in render_home(tmp_path,now=now)


def test_subscription_manager_keeps_open_for_consecutive_changes(tmp_path):
    """执行实际管理脚本，核对连续操作及手动关闭的刷新时机。"""
    from daily_analyzer.site import render_home
    node = shutil.which('node')
    if node is None:
        pytest.skip('当前环境没有node，无法执行订阅管理脚本')
    _fixture(tmp_path)
    html = render_home(tmp_path, managed=True)
    script = re.search(r'(  const manager =.*?)(?=  const settingsDialog=)', html, re.DOTALL).group(1)
    harness = r'''
const assert=require('node:assert/strict');
class Element {
  constructor(){this.children=[];this.events={};this.value='';this.textContent='';this.open=false;this.disabled=false;}
  addEventListener(name,handler){this.events[name]=handler;}
  appendChild(child){this.children.push(child);}
  replaceChildren(){this.children=[];}
  showModal(){this.open=true;}
  close(){this.open=false;this.events.close?.();}
  async emit(name,event={}){return this.events[name]?.(event);}
}
const ids=Object.fromEntries(['watchlist-manager','watchlist-form','manager-message','manager-list','manage-watchlist','close-manager','type-field','identity-message'].map(id=>[id,new Element()]));
const input=new Element(),type=new Element(),submit=new Element();
const formElement=ids['watchlist-form'];
formElement.elements={symbol:input,type};
formElement.querySelector=()=>submit;
formElement.reset=()=>{input.value='';type.value='';};
class FormData {
  constructor(form){this.rows=Object.entries(form.elements).map(([key,value])=>[key,value.value]);}
  [Symbol.iterator](){return this.rows[Symbol.iterator]();}
}
let items=[{symbol:'NVDA',name:'英伟达',type:'stock',enabled:true}],reloads=0,fail=false;
const global={document:{getElementById(id){return ids[id];},createElement(){return new Element();}},
  location:{reload(){reloads++;}},clearTimeout(){},setTimeout(){return 1;},
  async fetch(path,options={}){
    if(path.startsWith('/api/instruments')){const symbol=new URL(path,'http://localhost').searchParams.get('symbol');return {ok:true,json:async()=>({symbol,name:symbol,type:'stock',source:'测试资料'})};}
    if(options.body){
      const command=JSON.parse(options.body);
      if(fail)return {ok:false,json:async()=>({error:'保存失败'})};
      if(command.action==='add')items.push({...command.item,enabled:true});
      if(command.action==='remove')items=items.filter(item=>item.symbol!==command.symbol);
      if(command.action==='toggle'){const item=items.find(item=>item.symbol===command.symbol);item.enabled=!item.enabled;}
    }
    return {ok:true,json:async()=>({items:items.map(item=>({...item}))})};
  }};
'''+script+r'''
function listSymbols(){return ids['manager-list'].children.map(row=>row.children[0].textContent);}
async function add(symbol){input.value=symbol;await validateCode();await formElement.emit('submit',{preventDefault(){}});}
function action(symbol,index){return ids['manager-list'].children.find(row=>row.children[0].textContent.startsWith(symbol)).children[1].children[index].emit('click');}
(async()=>{
  await ids['manage-watchlist'].emit('click');
  assert.equal(ids['watchlist-manager'].open,true);
  await add('TSLA');
  assert.equal(ids['watchlist-manager'].open,true);
  assert.equal(reloads,0);
  assert.equal(input.value,'');
  assert.equal(submit.disabled,true);
  assert.match(ids['manager-message'].textContent,/已添加 TSLA/);
  await add('AAPL');
  assert.equal(listSymbols().length,3);
  await action('NVDA',1);
  assert.deepEqual(listSymbols(),['TSLA','AAPL']);
  await action('TSLA',0);
  assert.match(listSymbols()[0],/已暂停/);
  await action('TSLA',0);
  assert.equal(listSymbols()[0],'TSLA');
  assert.equal(ids['watchlist-manager'].open,true);
  assert.equal(reloads,0);
  fail=true;
  await add('AMZN');
  assert.equal(input.value,'AMZN');
  assert.equal(submit.disabled,false);
  assert.equal(ids['watchlist-manager'].open,true);
  assert.match(ids['manager-message'].textContent,/保存失败/);
  await action('AAPL',1);
  assert.equal(listSymbols().length,2);
  assert.equal(reloads,0);
  await ids['close-manager'].emit('click');
  assert.equal(ids['watchlist-manager'].open,false);
  assert.equal(reloads,1);
  await ids['manage-watchlist'].emit('click');
  await ids['close-manager'].emit('click');
  assert.equal(reloads,1);
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
    path = tmp_path / 'subscription-manager.js'
    path.write_text(harness, encoding='utf-8')
    result = subprocess.run([node, str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

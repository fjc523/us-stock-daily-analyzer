"""HTML 站点所用的内联模板。"""

from jinja2 import Environment, select_autoescape


_ENV = Environment(autoescape=select_autoescape(default_for_string=True))

BASE = _ENV.from_string(
    """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ title }} · 美股每日分析</title>
  <style>
    :root { color-scheme:light dark; --bg:#f5f6f8; --panel:#fff; --fg:#202c3b; --muted:#728093; --line:#e5e9ef; --accent:#355edb; --good:#157e63; --warn:#a36b08; --bad:#b45441; --soft:#eef2fc; --shadow:0 4px 24px #202c3b06; }
    @media(prefers-color-scheme:dark) { :root { --bg:#111923; --panel:#1b2532; --fg:#e6edf5; --muted:#9aaabd; --line:#2e3b4b; --accent:#a1b8ff; --good:#65ccaa; --warn:#e6ba68; --bad:#f6a291; --soft:#27354b; --shadow:none; } }
    .source-trigger { display:block; border:0; background:none; padding:3px 0; margin-top:3px; text-align:left; } .source-trigger:hover { background:none; text-decoration:underline; } .source-dialog { width:min(900px,94vw); max-width:94vw; }
    .source-status { font-size:11px; white-space:nowrap; } .source-normal { color:var(--good); } .source-degraded { color:var(--warn); } .source-failed { color:var(--bad); } .source-inactive { color:var(--muted); } .source-dot { display:inline-block; width:7px; height:7px; border-radius:50%; background:currentColor; margin-right:4px; } .source-table { font-size:13px; } .source-table td { overflow-wrap:anywhere; }
    * { box-sizing:border-box; } body { margin:0; background:var(--bg); color:var(--fg); font:14px/1.65 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif; }
    a { color:var(--accent); text-decoration:none; } a:hover { text-decoration:underline; } button,input,select { font:inherit; } button,a,input,select,summary { outline-offset:4px; }
    .topbar { background:var(--panel); border-bottom:1px solid var(--line); } .topbar-inner { max-width:1280px; margin:auto; min-height:58px; padding:12px 30px; display:flex; align-items:center; justify-content:space-between; gap:18px; }
    .brand { display:flex; align-items:center; gap:12px; color:var(--fg); font-weight:700; font-size:17px; letter-spacing:.04em; } .brand-icon { display:grid; place-items:center; width:34px; height:34px; border-radius:10px; background:#243e76; color:#fff; font-size:21px; }
    main { max-width:1280px; margin:auto; padding:18px 30px 36px; } .page-heading { display:flex; align-items:center; justify-content:space-between; gap:14px; margin-bottom:12px; } h1 { font-size:26px; letter-spacing:-.03em; margin:0; line-height:1.3; } h2 { font-size:17px; margin:0; } h3 { font-size:15px; } p { margin:8px 0; }
    .selectors { display:flex; align-items:center; gap:8px; flex-wrap:wrap; } label,.muted { color:var(--muted); } .small { font-size:12px; } select,input { color:var(--fg); background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:7px 10px; min-width:0; }
    button,.button { border:1px solid var(--line); border-radius:8px; background:var(--panel); color:var(--fg); padding:7px 13px; cursor:pointer; display:inline-block; white-space:nowrap; } button:hover,.button:hover { background:var(--soft); text-decoration:none; } .primary { color:#fff; background:#355edb; border-color:#355edb; } .primary:hover { background:#294cbd; } button:disabled { opacity:.55; cursor:wait; }
    .banner { border:1px solid var(--line); background:var(--panel); border-radius:10px; padding:11px 16px; margin-bottom:12px; } .banner h2 { font-size:14px; } .banner p { font-size:12px; margin:2px 0; color:var(--muted); } .banner-running { border-left:3px solid var(--accent); } .banner-failed { border-left:3px solid var(--bad); } .banner-done { border-left:3px solid var(--good); }
    .stats { display:grid; grid-template-columns:repeat(5,1fr); gap:12px; margin-bottom:16px; } .stat { border:1px solid var(--line); background:var(--panel); border-radius:12px; padding:10px 14px; box-shadow:var(--shadow); } .stat-label { color:var(--muted); font-size:12px; } .stat-value { display:block; font-size:25px; font-weight:650; line-height:1.45; font-variant-numeric:tabular-nums; } .stat-caption { font-size:11px; color:var(--muted); }
    .section-heading { display:flex; align-items:center; justify-content:space-between; gap:10px; margin:12px 0 10px; } .section-heading p { margin:2px 0; } .panel,.card { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:18px 22px; margin:14px 0; } .panel h2 { margin:0 0 12px; }
    .table-wrap { overflow:auto; border:1px solid var(--line); border-radius:12px; background:var(--panel); box-shadow:var(--shadow); } table { width:100%; border-collapse:collapse; min-width:650px; } th,td { padding:10px 14px; border-bottom:1px solid var(--line); text-align:left; vertical-align:middle; } th { background:color-mix(in srgb,var(--panel) 50%,var(--bg)); color:var(--muted); font-size:11px; font-weight:500; white-space:nowrap; } tr:last-child td { border-bottom:0; } .watch-table { table-layout:fixed; min-width:0; } .watch-table th:nth-child(1) { width:16%; } .watch-table th:nth-child(2) { width:31%; } .watch-table th:nth-child(3) { width:25%; } .watch-table th:nth-child(4) { width:9%; } .watch-table th:nth-child(5) { width:13%; } .watch-table th:nth-child(6) { width:6%; }
    .symbol { font-size:16px; font-weight:700; color:var(--fg); letter-spacing:.02em; } .subline { display:block; color:var(--muted); font-size:11px; } .advice { font-size:13px; line-height:1.65; margin-top:6px; overflow-wrap:anywhere; } .badge { display:inline-block; padding:2px 9px; border-radius:6px; font-size:12px; font-weight:600; background:var(--soft); color:var(--muted); } .rating-buy,.rating-overweight { color:var(--good); background:color-mix(in srgb,var(--good) 10%,var(--panel)); } .rating-hold { background:var(--soft); color:var(--fg); } .rating-underweight,.rating-sell { color:var(--bad); background:color-mix(in srgb,var(--bad) 10%,var(--panel)); } .rating-review { color:var(--muted); }
    .positive { color:var(--good); } .negative,.error { color:var(--bad); } .relative-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:6px; margin-top:6px; font-variant-numeric:tabular-nums; } .relative-grid span { font-size:13px; font-weight:600; } .relative-grid small { display:block; font-size:10px; font-weight:400; color:var(--muted); } .relative-grid .focus { background:var(--soft); border-radius:6px; padding:2px 6px; margin:-2px -6px; } .number { font-variant-numeric:tabular-nums; white-space:nowrap; font-weight:550; } .premarket-price { display:block; }
    .watch-table .analysis-price { min-width:0; white-space:normal; overflow-wrap:anywhere; } .analysis-price .quote-reason { display:block; }
    .allocation { font-size:12px; font-weight:600; margin-top:7px; } .price-plans { margin:6px 0 0; font-size:12px; line-height:1.6; } .price-plans > div { display:grid; grid-template-columns:4.5em 1fr; gap:5px; margin-top:4px; } .price-plans dt { color:var(--muted); } .price-plans dd { margin:0; overflow-wrap:anywhere; } .execution-details { padding:0; border:0; } .execution-details summary { cursor:pointer; } .execution-full { white-space:pre-wrap; margin-top:5px; } .allocation-note { font-size:12px; line-height:1.7; border-left:3px solid var(--line); padding:7px 12px; margin:12px 0; color:var(--muted); }
    .comparison + .comparison { margin-top:10px; padding-top:10px; border-top:1px solid var(--line); } .comparison-trigger { display:block; width:100%; border:0; padding:0; background:none; text-align:left; color:var(--fg); } .comparison-trigger:hover { color:var(--accent); background:none; } .comparison-title { display:flex; flex-wrap:wrap; justify-content:space-between; gap:4px; font-size:12px; } .comparison-dialog { width:min(900px,94vw); max-width:94vw; } .relative-chart { display:block; width:100%; height:auto; max-height:45vh; } .relative-chart text { fill:var(--muted); font-size:12px; } .chart-grid { stroke:var(--line); } .chart-baseline { stroke:var(--muted); stroke-dasharray:4 4; opacity:.6; } .stock-line { stroke:var(--accent); color:var(--accent); } .benchmark-line { stroke:#cf8a32; color:#cf8a32; } .chart-legend { display:flex; gap:20px; font-size:13px; } .chart-legend span::before { content:'━ '; } .relative-chart polyline { fill:none; stroke-width:2.5; } .chart-dot { fill:transparent; stroke:none; }
    @media(max-width:800px) { .watch-heading { flex-direction:column; align-items:flex-start; gap:12px; } .watch-heading .manager-actions { flex-wrap:wrap; } }
    .marks { display:flex; flex-wrap:wrap; gap:5px; margin-top:8px; } .mark { font-size:11px; color:var(--muted); border:1px solid var(--line); border-radius:5px; padding:1px 5px; } details { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:14px 18px; margin:10px 0; } summary { cursor:pointer; font-weight:550; } .row-details { padding:0; border:0; margin:4px 0; background:transparent; font-size:11px; } .row-details summary { color:var(--muted); font-weight:400; } .row-details p { overflow-wrap:anywhere; } .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(260px,100%),1fr)); gap:12px; }
    .markdown { overflow-x:auto; overflow-wrap:anywhere; max-width:920px; } .markdown p { margin:12px 0; } .markdown h2 { margin-top:24px; } .markdown table { min-width:0; font-size:13px; } .markdown pre { overflow:auto; padding:12px; background:var(--bg); border-radius:8px; } .markdown code { font-family:ui-monospace,SFMono-Regular,monospace; } .time-list { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(270px,100%),1fr)); gap:8px 20px; font-size:12px; } .empty { padding:32px 20px; color:var(--muted); text-align:center; }
    footer { max-width:1280px; margin:auto; padding:18px 30px; border-top:1px solid var(--line); color:var(--muted); font-size:11px; } dialog { width:min(650px,calc(100vw - 28px)); max-height:85vh; overflow:auto; border:1px solid var(--line); border-radius:16px; background:var(--panel); color:var(--fg); padding:24px; box-shadow:0 20px 90px #0003; } dialog::backdrop { background:#0d1c3e66; } .form-grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin:16px 0; } .form-grid label { font-size:12px; display:flex; flex-direction:column; gap:5px; } .manager-row { display:flex; gap:8px; justify-content:space-between; align-items:center; border-bottom:1px solid var(--line); padding:10px 0; } .manager-actions { display:flex; gap:5px; } .manager-actions button { font-size:12px; padding:4px 8px; } .toast { min-height:20px; font-size:12px; } [hidden] { display:none !important; } .analyze-button { display:block; font-size:11px; padding:4px 6px; margin-top:8px; white-space:nowrap; } button:disabled { opacity:.55; cursor:wait; }
    .mobile-label { display:none; }
    .analysis-progress { font-size:11px; line-height:1.7; overflow-wrap:anywhere; color:var(--accent); }
    .analysis-progress progress { display:block; width:100%; height:5px; margin:5px 0; accent-color:var(--accent); }
    @media(max-width:950px) { .topbar-inner,main { padding-left:18px; padding-right:18px; } .stats { gap:8px; } .stat { padding:12px; } .stat-value { font-size:21px; } .selectors label { display:none; } }
    @media(max-width:800px) { .topbar-inner { align-items:flex-start; flex-direction:column; gap:12px; } .stats { grid-template-columns:repeat(2,1fr); } .stat:first-child { grid-column:1/-1; } .page-heading { align-items:flex-start; } h1 { font-size:23px; } .watch-table { min-width:0; table-layout:auto; } .mobile-label { display:block; } .watch-table thead { display:none; } .watch-table tbody,.watch-table tr { display:block; } .watch-table tr { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); padding:15px; gap:10px; border-bottom:1px solid var(--line); } .watch-table td { border:0; padding:0; } .watch-table td:nth-child(2) { grid-column:1/-1; grid-row:2; } .watch-table td:nth-child(3) { grid-column:1/-1; grid-row:3; } .watch-table td:nth-child(4) { grid-column:2; grid-row:1; text-align:right; } .watch-table td:nth-child(5) { grid-column:1; } .watch-table td:nth-child(6) { grid-column:2; text-align:right; } .relative-grid { max-width:320px; } .form-grid { grid-template-columns:1fr; } }
  </style>
</head>
<body>
<header class="topbar"><div class="topbar-inner">
  <a class="brand" href="{{ root_prefix }}index.html"><span class="brand-icon" aria-hidden="true">↗</span> 美股每日研判</a>
  <nav class="selectors" aria-label="报告选择"><label for="date-select">历史报告</label><select id="date-select" aria-label="交易日"></select><select id="symbol-select" aria-label="标的"></select></nav>
</div></header>
<main>
  <div class="page-heading"><h1>{{ title }}</h1>{% if root_prefix %}<a class="button" href="{{ root_prefix }}index.html">自选首页</a>{% endif %}</div>
  <p class="small muted" data-display-timezone>页面时刻均为北京时间（YYYY-MM-DD HH:MM:SS）；交易日、日线日期及市场时段保持原口径。</p>
  {{ body|safe }}
</main>
<footer>仅供个人研究参考，不构成投资建议。</footer>
<script>
(function (global) {
  "use strict";
  const site = {{ ui_data|tojson }};
  function dateInZone(instant, zone) {
    const parts = new Intl.DateTimeFormat("en-US", {timeZone:zone,year:"numeric",month:"2-digit",day:"2-digit"}).formatToParts(instant);
    const values = Object.fromEntries(parts.map(part => [part.type, part.value]));
    return values.year + "-" + values.month + "-" + values.day;
  }
  function timeInZone(instant, zone) {
    const parts = new Intl.DateTimeFormat("en-US", {timeZone:zone,hour:"2-digit",minute:"2-digit",hourCycle:"h23"}).formatToParts(instant);
    const values = Object.fromEntries(parts.map(part => [part.type, part.value]));
    return Number(values.hour) * 60 + Number(values.minute);
  }
  function prettyTime(value) {
    if (value == null || value === "") return "—";
    const text = String(value).trim();
    const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(text);
    const match = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})(?::(\d{2})(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/.exec(text);
    if (!dateOnly && !match) return ["未提供","未核验","真实时段时间未知","来源时点未提供","—"].includes(text) ? text : "时间未核验";
    const day = new Date((dateOnly ? text : match[1]) + "T00:00:00Z");
    if (Number.isNaN(day.getTime()) || day.toISOString().slice(0,10) !== (dateOnly ? text : match[1])) return "时间未核验";
    if (dateOnly) return text;
    if (Number(match[2].slice(0,2)) > 23 || Number(match[2].slice(3)) > 59 || Number(match[3] || 0) > 59) return "时间未核验";
    const instant = new Date(match[1] + "T" + match[2] + ":" + (match[3] || "00") + (match[4] || "") + match[5]);
    if (Number.isNaN(instant.getTime())) return "时间未核验";
    const parts = new Intl.DateTimeFormat("en-US", {timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",second:"2-digit",hourCycle:"h23"}).formatToParts(instant);
    const values = Object.fromEntries(parts.map(part => [part.type, part.value]));
    return values.year + "-" + values.month + "-" + values.day + " " + values.hour + ":" + values.minute + ":" + values.second;
  }
  function elapsed(started, now) {
    const start = new Date(started).getTime();
    if (!Number.isFinite(start)) return "";
    const minutes = Math.max(0, Math.floor((now.getTime()-start)/60000));
    return "已用 " + Math.floor(minutes/60) + " 小时 " + (minutes%60) + " 分钟";
  }
  function errorSummary(value) {
    if (value && typeof value === "object") {
      const category = value.category || value.kind || value.code || value.error_type;
      const reason = value.message || value.error || value.detail;
      const summary = [category, reason].filter(Boolean).join("：");
      return summary || JSON.stringify(value);
    }
    return String(value || "");
  }
  function errorHint(error) {
    const value = String(error || "").toLowerCase();
    if (value.includes("login") || value.includes("登录")) return "请执行 codex login，完成登录后重试。";
    if (value.includes("quota") || value.includes("额度")) return "请检查 Codex 额度与订阅状态后手动重跑。";
    if (value.includes("model") || value.includes("模型") || value.includes("fatal_config")) return "请执行 npm install -g @openai/codex@latest 后重试。";
    return "请查看对应批次日志中的错误原因，再手动重跑。";
  }
  function bannerState(payload, nowValue) {
    const now = nowValue instanceof Date ? nowValue : new Date(nowValue);
    const today = dateInZone(now, payload.market_timezone || "America/New_York");
    const run = payload.last_run || {};
    const event = payload.last_schedule_event || {};
    const eventToday = (event.trade_date || "") === today;
    const runToday = (run.trade_date || run.date || "") === today;
    if (runToday) {
      const status = run.status;
      const progress = run.progress || {};
      const counts = String(progress.completed ?? run.completed ?? 0) + "/" + String(progress.total ?? run.total ?? 0);
      const started = prettyTime(run.started_at);
      if (status === "running") return {kind:"running",title:"今日运行中 " + counts,detail:started + "；" + elapsed(run.started_at, now) + (run.estimated_finish_at ? "；预计完成 " + prettyTime(run.estimated_finish_at) : "")};
      if (status === "completed") return {kind:"done",title:"今日已完成",detail:started + (run.finished_at ? "；结束 " + prettyTime(run.finished_at) : "")};
      if (status === "partial") return {kind:"failed",title:"今日部分失败",detail:errorSummary(run.last_error) || "部分标的未完成"};
      if (status === "failed" || status === "interrupted") {
        const error = errorSummary(run.last_error) || (status === "interrupted" ? "运行中断" : "运行失败");
        return {kind:"failed",title:"今日失败",detail:error + "。" + errorHint(error)};
      }
    }
    const sessions = payload.trading_days || [];
    const insideCalendar = today >= (payload.calendar_start || "0000-00-00") && today <= (payload.calendar_end || "9999-99-99");
    const isSession = insideCalendar ? sessions.includes(today) : ![0,6].includes(new Date(today + "T12:00:00Z").getUTCDay());
    if (!isSession) return {kind:"done",title:"今日非交易日",detail:"NYSE 今日休市。"};
    const anchor = String(payload.anchor_time || "08:30").split(":").map(Number);
    const afterWarning = timeInZone(now, payload.market_timezone || "America/New_York") >= anchor[0]*60+anchor[1]+15;
    let detail = "尚未记录今日运行。";
    if (afterWarning && !eventToday) detail = "今日尚未运行，请检查电脑是否开机、已登录且已唤醒。";
    else if (afterWarning && eventToday) detail = "今日已有调度记录，但尚无运行结果。";
    else detail = "尚未到美东锚点之后 15 分钟。";
    return {kind:"pending",title:"今日尚未运行",detail:detail};
  }
  global.dailyAnalyzerBannerState = bannerState;
  global.dailyAnalyzerPrettyTime = prettyTime;
  if (!global.document) return;
  const banner = global.document.getElementById("status-banner");
  if (banner) {
    const state = bannerState(site.banner || {}, new Date());
    banner.className = "banner banner-" + state.kind;
    banner.querySelector("h2").textContent = state.title;
    banner.querySelector("p[data-role=detail]").textContent = state.detail;
    const event = (site.banner || {}).last_schedule_event;
    const eventLine = banner.querySelector("p[data-role=event]");
    if (event && event.result && eventLine) {
      const labels = {started:"开始运行",recovery_started:"恢复运行",skipped_not_trading_day:"非交易日，跳过",skipped_before_anchor:"未到锚点，跳过",skipped_after_close:"已收盘，跳过",skipped_already_done:"今日已运行，跳过"};
      eventLine.textContent = prettyTime(event.at) + " 调度：" + (labels[event.result] || event.result || "已记录") + (event.reason ? "（"+event.reason+"）" : "");
    }
  }
  const byDate = site.index || [];
  const dateSelect = global.document.getElementById("date-select");
  const symbolSelect = global.document.getElementById("symbol-select");
  function fillSymbols() {
    const selected = byDate.find(item => item.date === dateSelect.value);
    symbolSelect.innerHTML = "";
    const overview = global.document.createElement("option");
    overview.value = ""; overview.textContent = "当日总览"; symbolSelect.appendChild(overview);
    (selected ? selected.items : []).forEach(item => { const option=global.document.createElement("option"); option.value=item.symbol; option.textContent=item.label; symbolSelect.appendChild(option); });
  }
  if (dateSelect && symbolSelect) {
    byDate.forEach(item => { const option=global.document.createElement("option"); option.value=item.date; option.textContent=item.date; dateSelect.appendChild(option); });
    dateSelect.value = site.selected_date || (byDate[0] ? byDate[0].date : "");
    fillSymbols();
    if (site.selected_symbol) symbolSelect.value = site.selected_symbol;
    dateSelect.addEventListener("change", function(){
      fillSymbols();
      const selected = byDate.find(item => item.date === dateSelect.value);
      global.location.href = site.root_prefix + (selected ? selected.overview_path : "index.html");
    });
    symbolSelect.addEventListener("change", function(){
      const selected = byDate.find(item => item.date === dateSelect.value);
      const item = selected && selected.items.find(entry => entry.symbol === symbolSelect.value);
      const target = item ? item.path : (selected ? selected.overview_path : "index.html");
      global.location.href = site.root_prefix + target;
    });
  }
  // 必须从背景按下并在背景释放，内部空白、边框和向外拖动都不关闭。
  global.document.querySelectorAll("dialog").forEach(dialog=>{
    let backdropPointer=null, backdropClick=false;
    function outside(event){
      const rect=dialog.getBoundingClientRect();
      return event.target===dialog && (event.clientX<rect.left || event.clientX>rect.right || event.clientY<rect.top || event.clientY>rect.bottom);
    }
    function reset(){backdropPointer=null;backdropClick=false;}
    dialog.addEventListener("pointerdown",event=>{
      reset();
      if(dialog.open && event.isPrimary!==false && event.button===0 && outside(event)){
        backdropPointer=event.pointerId;
        // 避免背景按下先让输入失焦，继而触发未提交代码的资料验证。
        event.preventDefault();
      }
    });
    dialog.addEventListener("pointerup",event=>{
      backdropClick=backdropPointer===event.pointerId && outside(event);
      backdropPointer=null;
    });
    dialog.addEventListener("pointercancel",reset);
    dialog.addEventListener("close",reset);
    dialog.addEventListener("click",event=>{
      const shouldClose=dialog.open && backdropClick && event.detail>0 && outside(event);
      reset();
      if(shouldClose)dialog.close();
    });
  });
  global.document.querySelectorAll("[data-comparison]").forEach(button=>button.addEventListener("click",()=>{
    button.closest(".comparison").querySelector("dialog").showModal();
  }));
  global.document.querySelectorAll("[data-close-comparison]").forEach(button=>button.addEventListener("click",()=>{
    button.closest("dialog").close();
  }));
  global.document.querySelectorAll("[data-source-open]").forEach(button=>button.addEventListener("click",()=>{
    global.document.getElementById(button.dataset.sourceOpen).showModal();
  }));
  global.document.querySelectorAll("[data-source-close]").forEach(button=>button.addEventListener("click",()=>{
    button.closest("dialog").close();
  }));
  {% if managed %}
  const manager = global.document.getElementById("watchlist-manager");
  const form = global.document.getElementById("watchlist-form");
  const message = global.document.getElementById("manager-message");
  let managerChanged = false;
  async function api(data, path="/api/watchlist") {
    const response = await global.fetch(path, data ? {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)} : {});
    const value = await response.json();
    if (!response.ok) throw new Error(value.error || "保存失败，请重试。");
    return value;
  }
  function renderManager(value) {
      const list = global.document.getElementById("manager-list");
      list.replaceChildren();
      value.items.forEach(item => {
        const row = global.document.createElement("div"); row.className="manager-row";
        const label=global.document.createElement("span"); label.textContent=item.symbol+(item.name?" · "+item.name:"")+(item.enabled?"":"（已暂停）"); row.appendChild(label);
        const actions=global.document.createElement("div"); actions.className="manager-actions";
        [[item.enabled?"暂停":"恢复","toggle"],["移除","remove"]].forEach(([text,action])=>{
          const button=global.document.createElement("button"); button.type="button"; button.textContent=text;
          button.addEventListener("click",async()=>{
            button.disabled=true;
            try {
              const value = await api({action,symbol:item.symbol});
              managerChanged = true;
              renderManager(value);
              message.className = "toast";
              message.textContent = "已"+(action==="remove"?"移除":item.enabled?"暂停":"恢复")+" "+item.symbol;
            }
            catch(error) { message.className="error toast"; message.textContent=error.message; button.disabled=false; }
          }); actions.appendChild(button);
        }); row.appendChild(actions); list.appendChild(row);
      });
  }
  async function showManager() {
    message.textContent = "";
    message.className = "error toast";
    manager.showModal();
    try { renderManager(await api()); }
    catch(error) { message.textContent=error.message; }
  }
  global.document.getElementById("manage-watchlist").addEventListener("click", showManager);
  global.document.getElementById("close-manager").addEventListener("click",()=>manager.close());
  manager.addEventListener("close",()=>{
    global.clearTimeout(validationTimer); ++validationVersion;
    if(managerChanged){managerChanged=false;global.location.reload();}
  });
  const codeInput=form.elements.symbol, typeInput=form.elements.type;
  const typeField=global.document.getElementById("type-field");
  const identityMessage=global.document.getElementById("identity-message");
  const submitButton=form.querySelector("button[type=submit]");
  let verified=null, validationTimer=null, validationVersion=0;
  function codeValue(){return codeInput.value.trim().toUpperCase();}
  function allowSubmit(){submitButton.disabled=!(verified && verified.symbol===codeValue() && (verified.type || typeInput.value));}
  async function validateCode(){
    if(!manager.open) return;
    const code=codeValue(), version=++validationVersion;
    verified=null; allowSubmit(); typeField.hidden=true; typeInput.value="";
    if(!code){identityMessage.textContent="输入代码后自动验证和识别类型";return;}
    identityMessage.textContent="正在验证 "+code+"…";
    try {
      const value=await api(null,"/api/instruments?symbol="+encodeURIComponent(code));
      if(version!==validationVersion || code!==codeValue()) return;
      verified=value; typeField.hidden=!!value.type;
      const types={stock:"个股",etf:"ETF",index:"指数"};
      identityMessage.textContent=value.symbol+" · "+value.name+" · "+(types[value.type]||"代码有效，请选择类型")+"（"+value.source+"）";
      if(value.type) typeInput.value=value.type;
      allowSubmit();
    } catch(error){
      if(version===validationVersion && code===codeValue()) identityMessage.textContent=error.message;
    }
  }
  codeInput.addEventListener("input",()=>{
    ++validationVersion; verified=null; submitButton.disabled=true; typeField.hidden=true;
    identityMessage.textContent="等待验证…"; global.clearTimeout(validationTimer);
    validationTimer=global.setTimeout(validateCode,500);
  });
  codeInput.addEventListener("blur",()=>{if(manager.open && !verified){global.clearTimeout(validationTimer);validateCode();}});
  typeInput.addEventListener("change",allowSubmit);
  form.addEventListener("submit",async event=>{
    event.preventDefault();
    if(!verified || verified.symbol!==codeValue()) return;
    submitButton.disabled=true;
    const item=Object.fromEntries(new FormData(form));
    Object.keys(item).forEach(key=>{if(!item[key].trim()) delete item[key];});
    item.symbol=verified.symbol;
    try {
      const value = await api({action:"add",item});
      managerChanged = true;
      renderManager(value);
      form.reset(); ++validationVersion; verified=null;
      global.clearTimeout(validationTimer);
      typeField.hidden=true; typeInput.value=""; allowSubmit();
      identityMessage.textContent="输入代码后自动验证和识别类型";
      message.className="toast";
      message.textContent="已添加 "+item.symbol+"，可继续管理订阅";
    }
    catch(error) { message.className="error toast"; message.textContent=error.message; allowSubmit(); }
  });
  const settingsDialog=global.document.getElementById("settings-manager");
  const settingsForm=global.document.getElementById("settings-form");
  const settingsMessage=global.document.getElementById("settings-message");
  global.document.getElementById("manage-settings").addEventListener("click",async()=>{
    settingsDialog.showModal();settingsMessage.textContent="正在读取参数…";
    settingsForm.querySelector("button[type=submit]").disabled=true;
    try {
      const value=await api(null,"/api/settings");
      ["quick","deep"].forEach(role=>{
        const modelSelect=settingsForm.elements[role+"_model"];
        modelSelect.replaceChildren();
        value.models.forEach(model=>{
          const option=global.document.createElement("option");option.value=model.id;option.textContent=model.name+" · "+model.id;modelSelect.appendChild(option);
        });
        modelSelect.value=value.llm[role].model;
        function fillEfforts(preferred){
          const model=value.models.find(item=>item.id===modelSelect.value);
          const effortSelect=settingsForm.elements[role+"_effort"];effortSelect.replaceChildren();
          if(!model){
            const option=global.document.createElement("option");option.value="";option.textContent="原配置 "+value.llm[role].model+" 不在当前目录，请选择";option.selected=true;modelSelect.prepend(option);
            return;
          }
          model.reasoning_efforts.forEach(effort=>{
            const option=global.document.createElement("option");option.value=effort;option.textContent=effort;effortSelect.appendChild(option);
          });
          effortSelect.value=model.reasoning_efforts.includes(preferred)?preferred:model.default_effort;
        }
        fillEfforts(value.llm[role].reasoning_effort);
        modelSelect.onchange=()=>fillEfforts(settingsForm.elements[role+"_effort"].value);
      });
      global.document.getElementById("model-source").textContent=value.source+"；更新时间 "+prettyTime(value.updated_at);
      settingsForm.elements.parallel.value=value.run.max_parallel_tickers;
      settingsForm.elements.calls.value=value.llm.max_concurrent_calls;
      settingsMessage.textContent="";settingsForm.querySelector("button[type=submit]").disabled=false;
    } catch(error){settingsMessage.textContent=error.message;}
  });
  global.document.getElementById("close-settings").addEventListener("click",()=>settingsDialog.close());
  settingsForm.addEventListener("submit",async event=>{
    event.preventDefault();const button=settingsForm.querySelector("button[type=submit]");button.disabled=true;
    const fields=settingsForm.elements;
    const value={llm:{quick:{model:fields.quick_model.value.trim(),reasoning_effort:fields.quick_effort.value},
                     deep:{model:fields.deep_model.value.trim(),reasoning_effort:fields.deep_effort.value},
                     max_concurrent_calls:Number(fields.calls.value)},run:{max_parallel_tickers:Number(fields.parallel.value)}};
    try {await api(value,"/api/settings");global.location.reload();}
    catch(error){settingsMessage.textContent=error.message;button.disabled=false;}
  });
  const analysisMessage=global.document.getElementById("analysis-message");
  const analysisButtons=[...global.document.querySelectorAll("[data-analyze]")];
  const analyzeAll=global.document.getElementById("analyze-all");
  let polling=false;
  let analysisTimer;
  const rowErrors=new Map();
  const seenRejections=new Set();
  const allError=global.document.getElementById("analysis-all-error");
  function durationText(seconds){
    seconds=Math.max(0,Math.floor(seconds || 0));
    return seconds<60?seconds+"秒":Math.floor(seconds/60)+"分"+(seconds%60?seconds%60+"秒":"");
  }
  function renderAnalysis(value){
    if(!value.busy)rowErrors.clear();
    (value.append_rejections || []).forEach(rejection=>{
      if(!seenRejections.has(rejection.request_id)){
        seenRejections.add(rejection.request_id);
        if(value.busy)rowErrors.set(rejection.symbol,rejection.reason);
      }
    });
    if(analyzeAll){analyzeAll.disabled=false;analyzeAll.textContent=value.busy?"追加其余订阅":"全部分析一次";}
    const active=new Set(value.active_symbols || (value.busy && value.symbol?[value.symbol]:[]));
    analysisButtons.forEach(button=>{
      const symbol=button.dataset.analyze;
      button.disabled=active.has(symbol);
      const status=((value.items || {})[symbol] || {}).status;
      button.textContent=button.disabled?(status==="pending"?"排队中":"分析中…"):(value.busy?"加入本批":"分析一次");
      const row=button.closest("tr");
      const box=row.querySelector("[data-analysis-progress]");
      const errorBox=row.querySelector("[data-analysis-error]");
      if(errorBox){errorBox.hidden=!rowErrors.has(symbol);errorBox.textContent=rowErrors.get(symbol) || "";}
      row.querySelector("[data-report-summary]").hidden=button.disabled;
      box.hidden=!button.disabled;
      if(!button.disabled)return;
      const item=(value.items || {})[symbol] || {stage:"正在启动",elapsed_seconds:0};
      const percent=item.estimated_percent;
      box.querySelector("[data-stage]").textContent=item.stage+(percent!=null?" · 预计 "+percent+"%":"");
      const bar=box.querySelector("progress");
      if(percent==null)bar.removeAttribute("value");else bar.value=percent;
      box.querySelector("[data-remaining]").textContent="已用 "+durationText(item.elapsed_seconds)+" · "+
        (item.overdue?"已超预计，仍在执行":item.remaining_seconds!=null?"剩余约 "+durationText(item.remaining_seconds):"暂无耗时估计");
      box.title=item.estimate_samples?item.estimate_source+"，参考 "+item.estimate_samples+" 次成功分析":"暂无成功历史样本";
      box.querySelector("[data-estimate-note]").textContent=item.estimate_source==="其他配置参考"?"参考配置不同，耗时可能有偏差":"";
    });
  }
  async function analysisStatus(){
    global.clearTimeout(analysisTimer);
    try {
      const value=await api(null,"/api/analysis");
      renderAnalysis(value);
      const progress=value.run && value.run.progress;
      analysisMessage.textContent=value.busy?"批次进度"+(progress?" · "+progress.completed+"/"+progress.total:""):"";
      if(value.busy){polling=true;analysisTimer=global.setTimeout(analysisStatus,3000);}
      else if(polling){
        const openDialog=global.document.querySelector("dialog[open]");
        if(openDialog) analysisTimer=global.setTimeout(analysisStatus,3000);
        else {polling=false;global.location.reload();}
      }
    } catch(error){analysisMessage.textContent=error.message;analysisTimer=global.setTimeout(analysisStatus,3000);}
  }
  analysisButtons.forEach(button=>button.addEventListener("click",async()=>{
    rowErrors.delete(button.dataset.analyze);
    const errorBox=button.closest("tr").querySelector("[data-analysis-error]");
    if(errorBox)errorBox.hidden=true;
    button.disabled=true;button.textContent="正在提交…";
    try {
      const value=await api({symbol:button.dataset.analyze},"/api/analysis");
      renderAnalysis(value);polling=true;analysisStatus();
    } catch(error){
      button.disabled=false;button.textContent="分析一次";
      rowErrors.set(button.dataset.analyze,error.message);
      if(errorBox){errorBox.hidden=false;errorBox.textContent=error.message;}
      await analysisStatus();
    }
  }));
  if(analyzeAll)analyzeAll.addEventListener("click",async()=>{
    if(allError)allError.textContent="";
    analyzeAll.disabled=true;analyzeAll.textContent="正在提交…";
    try {
      const value=await api({scope:"all"},"/api/analysis");
      renderAnalysis(value);polling=true;analysisStatus();
    } catch(error){
      await analysisStatus();if(allError)allError.textContent=error.message;
    }
  });
  analysisStatus();
  {% endif %}
  if (site.refresh_seconds > 0) {
    function refresh() {
      const openDialog=global.document.querySelector("dialog[open]");
      if (openDialog) global.setTimeout(refresh, 10000);
      else global.location.reload();
    }
    global.setTimeout(refresh, site.refresh_seconds*1000);
  }
})(typeof window === "undefined" ? globalThis : window);
</script>
</body>
</html>"""
)

# 汇总表与市场补充共用模板，首页优先显示订阅结论。
_SOURCE_STATUS = """{% macro source_badge(value) -%}
<span class="source-status source-{{ value.tone }}">{% if value.legacy %}来源未记录{% else %}<span class="source-dot" aria-hidden="true"></span>适用 {{ value.total }} 项：正常 {{ value.normal }} · 降级 {{ value.degraded }} · 失败 {{ value.failed }} · 跳过 {{ value.skipped }}<span class="subline">未启用 {{ value.inactive }} · 不适用 {{ value.unused }}{% if value.unknown %} · 状态未识别 {{ value.unknown }}{% endif %}</span>{% endif %}</span>
{%- endmacro %}
{% macro source_table(value) -%}
{% if value.legacy %}<p class="small muted">旧报告未记录数据源状态</p>{% else %}<p class="small muted">未启用：{{ value.inactive_categories or '无' }}；全部来源明细保留。</p><div class="table-wrap"><table class="source-table"><thead><tr><th>类别</th><th>使用来源</th><th>状态</th><th>说明</th></tr></thead><tbody>{% for source in value.rows %}<tr><td>{{ source.category }}</td><td>{{ source.source }}</td><td><span class="source-status source-{{ source.tone }}"><span class="source-dot" aria-hidden="true"></span>{{ source.status }}</span></td><td>{{ source.reason or '—' }}</td></tr>{% endfor %}</tbody></table></div>{% endif %}
{%- endmacro %}
{% macro source_details(value, id) -%}
<button type="button" class="source-trigger" data-source-open="{{ id }}" aria-haspopup="dialog">{{ source_badge(value) }} <span aria-hidden="true">›</span></button>
{%- endmacro %}
{% macro source_dialog(value, id) -%}
<dialog id="{{ id }}" class="source-dialog" aria-labelledby="{{ id }}-title"><div class="section-heading" style="margin-top:0"><h2 id="{{ id }}-title">数据源使用详情</h2><button type="button" data-source-close>关闭</button></div>{{ source_table(value) }}</dialog>
{%- endmacro %}
"""

_ROWS = """
{% if rows %}<div class="table-wrap"><table class="watch-table" aria-label="自选建议与相对基准强弱"><thead><tr><th>订阅标的</th><th>总体建议与点位</th><th>相对基准 · 百分点</th><th>分析时价格</th><th>报告状态</th><th></th></tr></thead><tbody>
{% for row in rows %}<tr>
  <td>{% if row.path %}<a class="symbol" href="{{ row.path }}">{{ row.symbol }}</a>{% else %}<span class="symbol">{{ row.symbol }}</span>{% endif %}<span class="subline">{{ row.name }}{% if row.name %} · {% endif %}{{ row.type }}</span>{% if row.proxy %}<span class="subline">以 {{ row.proxy }} 代理</span>{% endif %}</td>
  <td><span class="badge {{ row.rating_class }}">{{ row.rating }}</span><div class="advice">{{ row.advice }}</div><div class="allocation">{{ row.allocation }}</div><dl class="price-plans">{% for plan in row.plans %}<div><dt>{{ plan.label }}</dt><dd><details class="execution-details"><summary>{{ plan.text }}</summary><div class="execution-full">{{ plan.full_text }}</div></details></dd></div>{% endfor %}</dl>{% if row.matrix_note %}<small class="muted">{{ row.matrix_note }}</small>{% endif %}</td>
  <td>{% for comp in row.comparisons %}<div class="comparison"><button type="button" class="comparison-trigger" data-comparison aria-label="查看{{ row.symbol }}相对{{ comp.symbol }}归一化走势"><span class="comparison-title"><strong>{{ comp.kind }} · {{ comp.name }} {{ comp.symbol }} ↗</strong><span class="{{ comp.tone }}">{{ comp.strength }}</span></span><span class="relative-grid">{% for days in ['5','20','60'] %}<span class="{{ comp.relative[days].tone }}{% if days == '20' %} focus{% endif %}"><small>{{ days }} 日</small>{{ comp.relative[days].text }}</span>{% endfor %}</span></button><span class="subline">{% if row.comparisons_supplement %}补充 · {% endif %}{{ comp.reason }}</span>
    <dialog class="comparison-dialog"><div class="section-heading" style="margin-top:0"><h2>{{ row.symbol }} / {{ comp.name }} {{ comp.symbol }}</h2><button type="button" data-close-comparison>关闭</button></div>
    {% if comp.chart %}<p class="small muted">最近60个交易日 · {{ comp.chart.start }} 至 {{ comp.chart.end }} · {{ comp.chart.count }}个共同有效收盘点。两条复权曲线从共同首日100开始，显示累计相对表现。这里的100是价格指数，不是仓位比例。</p><div class="chart-legend"><span class="stock-line">{{ row.symbol }}</span><span class="benchmark-line">{{ comp.symbol }}</span></div><svg class="relative-chart" viewBox="0 0 640 295" role="img" aria-label="{{ row.symbol }}与{{ comp.symbol }}复权归一化走势图"><title>共同首日为100的复权收盘价对比</title>{% for tick in comp.chart.ticks %}<line class="chart-grid" x1="58" x2="618" y1="{{ tick.y }}" y2="{{ tick.y }}"/><text x="48" y="{{ tick.y }}" text-anchor="end">{{ tick.text }}</text>{% endfor %}<line class="chart-baseline" x1="58" x2="618" y1="{{ comp.chart.baseline_y }}" y2="{{ comp.chart.baseline_y }}"/>{% for series in comp.chart.series %}<polyline class="{{ series.color }}" points="{{ series.points }}"/>{% for dot in series.dots %}<circle class="chart-dot" cx="{{ dot.x }}" cy="{{ dot.y }}" r="6"><title>{{ dot.tip }}</title></circle>{% endfor %}{% endfor %}<text x="58" y="280">{{ comp.chart.start }}</text><text x="618" y="280" text-anchor="end">{{ comp.chart.end }}</text></svg><p class="small muted">来源：{{ comp.chart.sources }}。{% if row.comparisons_supplement %}本图为后补比较，原评级未重算。{% endif %}</p>{% else %}<p class="muted">图表数据不足；没有截至该报告日的共同有效日线。旧报告可在下次分析时生成曲线。</p>{% endif %}</dialog></div>{% else %}<span class="muted">{{ row.strength }}</span>{% endfor %}</td>
  <td class="number analysis-price"{% if row.premarket_title %} title="{{ row.premarket_title }}"{% endif %}><span class="mobile-label subline">分析时价格</span>{% if row.premarket_price %}<span class="premarket-price">{{ row.premarket_price }}</span>{{ row.premarket }}{% if row.premarket != "—" %}<small class="subline">相对P收盘</small>{% endif %}<small class="subline">{{ row.quote_time }}</small>{% else %}<span class="small muted quote-reason">{{ row.quote_reason }}</span>{% endif %}{% if row.quote_quality %}<details class="row-details" data-quote-quality><summary>决策日线与扩展参考</summary><p>决策日线：{{ row.quote_quality.decision.status }} · P_Close {{ row.quote_quality.decision.price or '未提供' }} · {{ row.quote_quality.decision.date or '日期未知' }} · {{ row.quote_quality.decision.source or '来源未知' }}</p>{% for quote in row.quote_quality.references %}<p>{{ quote.label }}仅参考：{{ quote.display_price if quote.display_price is not none else '无有效价' }} · {{ quote.quote_time }} · {{ quote.source or '来源未知' }} · {{ quote.display_status }}{% if quote.display_warning %} · {{ quote.display_warning }}{% endif %}<span class="subline">{{ quote.volume_label }} {{ quote.volume_value if quote.volume_value is not none else '未提供' }}；{{ quote.range_label }} {{ quote.high if quote.high is not none else '—' }}/{{ quote.low if quote.low is not none else '—' }}</span></p>{% endfor %}</details>{% endif %}</td>
  <td><span data-report-summary><span class="small">{{ row.status }}</span><span class="subline">{{ row.duration }}</span></span>{% if managed %}<div class="analysis-progress" data-analysis-progress hidden role="status"><span data-stage></span><progress max="100"></progress><span class="subline" data-remaining></span><span class="subline" data-estimate-note></span></div>{% endif %}<span class="subline">{% if row.date != '—' %}{{ row.date }} 报告{% if row.start_clock %} · {{ row.start_clock }}{% endif %}{% endif %}</span><details class="row-details" data-report-details><summary{% if row.report_brief and row.report_brief.startswith('重大消息 ') %} class="source-degraded"{% endif %}>{{ row.report_brief or "无异常" }}</summary>{{ source_details(row.source_status, "source-row-" ~ loop.index) }}{% if row.macro_review %}{% for event in row.macro_review %}<span class="mark" data-macro-review>{{ event.status }} · {{ event.detail }}</span>{% endfor %}{% endif %}{% if row.late_news_count %}<span class="subline">分析期间纳入 {{ row.late_news_count }} 条新增消息</span>{% endif %}{% if row.late_macro_count %}<span class="subline">分析期间补抓 {{ row.late_macro_count }} 条经济数据</span>{% endif %}{% if row.news_watch %}<details class="row-details{% if row.news_watch.major %} source-degraded{% endif %}" data-news-watch><summary>截止后新增 {{ row.news_watch.count }} 条消息</summary><p class="small muted">检查于 {{ row.news_watch.checked_at }} · 按保存证据分类，未自动重跑</p>{% for article in row.news_watch.articles %}{% if article.folded %}<details><summary>个股噪声（展开原文）</summary>{% endif %}<p class="small{% if article.major %} source-degraded{% endif %}">{{ article.time }} · {{ article.classification }}{% if article.evidence %} · {{ article.evidence }}{% endif %} · {% if article.url %}<a href="{{ article.url }}" target="_blank" rel="noopener noreferrer">{{ article.title }}</a>{% else %}{{ article.title }}{% endif %}<span class="subline">{{ article.summary }}</span></p>{% if article.folded %}</details>{% endif %}{% endfor %}</details>{% endif %}{% if row.quote_quality %}<span class="subline" data-time-quality-summary>{{ row.quote_quality.summary }}</span>{% endif %}<details class="row-details"><summary>时间与质量</summary><p>日线截至 {{ row.price_date }}；板块名次 {{ row.sector_rank }}；信息截止 {{ row.information_through }}；开始 {{ row.started_at }}；完成 {{ row.finished_at }}。</p><div class="marks">{% for mark in row.marks %}<span class="mark">{{ mark }}</span>{% endfor %}</div>{% if row.error %}<p class="error">{{ row.error }}</p>{% endif %}</details></details></td>
  <td>{% if row.path %}<a class="small" href="{{ row.path }}">详情 ↗</a>{% endif %}{% if managed %}<button class="analyze-button" data-analyze="{{ row.symbol }}" title="重新获取数据并分析该标的">分析一次</button><span class="small error" data-analysis-error hidden role="status"></span>{% endif %}</td>
</tr>{% endfor %}</tbody></table></div>{% for row in rows %}{{ source_dialog(row.source_status, "source-row-" ~ loop.index) }}{% endfor %}{% else %}<div class="table-wrap empty">还没有启用的订阅，点击「管理订阅」添加标的。</div>{% endif %}
<aside class="allocation-note" aria-label="标准仓位说明"><strong>标准仓位 100% 是什么？</strong> 它是你为单只股票设定的计划持仓量，只作比较单位。例如计划投入 1 万元为 100%，目标配置 60% 就是持有 6000 元。它不是账户总资产的 60%，也不是卖出现有持仓的 60%；实际买卖量还需结合已有持仓和你的标准金额。当前未设置标准金额，页面仅展示相对比例。</aside>
"""
_CONTEXT = """
{% if macro_followups %}<section data-macro-followups><h2>结论形成后的经济事件</h2><p class="small muted">报告结论形成于事件之前；下列保存数据仅提示复核，未重跑。</p>{% for event in macro_followups %}<article><strong>{{ event.title }}</strong><p>{{ event.published_at }} · {{ event.status }}</p><p>实际 {{ event.actual }} · 预期 {{ event.estimate }} · 前值 {{ event.prior }}</p><p class="small muted">来源 {{ event.source }} · 检查于 {{ event.checked_at }}</p></article>{% endfor %}</section>{% endif %}<div class="section-heading"><h2>市场背景与数据</h2><span class="small muted">展开查看，不影响自选比较</span></div>
<details><summary>大盘环境</summary>{% if market_cards %}<div class="grid">{% for card in market_cards %}<article class="card"><h3>{{ card.title }}</h3><div class="markdown">{{ card.body|safe }}</div></article>{% endfor %}</div>{% else %}<p class="muted">暂无大盘环境数据。</p>{% endif %}</details>
<details><summary>当日经济数据与市场要闻{% if macro_rows %} · {{ macro_rows|length }} 项{% endif %}</summary>
{% if macro_rows %}<div class="table-wrap"><table><thead><tr><th>指标</th><th>实际</th><th>预期</th><th>前值</th><th>发布时间</th></tr></thead><tbody>{% for row in macro_rows %}<tr><td>{{ row.metric }}</td><td>{{ row.actual }}</td><td>{{ row.expected }}</td><td>{{ row.prior }}</td><td>{{ row.published_at }}</td></tr>{% endfor %}</tbody></table></div>{% endif %}{% if macro_html %}<div class="markdown">{{ macro_html|safe }}</div>{% else %}<p class="muted">暂无经济数据。</p>{% endif %}</details>
<details><summary>板块强弱排名 · 相对 SPY</summary>{% if sector_html and '<table' in sector_html %}<div class="markdown">{{ sector_html|safe }}</div>{% else %}{% if sector_rows %}<div class="table-wrap"><table class="sector-ranking"><thead><tr><th>名次</th><th>行业 ETF</th><th>相对 SPY 5日</th><th>20日</th><th>60日</th><th>状态</th></tr></thead><tbody>{% for row in sector_rows %}<tr><td>{{ row.rank }}</td><td>{{ row.sector }}</td><td>{{ row.performance_5d or '—' }}</td><td>{{ row.performance }}</td><td>{{ row.performance_60d or '—' }}</td><td>{{ row.note }}</td></tr>{% endfor %}</tbody></table></div>{% endif %}{% if sector_html %}<div class="markdown">{{ sector_html|safe }}</div>{% elif not sector_rows %}<p class="muted">暂无板块数据。</p>{% endif %}{% endif %}</details>
"""
HOME = _ENV.from_string(_SOURCE_STATUS + """<section id="status-banner" class="banner" aria-live="polite"><h2></h2><p data-role="detail"></p><p data-role="event" class="muted small"></p></section>
<div class="stats">
  <article class="stat"><span class="stat-label">市场环境</span><strong class="stat-value">{{ market_label }}</strong><span class="stat-caption">VIX {{ vix }} · 最新日期 {{ latest_date or '—' }}</span></article>
  <article class="stat"><span class="stat-label">买入 / 增持</span><strong class="stat-value positive">{{ summary.positive }}</strong></article>
  <article class="stat"><span class="stat-label">持有</span><strong class="stat-value">{{ summary.neutral }}</strong></article>
  <article class="stat"><span class="stat-label">减持 / 卖出</span><strong class="stat-value negative">{{ summary.negative }}</strong></article>
  <article class="stat"><span class="stat-label">当前订阅</span><strong class="stat-value">{{ rows|length }} <span class="small muted">只</span></strong><span class="stat-caption">{{ summary.pending }} 项待分析或复核</span></article>
</div>
<div class="section-heading watch-heading"><div><h2>我的自选</h2><p class="small muted">板块与指数分别比较，强弱按20日超额收益判断；指数按QQQ → SPY → DIA选择。点击强弱查看归一化走势。</p></div>
{% if managed %}<div class="manager-actions"><button id="analyze-all" title="立即重新分析当前启用的全部订阅">全部分析一次</button><span id="analysis-all-error" class="small error" role="status"></span><button id="manage-settings">参数设置</button><button id="manage-watchlist" class="primary">＋ 管理订阅</button></div>{% else %}<a class="button primary" href="http://127.0.0.1:8765/">管理订阅 ↗</a>{% endif %}</div>
""" + _ROWS + """{% if managed %}<p id="analysis-message" class="small toast" role="status"></p>{% endif %}<p class="small muted">相对收益 = 个股收益 − 所选基准 ETF 收益，单位为百分点；日线截至各报告的上一交易日。ETF／指数不套用个股比较。标为“补充”的强弱为后补比较，未重算原评级。点位和目标配置摘自原报告，缺失时明确注明，点击详情查看完整条件和风险。当前模型 {{ model_label }}。</p>
""" + _CONTEXT + """
{% if managed %}<dialog id="watchlist-manager" aria-labelledby="manager-title"><div class="section-heading" style="margin-top:0"><h2 id="manager-title">管理订阅</h2><button id="close-manager" type="button" aria-label="关闭">关闭</button></div>
<p class="small muted">保存后从下次分析批次生效；移除或暂停不删除历史报告，不立即调用模型。</p>
<div id="manager-list"></div><h3>添加标的</h3><form id="watchlist-form"><div class="form-grid">
<label>代码<input name="symbol" required maxlength="20" placeholder="NVDA / BRK.B / ^NDX" autocomplete="off"></label>
<label id="type-field" hidden>类型（未能自动识别）<select name="type"><option value="">请选择类型</option><option value="stock">个股</option><option value="etf">ETF</option><option value="index">指数</option></select></label>
</div><p id="identity-message" class="small toast" role="status">输入代码后自动验证和识别类型</p>
<details><summary>高级选项（可选）</summary><div class="form-grid">
<label>名称<input name="name" maxlength="80" placeholder="默认使用识别名称"></label>
<label>板块 ETF（个股）<input name="sector_etf" maxlength="20" placeholder="自动识别，可填 SMH 等"></label>
<label>代理 ETF（指数）<input name="proxy" maxlength="20" placeholder="常用指数自动匹配；其他指数需填写"></label>
</div></details><p id="manager-message" class="error toast" role="status"></p><button class="primary" type="submit" disabled>添加订阅</button></form></dialog>
<dialog id="settings-manager" aria-labelledby="settings-title"><div class="section-heading" style="margin-top:0"><h2 id="settings-title">分析参数</h2><button id="close-settings" type="button">关闭</button></div>
<p class="small muted">下一次分析生效；当前批次继续使用原配置。定时在美股交易日开盘前一小时（08:30 ET），周末不分析。</p>
<form id="settings-form"><h3>分析师与辩论 · quick</h3><div class="form-grid"><label>模型<select name="quick_model" required></select></label><label>推理强度<select name="quick_effort" required></select></label></div>
<h3>研究经理、交易员、组合经理 · deep</h3><div class="form-grid"><label>模型<select name="deep_model" required></select></label><label>推理强度<select name="deep_effort" required></select></label></div>
<p id="model-source" class="small muted"></p>
<div class="form-grid"><label>并行分析标的数<input name="parallel" type="number" min="1" max="4" step="1" required></label><label>并行模型调用数<input name="calls" type="number" min="1" step="1" required></label></div>
<p class="small muted">模型与推理强度从本机 Codex 模型目录自动载入，保存时再次校验。标的并行数控制同时分析几只；调用并行数控制所有标的共享的模型调用上限。</p><p id="settings-message" class="error toast" role="status"></p><button class="primary" type="submit">保存参数</button></form></dialog>{% endif %}
""")
OVERVIEW = _ENV.from_string(_SOURCE_STATUS + """<p class="muted">分析请求日 {{ trade_date }}（美东）· 当日结果汇总</p><div class="section-heading"><h2>当日研判</h2><span class="small muted">相对基准收益单位：百分点</span></div>""" + _ROWS + _CONTEXT)
DETAIL = _ENV.from_string(_SOURCE_STATUS + """<p><span class="badge {{ rating_class }}">{{ rating }}</span>　{{ symbol }}{% if proxy %}（以 {{ proxy }} 代理分析）{% endif %}　{{ type_label }}　{{ mode_label }}　<a class="small" href="{{ history }}">查看标的历史 ↗</a></p>
<p class="small muted">附加上下文截至 {{ context_as_of }}；日线截至 {{ price_data_end_date }}；工具数据最晚查询于 {{ last_data_query_at }}。</p>
<div class="marks">{% for mark in marks %}<span class="mark">{{ mark }}</span>{% endfor %}</div>{% if error %}<p class="error">{{ error }}</p>{% endif %}
<section class="panel"><h2>组合经理最终决策（当日操作建议）</h2><div class="markdown">{{ decision|safe }}</div></section>
<details><summary>交易员方案</summary><div class="markdown">{{ trader_plan|safe }}</div></details>
<details><summary>研究经理结论</summary><div class="markdown">{{ investment_plan|safe }}</div></details>
{% if reports %}<div class="section-heading"><h2>分析师报告</h2></div>{% for report in reports %}<details><summary>{{ report.title }}</summary><div class="markdown">{{ report.body|safe }}</div></details>{% endfor %}{% endif %}
<details><summary>多空辩论</summary><div class="markdown">{{ investment_debate|safe }}</div></details>
<details><summary>风控辩论</summary><div class="markdown">{{ risk_debate|safe }}</div></details>
<details><summary>附加市场上下文</summary><div class="markdown">{{ injected_context|safe }}</div></details>
{{ source_details(source_status, "source-detail") }}{{ source_dialog(source_status, "source-detail") }}
<details><summary>时间与质量 · 数据查询记录</summary><div class="time-list">{% for item in times %}<div><strong>{{ item.label }}：</strong>{{ item.value }}</div>{% endfor %}</div>
{% if data_queries %}<h3>数据查询记录</h3><div class="table-wrap"><table><thead><tr><th>工具</th><th>开始</th><th>结束</th></tr></thead><tbody>{% for query in data_queries %}<tr><td>{{ query.name }}</td><td>{{ query.started_at }}</td><td>{{ query.finished_at }}</td></tr>{% endfor %}</tbody></table></div>{% endif %}
<h3>数据时间戳</h3>{% if timestamps %}<div class="table-wrap"><table><thead><tr><th>数据</th><th>时间</th><th>来源</th></tr></thead><tbody>{% for item in timestamps %}<tr><td>{{ item.name }}</td><td>{{ item.time }}</td><td>{{ item.source }}</td></tr>{% endfor %}</tbody></table></div>{% else %}<p class="muted">暂无数据源时间戳。</p>{% endif %}</details>
<details><summary>运行元数据</summary><div class="time-list">{% for item in metadata %}<div><strong>{{ item.label }}：</strong>{{ item.value }}</div>{% endfor %}</div></details>
{% if previous or next %}<nav class="panel"><a href="{{ previous }}" {% if not previous %}hidden{% endif %}>上一交易日结果</a>　<a href="{{ next }}" {% if not next %}hidden{% endif %}>下一交易日结果</a></nav>{% endif %}
""")
HISTORY = _ENV.from_string("""<p class="muted">{{ symbol }} 历次当前结果</p>{% if rows %}<div class="table-wrap"><table><thead><tr><th>日期</th><th>评级</th><th>建议摘要</th><th>状态</th><th>模式</th></tr></thead><tbody>{% for row in rows %}<tr><td><a href="{{ row.path }}">{{ row.date }}</a></td><td><span class="badge {{ row.rating_class }}">{{ row.rating }}</span></td><td>{{ row.advice }}</td><td>{{ row.status }}</td><td>{{ row.mode }}</td></tr>{% endfor %}</tbody></table></div>{% else %}<p class="empty">暂无历史结果。</p>{% endif %}""")

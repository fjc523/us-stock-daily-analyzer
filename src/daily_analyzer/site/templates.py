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
  {% if refresh_seconds %}<meta http-equiv="refresh" content="{{ refresh_seconds }}">{% endif %}
  <style>
    :root { color-scheme: light dark; --bg:#f4f6f8; --panel:#fff; --fg:#18212b; --muted:#586574; --line:#d8dee6; --accent:#1769aa; --bad:#a52c2c; --good:#19734a; }
    @media (prefers-color-scheme: dark) { :root { --bg:#12171d; --panel:#1c242d; --fg:#e6edf3; --muted:#a0adba; --line:#3a4652; --accent:#76b7f2; --bad:#ff9292; --good:#73d3a2; } }
    * { box-sizing:border-box; }
    body { margin:0; background:var(--bg); color:var(--fg); font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
    main { max-width:1180px; margin:0 auto; padding:24px 18px 44px; }
    h1,h2,h3 { line-height:1.25; } h1 { margin:12px 0 22px; font-size:2rem; } h2 { margin-top:28px; font-size:1.35rem; } h3 { font-size:1.08rem; }
    a { color:var(--accent); } .selectors,.panel,.banner,.card { background:var(--panel); border:1px solid var(--line); border-radius:12px; }
    .selectors { display:flex; flex-wrap:wrap; align-items:center; gap:12px; padding:12px 14px; }
    label { color:var(--muted); font-size:.9rem; } select { color:var(--fg); background:var(--panel); border:1px solid var(--line); border-radius:7px; padding:7px 9px; min-width:145px; }
    .banner,.panel { padding:17px 19px; margin:14px 0; } .banner h2 { margin:0 0 5px; } .banner p { margin:5px 0; }
    .banner-running { border-left:5px solid var(--accent); } .banner-failed { border-left:5px solid var(--bad); } .banner-done { border-left:5px solid var(--good); }
    .muted { color:var(--muted); } .small { font-size:.9rem; } .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px; }
    .card { padding:13px 15px; } .card h3 { margin:0 0 7px; } .card p { margin:0; }
    .table-wrap { overflow:auto; border:1px solid var(--line); border-radius:10px; background:var(--panel); }
    table { width:100%; border-collapse:collapse; min-width:760px; } th,td { padding:9px 10px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }
    th { background:color-mix(in srgb,var(--panel) 82%,var(--bg)); white-space:nowrap; } tr:last-child td { border-bottom:0; }
    .badge { display:inline-block; border-radius:999px; padding:2px 9px; font-size:.88rem; font-weight:650; background:#e3e9ef; color:#24313e; }
    @media (prefers-color-scheme: dark) { .badge { background:#34414d; color:#eef4f8; } }
    .rating-buy { background:#d9f2e5; color:#12663b; } .rating-overweight { background:#dff0e4; color:#257143; }
    .rating-hold { background:#e8ebef; color:#4c5966; } .rating-underweight { background:#fff0d5; color:#8c5d00; }
    .rating-sell { background:#f8dddd; color:#a02020; } .rating-review { background:#e8e1f5; color:#62419a; }
    @media (prefers-color-scheme: dark) { .rating-buy,.rating-overweight,.rating-hold,.rating-underweight,.rating-sell,.rating-review { color:#101820; } }
    .marks { display:flex; flex-wrap:wrap; gap:5px; } .mark { display:inline-block; border:1px solid var(--line); border-radius:6px; padding:1px 6px; color:var(--muted); font-size:.8rem; }
    .markdown { overflow-wrap:anywhere; } .markdown table { min-width:0; } .markdown pre { overflow:auto; padding:12px; background:var(--bg); border-radius:8px; }
    .markdown code { font-family:ui-monospace,SFMono-Regular,monospace; } .time-list { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:6px 20px; }
    details { border:1px solid var(--line); border-radius:9px; padding:10px 13px; margin:10px 0; background:var(--panel); } summary { cursor:pointer; font-weight:650; }
    footer { max-width:1180px; margin:0 auto; padding:16px 18px 28px; border-top:1px solid var(--line); color:var(--muted); font-size:.9rem; }
    .error { color:var(--bad); } .empty { padding:16px; color:var(--muted); }
  </style>
</head>
<body>
<main>
  <nav class="selectors" aria-label="报告选择">
    <label for="date-select">交易日</label><select id="date-select"></select>
    <label for="symbol-select">标的</label><select id="symbol-select"></select>
    <a href="{{ root_prefix }}index.html">首页</a>
  </nav>
  <h1>{{ title }}</h1>
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
  function prettyTime(value, zone) {
    if (!value) return "未记录";
    const instant = new Date(value);
    if (Number.isNaN(instant.getTime())) return String(value);
    return new Intl.DateTimeFormat("zh-CN", {timeZone:zone,month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hourCycle:"h23"}).format(instant);
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
      const started = prettyTime(run.started_at, "Asia/Shanghai") + " 北京 / " + prettyTime(run.started_at, "America/New_York") + " 美东";
      if (status === "running") return {kind:"running",title:"今日运行中 " + counts,detail:started + "；" + elapsed(run.started_at, now) + (run.estimated_finish_at ? "；预计完成 " + prettyTime(run.estimated_finish_at,"Asia/Shanghai") + " 北京 / " + prettyTime(run.estimated_finish_at,"America/New_York") + " 美东" : "")};
      if (status === "completed") return {kind:"done",title:"今日已完成",detail:started + (run.finished_at ? "；结束 " + prettyTime(run.finished_at,"Asia/Shanghai") + " 北京 / " + prettyTime(run.finished_at,"America/New_York") + " 美东" : "")};
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
  if (!global.document) return;
  const banner = global.document.getElementById("status-banner");
  if (banner) {
    const state = bannerState(site.banner || {}, new Date());
    banner.className = "banner banner-" + state.kind;
    banner.querySelector("h2").textContent = state.title;
    banner.querySelector("p[data-role=detail]").textContent = state.detail;
    const event = (site.banner || {}).last_schedule_event;
    const eventLine = banner.querySelector("p[data-role=event]");
    if (event && eventLine) {
      const labels = {started:"开始运行",recovery_started:"恢复运行",skipped_not_trading_day:"非交易日，跳过",skipped_before_anchor:"未到锚点，跳过",skipped_after_close:"已收盘，跳过",skipped_already_done:"今日已运行，跳过"};
      eventLine.textContent = prettyTime(event.at,"Asia/Shanghai") + " 调度：" + (labels[event.result] || event.result || "已记录") + (event.reason ? "（"+event.reason+"）" : "");
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
  if (site.refresh_seconds > 0) global.setTimeout(function(){ global.location.reload(); }, site.refresh_seconds*1000);
})(typeof window === "undefined" ? globalThis : window);
</script>
</body>
</html>"""
)

HOME = _ENV.from_string(
    """<section id="status-banner" class="banner" aria-live="polite">
  <h2></h2><p data-role="detail"></p><p data-role="event" class="muted small"></p>
</section>
{% if latest_date %}<p class="muted">最新分析日期：{{ latest_date }}</p>{% endif %}
<h2>大盘环境</h2>
{% if market_cards %}<div class="grid">{% for card in market_cards %}<article class="card"><h3>{{ card.title }}</h3><div class="markdown">{{ card.body|safe }}</div></article>{% endfor %}</div>{% else %}<p class="empty">暂无大盘环境数据。</p>{% endif %}
<h2>当日经济数据</h2>
{% if macro_rows %}<div class="table-wrap"><table><thead><tr><th>指标</th><th>实际</th><th>预期</th><th>前值</th><th>发布时间</th></tr></thead><tbody>{% for row in macro_rows %}<tr><td>{{ row.metric }}</td><td>{{ row.actual }}</td><td>{{ row.expected }}</td><td>{{ row.prior }}</td><td>{{ row.published_at }}</td></tr>{% endfor %}</tbody></table></div>{% if macro_html %}<details><summary>经济数据与市场要闻补充</summary><div class="markdown">{{ macro_html|safe }}</div></details>{% endif %}{% elif macro_html %}<div class="panel markdown">{{ macro_html|safe }}</div>{% else %}<p class="empty">暂无经济数据。</p>{% endif %}
<h2>板块强弱排名</h2>
{% if sector_rows %}<div class="table-wrap"><table><thead><tr><th>名次</th><th>板块</th><th>标的</th><th>表现</th><th>说明</th></tr></thead><tbody>{% for row in sector_rows %}<tr><td>{{ row.rank }}</td><td>{{ row.sector }}</td><td>{{ row.symbol }}</td><td>{{ row.performance }}</td><td>{{ row.note }}</td></tr>{% endfor %}</tbody></table></div>{% if sector_html %}<details><summary>板块与个股相对表现补充</summary><div class="markdown">{{ sector_html|safe }}</div></details>{% endif %}{% elif sector_html %}<div class="panel markdown">{{ sector_html|safe }}</div>{% else %}<p class="empty">暂无板块数据。</p>{% endif %}
<h2>标的汇总</h2>
{% if rows %}<div class="table-wrap"><table><thead><tr><th>代码</th><th>名称</th><th>类型</th><th>评级</th><th>一句话建议</th><th>盘前涨跌幅</th><th>板块名次</th><th>状态</th><th>开始</th><th>完成</th><th>信息截止</th><th>标记</th></tr></thead><tbody>{% for row in rows %}<tr><td><a href="{{ row.path }}">{{ row.symbol }}</a>{% if row.proxy %}<div class="muted small">代理 {{ row.proxy }}</div>{% endif %}</td><td>{{ row.name }}</td><td>{{ row.type }}</td><td><span class="badge {{ row.rating_class }}">{{ row.rating }}</span></td><td>{{ row.advice }}</td><td>{{ row.premarket }}</td><td>{{ row.sector_rank }}</td><td>{{ row.status }}{% if row.error %}<div class="error small">{{ row.error }}</div>{% endif %}</td><td>{{ row.started_at }}</td><td>{{ row.finished_at }}</td><td>{{ row.information_through }}</td><td><div class="marks">{% for mark in row.marks %}<span class="mark">{{ mark }}</span>{% endfor %}</div></td></tr>{% endfor %}</tbody></table></div>{% else %}<p class="empty">当前没有可展示的标的结果。</p>{% endif %}
"""
)

DETAIL = _ENV.from_string(
    """<p><span class="badge {{ rating_class }}">{{ rating }}</span>　{{ symbol }}{% if proxy %}（以 {{ proxy }} 代理分析）{% endif %}　{{ type_label }}　{{ mode_label }}</p>
<section class="panel"><h2>时间信息</h2><div class="time-list">{% for item in times %}<div><strong>{{ item.label }}：</strong>{{ item.value }}</div>{% endfor %}</div><p class="muted">附加上下文截至 {{ context_as_of }}；日线截至 {{ price_data_end_date }}；工具数据最晚查询于 {{ last_data_query_at }}。</p>
<div class="marks">{% for mark in marks %}<span class="mark">{{ mark }}</span>{% endfor %}</div>{% if error %}<p class="error">{{ error }}</p>{% endif %}</section>
{% if data_queries %}<h2>数据查询记录</h2><div class="table-wrap"><table><thead><tr><th>工具</th><th>开始</th><th>结束</th></tr></thead><tbody>{% for query in data_queries %}<tr><td>{{ query.name }}</td><td>{{ query.started_at }}</td><td>{{ query.finished_at }}</td></tr>{% endfor %}</tbody></table></div>{% endif %}
<section class="panel"><h2>组合经理最终决策（当日操作建议）</h2><div class="markdown">{{ decision|safe }}</div></section>
<section class="panel"><h2>交易员方案</h2><div class="markdown">{{ trader_plan|safe }}</div></section>
<section class="panel"><h2>研究经理结论</h2><div class="markdown">{{ investment_plan|safe }}</div></section>
{% if reports %}<section><h2>分析师报告</h2>{% for report in reports %}<details><summary>{{ report.title }}</summary><div class="markdown">{{ report.body|safe }}</div></details>{% endfor %}</section>{% endif %}
<section class="panel"><h2>多空辩论</h2><div class="markdown">{{ investment_debate|safe }}</div></section>
<section class="panel"><h2>风控辩论</h2><div class="markdown">{{ risk_debate|safe }}</div></section>
<section class="panel"><h2>附加市场上下文</h2><div class="markdown">{{ injected_context|safe }}</div></section>
<h2>数据时间戳</h2>{% if timestamps %}<div class="table-wrap"><table><thead><tr><th>数据</th><th>时间</th><th>来源</th></tr></thead><tbody>{% for item in timestamps %}<tr><td>{{ item.name }}</td><td>{{ item.time }}</td><td>{{ item.source }}</td></tr>{% endfor %}</tbody></table></div>{% else %}<p class="empty">暂无数据源时间戳。</p>{% endif %}
<section class="panel"><h2>运行元数据</h2><div class="time-list">{% for item in metadata %}<div><strong>{{ item.label }}：</strong>{{ item.value }}</div>{% endfor %}</div></section>
<nav class="panel"><a href="{{ previous }}" {% if not previous %}hidden{% endif %}>上一交易日结果</a>　<a href="{{ next }}" {% if not next %}hidden{% endif %}>下一交易日结果</a></nav>
"""
)

OVERVIEW = _ENV.from_string(
    """<p class="muted">交易日 {{ trade_date }} · 当日结果汇总</p>
{% if market_cards %}<h2>大盘环境</h2><div class="grid">{% for card in market_cards %}<article class="card"><h3>{{ card.title }}</h3><div class="markdown">{{ card.body|safe }}</div></article>{% endfor %}</div>{% else %}<h2>大盘环境</h2><p class="empty">暂无大盘环境数据。</p>{% endif %}
<h2>当日经济数据</h2>{% if macro_rows %}<div class="table-wrap"><table><thead><tr><th>指标</th><th>实际</th><th>预期</th><th>前值</th><th>发布时间</th></tr></thead><tbody>{% for row in macro_rows %}<tr><td>{{ row.metric }}</td><td>{{ row.actual }}</td><td>{{ row.expected }}</td><td>{{ row.prior }}</td><td>{{ row.published_at }}</td></tr>{% endfor %}</tbody></table></div>{% if macro_html %}<details><summary>经济数据与市场要闻补充</summary><div class="markdown">{{ macro_html|safe }}</div></details>{% endif %}{% elif macro_html %}<div class="panel markdown">{{ macro_html|safe }}</div>{% else %}<p class="empty">暂无经济数据。</p>{% endif %}
<h2>板块强弱排名</h2>{% if sector_rows %}<div class="table-wrap"><table><thead><tr><th>名次</th><th>板块</th><th>标的</th><th>表现</th><th>说明</th></tr></thead><tbody>{% for row in sector_rows %}<tr><td>{{ row.rank }}</td><td>{{ row.sector }}</td><td>{{ row.symbol }}</td><td>{{ row.performance }}</td><td>{{ row.note }}</td></tr>{% endfor %}</tbody></table></div>{% if sector_html %}<details><summary>板块与个股相对表现补充</summary><div class="markdown">{{ sector_html|safe }}</div></details>{% endif %}{% elif sector_html %}<div class="panel markdown">{{ sector_html|safe }}</div>{% else %}<p class="empty">暂无板块数据。</p>{% endif %}
{% if rows %}<h2>标的汇总</h2><div class="table-wrap"><table><thead><tr><th>代码</th><th>名称</th><th>类型</th><th>评级</th><th>一句话建议</th><th>盘前涨跌幅</th><th>板块名次</th><th>状态</th><th>开始</th><th>完成</th><th>信息截止</th><th>标记</th></tr></thead><tbody>{% for row in rows %}<tr><td><a href="{{ row.path }}">{{ row.symbol }}</a>{% if row.proxy %}<div class="muted small">代理 {{ row.proxy }}</div>{% endif %}</td><td>{{ row.name }}</td><td>{{ row.type }}</td><td><span class="badge {{ row.rating_class }}">{{ row.rating }}</span></td><td>{{ row.advice }}</td><td>{{ row.premarket }}</td><td>{{ row.sector_rank }}</td><td>{{ row.status }}{% if row.error %}<div class="error small">{{ row.error }}</div>{% endif %}</td><td>{{ row.started_at }}</td><td>{{ row.finished_at }}</td><td>{{ row.information_through }}</td><td><div class="marks">{% for mark in row.marks %}<span class="mark">{{ mark }}</span>{% endfor %}</div></td></tr>{% endfor %}</tbody></table></div>{% endif %}
"""
)

HISTORY = _ENV.from_string(
    """<p class="muted">{{ symbol }} 历次当前结果</p>
{% if rows %}<div class="table-wrap"><table><thead><tr><th>日期</th><th>中文评级</th><th>一句话建议</th><th>状态</th><th>模式</th></tr></thead><tbody>{% for row in rows %}<tr><td><a href="{{ row.path }}">{{ row.date }}</a></td><td><span class="badge {{ row.rating_class }}">{{ row.rating }}</span></td><td>{{ row.advice }}</td><td>{{ row.status }}</td><td>{{ row.mode }}</td></tr>{% endfor %}</tbody></table></div>{% else %}<p class="empty">暂无历史结果。</p>{% endif %}
"""
)

"""北京时间展示的定向契约，原始业务数据保持不变。"""
import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from markupsafe import Markup

from daily_analyzer.site import _beijing_display, _pretty_timestamp, _rows, build_site, render_home
from test_site import _fixture, _write_json


CASES = [
    ("2026-10-07T10:30:00-04:00", "2026-10-07 22:30:00"),
    ("2026-10-07T14:30:00Z", "2026-10-07 22:30:00"),
    ("2026-10-07T14:30:00+00:00", "2026-10-07 22:30:00"),
    ("2026-10-07T23:30:01+09:00", "2026-10-07 22:30:01"),
    ("2026-10-07T18:30:05-07:00", "2026-10-08 09:30:05"),
    ("2026-01-07T10:30:00-05:00", "2026-01-07 23:30:00"),
    ("2026-10-07T10:30:00.456292-04:00", "2026-10-07 22:30:00"),
    ("2026-10-07", "2026-10-07"),
    (None, "—"), ("", "—"), ("未提供", "未提供"),
    ("2026-10-07T10:30:00", "时间未核验"),
    ("2026-02-30T10:30:00Z", "时间未核验"),
    ("2026-10-07T24:00:00Z", "时间未核验"),
    ("2026-10-07T10:60:00Z", "时间未核验"),
    ("不是时间", "时间未核验"),
    ("2026-10-07 10:30:00-04:00", "2026-10-07 22:30:00"),
    ("2026-10-07T10:30:00+00:60", "时间未核验"),
    ("2026-10-07T10:30:00-00:60", "时间未核验"),
    ("2026-10-07T10:30:00+24:00", "时间未核验"),
    ("2026-10-07T10:30:00-24:00", "时间未核验"),
    ("真实时段时间未知", "真实时段时间未知"),
    ("来源时点未提供", "来源时点未提供"),
]


@pytest.mark.parametrize("value,expected", CASES)
def test_python_beijing_timestamp(value, expected):
    assert _pretty_timestamp(value) == expected


def test_named_new_york_summer_winter_and_cross_day():
    for month, expected in [(10, "2026-10-08 11:30:00"), (1, "2026-01-08 12:30:00")]:
        instant = datetime(2026, month, 7, 23, 30, tzinfo=ZoneInfo("America/New_York"))
        assert _pretty_timestamp(instant) == expected


@pytest.mark.parametrize("local_zone", ["America/Los_Angeles", "Asia/Tokyo"])
def test_javascript_matches_static_in_foreign_computer_zone(tmp_path, local_zone):
    node = shutil.which("node")
    if node is None:
        pytest.skip("当前环境没有 node，无法验证动态脚本")
    _fixture(tmp_path)
    html = render_home(tmp_path)
    script = re.search(r"<script>\s*(.*?)</script>", html, re.S)[1]
    harness = script + "\nconsole.log(JSON.stringify(" + json.dumps([value for value, _ in CASES], ensure_ascii=False) + ".map(dailyAnalyzerPrettyTime)));"
    result = subprocess.run([node, "-e", harness], capture_output=True, text=True, check=True, env={**os.environ, "TZ": local_zone})
    assert json.loads(result.stdout) == [expected for _, expected in CASES]


def test_report_text_preserves_facts_links_attributes_and_real_code():
    raw = Markup('<p>若价格 &gt; 172.2，则在 2026-10-07T10:30:00-04:00 后复核；日期 2026-10-07。</p>'
                 '<a href="https://example.com/2026-10-07T10:30:00-04:00" title="原链接">来源</a>'
                 '<code>2026-10-07T10:30:00-04:00</code>'
                 '<pre><code>value = "2026-10-07T10:30:00-04:00"</code></pre>'
                 '<p>未知 2026-10-07T10:30:00；非法 2026-02-30T10:30:00Z</p>'
                 '<p>https://example.com/?at=2026-10-07T10:30:00-04:00</p>')
    rendered = str(_beijing_display(raw))
    assert '若价格 &gt; 172.2，则在 2026-10-07 22:30:00 后复核；日期 2026-10-07。' in rendered
    assert '<a href="https://example.com/2026-10-07T10:30:00-04:00" title="原链接">来源</a>' in rendered
    assert '<code>2026-10-07 22:30:00</code>' in rendered
    assert '<pre><code>value = "2026-10-07T10:30:00-04:00"</code></pre>' in rendered
    assert '<p>未知 时间未核验；非法 时间未核验</p>' in rendered
    assert '<p>https://example.com/?at=2026-10-07T10:30:00-04:00</p>' in rendered


def test_home_detail_and_macro_time_projection_preserves_saved_data(tmp_path):
    _fixture(tmp_path)
    path = tmp_path / 'data/runs/2026-10-01/current/NVDA.json'
    result = json.loads(path.read_text())
    result['final_trade_decision'] = '若价格高于 172.2，在 `2026-10-07T10:30:00-04:00` 后复核；日线截至 2026-10-01。'
    result['reports'] = {'news_report': '新闻发布于 2026-10-07T14:30:00Z，价格条件 > 172.2。'}
    _write_json(path, result)
    saved = path.read_bytes()
    build_site(tmp_path)
    for page in [render_home(tmp_path), (tmp_path/'site/index.html').read_text(), (tmp_path/'site/days/2026-10-01/NVDA.html').read_text()]:
        assert '页面时刻均为北京时间' in page
        assert ' 北京 / ' not in page
    detail = (tmp_path/'site/days/2026-10-01/NVDA.html').read_text()
    assert '2026-10-07 22:30:00' in detail and '172.2' in detail and '2026-10-01' in detail
    assert '2026-10-07T10:30:00-04:00' not in detail
    assert path.read_bytes() == saved
    assert _rows([{'title':'EIA','published_at':'2026-10-07T10:30:00-04:00'}], 'macro')[0]['published_at'] == '2026-10-07 22:30:00'


def test_chinese_adjacent_iso_and_spaced_timestamp():
    rendered = str(_beijing_display(Markup('<p>发布时间2026-10-07T10:30:00-04:00发布/美东；2026-10-07 10:30:00-04:00公布</p>')))
    assert rendered == '<p>发布时间2026-10-07 22:30:00发布/美东；2026-10-07 22:30:00公布</p>'


def test_et_context_projection_preserves_event_facts_and_market_sessions():
    from daily_analyzer.site import _markdown
    raw = """最近盘后报价 2026-10-06 20:00 ET；冬季 2026-01-06 20:00 ET。
新闻及当日发布时刻均为ET，当日仅列时分秒，其他日期列月日时刻。
#### 市场要闻
- 05:04:32：价格高于 172.2 后复核
截至 05:07:19 ET 未见当日经济数据标题。
重要度：高=HIGH、中=MEDIUM；时间为ET，未列月日沿用本组首行，↳同上。事件均为美国；年份同上下文。
|发布时间ET|事件|实际|
|---|---|---|
|10-07 07:00|EIA原油库存|172.2|
|08:30|贸易帐|-1056|
|↳|同刻事件|92.2|
|2026-10-07 10:30|完整日期事件|55.3|
### 市场时段
常规时段 09:30–16:00 ET；调度锚点08:30 ET；剔除16:00–16:01竞价。
"""
    display = str(_beijing_display(_markdown(raw)))
    assert '2026-10-07 08:00:00' in display and '2026-01-07 09:00:00' in display
    assert '2026-10-07 22:30:00' in display
    assert '发布时间ET' not in display and '10-07 07:00' not in display and '05:04:32' not in display
    assert '时间未核验' in display and '当日仅列时分秒' not in display
    assert '172.2' in display and '-1056' in display and '价格高于' in display
    assert '常规时段 09:30–16:00 ET' in display and '调度锚点08:30 ET' in display and '剔除16:00–16:01竞价' in display


def test_et_chinese_suffix_preserves_price_fact():
    raw = Markup('<p>富途2026-10-05 08:32 ET查询采用前收盘价186.59美元</p>')
    assert str(_beijing_display(raw)) == '<p>富途2026-10-05 20:32:00查询采用前收盘价186.59美元</p>'

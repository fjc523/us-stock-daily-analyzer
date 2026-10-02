"""验证本机管理保存、正常请求及配置/数据隔离。"""

import json
import plistlib
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
import yaml

from daily_analyzer.config import ConfigurationError, load_watchlist
from daily_analyzer.deployment.viewer import LABEL, viewer_action
from daily_analyzer.site import build_site
from daily_analyzer.viewer import WatchlistStore, SettingsStore, create_server
from daily_analyzer.instruments import InstrumentUnavailableError
from daily_analyzer.manual_analysis import AnalysisLauncher, AnalysisBusyError
from datetime import datetime
from daily_analyzer.time_utils import NEW_YORK
from daily_analyzer.storage import run_lock, atomic_write_json



def identity(symbol):
    if symbol.startswith("^"):
        raise ConfigurationError("未找到有效标的")
    return {"symbol": symbol, "type": "etf" if symbol == "QQQ" else "stock",
            "name": "测试标的", "source": "固定测试样例"}


@pytest.fixture(autouse=True)
def offline_identity(monkeypatch):
    monkeypatch.setattr("daily_analyzer.viewer.InstrumentResolver", lambda root: identity)
    monkeypatch.setattr("daily_analyzer.viewer.load_codex_models", lambda: {"models": [{"id": "gpt-6.1-sol", "name": "固定模型", "reasoning_efforts": ["medium", "xhigh"], "default_effort": "medium"}], "updated_at": "固定时间", "source": "固定目录"})


def project(root: Path) -> Path:
    (root / "config").mkdir()
    (root / "config/watchlist.yaml").write_text(
        "items:\n  - symbol: NVDA\n    type: stock\n    name: 英伟达\n"
        "    analysts: [market, news]\n    context_providers: [sector_strength]\n    note: 原备注\n", encoding="utf-8")
    return root


@contextmanager
def http(root: Path):
    server = create_server(root, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def request(url: str, body=None, **headers):
    data = json.dumps(body).encode() if body is not None else None
    if data:
        headers.setdefault("Content-Type", "application/json")
    try:
        response = urlopen(Request(url, data=data, headers=headers), timeout=5)
    except HTTPError as error:
        response = error
    with response:
        return response.status, response.read().decode()


def test_save_subscription_preserves_overrides_and_history(tmp_path):
    root = project(tmp_path)
    history = root / "data/runs/2026-10-01/current/NVDA.json"
    history.parent.mkdir(parents=True)
    history.write_text('{"symbol":"NVDA","status":"success","type":"stock"}')
    store = WatchlistStore(root)
    original = yaml.safe_load((root / "config/watchlist.yaml").read_text())["items"][0]
    store.update({"action": "add", "item": {"symbol": "aapl", "type": "stock", "name": "苹果"}})
    assert yaml.safe_load((root / "config/watchlist.yaml").read_text())["items"][0] == original
    assert load_watchlist(root).active_items[-1].symbol == "AAPL"
    store.update({"action": "toggle", "symbol": "aapl"})
    assert [i.symbol for i in load_watchlist(root).active_items] == ["NVDA"]
    store.update({"action": "toggle", "symbol": "AAPL"})
    store.update({"action": "remove", "symbol": "NVDA"})
    store.update({"action": "remove", "symbol": "AAPL"})
    assert load_watchlist(root).items == []
    assert history.read_text() == '{"symbol":"NVDA","status":"success","type":"stock"}'
    assert not (root / "data/status.json").exists()


@pytest.mark.parametrize("item", [
    {"symbol": "nvda", "type": "stock"}, {"symbol": "ABC", "type": "fund"},
    {"symbol": "^UNKNOWN", "type": "index"}, {"symbol": "../../ABC", "type": "stock"},
])
def test_invalid_add_keeps_config_bytes(tmp_path, item):
    root = project(tmp_path)
    path = root / "config/watchlist.yaml"
    original = path.read_bytes()
    with pytest.raises(ConfigurationError):
        WatchlistStore(root).update({"action": "add", "item": item})
    assert path.read_bytes() == original


def test_http_management_and_static_route_scope(tmp_path):
    root = project(tmp_path)
    build_site(root)
    (root / "config/secrets.env").write_text("不可公开的测试内容")
    with http(root) as base:
        code, html = request(base + "/")
        assert code == 200 and "管理订阅" in html and "watchlist-form" in html
        assert 'http-equiv="refresh"' not in html
        code, body = request(base + "/api/watchlist")
        assert code == 200 and json.loads(body)["items"][0]["symbol"] == "NVDA"
        code, body = request(base + "/api/watchlist", {"action": "add", "item": {"symbol": "BRK.B", "type": "stock"}})
        assert code == 200 and "BRK.B" in body
        assert "BRK.B" in request(base + "/")[1]
        for path in ("/config/secrets.env", "/../config/secrets.env", "/%2e%2e/config/secrets.env", "/api/unknown"):
            code, body = request(base + path)
            assert code == 404 and "不可公开" not in body
        assert request(base + "/", Host="evil.example")[0] == 403
        assert request(base + "/api/watchlist", {"action": "remove", "symbol": "NVDA"}, Origin="https://evil.example")[0] == 403
        assert request(base + "/api/watchlist", {"action": "remove", "symbol": "NVDA"}, **{"Content-Type": "text/plain"})[0] == 415
        assert load_watchlist(root).active_items[0].symbol == "NVDA"
        assert not (root / "data/status.json").exists()


def test_concurrent_adds_are_not_lost(tmp_path):
    root = project(tmp_path)
    with http(root) as base:
        results = []
        def add(symbol):
            results.append(request(base + "/api/watchlist", {"action": "add", "item": {"symbol": symbol, "type": "stock"}})[0])
        threads = [threading.Thread(target=add, args=(symbol,)) for symbol in ("AAPL", "MSFT")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert results == [200, 200]
        assert {item.symbol for item in load_watchlist(root).items} == {"NVDA", "AAPL", "MSFT"}


def test_save_failure_keeps_original_config(tmp_path, monkeypatch):
    import daily_analyzer.viewer as viewer
    root = project(tmp_path)
    path = root / "config/watchlist.yaml"
    original = path.read_bytes()
    def fail_replace(*args):
        raise OSError("模拟保存失败")
    monkeypatch.setattr(viewer.os, "replace", fail_replace)
    with pytest.raises(OSError, match="模拟保存失败"):
        WatchlistStore(root).update({"action": "remove", "symbol": "NVDA"})
    assert path.read_bytes() == original
    assert list(path.parent.glob(".watchlist-*")) == []


def test_viewer_launchagent_is_separate_from_analysis(tmp_path):
    root = project(tmp_path)
    commands = []
    def runner(args, **kwargs):
        commands.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    directory = root / "agents"
    result = viewer_action(root, "install", runner=runner, launch_agents_dir=directory)
    assert result["ok"] and result["loaded"]
    value = plistlib.loads((directory / f"{LABEL}.plist").read_bytes())
    assert value["RunAtLoad"] and value["KeepAlive"]
    assert value["ProgramArguments"][-1] == "serve"
    assert "StartCalendarInterval" not in value
    assert all("local.us-stock-daily-analyzer.plist" not in str(arg) for cmd in commands for arg in cmd)
    viewer_action(root, "uninstall", runner=runner, launch_agents_dir=directory)
    assert not (directory / f"{LABEL}.plist").exists()
    assert (root / "config/watchlist.yaml").is_file()


def test_identity_api_autotype_and_backend_revalidation(tmp_path):
    root = project(tmp_path)
    with http(root) as base:
        code, body = request(base + "/api/instruments?symbol=qqq")
        assert code == 200 and json.loads(body)["type"] == "etf"
        code, body = request(base + "/api/watchlist", {"action": "add", "item": {"symbol": "QQQ"}})
        assert code == 200
        assert load_watchlist(root).items[-1].type == "etf"
        assert request(base + "/api/watchlist", {"action": "add", "item": {"symbol": "QQQ", "type": "stock"}})[0] == 400
        assert request(base + "/api/instruments?symbol=%5EINVALID")[0] == 400
        html = request(base + "/")[1]
        assert 'id="type-field" hidden' in html and 'data-analyze="QQQ"' in html


def test_unknown_type_requires_selection_and_outage_does_not_save(tmp_path):
    root = project(tmp_path)
    resolver = lambda symbol: {"symbol": symbol, "type": None, "name": "未知类型标的"}
    store = WatchlistStore(root, resolver=resolver)
    with pytest.raises(ConfigurationError, match="请选择类型"):
        store.update({"action": "add", "item": {"symbol": "ABC"}})
    store.update({"action": "add", "item": {"symbol": "ABC", "type": "etf"}})
    assert load_watchlist(root).items[-1].type == "etf"
    original = (root / "config/watchlist.yaml").read_bytes()
    def unavailable(symbol):
        raise InstrumentUnavailableError("暂时无法验证")
    with pytest.raises(InstrumentUnavailableError):
        WatchlistStore(root, resolver=unavailable).update({"action": "add", "item": {"symbol": "XYZ", "type": "stock"}})
    server = create_server(root, port=0, resolver=unavailable)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        assert request(base + "/api/instruments?symbol=XYZ")[0] == 503
        assert request(base + "/api/watchlist", {"action": "add", "item": {"symbol": "XYZ"}})[0] == 503
    finally:
        server.shutdown(); thread.join(); server.server_close()
    assert (root / "config/watchlist.yaml").read_bytes() == original


def test_manual_launch_command_busy_window_and_result(tmp_path):
    root = project(tmp_path)
    calls = []
    process = SimpleNamespace(poll=lambda: None)
    def launch(command, **kwargs):
        calls.append((command, kwargs))
        return process
    launcher = AnalysisLauncher(root, popen=launch, clock=lambda: datetime(2026, 10, 2, 8, 40, tzinfo=NEW_YORK))
    with run_lock(root), pytest.raises(AnalysisBusyError):
        launcher.start("NVDA")
    assert calls == []
    assert launcher.start("nvda")["status"] == "running"
    (root / "data/status.json").write_text(json.dumps({"last_run": {"started_at": "2026-10-02T08:40:00-04:00", "progress": {"completed": 0, "total": 1}}}))
    assert launcher.snapshot()["run"]["progress"] == {"completed": 0, "total": 1}
    command, kwargs = calls[0]
    assert command[-3:] == ["--tickers", "NVDA", "--force"]
    assert "--date" not in command and kwargs["cwd"] == root
    assert "PATH" in kwargs["env"]
    with pytest.raises(AnalysisBusyError):
        launcher.start("NVDA")
    process.poll = lambda: 2
    assert launcher.snapshot()["status"] == "failed"
    process.poll = lambda: 0
    assert launcher.snapshot()["status"] == "completed"
    with pytest.raises(ConfigurationError, match="启用"):
        launcher.start("AAPL")
    launcher.clock = lambda: datetime(2026, 10, 2, 17, tzinfo=NEW_YORK)
    with pytest.raises(ValueError, match="交易日"):
        launcher.start("NVDA")
    assert len(calls) == 1


def test_manual_analysis_http_is_async_and_reports_busy(tmp_path):
    root = project(tmp_path)
    launcher = AnalysisLauncher(root, popen=lambda *a, **kw: SimpleNamespace(poll=lambda: None),
                                clock=lambda: datetime(2026, 10, 2, 8, 40, tzinfo=NEW_YORK))
    server = create_server(root, port=0, launcher=launcher)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        code, body = request(base + "/api/analysis", {"symbol": "NVDA"})
        assert code == 202 and json.loads(body)["status"] == "running"
        assert request(base + "/api/analysis", {"symbol": "NVDA"})[0] == 409
        assert json.loads(request(base + "/api/analysis")[1])["symbol"] == "NVDA"
        assert not (root / "data/status.json").exists()
    finally:
        server.shutdown(); thread.join(); server.server_close()


def test_analyze_all_launches_enabled_subscriptions_with_shared_lock(tmp_path):
    root = project(tmp_path)
    path = root / "config/watchlist.yaml"
    with path.open("a") as stream:
        stream.write("  - {symbol: TSLA, type: stock}\n  - {symbol: MSFT, type: stock, enabled: false}\n")
    calls = []
    process = SimpleNamespace(poll=lambda: None)
    def launch(command, **kwargs):
        calls.append(command)
        return process
    launcher = AnalysisLauncher(root, popen=launch, clock=lambda: datetime(2026, 10, 2, 8, 40, tzinfo=NEW_YORK))
    server = create_server(root, port=0, launcher=launcher)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        code, body = request(base + "/api/analysis", {"scope": "all"})
        assert code == 202 and json.loads(body)["active_symbols"] == ["NVDA", "TSLA"]
        assert calls[0][-3:] == ["--tickers", "NVDA,TSLA", "--force"]
        assert request(base + "/api/analysis", {"scope": "all"})[0] == 409
        assert request(base + "/api/analysis", {"symbol": "NVDA"})[0] == 409
        assert len(calls) == 1 and not (root / "data/status.json").exists()
        process.poll = lambda: 0
        assert request(base + "/api/analysis", {"scope": "bad"})[0] == 400
        raw = yaml.safe_load(path.read_text())
        for row in raw["items"]:
            row["enabled"] = False
        path.write_text(yaml.safe_dump(raw))
        code, body = request(base + "/api/analysis", {"scope": "all"})
        assert code == 400 and "没有启用" in json.loads(body)["error"]
    finally:
        server.shutdown(); thread.join(); server.server_close()


def test_settings_preserve_hidden_values_and_validate_atomically(tmp_path, monkeypatch):
    root = project(tmp_path)
    path = root / "config/settings.yaml"
    path.write_text("llm:\n  call_timeout_seconds: 720\nrun:\n  max_duration_minutes: 160\nfutu:\n  port: 12345\n")
    store = SettingsStore(root)
    store.update({"llm": {"quick": {"model": "gpt-6.1-sol", "reasoning_effort": "medium"},
                          "deep": {"model": "gpt-6.1-sol", "reasoning_effort": "xhigh"},
                          "max_concurrent_calls": 2}, "run": {"max_parallel_tickers": 1}})
    raw = yaml.safe_load(path.read_text())
    assert raw["llm"]["call_timeout_seconds"] == 720 and raw["futu"]["port"] == 12345
    assert raw["run"]["max_duration_minutes"] == 160
    original = path.read_bytes()
    for command in ({"run": {"max_parallel_tickers": 0}}, {"llm": {"deep": {"reasoning_effort": "bad"}}},
                    {"llm": {"provider": "bad"}}, {"futu": {"enabled": False}},
                    {"llm": {"deep": {"model": "未列出的模型"}}}, {"llm": {"quick": {"reasoning_effort": "high"}}}):
        with pytest.raises(ConfigurationError):
            store.update(command)
        assert path.read_bytes() == original
    with http(root) as base:
        assert json.loads(request(base + "/api/settings")[1])["llm"]["deep"]["reasoning_effort"] == "xhigh"
        html = request(base + "/")[1]
        assert 'id="settings-form"' in html and '<select name="quick_model"' in html
        assert 'list="model-options"' not in html and "模型名可自行填写" not in html
        assert request(base + "/api/settings", {"run": {"max_parallel_tickers": 2}})[0] == 200
    original = path.read_bytes()
    def fail_replace(*args):
        raise OSError("模拟保存失败")
    monkeypatch.setattr("daily_analyzer.viewer.os.replace", fail_replace)
    with pytest.raises(OSError):
        store.update({"run": {"max_parallel_tickers": 3}})
    assert path.read_bytes() == original


def test_progress_recovers_symbols_and_estimates_from_matching_history(tmp_path):
    root = project(tmp_path)
    now = [datetime(2026, 10, 2, 8, 45, tzinfo=NEW_YORK)]
    batch_dir = root / "data/runs/2026-10-02/batches/current"
    config = {"quick": {"model": "gpt-6.1-sol", "reasoning_effort": "medium"},
              "deep": {"model": "gpt-6.1-sol", "reasoning_effort": "xhigh"}}
    batch = {"run_id": "current", "effective_config": config,
             "items": {"NVDA": {"symbol": "NVDA", "status": "running"}}}
    atomic_write_json(batch_dir / "batch.json", batch)
    atomic_write_json(root / "data/status.json", {"last_run": {"run_id": "current", "trade_date": "2026-10-02", "started_at": "2026-10-02T08:40:00-04:00", "status": "running"}})
    atomic_write_json(batch_dir / "results/NVDA/progress.json", {"stage": "新闻分析", "started_at": "2026-10-02T08:40:00-04:00"})
    for number, duration in enumerate([500, 600, 700]):
        atomic_write_json(root / f"data/runs/2026-10-01/batches/sample{number}/batch.json", {
            "run_id": f"sample{number}", "effective_config": config,
            "items": {"NVDA": {"symbol": "NVDA", "status": "success", "duration_seconds": duration},
                      "SPY": {"symbol": "SPY", "status": "success", "duration_seconds": 3000},
                      "FAILED": {"symbol": "FAILED", "status": "failed", "duration_seconds": 1}}})
    atomic_write_json(root / "data/runs/2026-10-01/batches/old/batch.json", {
        "run_id": "old", "effective_config": {},
        "items": {"NVDA": {"symbol": "NVDA", "status": "success", "duration_seconds": 60}}})
    launcher = AnalysisLauncher(root, clock=lambda: now[0])
    with run_lock(root):
        value = launcher.snapshot()
        assert value["active_symbols"] == ["NVDA"]
        item = value["items"]["NVDA"]
        assert item["stage"] == "新闻分析" and item["elapsed_seconds"] == 300
        assert item["estimated_percent"] == 50 and item["remaining_seconds"] == 300
        assert item["estimate_source"] == "同模型与强度" and item["estimate_samples"] == 3
        now[0] = datetime(2026, 10, 2, 8, 55, tzinfo=NEW_YORK)
        item = launcher.snapshot()["items"]["NVDA"]
        assert item["estimated_percent"] == 95 and item["overdue"]
    assert launcher.snapshot()["active_symbols"] == []


def test_progress_no_history_and_other_config_reference(tmp_path):
    from daily_analyzer.manual_analysis import _item_progress
    root = project(tmp_path)
    batch_dir = root / "data/runs/2026-10-02/batches/current"
    batch = {"run_id": "current", "effective_config": {"quick": {"model": "新模型"}},
             "items": {"NVDA": {"symbol": "NVDA", "status": "running"}}}
    atomic_write_json(batch_dir / "results/NVDA/progress.json", {"stage": "交易员方案", "started_at": "2026-10-02T08:40:00-04:00"})
    now = datetime(2026, 10, 2, 8, 45, tzinfo=NEW_YORK)
    item = _item_progress(root, batch_dir, batch, now)["NVDA"]
    assert item["estimated_percent"] is None and item["remaining_seconds"] is None
    atomic_write_json(root / "data/runs/2026-10-01/batches/old/batch.json", {
        "run_id": "old", "items": {"SPY": {"symbol": "SPY", "status": "success", "duration_seconds": 600}}})
    item = _item_progress(root, batch_dir, batch, now)["NVDA"]
    assert item["estimated_percent"] == 50 and item["estimate_source"] == "其他配置参考"
    batch["items"]["NVDA"].update(status="success", duration_seconds=650)
    item = _item_progress(root, batch_dir, batch, now)["NVDA"]
    assert item["estimated_percent"] == 100 and item["elapsed_seconds"] == 650

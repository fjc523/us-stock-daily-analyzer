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
from daily_analyzer.viewer import WatchlistStore, create_server


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

import json
import importlib
import os
import plistlib
import subprocess
import sys
import types
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from daily_analyzer.deployment import (
    PLIST_NAME,
    doctor,
    render_plist,
    schedule_install,
    schedule_status,
    schedule_trigger_times,
    schedule_uninstall,
)
from daily_analyzer.config import load_settings


class _FakeRunner:
    def __init__(self, *, version: str = "codex-cli 0.159.3", path_ok: bool = True, wake: bool = True, login_output: str = "Logged in using ChatGPT\n"):
        self.version = version
        self.path_ok = path_ok
        self.wake = wake
        self.login_output = login_output
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str], **kwargs):
        self.calls.append(command)
        if command[:2] == ["git", "-C"]:
            if command[3:] == ["rev-parse", "HEAD"]:
                return subprocess.CompletedProcess(command, 0, "abc123456789\n", "")
            if command[3:] == ["status", "--porcelain"]:
                return subprocess.CompletedProcess(command, 0, "", "")
            if command[3:] == ["rev-list", "--left-right", "--count", "HEAD...origin/main"]:
                return subprocess.CompletedProcess(command, 0, "0\t0\n", "")
        if command[-1:] == ["--version"]:
            if command[0] == "/usr/bin/env":
                result = 0 if self.path_ok else 127
                output = "codex-cli 0.159.3\n" if self.path_ok else "codex: command not found\n"
                return subprocess.CompletedProcess(command, result, output, "")
            return subprocess.CompletedProcess(command, 0, self.version + "\n", "")
        if command[-2:] == ["login", "status"]:
            return subprocess.CompletedProcess(command, 0, self.login_output, "")
        if command[-2:] == ["-g", "sched"]:
            output = "Repeating power events:\n  wakepoweron at 20:15 every weekday\n" if self.wake else "Repeating power events:\n  No scheduled power events.\n"
            return subprocess.CompletedProcess(command, 0, output, "")
        return subprocess.CompletedProcess(command, 0, "state = running\n", "")


def _write_settings(root: Path, codex: Path) -> None:
    config = root / "config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "settings.yaml").write_text(f"codex:\n  binary: {codex}\n", encoding="utf-8")
    secrets = config / "secrets.env"
    secrets.write_text("APCA_API_KEY_ID=test-key\nAPCA_API_SECRET_KEY=test-secret\n", encoding="utf-8")
    secrets.chmod(0o600)


def _write_fake_fork(root: Path, monkeypatch) -> Path:
    package = root / "TradingAgents" / "tradingagents"
    for name in ("llm_clients", "graph", "dataflows", "dataflows/vendors/alpaca", "agents"):
        (package / name).mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "llm_clients" / "factory.py").write_text(
        "def create_llm_client(provider, model, base_url=None, **kwargs):\n"
        "    provider_lower = provider.lower()\n"
        "    if provider_lower == 'codex_exec':\n"
        "        from .codex_exec import CodexExecClient\n"
        "        return CodexExecClient(model, base_url, **kwargs)\n"
        "def build_llm_kwargs(config, role=None):\n"
        "    kwargs = {}\n"
        "    provider = config.get('llm_provider', '').lower()\n"
        "    if provider == 'codex_exec':\n"
        "        role_effort = config.get(f'codex_{role}_reasoning_effort') if role else None\n"
        "        kwargs['reasoning_effort'] = role_effort or config.get('codex_reasoning_effort') or 'high'\n"
        "        kwargs['role'] = role\n"
        "    return kwargs\n",
        encoding="utf-8",
    )
    (package / "graph" / "trading_graph.py").write_text(
        "_NOT_IN_SIGNATURE = frozenset({'codex_binary', 'codex_usage_log_path', 'codex_prompt_log_dir'})\n"
        "def _run_signature(self):\n"
        "    settings = {k: v for k, v in self.config.items() if k not in _NOT_IN_SIGNATURE}\n"
        "    return settings\n",
        encoding="utf-8",
    )
    (package / "default_config.py").write_text(
        "market_timezone = None\nprice_data_end_date = None\nnews_cutoff_utc = None\n",
        encoding="utf-8",
    )
    (package / "dataflows" / "date_window.py").write_text(
        "def get_current_date():\n"
        "    timezone = get_config().get('market_timezone')\n"
        "    if timezone:\n"
        "        return datetime.now(ZoneInfo(timezone)).date().isoformat()\n"
        "    return date.today().isoformat()\n"
        "def in_window(pub_dt, start_dt, end_dt):\n"
        "    end = end_dt + timedelta(days=1)\n"
        "    cutoff = get_config().get('news_cutoff_utc')\n"
        "    if cutoff:\n"
        "        cutoff_dt = datetime.fromisoformat(cutoff)\n"
        "        end = min(end, to_utc(cutoff_dt))\n"
        "    return to_utc(start_dt) <= to_utc(pub_dt) < end\n",
        encoding="utf-8",
    )
    (package / "dataflows" / "router.py").write_text(
        "VENDOR_METHODS = {\n"
        "    'get_news': {'alpaca': get_alpaca_news},\n"
        "    'get_global_news': {'alpaca': get_alpaca_global_news},\n"
        "}\n",
        encoding="utf-8",
    )
    (package / "agents" / "tools.py").write_text(
        "def get_stock_data(start_date, end_date, trade_date):\n"
        "    start_date, end_date = as_of_window(start_date, end_date, price_data_end_date(trade_date))\n"
        "def get_indicators(curr_date, trade_date):\n"
        "    return as_of(curr_date, price_data_end_date(trade_date))\n"
        "def get_verified_market_snapshot(curr_date, trade_date):\n"
        "    return build_snapshot(as_of(curr_date, price_data_end_date(trade_date)))\n",
        encoding="utf-8",
    )
    (package / "dataflows" / "vendors" / "alpaca" / "client.py").write_text(
        "_SINGLETON = object()\n"
        "def get_shared_client():\n    return _SINGLETON\n",
        encoding="utf-8",
    )
    (package / "dataflows" / "vendors" / "alpaca" / "news.py").write_text(
        "from .client import get_shared_client\n"
        "def _read(symbols, start, end):\n"
        "    return get_shared_client().get_news(symbols, start, end, limit=None)\n",
        encoding="utf-8",
    )
    module = importlib.import_module("daily_analyzer.deployment.doctor")
    monkeypatch.setattr(
        module.importlib.util,
        "find_spec",
        lambda name: SimpleNamespace(origin=str(package / "__init__.py")) if name == "tradingagents" else None,
    )
    return package


def _probe_set(ping: dict | None = None) -> dict:
    values = {
        "alpaca": lambda: {"ok": True, "detail": "历史日线可用", "remaining": 187},
        "futu": lambda: {"ok": True, "detail": "OpenD 已连接", "remaining": 88},
        "yfinance": lambda: {"ok": True, "detail": "Yahoo 可用"},
    }
    if ping is not None:
        values["ping"] = lambda: ping
    return values


def _doctor_fixture(tmp_path: Path, monkeypatch, *, runner: _FakeRunner | None = None) -> tuple[Path, Path, _FakeRunner]:
    root = tmp_path / "project"
    root.mkdir()
    home = tmp_path / "user"
    codex = home / "nvm" / "bin" / "codex"
    codex.parent.mkdir(parents=True)
    codex.write_text("", encoding="utf-8")
    codex.chmod(0o755)
    _write_settings(root, codex)
    for name in ("data", "site", "logs"):
        (root / name).mkdir()
    _write_fake_fork(root, monkeypatch)
    launch_agents = home / "Library" / "LaunchAgents"
    launch_agents.mkdir(parents=True)
    plist = render_plist(root, local_timezone="Asia/Shanghai", codex_binary=str(codex), home=home, year=2026)
    (launch_agents / PLIST_NAME).write_text(plist, encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("TZ", "Asia/Shanghai")
    return root, home, runner or _FakeRunner()


def test_trigger_conversion_and_rendered_plist_cover_dst_and_fixed_offset(tmp_path: Path) -> None:
    beijing = ZoneInfo("Asia/Shanghai")
    assert schedule_trigger_times("08:30 America/New_York", local_timezone=beijing, year=2026) == [
        {"Hour": 20, "Minute": 30},
        {"Hour": 21, "Minute": 30},
    ]
    assert schedule_trigger_times("08:30 Etc/GMT+4", local_timezone=beijing, year=2026) == [
        {"Hour": 20, "Minute": 30},
    ]
    assert schedule_trigger_times("08:30 America/Phoenix", local_timezone=beijing, year=2026) == [
        {"Hour": 23, "Minute": 30},
    ]

    codex = tmp_path / "nvm" / "bin" / "codex"
    root = tmp_path / "project"
    root.mkdir()
    _write_settings(root, codex)
    plist = plistlib.loads(
        render_plist(root, local_timezone="Asia/Shanghai", codex_binary=str(codex), home=tmp_path, year=2026).encode()
    )
    assert plist["ProgramArguments"] == [
        "/usr/bin/caffeinate", "-i", str(root / ".venv" / "bin" / "python"),
        "-m", "daily_analyzer", "run", "--scheduled",
    ]
    assert plist["WorkingDirectory"] == str(root)
    assert plist["StartCalendarInterval"] == [{"Hour": 20, "Minute": 30}, {"Hour": 21, "Minute": 30}]
    assert str(codex.parent) in plist["EnvironmentVariables"]["PATH"]
    assert plist["EnvironmentVariables"]["PYTHONUNBUFFERED"] == "1"
    assert "secrets" not in str(plist)


def test_install_status_and_uninstall_use_only_injected_launchctl(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    home = tmp_path / "user"
    launch_agents = home / "Library" / "LaunchAgents"
    _write_settings(root, tmp_path / "codex")
    runner = _FakeRunner()
    install = schedule_install(root, runner=runner, launch_agents_dir=launch_agents, local_timezone="Asia/Shanghai")
    plist_path = launch_agents / PLIST_NAME
    assert install["ok"] is True
    assert install["triggers"] == ["20:30", "21:30"]
    assert runner.calls[0][1] == "bootout"
    assert runner.calls[-1][1] == "bootstrap"
    assert plist_path.is_file()

    status_file = root / "data" / "status.json"
    status_file.parent.mkdir(parents=True)
    status_file.write_text(
        json.dumps({
            "last_run": {"trade_date": "2026-10-01", "mode": "live", "status": "partial", "started_at": "2026-10-01T12:31:00Z", "finished_at": "2026-10-01T13:10:00Z", "progress": {"completed": 3, "total": 4}},
            "last_schedule_event": {"trade_date": "2026-10-01", "result": "skipped_already_done", "reason": "今日已运行"},
        }),
        encoding="utf-8",
    )
    status = schedule_status(
        root,
        now=datetime(2026, 10, 2, 12, 0, tzinfo=ZoneInfo("UTC")),
        runner=runner,
        launch_agents_dir=launch_agents,
    )
    assert status["installed"] is True and status["loaded"] is True
    assert status["triggers"] == ["20:30", "21:30"]
    assert status["today_anchor_beijing"] == "2026-10-02 20:30 北京时间"
    assert "2026-10-05 20:30" in status["next_trading_day_anchor_beijing"]
    assert status["last_run"]["status"] == "partial"
    assert status["last_schedule_event"]["result"] == "skipped_already_done"

    uninstalled = schedule_uninstall(root, runner=runner, launch_agents_dir=launch_agents)
    assert uninstalled["ok"] is True
    assert not plist_path.exists()
    assert [call[1] for call in runner.calls if call[0] == "launchctl"].count("bootout") == 2


def test_doctor_success_uses_mocked_read_only_probes_and_reports_ping(tmp_path: Path, monkeypatch) -> None:
    root, home, runner = _doctor_fixture(tmp_path, monkeypatch)
    now = datetime(2026, 10, 2, 8, 30, tzinfo=ZoneInfo("America/New_York"))
    result = doctor(root, ping=True, runner=runner, now=now, probes=_probe_set({
        "ok": True,
        "detail": "模型调用成功",
        "duration_seconds": 1.25,
        "input_tokens": 19,
        "config_drift": [],
    }))
    assert result["ok"] is True
    checks = {item["name"]: item for item in result["checks"]}
    assert checks["Codex 极小推理"]["status"] == "pass"
    assert checks["ChatGPT 登录"]["status"] == "pass"
    assert "输入 token 19" in checks["Codex 极小推理"]["detail"]
    assert checks["Alpaca 连通与剩余限额"]["status"] == "pass"
    assert "剩余限额 187" in checks["Alpaca 连通与剩余限额"]["detail"]
    assert all(checks[f"fork 修改：{name}"]["status"] == "pass" for name in (
        "codex_exec provider 注册", "按角色传递 LLM 参数", "精简配置项不进入签名",
        "市场时区日期", "Alpaca 共享客户端", "Alpaca 新闻注册", "日线截止日", "新闻截止时刻",
    ))
    assert not any("auth" in " ".join(call).lower() for call in runner.calls)
    assert all(call[0] != "pmset" or call[1:3] == ["-g", "sched"] for call in runner.calls)


def test_doctor_reports_failure_warning_and_config_drift_cases(tmp_path: Path, monkeypatch) -> None:
    root, home, runner = _doctor_fixture(tmp_path, monkeypatch, runner=_FakeRunner(version="codex-cli 0.142.5", path_ok=False, wake=False))
    secrets = root / "config" / "secrets.env"
    secrets.chmod(0o644)
    plist_path = home / "Library" / "LaunchAgents" / PLIST_NAME
    plist = plistlib.loads(plist_path.read_bytes())
    plist["EnvironmentVariables"]["PATH"] = "/usr/bin"
    plist_path.write_bytes(plistlib.dumps(plist))
    now = datetime(2026, 10, 2, 8, 30, tzinfo=ZoneInfo("America/New_York"))
    result = doctor(root, ping=True, runner=runner, now=now, probes=_probe_set({
        "ok": True,
        "duration_seconds": 2,
        "input_tokens": 55,
        "config_drift": ["include_environment_context"],
    }))
    checks = {item["name"]: item for item in result["checks"]}
    assert result["ok"] is False
    assert checks["Codex 版本"]["status"] == "fail"
    assert checks["项目内 Alpaca 凭据"]["status"] == "fail"
    assert checks["LaunchAgent PATH 可找到 Codex"]["status"] == "fail"
    assert checks["定时唤醒"]["status"] == "warning"
    assert "sudo pmset repeat wakeorpoweron MTWRF" in checks["定时唤醒"]["detail"]
    assert checks["Codex 极小推理"]["status"] == "warning"
    assert "include_environment_context" in checks["Codex 极小推理"]["detail"]


def test_doctor_detects_uninitialized_submodule_and_requires_only_codex_status(tmp_path: Path, monkeypatch) -> None:
    root, home, runner = _doctor_fixture(tmp_path, monkeypatch)
    import shutil as shutil_module

    shutil_module.rmtree(root / "TradingAgents")
    result = doctor(root, runner=runner, now=datetime(2026, 10, 2, 8, 30, tzinfo=ZoneInfo("America/New_York")), probes=_probe_set())
    checks = {item["name"]: item for item in result["checks"]}
    assert checks["TradingAgents 子模块"]["status"] == "fail"
    assert "git submodule update --init" in checks["TradingAgents 子模块"]["detail"]
    assert any(call[-2:] == ["login", "status"] for call in runner.calls)
    assert not any("auth" in " ".join(call).lower() for call in runner.calls)


def test_doctor_does_not_treat_api_key_login_as_chatgpt_login(tmp_path: Path, monkeypatch) -> None:
    api_key_runner = _FakeRunner(login_output="Logged in using API key\n")
    root, _home, _runner = _doctor_fixture(tmp_path, monkeypatch, runner=api_key_runner)
    result = doctor(
        root,
        runner=api_key_runner,
        now=datetime(2026, 10, 2, 8, 30, tzinfo=ZoneInfo("America/New_York")),
        probes=_probe_set(),
    )
    checks = {item["name"]: item for item in result["checks"]}
    assert checks["ChatGPT 登录"]["status"] == "fail"
    assert checks["ChatGPT 登录"]["detail"] == "Logged in using API key"


def test_default_external_probes_use_mock_clients_and_close_futu(tmp_path: Path, monkeypatch) -> None:
    module = importlib.import_module("daily_analyzer.deployment.doctor")
    root = tmp_path / "project"
    root.mkdir()
    _write_settings(root, tmp_path / "codex")
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)

    calls = []

    class AlpacaClient:
        rate_limit_remaining = 181

        def get_bars(self, **kwargs):
            calls.append(("alpaca", kwargs, os.environ.get("APCA_API_KEY_ID"), os.environ.get("APCA_API_SECRET_KEY")))
            return {"SPY": [{"close": 500}]}

    alpaca_module = types.ModuleType("tradingagents.dataflows.vendors.alpaca.client")
    alpaca_module.get_shared_client = lambda: AlpacaClient()
    monkeypatch.setitem(sys.modules, "tradingagents.dataflows.vendors.alpaca.client", alpaca_module)
    weekend = datetime(2026, 10, 3, 10, 0, tzinfo=ZoneInfo("America/New_York"))
    alpaca = module._probe_alpaca(root, now=weekend)
    assert alpaca["ok"] is True and alpaca["remaining"] == 181
    assert calls[0][1]["symbols"] == ["SPY"]
    assert calls[0][1]["feed"] == "sip" and calls[0][1]["adjustment"] == "all"
    assert calls[0][1]["timeframe"] == "1Day"
    assert calls[0][1]["end"] == "2026-10-02"
    assert calls[0][1]["start"] == "2026-09-25"
    assert calls[0][2:] == ("test-key", "test-secret")
    assert os.environ.get("APCA_API_KEY_ID") is None
    assert "test-secret" not in json.dumps(alpaca)

    holiday = datetime(2026, 11, 26, 10, 0, tzinfo=ZoneInfo("America/New_York"))
    holiday_probe = module._probe_alpaca(root, now=holiday)
    assert holiday_probe["ok"] is True
    assert calls[-1][1]["end"] == "2026-11-25"

    futu_module = types.ModuleType("futu")
    futu_module.RET_OK = 0

    class OpenQuoteContext:
        def __init__(self, **kwargs):
            calls.append(("futu-open", kwargs))

        def query_subscription(self):
            calls.append(("futu-query",))
            return 0, {"remain": 74}

        def close(self):
            calls.append(("futu-close",))

    futu_module.OpenQuoteContext = OpenQuoteContext
    monkeypatch.setitem(sys.modules, "futu", futu_module)
    futu = module._probe_futu(load_settings(root))
    assert futu["ok"] is True and futu["remaining"] == 74
    assert calls[-1] == ("futu-close",)

    yahoo_module = types.ModuleType("yfinance")

    class Frame:
        empty = False

    class Ticker:
        def __init__(self, symbol):
            assert symbol == "SPY"

        def history(self, **kwargs):
            calls.append(("yahoo", kwargs))
            return Frame()

    yahoo_module.Ticker = Ticker
    monkeypatch.setitem(sys.modules, "yfinance", yahoo_module)
    yahoo = module._probe_yfinance()
    assert yahoo["ok"] is True


def test_fork_feature_checks_require_active_feature_consumers(tmp_path: Path, monkeypatch) -> None:
    module = importlib.import_module("daily_analyzer.deployment.doctor")
    root = tmp_path / "project"
    root.mkdir()
    package = _write_fake_fork(root, monkeypatch)
    mutations = [
        (
            "llm_clients/factory.py",
            "return CodexExecClient(model, base_url, **kwargs)",
            "return None",
            "fork 修改：codex_exec provider 注册",
        ),
        (
            "llm_clients/factory.py",
            "role_effort = config.get(f'codex_{role}_reasoning_effort') if role else None",
            "role_effort = None",
            "fork 修改：按角色传递 LLM 参数",
        ),
        (
            "graph/trading_graph.py",
            "settings = {k: v for k, v in self.config.items() if k not in _NOT_IN_SIGNATURE}",
            "settings = dict(self.config)",
            "fork 修改：精简配置项不进入签名",
        ),
        (
            "dataflows/date_window.py",
            "timezone = get_config().get('market_timezone')",
            "timezone = None\n    unused = 'market_timezone'",
            "fork 修改：市场时区日期",
        ),
        (
            "dataflows/vendors/alpaca/news.py",
            "return get_shared_client().get_news(symbols, start, end, limit=None)",
            "return []",
            "fork 修改：Alpaca 共享客户端",
        ),
        (
            "dataflows/router.py",
            "{'alpaca': get_alpaca_news}",
            "{'yfinance': get_news_yfinance}",
            "fork 修改：Alpaca 新闻注册",
        ),
        (
            "agents/tools.py",
            "price_data_end_date(trade_date)",
            "trade_date",
            "fork 修改：日线截止日",
        ),
        (
            "dataflows/date_window.py",
            "end = min(end, to_utc(cutoff_dt))",
            "end = end",
            "fork 修改：新闻截止时刻",
        ),
    ]
    for relative, old, new, check_name in mutations:
        path = package / relative
        original = path.read_text(encoding="utf-8")
        assert old in original
        path.write_text(original.replace(old, new), encoding="utf-8")
        checks = {name: ok for name, ok, _detail in module._fork_feature_checks(package)}
        assert checks[check_name] is False
        path.write_text(original, encoding="utf-8")


def test_default_ping_uses_current_model_with_strict_schema_without_cli_process(tmp_path: Path, monkeypatch) -> None:
    module = importlib.import_module("daily_analyzer.deployment.doctor")
    root = tmp_path / "project"
    root.mkdir()
    codex = tmp_path / "nvm" / "bin" / "codex"
    _write_settings(root, codex)
    calls = []
    runner_module = types.ModuleType("tradingagents.llm_clients.codex_exec.runner")
    runner_module.reset_abort = lambda: calls.append(("reset-abort",))

    class CodexExecRunner:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs))

        def run(self, prompt, schema):
            calls.append(("run", prompt, schema))
            return SimpleNamespace(output={"ok": True}, events={"usage": {"input_tokens": 23}, "config_drift": []})

    runner_module.CodexExecRunner = CodexExecRunner
    monkeypatch.setitem(sys.modules, "tradingagents.llm_clients.codex_exec.runner", runner_module)
    result = module._probe_ping(root, load_settings(root))
    assert result["ok"] is True
    assert result["input_tokens"] == 23
    assert calls[0] == ("reset-abort",)
    assert calls[1][1]["model"] == "gpt-6.1-sol"
    assert calls[1][1]["reasoning_effort"] == "high"
    assert calls[1][1]["retries"] == 0
    assert calls[2][2]["additionalProperties"] is False

"""本机运行环境与只读外部依赖自检。"""

from __future__ import annotations

import ast
import importlib.metadata
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import exchange_calendars as xcals

from daily_analyzer.config import ConfigurationError, load_credentials, load_settings, parse_settings
from daily_analyzer.deployment.schedule import (
    LABEL,
    PLIST_NAME,
    _anchor_parts,
    _call,
    _codex_binary,
    _default_launch_agents_dir,
    _launch_domain,
    _result_detail,
    machine_timezone,
    schedule_trigger_times,
    schedule_calendar_intervals,
)

Probe = Callable[[], Mapping[str, Any]]
_NEW_YORK = ZoneInfo("America/New_York")
_BEIJING = ZoneInfo("Asia/Shanghai")


def _version_tuple(value: str) -> tuple[int, ...] | None:
    match = re.search(r"\b(\d+(?:\.\d+){1,3})\b", value)
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def _as_completed(result: Any) -> tuple[int, str, str]:
    return (
        int(getattr(result, "returncode", 1)),
        str(getattr(result, "stdout", "") or ""),
        str(getattr(result, "stderr", "") or ""),
    )


def _add(
    checks: list[dict[str, str]],
    name: str,
    status: str,
    detail: str,
) -> None:
    checks.append({"name": name, "status": status, "detail": detail})


def _failure_detail(exc: Exception, secrets: tuple[str, ...] = ()) -> str:
    value = str(exc)
    for secret in secrets:
        if secret:
            value = value.replace(secret, "[已隐藏]")
    return f"{type(exc).__name__}: {value[:240]}"


def _probe_alpaca(project_root: Path, *, now: datetime | None = None) -> Mapping[str, Any]:
    credentials = load_credentials(project_root, require_alpaca=True)
    key_id = credentials.alpaca_key_id.get_secret_value() if credentials.alpaca_key_id else ""
    secret_key = credentials.alpaca_secret_key.get_secret_value() if credentials.alpaca_secret_key else ""
    try:
        from unittest.mock import patch

        with patch.dict(os.environ, {"APCA_API_KEY_ID": key_id, "APCA_API_SECRET_KEY": secret_key}):
            from tradingagents.dataflows.vendors.alpaca.client import get_shared_client

            client = get_shared_client()
            current = now or datetime.now(_NEW_YORK)
            if current.tzinfo is None:
                current = current.replace(tzinfo=_NEW_YORK)
            from daily_analyzer.context.market_data import previous_trading_day

            end_day = previous_trading_day(current.astimezone(_NEW_YORK).date())
            bars = client.get_bars(
                symbols=["SPY"],
                start=(end_day - timedelta(days=7)).isoformat(),
                end=end_day.isoformat(),
                feed="sip",
                adjustment="all",
                timeframe="1Day",
            )
            remaining = client.rate_limit_remaining
        return {
            "ok": isinstance(bars, Mapping),
            "detail": (
                "Alpaca 历史日线查询成功"
                if remaining is not None
                else "Alpaca 历史日线查询成功，但响应未提供剩余请求数"
            ) if isinstance(bars, Mapping) else "Alpaca 返回格式不正确",
            "remaining": remaining,
            "warning": remaining is None,
        }
    except Exception as exc:
        return {"ok": False, "error": _failure_detail(exc, (key_id, secret_key))}


def _probe_futu(settings: Any) -> Mapping[str, Any]:
    if not settings.futu.enabled:
        return {"ok": True, "detail": "配置已停用富途连接", "skipped": True}
    context = None
    try:
        from futu import OpenQuoteContext, RET_OK

        context = OpenQuoteContext(host=settings.futu.host, port=settings.futu.port)
        ret, data = context.query_subscription()
        if ret != RET_OK:
            return {"ok": False, "error": str(data)}
        return {
            "ok": True,
            "remaining": int(data["remain"]),
            "detail": "OpenD 连接成功，已读取订阅剩余额度",
        }
    except Exception as exc:
        return {"ok": False, "error": _failure_detail(exc)}
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass


def _probe_yfinance() -> Mapping[str, Any]:
    try:
        import yfinance

        data = yfinance.Ticker("SPY").history(period="5d", interval="1d", auto_adjust=True)
        if data is None or data.empty:
            return {"ok": False, "error": "Yahoo 未返回 SPY 日线"}
        return {"ok": True, "detail": "Yahoo SPY 日线查询成功"}
    except Exception as exc:
        return {"ok": False, "error": _failure_detail(exc)}


def _usage_input_tokens(value: Any) -> int | None:
    if isinstance(value, Mapping):
        for key in ("input_tokens", "prompt_tokens", "input_token_count"):
            item = value.get(key)
            if isinstance(item, (int, float)):
                return int(item)
        for child in value.values():
            result = _usage_input_tokens(child)
            if result is not None:
                return result
    elif isinstance(value, list):
        for child in value:
            result = _usage_input_tokens(child)
            if result is not None:
                return result
    return None


def _probe_ping(project_root: Path, settings: Any) -> Mapping[str, Any]:
    try:
        from tradingagents.llm_clients.codex_exec.runner import CodexExecRunner, reset_abort

        reset_abort()
        role = settings.llm.deep
        runner = CodexExecRunner(
            binary=_codex_binary(settings),
            model=role.model,
            reasoning_effort=role.reasoning_effort,
            timeout=settings.llm.call_timeout_seconds,
            retries=0,
            max_concurrency=1,
            usage_log_path=None,
            prompt_log_dir=None,
        )
        schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean", "const": True}},
            "required": ["ok"],
            "additionalProperties": False,
        }
        started = datetime.now().timestamp()
        result = runner.run("请仅返回 JSON：{\"ok\":true}。", schema)
        elapsed = max(0.0, datetime.now().timestamp() - started)
        events = result.events if isinstance(result.events, Mapping) else {}
        drift = events.get("config_drift", []) or []
        return {
            "ok": isinstance(result.output, Mapping) and result.output.get("ok") is True,
            "detail": f"{role.model} + {role.reasoning_effort} 调用成功",
            "duration_seconds": round(elapsed, 3),
            "input_tokens": _usage_input_tokens(events.get("usage")),
            "config_drift": drift,
        }
    except Exception as exc:
        return {"ok": False, "error": _failure_detail(exc)}


def _tzdata_version() -> str:
    try:
        return f"tzdata {importlib.metadata.version('tzdata')}"
    except importlib.metadata.PackageNotFoundError:
        for path in (
            Path("/usr/share/zoneinfo/tzdata.zi"),
            Path("/var/db/timezone/zoneinfo/tzdata.zi"),
        ):
            try:
                first = path.read_text(encoding="ascii").splitlines()[0]
            except (OSError, IndexError, UnicodeError):
                continue
            match = re.search(r"version\s+(\S+)", first)
            if match:
                return match.group(1)
    return "系统时区库版本未提供"


def _fork_feature_checks(package_root: Path) -> list[tuple[str, bool, str]]:
    def _target_source(relative: str, *, kind: str, name: str) -> str:
        try:
            source = (package_root / relative).read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, UnicodeError, SyntaxError):
            return ""
        for node in ast.walk(tree):
            if kind == "function" and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                return ast.get_source_segment(source, node) or ""
            if kind == "assignment" and isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(isinstance(target, ast.Name) and target.id == name for target in targets):
                    return ast.get_source_segment(source, node) or ""
        return ""

    factory = _target_source("llm_clients/factory.py", kind="function", name="create_llm_client")
    registered = bool(re.search(
        r"if\s+provider_lower\s*==\s*(['\"])codex_exec\1\s*:\s*"
        r"from\s+\.codex_exec\s+import\s+CodexExecClient\s*"
        r"return\s+CodexExecClient\s*\(", factory
    ))
    kwargs = _target_source("llm_clients/factory.py", kind="function", name="build_llm_kwargs")
    role_mapping = bool(
        re.search(r"def\s+build_llm_kwargs\s*\([^)]*\brole\b", kwargs)
        and re.search(r"(?:if|elif)\s+provider\s*==\s*['\"]codex_exec['\"]\s*:", kwargs)
        and re.search(r"config\.get\(f['\"]codex_\{role\}_reasoning_effort['\"]\)", kwargs)
        and re.search(r"config\.get\(['\"]codex_reasoning_effort['\"]\)", kwargs)
        and re.search(r"kwargs\[['\"]reasoning_effort['\"]\]\s*=\s*\(?\s*role_effort\b", kwargs)
        and re.search(r"kwargs\[['\"]role['\"]\]\s*=\s*role", kwargs)
    )

    signature_set = _target_source("graph/trading_graph.py", kind="assignment", name="_NOT_IN_SIGNATURE")
    signature_function = _target_source("graph/trading_graph.py", kind="function", name="_run_signature")
    signature_ok = all(
        re.search(rf"(['\"]){re.escape(key)}\1", signature_set)
        for key in ("codex_binary", "codex_usage_log_path", "codex_prompt_log_dir")
    ) and bool(re.search(r"if\s+k\s+not\s+in\s+_NOT_IN_SIGNATURE", signature_function))

    current_date = _target_source("dataflows/date_window.py", kind="function", name="get_current_date")
    timezone_active = bool(
        re.search(r"timezone\s*=\s*get_config\(\)\.get\(['\"]market_timezone['\"]\)", current_date)
        and re.search(r"return\s+datetime\.now\(ZoneInfo\(timezone\)\)\.date\(\)\.isoformat\(\)", current_date)
    )

    client = _target_source("dataflows/vendors/alpaca/client.py", kind="function", name="get_shared_client")
    alpaca_read = _target_source("dataflows/vendors/alpaca/news.py", kind="function", name="_read")
    shared_client_ok = bool(
        re.search(r"return\s+_SINGLETON\b", client)
        and re.search(r"get_shared_client\(\)\.get_news\(", alpaca_read)
    )

    router = _target_source("dataflows/router.py", kind="assignment", name="VENDOR_METHODS")
    router_news_ok = bool(
        re.search(r"['\"]get_news['\"]\s*:\s*\{[^}]*['\"]alpaca['\"]\s*:\s*get_alpaca_news\b", router)
        and re.search(r"['\"]get_global_news['\"]\s*:\s*\{[^}]*['\"]alpaca['\"]\s*:\s*get_alpaca_global_news\b", router)
    )

    stock_tool = _target_source("agents/tools.py", kind="function", name="get_stock_data")
    indicator_tool = _target_source("agents/tools.py", kind="function", name="get_indicators")
    snapshot_tool = _target_source("agents/tools.py", kind="function", name="get_verified_market_snapshot")
    price_cap_ok = all((
        re.search(r"as_of_window\([^\n]*price_data_end_date\(trade_date\)", stock_tool),
        re.search(r"as_of\([^\n]*price_data_end_date\(trade_date\)", indicator_tool),
        re.search(r"as_of\([^\n]*price_data_end_date\(trade_date\)", snapshot_tool),
    ))

    in_window = _target_source("dataflows/date_window.py", kind="function", name="in_window")
    news_cutoff_ok = bool(
        re.search(r"cutoff\s*=\s*get_config\(\)\.get\(['\"]news_cutoff_utc['\"]\)", in_window)
        and re.search(r"end\s*=\s*min\(end,\s*to_utc\(cutoff_dt\)\)", in_window)
    )

    return [
        ("fork 修改：codex_exec provider 注册", bool(registered), "检查 create_llm_client 的分支导入与实例化"),
        ("fork 修改：按角色传递 LLM 参数", bool(role_mapping), "检查 build_llm_kwargs 的角色键读取与参数传递"),
        ("fork 修改：精简配置项不进入签名", bool(signature_ok), "检查 _run_signature 实际排除路径配置"),
        ("fork 修改：市场时区日期", bool(timezone_active), "检查 get_current_date 实际用市场时区取日期"),
        ("fork 修改：Alpaca 共享客户端", bool(shared_client_ok), "检查单例入口与 Alpaca 新闻实际调用"),
        ("fork 修改：Alpaca 新闻注册", bool(router_news_ok), "检查 router 中个股与全球新闻的 Alpaca 映射"),
        ("fork 修改：日线截止日", bool(price_cap_ok), "检查股票、指标、验证快照均消费价格截止日"),
        ("fork 修改：新闻截止时刻", bool(news_cutoff_ok), "检查 in_window 实际夹紧新闻窗口上界"),
    ]


def _status_json(root: Path) -> Mapping[str, Any]:
    path = root / "data" / "status.json"
    if not path.is_file():
        return {}
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
        return result if isinstance(result, Mapping) else {}
    except (OSError, ValueError):
        return {}


def _anchor_report(anchor: str, now: datetime) -> tuple[str, str]:
    today = now.astimezone(_NEW_YORK).date()
    calendar = xcals.get_calendar("XNYS")
    sessions = calendar.sessions_in_range(today.isoformat(), (today + timedelta(days=20)).isoformat())
    dates = [session.date() for session in sessions]
    is_today_session = today in dates
    next_session = next((day for day in dates if day > today), dates[0] if dates else None)
    if not is_today_session:
        next_session = next((day for day in dates if day >= today), None)
    hour, minute, zone_name = _anchor_parts(anchor)
    anchor_zone = ZoneInfo(zone_name)
    today_value = datetime.combine(today, time(hour, minute), anchor_zone).astimezone(_BEIJING)
    next_value = datetime.combine(next_session, time(hour, minute), anchor_zone).astimezone(_BEIJING) if next_session else None
    return (
        f"今天 {today.isoformat()}：{today_value.strftime('%H:%M')} 北京时间（NYSE {'交易日' if is_today_session else '休市'}）",
        f"下一个交易日 {next_value.date().isoformat()}：{next_value.strftime('%H:%M')} 北京时间" if next_value else "下一个交易日：无法计算",
    )


def _wake_time(anchor: str, now: datetime) -> tuple[str, str]:
    today = now.astimezone(_NEW_YORK).date()
    hour, minute, zone_name = _anchor_parts(anchor)
    start = datetime.combine(today, time(hour, minute), ZoneInfo(zone_name)).astimezone(_BEIJING)
    wake = start - timedelta(minutes=15)
    command = f"sudo pmset repeat wakeorpoweron MTWRF {wake.strftime('%H:%M:%S')}"
    return wake.strftime("%H:%M"), command


def _pmset_has_wake_plan(output: str, anchor: str, now: datetime) -> bool:
    target, _ = _wake_time(anchor, now)
    target_hour, target_minute = map(int, target.split(":"))
    compact_12h = datetime.strptime(target, "%H:%M").strftime("%I:%M%p").lstrip("0").lower()
    normalized = output.lower().replace(" ", "")
    exact_24h = f"{target_hour:02d}:{target_minute:02d}"
    return exact_24h in normalized or compact_12h.replace(":", "") in normalized


def _writable(path: Path) -> tuple[bool, str]:
    target = path
    while not target.exists() and target != target.parent:
        target = target.parent
    writable = target.is_dir() and os.access(target, os.W_OK)
    return writable, "可写" if writable else "目录不存在或不可写"


def _load_plist(path: Path) -> Mapping[str, Any] | None:
    if not path.is_file():
        return None
    try:
        result = __import__("plistlib").loads(path.read_bytes())
    except (OSError, ValueError, TypeError):
        return {}
    return result if isinstance(result, Mapping) else {}


def _call_probe(name: str, probe: Probe, severity: str, checks: list[dict[str, str]]) -> Mapping[str, Any]:
    try:
        value = probe()
        result = value if isinstance(value, Mapping) else {"ok": False, "error": "探针返回格式不正确"}
    except Exception as exc:
        result = {"ok": False, "error": _failure_detail(exc)}
    if result.get("skipped"):
        status = "info"
    elif result.get("ok"):
        status = "pass" if not result.get("config_drift") and not result.get("warning") else "warning"
    else:
        status = severity
    details = []
    if result.get("detail"):
        details.append(str(result["detail"]))
    if result.get("remaining") is not None:
        details.append(f"剩余限额 {result['remaining']}")
    if result.get("duration_seconds") is not None:
        details.append(f"耗时 {result['duration_seconds']} 秒")
    if result.get("input_tokens") is not None:
        details.append(f"输入 token {result['input_tokens']}")
    if result.get("config_drift"):
        details.append("config_drift：" + "；".join(map(str, result["config_drift"])))
    if result.get("error"):
        details.append(str(result["error"]))
    _add(checks, name, status, "；".join(details) or "检查完成")
    return result


def doctor(
    project_root: str | Path,
    *,
    ping: bool = False,
    runner: Callable[..., Any] | None = None,
    now: datetime | None = None,
    probes: Mapping[str, Probe] | None = None,
) -> dict[str, Any]:
    """检查 Python、fork、Codex、数据源、定时任务与可写目录。"""
    root = Path(project_root).expanduser().resolve()
    checks: list[dict[str, str]] = []
    current = now or datetime.now(_NEW_YORK)
    if current.tzinfo is None:
        current = current.replace(tzinfo=_NEW_YORK)
    config_valid = True
    try:
        settings = load_settings(root)
    except Exception as exc:
        config_valid = False
        _add(checks, "配置读取", "fail", f"配置校验失败：{type(exc).__name__}: {exc}")
        settings = parse_settings({})
    is_venv = sys.prefix != sys.base_prefix
    py_ok = sys.version_info >= (3, 13) and is_venv
    _add(checks, "Python 与虚拟环境", "pass" if py_ok else "fail", f"Python {sys.version_info.major}.{sys.version_info.minor}；{'已进入 venv' if is_venv else '当前未运行在 venv'}")

    submodule = root / "TradingAgents"
    package_dir = submodule / "tradingagents"
    if not package_dir.is_dir():
        _add(checks, "TradingAgents 子模块", "fail", "子模块未初始化；请执行 git submodule update --init，再执行 pip install -e ./TradingAgents")
    else:
        spec = importlib.util.find_spec("tradingagents")
        origin = Path(spec.origin).resolve() if spec and spec.origin else None
        editable = bool(origin and (origin == package_dir.resolve() or package_dir.resolve() in origin.parents))
        _add(checks, "TradingAgents 可编辑安装", "pass" if editable else "fail", str(origin) if editable else "未从项目 TradingAgents 子模块导入；请执行 pip install -e ./TradingAgents")
        git = _call(runner, ["git", "-C", str(submodule), "rev-parse", "HEAD"])
        code, stdout, stderr = _as_completed(git)
        commit = stdout.strip()[:12] if code == 0 else "未知"
        dirty_result = _call(runner, ["git", "-C", str(submodule), "status", "--porcelain"])
        dirty = bool(getattr(dirty_result, "stdout", "").strip())
        upstream_result = _call(runner, ["git", "-C", str(submodule), "rev-list", "--left-right", "--count", "HEAD...origin/main"])
        if getattr(upstream_result, "returncode", 1) == 0:
            parts = str(getattr(upstream_result, "stdout", "")).split()
            behind = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else None
            upstream_detail = f"origin/main 落后 {behind} 个提交" if behind is not None else "无法计算 origin/main 差异"
        else:
            upstream_detail = "origin/main 不可用，未比较落后提交数"
        _add(checks, "TradingAgents 版本状态", "info", f"commit {commit}；{'有' if dirty else '无'}未提交改动；{upstream_detail}")
        for name, effective, detail in _fork_feature_checks(package_dir):
            _add(checks, name, "pass" if effective else "fail", detail if effective else f"{detail}；未确认修改已生效")

    codex = _codex_binary(settings)
    codex_path = shutil.which(codex) if not Path(codex).is_absolute() else codex
    if not codex_path or not Path(codex_path).is_file():
        _add(checks, "Codex CLI", "fail", "找不到 codex 可执行文件")
        _add(checks, "Codex 版本", "fail", f"最低要求 {settings.codex.min_version}")
        _add(checks, "ChatGPT 登录", "fail", "无法执行 codex login status")
    else:
        version_result = _call(runner, [codex_path, "--version"])
        version_code, version_out, version_err = _as_completed(version_result)
        actual_text = version_out.strip() or version_err.strip()
        actual, minimum = _version_tuple(actual_text), _version_tuple(settings.codex.min_version)
        version_ok = version_code == 0 and actual is not None and minimum is not None and actual >= minimum
        version_detail = f"{actual_text or '未读到版本'}；要求不低于 {settings.codex.min_version}"
        if not version_ok:
            version_detail += "；请执行 npm install -g @openai/codex@latest"
        _add(checks, "Codex 版本", "pass" if version_ok else "fail", version_detail)
        login_result = _call(runner, [codex_path, "login", "status"])
        login_code, login_out, login_err = _as_completed(login_result)
        login_text = (login_out + " " + login_err).strip()
        login_lower = login_text.casefold()
        login_ok = (
            login_code == 0
            and "logged in" in login_lower
            and "chatgpt" in login_lower
            and "not logged in" not in login_lower
        )
        login_detail = "codex login status 确认已登录 ChatGPT" if login_ok else (login_text[:240] or "未登录；请执行 codex login")
        _add(checks, "ChatGPT 登录", "pass" if login_ok else "fail", login_detail)

    try:
        _add(checks, "IANA 时区库", "info", _tzdata_version())
        today_anchor, next_anchor = _anchor_report(settings.schedule.anchor, current)
        _add(checks, "锚点北京时间", "info", f"{today_anchor}；{next_anchor}")
    except Exception as exc:
        _add(checks, "锚点北京时间", "fail", _failure_detail(exc))

    secret_path = root / "config" / "secrets.env"
    try:
        credentials = load_credentials(root)
        mode = secret_path.stat().st_mode & 0o777 if secret_path.exists() else None
        secret_ok = secret_path.is_file() and mode == 0o600
        secret_detail = "存在且权限为 0600" if secret_ok else ("不存在" if not secret_path.exists() else f"权限为 {mode:o}，要求 600")
        _add(checks, "项目内 Alpaca 凭据", "pass" if secret_ok else "fail", secret_detail)
    except ConfigurationError as exc:
        credentials = None
        _add(checks, "项目内 Alpaca 凭据", "fail", str(exc))

    for directory_name in ("data", "site", "logs"):
        writable, detail = _writable(root / directory_name)
        _add(checks, f"{directory_name}/ 可写", "pass" if writable else "fail", detail)

    launch_agents_dir = _default_launch_agents_dir()
    plist_path = launch_agents_dir / PLIST_NAME
    plist = _load_plist(plist_path)
    if plist is None:
        _add(checks, "LaunchAgent plist", "info", f"未安装：{plist_path}")
        _add(checks, "LaunchAgent PATH", "info", "安装 schedule 后执行 PATH 验证")
    elif not plist:
        _add(checks, "LaunchAgent plist", "fail", "plist 无法解析")
        _add(checks, "LaunchAgent PATH", "fail", "无法读取 plist 中的 PATH")
    else:
        expected = schedule_calendar_intervals(settings.schedule.anchor, local_timezone=machine_timezone(), year=current.year)
        installed = plist.get("StartCalendarInterval", [])
        actual_points = sorted((int(item.get("Hour", -1)), int(item.get("Minute", -1)), int(item.get("Weekday", -1))) for item in installed if isinstance(item, Mapping))
        expected_points = sorted((item["Hour"], item["Minute"], item["Weekday"]) for item in expected)
        match = actual_points == expected_points
        _add(checks, "LaunchAgent plist", "pass" if match else "fail", f"已安装；触发点 {actual_points}；锚点应为 {expected_points}")
        environment = plist.get("EnvironmentVariables", {})
        path_value = str(environment.get("PATH", ""))
        path_codex = str(environment.get("HOME", os.environ.get("HOME", "")))
        command_binary = codex_path if "codex_path" in locals() and codex_path else codex
        env_command = ["/usr/bin/env", "-i", f"PATH={path_value}", f"HOME={path_codex}", command_binary, "--version"]
        path_result = _call(runner, env_command)
        path_code, path_out, path_err = _as_completed(path_result)
        _add(checks, "LaunchAgent PATH 可找到 Codex", "pass" if path_code == 0 else "fail", (path_out or path_err).strip()[:220] or _result_detail(path_result))
        launch_result = _call(runner, ["launchctl", "print", f"{_launch_domain()}/{LABEL}"])
        launch_loaded = getattr(launch_result, "returncode", 1) == 0
        _add(checks, "LaunchAgent 加载状态", "pass" if launch_loaded else "warning", "已加载" if launch_loaded else "已安装但未加载；请重新执行 schedule install")

    try:
        pmset_result = _call(runner, ["/usr/bin/pmset", "-g", "sched"])
        pmset_code, pmset_out, pmset_err = _as_completed(pmset_result)
        pmset_text = pmset_out + "\n" + pmset_err
        if pmset_code == 0 and _pmset_has_wake_plan(pmset_text, settings.schedule.anchor, current):
            _add(checks, "定时唤醒", "pass", "检测到锚点前 15 分钟的唤醒计划")
        else:
            wake_time, command = _wake_time(settings.schedule.anchor, current)
            detail = f"未检测到锚点前 15 分钟（{wake_time} 北京时间）的唤醒计划；可执行：{command}"
            if pmset_code != 0:
                detail = "pmset 查询不可用；" + detail
            _add(checks, "定时唤醒", "warning", detail)
    except Exception as exc:
        wake_time, command = _wake_time(settings.schedule.anchor, current)
        _add(checks, "定时唤醒", "warning", f"{_failure_detail(exc)}；可执行：{command}")

    if config_valid:
        active_probes: dict[str, Probe] = {
            "alpaca": lambda: _probe_alpaca(root, now=current),
            "futu": lambda: _probe_futu(settings),
            "yfinance": _probe_yfinance,
        }
    else:
        active_probes = {
            name: (lambda: {"ok": True, "skipped": True, "detail": "配置校验失败，跳过外部探针"})
            for name in ("alpaca", "futu", "yfinance")
    }
    if ping:
        active_probes["ping"] = (
            (lambda: _probe_ping(root, settings))
            if config_valid
            else (lambda: {"ok": True, "skipped": True, "detail": "配置校验失败，跳过 Codex ping"})
        )
    if probes:
        active_probes.update(probes)
    alpaca_result = _call_probe("Alpaca 连通与剩余限额", active_probes["alpaca"], "fail", checks)
    if credentials is not None and not credentials.alpaca_configured and (
        probes is None or "alpaca" not in probes
    ):
        # 不暴露凭据值；检查项前面已经说明缺少密钥。
        checks[-1]["status"] = "fail"
        checks[-1]["detail"] = "缺少项目内 Alpaca 凭据，未发起请求"
    _call_probe("富途 OpenD 与订阅剩余额度", active_probes["futu"], "warning", checks)
    _call_probe("Yahoo 连通", active_probes["yfinance"], "warning", checks)
    if ping:
        _call_probe("Codex 极小推理", active_probes["ping"], "fail", checks)

    ok = all(item["status"] != "fail" for item in checks)
    failures = sum(item["status"] == "fail" for item in checks)
    warnings = sum(item["status"] == "warning" for item in checks)
    summary = f"{len(checks)} 项检查：{failures} 项致命失败，{warnings} 项告警。"
    return {"ok": ok, "exit_code": 0 if ok else 1, "checks": checks, "summary": summary}

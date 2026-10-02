"""launchd 定时任务的渲染与只读状态查询。"""

from __future__ import annotations

import os
import json
import plistlib
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import exchange_calendars as xcals

from daily_analyzer.config import load_settings

LABEL = "local.us-stock-daily-analyzer"
PLIST_NAME = f"{LABEL}.plist"
_NEW_YORK = ZoneInfo("America/New_York")
_BEIJING = ZoneInfo("Asia/Shanghai")
CommandRunner = Callable[..., Any]


def _anchor_parts(anchor: str) -> tuple[int, int, str]:
    match = re.fullmatch(r"(\d{2}):(\d{2})\s+(\S+)", anchor.strip())
    if not match:
        raise ValueError("schedule.anchor 格式必须为 HH:MM <IANA 时区>")
    try:
        ZoneInfo(match.group(3))
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"未知 IANA 时区：{match.group(3)}") from exc
    return int(match.group(1)), int(match.group(2)), match.group(3)


def machine_timezone() -> tzinfo:
    """从 TZ 或系统 localtime 读取本机时区规则。"""
    configured = os.environ.get("TZ", "").lstrip(":")
    if configured:
        try:
            return ZoneInfo(configured)
        except ZoneInfoNotFoundError:
            pass
    localtime = Path("/etc/localtime")
    try:
        resolved = localtime.resolve(strict=True)
        parts = resolved.parts
        if "zoneinfo" in parts:
            index = parts.index("zoneinfo")
            return ZoneInfo("/".join(parts[index + 1 :]))
        with resolved.open("rb") as stream:
            return ZoneInfo.from_file(stream)
    except (OSError, ValueError):
        return datetime.now().astimezone().tzinfo or timezone.utc


def schedule_trigger_times(
    anchor: str,
    *,
    local_timezone: str | tzinfo | None = None,
    year: int | None = None,
) -> list[dict[str, int]]:
    """按锚点时区冬夏两季换算并去重本机触发时分。"""
    hour, minute, anchor_zone_name = _anchor_parts(anchor)
    anchor_zone = ZoneInfo(anchor_zone_name)
    local_zone = ZoneInfo(local_timezone) if isinstance(local_timezone, str) else (local_timezone or machine_timezone())
    sample_year = year or datetime.now(_NEW_YORK).year
    points = set()
    for month in (1, 7):
        anchored = datetime.combine(date(sample_year, month, 15), time(hour, minute), anchor_zone)
        local = anchored.astimezone(local_zone)
        points.add((local.hour, local.minute))
    return [{"Hour": h, "Minute": m} for h, m in sorted(points)]



def schedule_calendar_intervals(anchor: str, *, local_timezone=None, year=None) -> list[dict[str, int]]:
    """将锚点工作日换算到本地星期，兼容跨午夜与冬夏令时。"""
    hour, minute, zone = _anchor_parts(anchor)
    local_zone = ZoneInfo(local_timezone) if isinstance(local_timezone, str) else (local_timezone or machine_timezone())
    sample_year = year or datetime.now(_NEW_YORK).year
    points = set()
    for month in (1, 7):
        for day in range(15, 22):
            anchored = datetime(sample_year, month, day, hour, minute, tzinfo=ZoneInfo(zone))
            if anchored.weekday() >= 5:
                continue
            local = anchored.astimezone(local_zone)
            points.add((local.hour, local.minute, local.isoweekday() % 7))
    return [{"Hour": h, "Minute": m, "Weekday": w} for h, m, w in sorted(points)]


def _codex_binary(settings: Any) -> str:
    configured = settings.codex.binary
    if configured:
        if Path(configured).is_absolute():
            return configured
        return shutil.which(configured) or configured
    return shutil.which("codex") or "codex"


def _environment_path(codex_binary: str, project_root: Path) -> str:
    path_values = [str(Path(codex_binary).expanduser().resolve().parent)] if Path(codex_binary).is_absolute() else []
    path_values.extend(
        [
            str(project_root / ".venv" / "bin"),
            "/opt/homebrew/bin",
            "/usr/local/bin",
            "/usr/bin",
            "/bin",
        ]
    )
    path_values.extend(os.environ.get("PATH", "").split(os.pathsep))
    unique = []
    for value in path_values:
        if value and value not in unique:
            unique.append(value)
    return os.pathsep.join(unique)


def render_plist(
    project_root: str | Path,
    *,
    anchor: str | None = None,
    local_timezone: str | tzinfo | None = None,
    codex_binary: str | None = None,
    home: str | Path | None = None,
    year: int | None = None,
) -> str:
    """生成不含密钥的 launchd plist XML。"""
    root = Path(project_root).expanduser().resolve()
    settings = load_settings(root)
    configured_anchor = anchor or settings.schedule.anchor
    binary = codex_binary or _codex_binary(settings)
    user_home = str(Path(home).expanduser()) if home else os.environ.get("HOME", str(Path.home()))
    program_arguments = [
        "/usr/bin/caffeinate",
        "-i",
        str(root / ".venv" / "bin" / "python"),
        "-m",
        "daily_analyzer",
        "run",
        "--scheduled",
    ]
    value = {
        "Label": LABEL,
        "ProgramArguments": program_arguments,
        "WorkingDirectory": str(root),
        "StartCalendarInterval": schedule_calendar_intervals(
            configured_anchor, local_timezone=local_timezone, year=year
        ),
        "EnvironmentVariables": {
            "HOME": user_home,
            "PATH": _environment_path(binary, root),
            "PYTHONUNBUFFERED": "1",
        },
        "StandardOutPath": str(root / "logs" / "launchd.stdout.log"),
        "StandardErrorPath": str(root / "logs" / "launchd.stderr.log"),
    }
    return plistlib.dumps(value, fmt=plistlib.FMT_XML, sort_keys=True).decode("utf-8")


def _default_launch_agents_dir() -> Path:
    return Path(os.environ.get("HOME", str(Path.home()))) / "Library" / "LaunchAgents"


def _launch_domain() -> str:
    return f"gui/{os.getuid()}"


def _call(runner: CommandRunner | None, command: list[str], **kwargs: Any) -> Any:
    command_runner = runner or subprocess.run
    return command_runner(command, capture_output=True, text=True, check=False, **kwargs)


def _result_detail(result: Any) -> str:
    output = (getattr(result, "stdout", "") or "").strip()
    error = (getattr(result, "stderr", "") or "").strip()
    return output or error or f"退出码 {getattr(result, 'returncode', '未知')}"


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def schedule_install(
    project_root: str | Path,
    *,
    runner: CommandRunner | None = None,
    now: datetime | None = None,
    launch_agents_dir: str | Path | None = None,
    local_timezone: str | tzinfo | None = None,
) -> dict[str, Any]:
    """先卸载旧任务，再写入 plist 并加载 LaunchAgent。"""
    root = Path(project_root).expanduser().resolve()
    current = now or datetime.now(_NEW_YORK)
    if current.tzinfo is None:
        current = current.replace(tzinfo=_NEW_YORK)
    directory = Path(launch_agents_dir).expanduser() if launch_agents_dir else _default_launch_agents_dir()
    plist_path = directory / PLIST_NAME
    domain = _launch_domain()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        (root / "logs").mkdir(parents=True, exist_ok=True)
        _call(runner, ["launchctl", "bootout", domain, str(plist_path)])
        settings = load_settings(root)
        payload = render_plist(
            root,
            local_timezone=local_timezone,
            year=current.astimezone(_NEW_YORK).year,
        )
        _write_atomic(plist_path, payload)
        loaded = _call(runner, ["launchctl", "bootstrap", domain, str(plist_path)])
        success = getattr(loaded, "returncode", 1) == 0
        decoded = plistlib.loads(payload.encode("utf-8"))
        return {
            "ok": success,
            "installed": True,
            "loaded": success,
            "plist_path": str(plist_path),
            "triggers": sorted({f"{item['Hour']:02d}:{item['Minute']:02d}" for item in decoded["StartCalendarInterval"]}),
            "error": None if success else _result_detail(loaded),
        }
    except Exception as exc:
        return {
            "ok": False,
            "installed": plist_path.is_file(),
            "loaded": False,
            "plist_path": str(plist_path),
            "triggers": [],
            "error": f"{type(exc).__name__}: {exc}",
        }


def schedule_uninstall(
    project_root: str | Path,
    *,
    runner: CommandRunner | None = None,
    launch_agents_dir: str | Path | None = None,
) -> dict[str, Any]:
    """卸载本项目任务并删除其 plist。"""
    del project_root  # 卸载只定位用户 LaunchAgents 中本项目唯一的 label。
    directory = Path(launch_agents_dir).expanduser() if launch_agents_dir else _default_launch_agents_dir()
    plist_path = directory / PLIST_NAME
    try:
        _call(runner, ["launchctl", "bootout", _launch_domain(), str(plist_path)])
        plist_path.unlink(missing_ok=True)
        return {"ok": True, "installed": False, "loaded": False, "plist_path": str(plist_path), "error": None}
    except Exception as exc:
        return {"ok": False, "installed": plist_path.is_file(), "loaded": False, "plist_path": str(plist_path), "error": f"{type(exc).__name__}: {exc}"}


def _next_session_dates(now: datetime) -> tuple[date, list[date]]:
    today = now.astimezone(_NEW_YORK).date()
    calendar = xcals.get_calendar("XNYS")
    sessions = calendar.sessions_in_range(today.isoformat(), (today + timedelta(days=14)).isoformat())
    values = [item.date() for item in sessions]
    if len(values) < 2:
        sessions = calendar.sessions_in_range(today.isoformat(), (today + timedelta(days=30)).isoformat())
        values = [item.date() for item in sessions]
    return today, values


def _anchor_display(anchor: str, day: date | None) -> str:
    if day is None:
        return "无法计算"
    hour, minute, zone_name = _anchor_parts(anchor)
    local = datetime.combine(day, time(hour, minute), ZoneInfo(zone_name))
    return f"{day.isoformat()} {local.astimezone(_BEIJING).strftime('%H:%M')} 北京时间"


def _last_status_summary(root: Path) -> dict[str, Any]:
    path = root / "data" / "status.json"
    if not path.is_file():
        return {"last_run": None, "last_schedule_event": None}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"last_run": None, "last_schedule_event": None}
    status = value if isinstance(value, Mapping) else {}
    return {"last_run": status.get("last_run"), "last_schedule_event": status.get("last_schedule_event")}


def schedule_status(
    project_root: str | Path,
    *,
    now: datetime | None = None,
    runner: CommandRunner | None = None,
    launch_agents_dir: str | Path | None = None,
) -> dict[str, Any]:
    """汇总 plist、launchd 加载情况、锚点与最近状态记录。"""
    root = Path(project_root).expanduser().resolve()
    directory = Path(launch_agents_dir).expanduser() if launch_agents_dir else _default_launch_agents_dir()
    plist_path = directory / PLIST_NAME
    current = now or datetime.now(_NEW_YORK)
    if current.tzinfo is None:
        current = current.replace(tzinfo=_NEW_YORK)
    try:
        anchor = load_settings(root).schedule.anchor
    except Exception as exc:
        return {"ok": False, "installed": plist_path.is_file(), "loaded": False, "error": f"配置读取失败：{exc}"}
    installed = plist_path.is_file()
    triggers: list[str] = []
    if installed:
        try:
            value = plistlib.loads(plist_path.read_bytes())
            triggers = sorted({f"{point['Hour']:02d}:{point['Minute']:02d}" for point in value.get("StartCalendarInterval", [])})
        except (OSError, plistlib.InvalidFileException, ValueError, KeyError, TypeError):
            triggers = []
    loaded = False
    if installed:
        result = _call(runner, ["launchctl", "print", f"{_launch_domain()}/{LABEL}"])
        loaded = getattr(result, "returncode", 1) == 0
    today, sessions = _next_session_dates(current)
    today_session = today in sessions
    next_day = next((day for day in sessions if day > today), sessions[0] if sessions else None)
    if not today_session:
        next_day = next((day for day in sessions if day >= today), None)
    records = _last_status_summary(root)
    status = {
        "ok": True,
        "installed": installed,
        "loaded": loaded,
        "plist_path": str(plist_path),
        "triggers": triggers,
        "today_is_trading_day": today_session,
        "today_anchor_beijing": _anchor_display(anchor, today),
        "next_trading_day_anchor_beijing": _anchor_display(anchor, next_day),
        **records,
        "logs_path": str(root / "logs"),
        "error": None,
    }
    return status

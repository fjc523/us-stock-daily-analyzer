"""管理独立的本机报告查看器 LaunchAgent。"""

from __future__ import annotations

import plistlib
from pathlib import Path
from typing import Any

from daily_analyzer.deployment.schedule import (
    _call, _default_launch_agents_dir, _launch_domain, _result_detail, _write_atomic,
)
from daily_analyzer.viewer import URL

LABEL = "local.us-stock-daily-analyzer.viewer"


def viewer_action(project_root: str | Path, action: str, *, runner=None,
                  launch_agents_dir: str | Path | None = None) -> dict[str, Any]:
    """只操作查看器服务，分析定时任务与历史结果保持独立。"""
    root = Path(project_root).resolve()
    directory = Path(launch_agents_dir) if launch_agents_dir else _default_launch_agents_dir()
    path = directory / f"{LABEL}.plist"
    domain = _launch_domain()
    try:
        if action == "install":
            (root / "logs").mkdir(parents=True, exist_ok=True)
            directory.mkdir(parents=True, exist_ok=True)
            payload = {
                "Label": LABEL,
                "ProgramArguments": [str(root / ".venv/bin/python"), "-m", "daily_analyzer", "serve"],
                "WorkingDirectory": str(root), "RunAtLoad": True, "KeepAlive": True,
                "StandardOutPath": str(root / "logs/viewer.stdout.log"),
                "StandardErrorPath": str(root / "logs/viewer.stderr.log"),
            }
            _call(runner, ["launchctl", "bootout", domain, str(path)])
            _write_atomic(path, plistlib.dumps(payload).decode())
            result = _call(runner, ["launchctl", "bootstrap", domain, str(path)])
            if result.returncode:
                return {"ok": False, "error": _result_detail(result), "plist_path": str(path)}
        elif action == "uninstall":
            _call(runner, ["launchctl", "bootout", domain, str(path)])
            path.unlink(missing_ok=True)
        elif action != "status":
            raise ValueError("未知查看器操作")
        result = _call(runner, ["launchctl", "print", f"{domain}/{LABEL}"])
        return {"ok": True, "installed": path.is_file(), "loaded": result.returncode == 0,
                "url": URL, "plist_path": str(path)}
    except OSError as exc:
        return {"ok": False, "error": str(exc), "plist_path": str(path)}

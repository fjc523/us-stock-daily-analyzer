"""从本机查看器启动现有单标的运行器，不参与结果和站点写入。"""

from __future__ import annotations

import fcntl
import os
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from daily_analyzer.config import ConfigurationError, load_settings, load_watchlist
from daily_analyzer.deployment.schedule import _codex_binary, _environment_path
from daily_analyzer.instruments import normalize_code
from daily_analyzer.storage import read_json
from daily_analyzer.time_utils import NEW_YORK, select_run_window


class AnalysisBusyError(RuntimeError):
    """当前已有批次，避免点击创建等待队列。"""


def analysis_busy(root: Path) -> bool:
    path = root / "data/run.lock"
    if not path.exists():
        return False
    with path.open("r+") as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    return False


class AnalysisLauncher:
    def __init__(self, root: Path, *, popen=subprocess.Popen, clock=None):
        self.root = root
        self.popen = popen
        self.clock = clock or (lambda: datetime.now(NEW_YORK))
        self.lock = threading.Lock()
        self.process = None
        self.symbol = None
        self.started_at = None

    def start(self, value: str) -> dict:
        symbol = normalize_code(value)
        with self.lock:
            if (self.process is not None and self.process.poll() is None) or analysis_busy(self.root):
                raise AnalysisBusyError("已有分析批次运行中，请等完成后再试")
            if symbol not in {item.symbol for item in load_watchlist(self.root).active_items}:
                raise ConfigurationError("只能分析当前启用的订阅")
            now = self.clock()
            select_run_window(None, now)
            settings = load_settings(self.root)
            environment = {**os.environ, "PATH": _environment_path(_codex_binary(settings), self.root)}
            log = self.root / "logs/manual-analysis.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("a", encoding="utf-8") as stream:
                self.process = self.popen(
                    [str(self.root / ".venv/bin/python"), "-m", "daily_analyzer", "run",
                     "--tickers", symbol, "--force"],
                    cwd=self.root, env=environment, stdin=subprocess.DEVNULL,
                    stdout=stream, stderr=subprocess.STDOUT,
                )
            self.symbol = symbol
            self.started_at = now.isoformat()
            return self._snapshot()

    def snapshot(self) -> dict:
        with self.lock:
            return self._snapshot()

    def _snapshot(self) -> dict:
        busy = analysis_busy(self.root)
        last_run = (read_json(self.root / "data/status.json", {}) or {}).get("last_run", {})
        if self.process is None:
            return {"status": "running" if busy else "idle", "busy": busy,
                    "message": "已有分析批次运行中" if busy else ""}
        code = self.process.poll()
        status = "running" if code is None else "completed" if code == 0 else "failed"
        message = f"{self.symbol} 正在分析，请稍候" if code is None else (
            f"{self.symbol} 分析完成" if code == 0 else f"{self.symbol} 分析失败，请查看运行状态或 logs/manual-analysis.log")
        result = {"status": status, "busy": busy or code is None, "symbol": self.symbol,
                  "started_at": self.started_at, "message": message}
        run_started = last_run.get("started_at")
        if run_started and datetime.fromisoformat(run_started) >= datetime.fromisoformat(self.started_at).replace(microsecond=0):
            result["run"] = last_run
            if last_run.get("last_error"):
                result["message"] += "：" + str(last_run["last_error"])
        return result

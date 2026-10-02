"""从本机查看器启动现有单标的运行器，不参与结果和站点写入。"""

from __future__ import annotations

import fcntl
import os
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from statistics import median

from daily_analyzer.config import ConfigurationError, load_settings, load_watchlist
from daily_analyzer.deployment.schedule import _codex_binary, _environment_path
from daily_analyzer.instruments import normalize_code
from daily_analyzer.site import symbol_slug
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


def _history_samples(root: Path, batch: dict) -> list[dict]:
    """取最近二十个成功耗时，不把失败、等待和当前批次当样本。"""
    samples = []
    for path in sorted((root / "data/runs").glob("*/batches/*/batch.json"), reverse=True):
        previous = read_json(path, {})
        if previous.get("run_id") == batch.get("run_id"):
            continue
        for item in previous.get("items", {}).values():
            seconds = item.get("duration_seconds")
            if item.get("status") == "success" and isinstance(seconds, (int, float)) and seconds > 0:
                samples.append({**item, "config": previous.get("effective_config", {})})
                if len(samples) == 20:
                    return samples
    return samples


def _item_progress(root: Path, batch_dir: Path, batch: dict, now: datetime) -> dict:
    samples = _history_samples(root, batch)
    config = batch.get("effective_config", {})
    matching = [row for row in samples if all(row["config"].get(key) == config.get(key) for key in ("quick", "deep"))]
    result = {}
    for item in batch.get("items", {}).values():
        symbol = item["symbol"]
        progress = read_json(batch_dir / "results" / symbol_slug(symbol) / "progress.json", {})
        status = item.get("status")
        started = progress.get("started_at") or item.get("started_at")
        elapsed = max(0, (now - datetime.fromisoformat(started)).total_seconds()) if started else 0
        reference = matching or samples
        same_symbol = [row for row in reference if row["symbol"] == symbol]
        reference = same_symbol or reference
        expected = median(row["duration_seconds"] for row in reference) if reference else None
        running = status in {"pending", "running"}
        if running:
            stage = progress.get("stage") or ("准备批次数据" if status == "pending" else "分析中（旧任务未记录阶段）")
        else:
            stage = "已完成" if status == "success" else "分析失败" if status == "failed" else "已结束"
            elapsed = item.get("duration_seconds") or elapsed
        result[symbol] = {
            "status": status, "stage": stage, "elapsed_seconds": int(elapsed),
            "estimated_percent": min(95, int(elapsed / expected * 100)) if running and expected else 100 if status == "success" else None,
            "remaining_seconds": max(0, int(expected - elapsed)) if running and expected else None,
            "overdue": bool(running and expected and elapsed >= expected),
            "estimate_samples": len(reference),
            "estimate_source": "同模型与强度" if matching else "其他配置参考" if samples else "无历史样本",
        }
    return result


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
        code = self.process.poll() if self.process is not None else None
        if busy or (self.process is not None and code is None):
            status = "running"
            message = f"{self.symbol} 正在分析，请稍候" if self.symbol else "已有分析批次运行中"
        elif self.process is None:
            status, message = "idle", ""
        else:
            status = "completed" if code == 0 else "failed"
            message = f"{self.symbol} 分析完成" if code == 0 else f"{self.symbol} 分析失败，请查看运行状态或 logs/manual-analysis.log"
        result = {"status": status, "busy": status == "running", "symbol": self.symbol,
                  "started_at": self.started_at, "message": message, "active_symbols": [], "items": {}}
        run_started = last_run.get("started_at")
        if run_started and (self.started_at is None or datetime.fromisoformat(run_started) >= datetime.fromisoformat(self.started_at).replace(microsecond=0)):
            result["run"] = last_run
            batch_dir = self.root / "data/runs" / last_run["trade_date"] / "batches" / last_run["run_id"] if last_run.get("trade_date") and last_run.get("run_id") else None
            batch = read_json(batch_dir / "batch.json", {}) if batch_dir else {}
            if batch and (busy or self.process is not None):
                result["items"] = _item_progress(self.root, batch_dir, batch, self.clock())
                if result["busy"]:
                    result["active_symbols"] = [symbol for symbol, item in result["items"].items() if item["status"] in {"running", "pending"}]
                    if result["active_symbols"]:
                        result["symbol"] = result["active_symbols"][0] if len(result["active_symbols"]) == 1 else None
                        result["message"] = "、".join(result["active_symbols"]) + " 正在处理，请稍候"
            if last_run.get("last_error"):
                result["message"] += "：" + str(last_run["last_error"])
        if result["busy"] and not result["active_symbols"] and self.symbol:
            result["active_symbols"] = [self.symbol]
        return result

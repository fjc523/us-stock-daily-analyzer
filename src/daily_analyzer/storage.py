"""原子文件写入、运行锁与运行日志。"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator


class RunAlreadyRunningError(RuntimeError):
    def __init__(self, pid: int | None) -> None:
        self.pid = pid
        super().__init__(f"已有运行中的实例（PID={pid if pid is not None else '未知'}）")


def jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        return jsonable(value.model_dump(mode="json"))
    if hasattr(value, "item"):
        try:
            return jsonable(value.item())
        except (TypeError, ValueError):
            pass
    if hasattr(value, "get_secret_value"):
        return "[已隐藏]"
    return str(value)


def atomic_write_json(path: str | Path, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(jsonable(value), stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def read_json(path: str | Path, default: Any = None) -> Any:
    target = Path(path)
    if not target.is_file():
        return default
    with target.open("r", encoding="utf-8") as stream:
        return json.load(stream)


@contextmanager
def run_lock(project_root: str | Path) -> Iterator[None]:
    path = Path(project_root) / "data" / "run.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+", encoding="ascii")
    try:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            stream.seek(0)
            try:
                pid = int(stream.read().strip())
            except ValueError:
                pid = None
            raise RunAlreadyRunningError(pid) from exc
        stream.seek(0)
        stream.truncate()
        stream.write(str(os.getpid()))
        stream.flush()
        os.fsync(stream.fileno())
        yield
    finally:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()


def append_log(project_root: str | Path, day: date, now: datetime, message: str) -> None:
    root = Path(project_root)
    directory = root / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = now.isoformat(timespec="seconds")
    with (directory / f"{day.isoformat()}.log").open("a", encoding="utf-8") as stream:
        stream.write(f"{stamp} {message}\n")
    cutoff = now.timestamp() - 60 * 86400
    for path in directory.glob("*.log"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            continue

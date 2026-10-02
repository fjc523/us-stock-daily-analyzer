"""只在本机提供报告浏览和自选订阅保存。"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import yaml

from daily_analyzer.config import ConfigurationError, load_watchlist, parse_watchlist
from daily_analyzer.site import render_home

PORT = 8765
URL = f"http://127.0.0.1:{PORT}/"
_SYMBOL = re.compile(r"[A-Z^][A-Z0-9.^-]{0,19}")


class WatchlistStore:
    """在服务内串行校验并原子保存清单，不改写任何历史结果。"""

    def __init__(self, root: Path):
        self.root = root
        self.lock = threading.Lock()

    def snapshot(self) -> dict[str, Any]:
        return {"items": [item.model_dump(mode="json") for item in load_watchlist(self.root).items]}

    def update(self, command: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            path = self.root / "config" / "watchlist.yaml"
            load_watchlist(self.root)
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            rows = raw["items"]
            action = command.get("action")
            if action == "add":
                item = command.get("item")
                if not isinstance(item, dict):
                    raise ConfigurationError("请填写订阅代码和类型")
                candidate = parse_watchlist({"items": [item]}).items[0]
                for value in (candidate.symbol, candidate.proxy, candidate.sector_etf):
                    if value and not _SYMBOL.fullmatch(value):
                        raise ConfigurationError("代码只能包含字母、数字、点号、连字符和指数前缀 ^")
                rows.append(candidate.model_dump(mode="json", exclude_none=True))
            elif action in {"remove", "toggle"}:
                symbol = str(command.get("symbol") or "").strip().upper()
                found = next((row for row in rows if str(row["symbol"]).strip().upper() == symbol), None)
                if found is None:
                    raise ConfigurationError(f"订阅不存在：{symbol}")
                if action == "remove":
                    rows.remove(found)
                else:
                    found["enabled"] = not found.get("enabled", True)
            else:
                raise ConfigurationError("订阅操作只能为添加、移除或暂停/恢复")
            checked = parse_watchlist(raw, "config/watchlist.yaml")
            text = yaml.safe_dump(raw, allow_unicode=True, sort_keys=False)
            descriptor, temporary = tempfile.mkstemp(prefix=".watchlist-", dir=path.parent)
            try:
                os.fchmod(descriptor, path.stat().st_mode & 0o777)
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    stream.write(text)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                Path(temporary).unlink(missing_ok=True)
            return {"items": [item.model_dump(mode="json") for item in checked.items],
                    "message": "订阅已保存，下次分析批次生效。历史报告保留。"}


def create_server(project_root: str | Path, *, port: int = PORT) -> ThreadingHTTPServer:
    """生产固定监听回环地址；测试可使用系统分配的端口。"""
    root = Path(project_root).resolve()
    store = WatchlistStore(root)

    class Handler(BaseHTTPRequestHandler):
        def _local_request(self) -> bool:
            authority = f"127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != authority:
                self._json(403, {"error": "请使用本机查看器地址访问"})
                return False
            origin = self.headers.get("Origin")
            if origin and origin != f"http://{authority}":
                self._json(403, {"error": "不接受其他来源的请求"})
                return False
            return True

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status: int, value: dict[str, Any]) -> None:
            self._send(status, json.dumps(value, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def do_GET(self) -> None:
            if not self._local_request():
                return
            path = unquote(urlsplit(self.path).path)
            try:
                if path == "/api/watchlist":
                    self._json(200, store.snapshot())
                elif path in {"/", "/index.html"}:
                    self._send(200, render_home(root, managed=True).encode(), "text/html; charset=utf-8")
                else:
                    site = (root / "site").resolve()
                    target = (site / path.lstrip("/")).resolve()
                    if not target.is_relative_to(site) or target.suffix != ".html" or not target.is_file():
                        self._json(404, {"error": "报告不存在"})
                        return
                    self._send(200, target.read_bytes(), "text/html; charset=utf-8")
            except (ConfigurationError, ValueError, OSError) as exc:
                self._json(500, {"error": f"查看失败：{exc}"})

        def do_HEAD(self) -> None:
            self.do_GET()

        def do_POST(self) -> None:
            if not self._local_request():
                return
            if urlsplit(self.path).path != "/api/watchlist":
                self._json(404, {"error": "接口不存在"})
                return
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                self._json(415, {"error": "订阅保存仅接受 JSON 请求"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16384:
                    raise ConfigurationError("订阅请求长度不正确")
                command = json.loads(self.rfile.read(length))
                if not isinstance(command, dict):
                    raise ConfigurationError("订阅请求必须是 JSON 对象")
                self._json(200, store.update(command))
            except (ConfigurationError, ValueError) as exc:
                self._json(400, {"error": str(exc)})
            except OSError:
                self._json(500, {"error": "无法保存订阅，请检查配置目录权限"})

        def log_message(self, format: str, *args: Any) -> None:
            # 服务日志不记录配置正文。
            return

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def serve(project_root: str | Path) -> None:
    with create_server(project_root) as server:
        print(f"本机报告与订阅管理：{URL}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass

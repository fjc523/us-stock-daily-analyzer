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
from urllib.parse import parse_qs, unquote, urlsplit

import yaml

from daily_analyzer.config import ConfigurationError, load_watchlist, parse_watchlist, load_settings, parse_settings
from daily_analyzer.site import render_home
from daily_analyzer.codex_models import load_codex_models
from daily_analyzer.instruments import InstrumentResolver, InstrumentUnavailableError, normalize_code
from daily_analyzer.manual_analysis import AnalysisLauncher, AnalysisBusyError

PORT = 8765
URL = f"http://127.0.0.1:{PORT}/"
_SYMBOL = re.compile(r"[A-Z^][A-Z0-9.^-]{0,19}")



def _save_yaml(path: Path, raw: dict) -> None:
    text = yaml.safe_dump(raw, allow_unicode=True, sort_keys=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.stem + "-", dir=path.parent)
    try:
        os.fchmod(descriptor, path.stat().st_mode & 0o777 if path.exists() else 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class SettingsStore:
    """只开放模型和并发参数，保留未展示的配置。"""
    def __init__(self, root: Path):
        self.root = root
        self.lock = threading.Lock()

    @staticmethod
    def _snapshot(settings) -> dict:
        return {"llm": {"quick": settings.llm.quick.model_dump(), "deep": settings.llm.deep.model_dump(),
                        "max_concurrent_calls": settings.llm.max_concurrent_calls},
                "run": {"max_parallel_tickers": settings.run.max_parallel_tickers}}

    def snapshot(self) -> dict:
        return {**self._snapshot(load_settings(self.root)), **load_codex_models()}

    def update(self, command: dict) -> dict:
        with self.lock:
            path = self.root / "config/settings.yaml"
            raw = yaml.safe_load(path.read_text()) if path.is_file() else {}
            raw = raw or {}
            parse_settings(raw)
            if set(command) - {"llm", "run"}:
                raise ConfigurationError("只能修改模型和并发参数")
            for section, values in command.items():
                allowed = {"quick", "deep", "max_concurrent_calls"} if section == "llm" else {"max_parallel_tickers"}
                if not isinstance(values, dict) or set(values) - allowed:
                    raise ConfigurationError("配置字段不在开放范围内")
                for key, value in values.items():
                    if key in {"quick", "deep"}:
                        if not isinstance(value, dict) or set(value) - {"model", "reasoning_effort"}:
                            raise ConfigurationError("模型设置只能包含模型名和推理强度")
                        raw.setdefault(section, {}).setdefault(key, {}).update(value)
                    else:
                        raw.setdefault(section, {})[key] = value
            checked = parse_settings(raw)
            if {"quick", "deep"} & set(command.get("llm", {})):
                catalog = {item["id"]: item for item in load_codex_models()["models"]}
                for role in ("quick", "deep"):
                    if role not in command.get("llm", {}):
                        continue
                    settings = getattr(checked.llm, role)
                    if settings.model not in catalog:
                        raise ConfigurationError(f"{role} 模型不在当前 Codex 可选目录中，请重新选择")
                    if settings.reasoning_effort not in catalog[settings.model]["reasoning_efforts"]:
                        raise ConfigurationError(f"{settings.model} 不支持推理强度 {settings.reasoning_effort}")
            _save_yaml(path, raw)
            return {**self._snapshot(checked), "message": "参数已保存，从下一次分析生效；正在执行的批次保持原配置"}


class WatchlistStore:
    """在服务内串行校验并原子保存清单，不改写任何历史结果。"""

    def __init__(self, root: Path, *, resolver=None):
        self.root = root
        self.resolver = resolver or InstrumentResolver(root)
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
                    raise ConfigurationError("请填写订阅代码")
                item = dict(item)
                identity = self.resolver(normalize_code(item.get("symbol")))
                item["symbol"] = identity["symbol"]
                if identity.get("type"):
                    if item.get("type") and item["type"] != identity["type"]:
                        raise ConfigurationError("所选类型与数据源识别结果不一致")
                    item["type"] = identity["type"]
                elif not item.get("type"):
                    raise ConfigurationError("代码有效，但类型未能自动识别，请选择类型")
                item.setdefault("name", identity.get("name"))
                if identity.get("proxy"):
                    item.setdefault("proxy", identity["proxy"])
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
            _save_yaml(path, raw)
            return {"items": [item.model_dump(mode="json") for item in checked.items],
                    "message": "订阅已保存，下次分析批次生效。历史报告保留。"}


def create_server(project_root: str | Path, *, port: int = PORT, resolver=None, launcher=None) -> ThreadingHTTPServer:
    """生产固定监听回环地址；测试可使用系统分配的端口。"""
    root = Path(project_root).resolve()
    resolver = resolver or InstrumentResolver(root)
    store = WatchlistStore(root, resolver=resolver)
    launcher = launcher or AnalysisLauncher(root)
    settings_store = SettingsStore(root)

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
                elif path == "/api/settings":
                    self._json(200, settings_store.snapshot())
                elif path == "/api/instruments":
                    symbol = parse_qs(urlsplit(self.path).query).get("symbol", [""])[0]
                    self._json(200, resolver(normalize_code(symbol)))
                elif path == "/api/analysis":
                    self._json(200, launcher.snapshot())
                elif path in {"/", "/index.html"}:
                    self._send(200, render_home(root, managed=True).encode(), "text/html; charset=utf-8")
                else:
                    site = (root / "site").resolve()
                    target = (site / path.lstrip("/")).resolve()
                    if not target.is_relative_to(site) or target.suffix != ".html" or not target.is_file():
                        self._json(404, {"error": "报告不存在"})
                        return
                    self._send(200, target.read_bytes(), "text/html; charset=utf-8")
            except InstrumentUnavailableError as exc:
                self._json(503, {"error": str(exc)})
            except (ConfigurationError, ValueError) as exc:
                self._json(400, {"error": str(exc)})
            except OSError as exc:
                self._json(500, {"error": f"查看失败：{exc}"})

        def do_HEAD(self) -> None:
            self.do_GET()

        def do_POST(self) -> None:
            if not self._local_request():
                return
            path = urlsplit(self.path).path
            if path not in {"/api/watchlist", "/api/analysis", "/api/settings"}:
                self._json(404, {"error": "接口不存在"})
                return
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                self._json(415, {"error": "参数及订阅操作仅接受 JSON 请求"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16384:
                    raise ConfigurationError("请求长度不正确")
                command = json.loads(self.rfile.read(length))
                if not isinstance(command, dict):
                    raise ConfigurationError("请求必须是 JSON 对象")
                if path == "/api/analysis":
                    self._json(202, launcher.start(command.get("symbol"), scope=command.get("scope", "symbol")))
                elif path == "/api/settings":
                    self._json(200, settings_store.update(command))
                else:
                    self._json(200, store.update(command))
            except AnalysisBusyError as exc:
                self._json(409, {"error": str(exc)})
            except InstrumentUnavailableError as exc:
                self._json(503, {"error": str(exc)})
            except (ConfigurationError, ValueError) as exc:
                self._json(400, {"error": str(exc)})
            except OSError:
                self._json(500, {"error": "操作失败，请检查配置目录权限及项目运行环境"})

        def log_message(self, format: str, *args: Any) -> None:
            # 服务日志不记录配置正文。
            return

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def serve(project_root: str | Path) -> None:
    from daily_analyzer.news_watch import NewsWatcher
    watcher = NewsWatcher(Path(project_root).resolve())
    with create_server(project_root) as server:
        watcher.start()
        print(f"本机报告与订阅管理：{URL}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            watcher.stop()

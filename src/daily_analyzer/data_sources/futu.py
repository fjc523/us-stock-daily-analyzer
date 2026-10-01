"""富途 OpenD QUOTE 订阅及快照生命周期。"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Iterable, Mapping
from typing import Any, Callable


def futu_code(symbol: str) -> str:
    normalized = str(symbol).strip().upper().removeprefix("US.").replace("-", ".")
    return f"US.{normalized}" if normalized else ""


def _records(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        return [dict(value)]
    if hasattr(value, "to_dict"):
        try:
            rows = value.to_dict(orient="records")
            return [dict(row) for row in rows]
        except (TypeError, ValueError):
            pass
    if hasattr(value, "iterrows"):
        return [dict(row) for _, row in value.iterrows()]
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        return [dict(row) for row in value if isinstance(row, Mapping)]
    return []


class FutuQuoteManager:
    """管理单批次订阅；OpenD 不可用或额度不足时改用快照。"""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 11111,
        max_subscriptions: int = 40,
        context_factory: Callable[..., Any] | None = None,
        quote_subtype: Any | None = None,
        ret_ok: int = 0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.host = host
        self.port = port
        self.max_subscriptions = max_subscriptions
        self.context_factory = context_factory
        self.quote_subtype = quote_subtype
        self.ret_ok = ret_ok
        self.clock = clock
        self.sleep = sleep
        self.context: Any | None = None
        self.mode = "unavailable"
        self.warning: str | None = None
        self.symbols: list[str] = []
        self.subscribed_codes: list[str] = []
        self._subscription_started_at: float | None = None
        self._snapshot_calls: deque[float] = deque()
        self._closed = False

    def _load_futu(self) -> tuple[Callable[..., Any], Any]:
        if self.context_factory is not None:
            return self.context_factory, self.quote_subtype or "QUOTE"
        from futu import OpenQuoteContext, SubType

        return self.context_factory or OpenQuoteContext, self.quote_subtype or SubType.QUOTE

    def start_batch(self, symbols: Iterable[str]) -> FutuQuoteManager:
        self.symbols = list(dict.fromkeys(s for s in (futu_code(x) for x in symbols) if s))
        if not self.symbols:
            self.mode = "unavailable"
            self.warning = "没有待订阅代码"
            return self
        try:
            factory, self.quote_subtype = self._load_futu()
            self.context = factory(host=self.host, port=self.port)
            ret, subscription = self.context.query_subscription(is_all_conn=True)
            if ret != self.ret_ok:
                self.mode = "snapshot"
                self.warning = "无法查询富途订阅额度，改用快照"
                return self
            remain = int((subscription or {}).get("remain", 0))
            if len(self.symbols) > self.max_subscriptions or remain < len(self.symbols):
                self.mode = "snapshot"
                self.warning = "额度不足，使用快照"
                return self
            for offset in range(0, len(self.symbols), self.max_subscriptions):
                chunk = self.symbols[offset : offset + self.max_subscriptions]
                ret, result = self.context.subscribe(
                    chunk,
                    [self.quote_subtype],
                    is_first_push=False,
                    subscribe_push=False,
                    extended_time=True,
                )
                if ret != self.ret_ok:
                    self.mode = "snapshot"
                    self.warning = "富途订阅失败，改用快照"
                    return self
                self.subscribed_codes.extend(chunk)
                if self._subscription_started_at is None:
                    self._subscription_started_at = self.clock()
            self.mode = "subscription"
        except Exception as exc:
            self.mode = "unavailable"
            self.warning = f"富途 OpenD 不可用：{type(exc).__name__}"
            if self.context is not None and not self.subscribed_codes:
                self._close_context()
        return self

    def get_quotes(self, symbols: Iterable[str]) -> dict[str, dict[str, Any]]:
        codes = list(dict.fromkeys(s for s in (futu_code(x) for x in symbols) if s))
        if not codes or self.context is None or self.mode == "unavailable":
            return {}
        output: dict[str, dict[str, Any]] = {}
        if self.mode == "subscription":
            for offset in range(0, len(codes), self.max_subscriptions):
                chunk = codes[offset : offset + self.max_subscriptions]
                try:
                    ret, rows = self.context.get_stock_quote(chunk)
                except Exception as exc:
                    self.warning = f"富途订阅报价不可用：{type(exc).__name__}"
                    continue
                if ret == self.ret_ok:
                    output.update(self._index_rows(rows))
                else:
                    self.warning = "富途订阅报价不可用：接口返回失败"
            return output
        return self.get_snapshots(codes)

    def get_snapshots(self, symbols: Iterable[str]) -> dict[str, dict[str, Any]]:
        """显式读取富途快照，供订阅报价缺项时逐级降级。"""
        codes = list(dict.fromkeys(s for s in (futu_code(x) for x in symbols) if s))
        if not codes or self.context is None:
            return {}
        output: dict[str, dict[str, Any]] = {}
        for offset in range(0, len(codes), 400):
            chunk = codes[offset : offset + 400]
            self._respect_snapshot_limit()
            try:
                ret, rows = self.context.get_market_snapshot(chunk)
            except Exception as exc:
                self.warning = f"富途快照不可用：{type(exc).__name__}"
                continue
            if ret == self.ret_ok:
                output.update(self._index_rows(rows))
            else:
                self.warning = "富途快照不可用：接口返回失败"
        return output

    def _respect_snapshot_limit(self) -> None:
        now = self.clock()
        while self._snapshot_calls and now - self._snapshot_calls[0] >= 30:
            self._snapshot_calls.popleft()
        if len(self._snapshot_calls) >= 60:
            delay = max(0.0, 30 - (now - self._snapshot_calls[0]))
            self.sleep(delay)
            now = self.clock()
            while self._snapshot_calls and now - self._snapshot_calls[0] >= 30:
                self._snapshot_calls.popleft()
        self._snapshot_calls.append(now)

    @staticmethod
    def _index_rows(rows: Any) -> dict[str, dict[str, Any]]:
        indexed: dict[str, dict[str, Any]] = {}
        for row in _records(rows):
            code = str(row.get("code") or "").strip().upper()
            if code:
                indexed[code] = row
        return indexed

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self.context is not None and self.subscribed_codes:
                started_at = self._subscription_started_at
                elapsed = self.clock() - (started_at if started_at is not None else self.clock())
                if elapsed < 60:
                    self.sleep(60 - elapsed)
                try:
                    ret, result = self.context.unsubscribe(
                        self.subscribed_codes, [self.quote_subtype]
                    )
                    if ret != self.ret_ok:
                        self.warning = "富途取消订阅失败：接口返回失败"
                except Exception as exc:
                    self.warning = f"富途取消订阅失败：{type(exc).__name__}"
        finally:
            self._close_context()

    def _close_context(self) -> None:
        context, self.context = self.context, None
        if context is not None:
            try:
                context.close()
            except Exception:
                pass

    def __enter__(self) -> FutuQuoteManager:
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

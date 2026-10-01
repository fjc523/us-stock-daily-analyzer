"""复用 TradingAgents fork 中的 Alpaca 唯一请求入口。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable


class AlpacaDataSource:
    """为上下文提供器封装 fork 共享 Alpaca 客户端。"""

    def __init__(
        self,
        client: Any | None = None,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._client = client
        self._client_factory = client_factory

    @property
    def client(self) -> Any:
        if self._client is None:
            factory = self._client_factory
            if factory is None:
                from tradingagents.dataflows.vendors.alpaca.client import (
                    get_shared_client,
                )

                factory = get_shared_client
            self._client = factory()
        return self._client

    def daily_bars(
        self, symbols: list[str], start: date | str, end: date | str
    ) -> dict[str, list[dict[str, Any]]]:
        """读取 SIP 复权日线，调用方将 end 限定为 P。"""
        return self.client.get_bars(
            symbols,
            start,
            end,
            feed="sip",
            adjustment="all",
            timeframe="1Day",
        )

    def snapshots(
        self, symbols: list[str], feed: str
    ) -> dict[str, dict[str, Any]]:
        if feed not in {"overnight", "iex"}:
            raise ValueError("Alpaca 快照 feed 只能是 overnight 或 iex")
        return self.client.get_snapshots(symbols, feed=feed)

    def iex_minute_bars(
        self, symbols: list[str], start: datetime | str, end: datetime | str
    ) -> dict[str, list[dict[str, Any]]]:
        return self.client.get_bars(
            symbols,
            start,
            end,
            feed="iex",
            adjustment="raw",
            timeframe="1Min",
        )

    def news(
        self,
        symbols: list[str] | None,
        start: datetime,
        end: datetime,
        *,
        limit: int | None = None,
        max_pages: int = 20,
    ) -> dict[str, Any]:
        return self.client.get_news(
            symbols,
            start,
            end,
            limit=limit,
            max_pages=max_pages,
        )

"""上下文提供器契约、批次管理与 Markdown 渲染。"""

from __future__ import annotations

import importlib
import json
import logging
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol

from daily_analyzer.data_sources import AlpacaDataSource, FutuQuoteManager, YahooDataSource


_LOGGER = logging.getLogger(__name__)


def _value(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, Mapping) else getattr(obj, key, default)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            pass
    return str(value)


def _jsonable(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, set):
        return [_jsonable(item) for item in sorted(value, key=str)]
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "item"):
        try:
            return _jsonable(value.item())
        except (TypeError, ValueError):
            pass
    if hasattr(value, "isoformat"):
        return _iso(value)
    return str(value)


@dataclass(frozen=True)
class ContextBlock:
    title: str
    markdown: str
    data: Any = field(default_factory=dict)
    as_of: datetime | date | str | None = None
    sources: Sequence[str] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """返回可直接写入 JSON 的块内容。"""
        sources = [self.sources] if isinstance(self.sources, str) else list(self.sources)
        return {
            "title": self.title,
            "markdown": self.markdown,
            "data": _jsonable(self.data),
            "as_of": _iso(self.as_of),
            "sources": sources,
        }


class ContextProvider(Protocol):
    name: str
    scope: str

    def prepare(self, batch: Any) -> None: ...

    def build(self, item: Any, cutoff: datetime | date | str) -> ContextBlock | None: ...


@dataclass
class ProviderServices:
    alpaca: Any = None
    futu: Any = None
    futu_enabled: bool = True
    yahoo: Any = None
    prices: Any = None
    index_metadata: Any = None
    project_root: str = "."
    clock: Callable[[], datetime] = datetime.now
    sleep: Callable[[float], None] | None = None

    def __post_init__(self) -> None:
        if self.alpaca is None:
            self.alpaca = AlpacaDataSource()
        if self.futu is None:
            options: dict[str, Any] = {}
            if self.sleep is not None:
                options["sleep"] = self.sleep
            self.futu = FutuQuoteManager(**options)
        if self.yahoo is None:
            self.yahoo = YahooDataSource(project_root=self.project_root)
        if self.prices is None:
            from .market_data import DailyPriceService

            self.prices = DailyPriceService(self.alpaca, self.yahoo)
        if self.index_metadata is None:
            from daily_analyzer.data_sources.index_metadata import IndexMetadataSource

            self.index_metadata = IndexMetadataSource()


class ProviderRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, Callable[[ProviderServices], ContextProvider]] = {}

    def register(
        self,
        name: str,
        factory: Callable[[ProviderServices], ContextProvider],
        *,
        replace: bool = False,
    ) -> None:
        if name in self._factories and not replace:
            raise ValueError(f"上下文提供器已注册：{name}")
        self._factories[name] = factory

    def create(self, name: str, services: ProviderServices) -> ContextProvider:
        if name in self._factories:
            provider = self._factories[name](services)
        elif ":" in name:
            module_name, class_name = name.split(":", 1)
            provider_class = getattr(importlib.import_module(module_name), class_name)
            provider = provider_class()
        else:
            raise ValueError(f"未知上下文提供器：{name}")
        if not callable(getattr(provider, "prepare", None)) or not callable(
            getattr(provider, "build", None)
        ):
            raise TypeError(f"上下文提供器 {name} 必须实现 prepare 和 build")
        if getattr(provider, "scope", None) not in {"batch", "ticker"}:
            raise ValueError(f"上下文提供器 {name} 的 scope 必须是 batch 或 ticker")
        return provider


class ContextManager:
    """按全局与逐项配置计算上下文，并隔离单个提供器的异常。"""

    def __init__(
        self,
        provider_names: Sequence[str],
        *,
        services: ProviderServices | None = None,
        registry: ProviderRegistry | None = None,
    ) -> None:
        self.provider_names = list(provider_names)
        self.services = services or ProviderServices()
        if registry is None:
            from .providers import make_registry

            registry = make_registry()
        self.registry = registry
        self._providers: dict[str, ContextProvider] = {}
        self._prepare_errors: dict[str, Exception] = {}
        self._batch_blocks: dict[str, ContextBlock] = {}
        self._prepared = False

    def _ensure_provider(self, name: str) -> ContextProvider:
        if name not in self._providers:
            self._providers[name] = self.registry.create(name, self.services)
        return self._providers[name]

    def prepare(self, batch: Any) -> dict[str, ContextBlock]:
        batch_items = _value(batch, "items")
        if batch_items is None:
            configured = _item_provider_names(batch)
            names = configured if configured is not None else self.provider_names
        else:
            names = []
            for item in batch_items or []:
                configured = _explicit_item_provider_names(item)
                names.extend(configured if configured is not None else self.provider_names)
        names = list(dict.fromkeys(names))
        for name in names:
            provider = self._ensure_provider(name)
            try:
                provider.prepare(batch)
                self._prepare_errors.pop(name, None)
            except Exception as exc:
                self._prepare_errors[name] = exc
                _LOGGER.warning("上下文提供器 %s prepare 失败：%s", name, type(exc).__name__)
                if getattr(provider, "scope", None) == "batch":
                    self._batch_blocks[name] = _unavailable_block(name, exc, _batch_as_of(batch))
            if getattr(provider, "scope", None) == "batch" and name not in self._batch_blocks:
                try:
                    block = provider.build(None, _batch_as_of(batch))
                except Exception as exc:
                    self._prepare_errors[name] = exc
                    _LOGGER.warning("上下文提供器 %s build 失败：%s", name, type(exc).__name__)
                    block = _unavailable_block(name, exc, _batch_as_of(batch))
                if block is not None:
                    self._batch_blocks[name] = block
        self._prepared = True
        return dict(self._batch_blocks)

    def build(
        self, item: Any, cutoff: datetime | date | str
    ) -> dict[str, ContextBlock]:
        if not self._prepared:
            self.prepare({"items": [item], "context_as_of": cutoff})
        names = _item_provider_names(item)
        if names is None:
            names = self.provider_names
        blocks: dict[str, ContextBlock] = {}
        for name in names:
            provider = self._ensure_provider(name)
            if name in self._prepare_errors:
                blocks[name] = _unavailable_block(name, self._prepare_errors[name], cutoff)
                continue
            if getattr(provider, "scope", None) == "batch":
                block = self._batch_blocks.get(name)
            else:
                try:
                    block = provider.build(item, cutoff)
                except Exception as exc:
                    _LOGGER.warning("上下文提供器 %s build 失败：%s", name, type(exc).__name__)
                    block = _unavailable_block(name, exc, cutoff)
            if block is not None:
                blocks[name] = block
        return blocks

    def close(self) -> None:
        """释放批次级数据源资源，调用方应在 finally 中执行。"""
        close = getattr(self.services.futu, "close", None)
        if callable(close):
            close()


def _item_provider_names(value: Any) -> list[str] | None:
    if isinstance(value, Mapping):
        direct = value.get("context_providers")
        items = value.get("items")
    else:
        direct = getattr(value, "context_providers", None)
        items = getattr(value, "items", None)
    if direct is not None:
        return list(direct)
    if items is None:
        return None
    output: list[str] = []
    has_override = False
    for item in items or []:
        names = _explicit_item_provider_names(item)
        if names is not None:
            has_override = True
            output.extend(names)
    return output if has_override else None


def _explicit_item_provider_names(item: Any) -> list[str] | None:
    if isinstance(item, Mapping):
        value = item.get("context_providers")
    else:
        value = getattr(item, "context_providers", None)
    return list(value) if value is not None else None


def _batch_as_of(batch: Any) -> Any:
    if isinstance(batch, Mapping):
        return batch.get("context_as_of") or batch.get("as_of")
    return getattr(batch, "context_as_of", None) or getattr(batch, "as_of", None)


def _unavailable_block(
    name: str, error: Exception, cutoff: datetime | date | str | None
) -> ContextBlock:
    reason = type(error).__name__
    markdown = f"该维度数据不可用：{reason}"
    if name == "macro_releases":
        markdown += "；经济数据与要闻不可用。"
    return ContextBlock(
        title=name,
        markdown=markdown,
        data={"error": reason},
        as_of=cutoff,
        sources=(name,),
    )


def serialize_blocks(blocks: Mapping[str, ContextBlock]) -> dict[str, dict[str, Any]]:
    return {name: block.to_dict() for name, block in blocks.items()}


def render_context(
    blocks: Mapping[str, ContextBlock] | Mapping[str, Mapping[str, Any]],
    context_as_of: datetime | date | str,
) -> str:
    timestamp = _iso(context_as_of)
    lines = [f"## 附加市场上下文（截至 {timestamp}）"]
    for block in blocks.values():
        payload = block.to_dict() if isinstance(block, ContextBlock) else block
        title = str(payload.get("title") or "市场上下文")
        as_of = payload.get("as_of")
        sources = payload.get("sources") or []
        if isinstance(sources, str):
            sources = [sources]
        source_text = "、".join(str(source) for source in sources) or "未注明"
        lines.extend(
            [
                "",
                f"### {title}",
                f"数据时间：{as_of or '未注明'}；数据源：{source_text}",
                str(payload.get("markdown") or ""),
            ]
        )
    return "\n".join(lines).rstrip()


def context_json(blocks: Mapping[str, ContextBlock]) -> str:
    return json.dumps(serialize_blocks(blocks), ensure_ascii=False, separators=(",", ":"))

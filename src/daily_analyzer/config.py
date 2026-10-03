"""项目配置、校验、CLI 覆盖与本地凭据加载。"""

from __future__ import annotations

import importlib
import inspect
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from dotenv import dotenv_values
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

DEFAULT_ANALYSTS = {
    "stock": ["market", "social", "news", "fundamentals"],
    "etf": ["market", "news"],
    "index": ["market", "news"],
}
SUPPORTED_ANALYSTS = frozenset({"market", "social", "news", "fundamentals"})
DEFAULT_INDEX_PROXIES = {
    "^GSPC": "SPY",
    "^NDX": "QQQ",
    "^DJI": "DIA",
    "^RUT": "IWM",
    "^SOX": "SOXX",
}
BUILTIN_CONTEXT_PROVIDERS = frozenset(
    {"market_regime", "sector_strength", "extended_hours", "macro_releases", "price_anchors", "position_structure"}
)
SUPPORTED_REASONING_EFFORTS = frozenset(
    {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
)


class ConfigurationError(ValueError):
    """配置文件或凭据不符合项目约定。"""


def _field_path(location: tuple[Any, ...] | list[Any]) -> str:
    path = ""
    for part in location:
        if isinstance(part, int):
            path += f"[{part}]"
        elif part == "__root__":
            continue
        else:
            path += ("." if path else "") + str(part)
    return path or "配置"


def _validation_message(detail: dict[str, Any]) -> str:
    message = str(detail.get("msg", ""))
    if message.startswith("Value error, "):
        return message[len("Value error, ") :]
    if message == "Field required":
        return "缺少必填项"
    error_type = detail.get("type")
    if error_type == "extra_forbidden":
        return "不支持此配置项"
    if error_type == "int_parsing":
        return "必须填写整数"
    if error_type == "float_parsing":
        return "必须填写数字"
    if error_type == "string_type":
        return "必须填写文本"
    if error_type == "list_type":
        return "必须填写列表"
    if error_type == "dict_type":
        return "必须填写键值对象"
    if error_type in {"model_type", "model_attributes_type"}:
        return "必须填写键值对象"
    return "值格式不正确"


def _raise_validation_error(exc: ValidationError, source: str) -> ConfigurationError:
    lines = [f"配置校验失败：{source}"]
    for detail in exc.errors(include_url=False):
        lines.append(f"- {_field_path(detail.get('loc', ()))}：{_validation_message(detail)}")
    return ConfigurationError("\n".join(lines))


def _validate_context_provider_names(value: list[str] | None) -> list[str] | None:
    if value is None:
        return value
    for index, name in enumerate(value):
        if name in BUILTIN_CONTEXT_PROVIDERS:
            continue
        if not isinstance(name, str) or ":" not in name:
            raise ValueError(
                f"第 {index + 1} 项必须是内置提供器名称或 module.path:ClassName"
            )
        module_name, class_name = name.split(":", 1)
        if not module_name or not class_name or not class_name.isidentifier():
            raise ValueError(f"第 {index + 1} 项格式必须为 module.path:ClassName")
        try:
            module = importlib.import_module(module_name)
            provider_class = getattr(module, class_name)
        except Exception as exc:
            raise ValueError(f"无法导入自定义上下文提供器 {name}") from exc
        if not inspect.isclass(provider_class):
            raise ValueError(f"自定义上下文提供器 {name} 必须是类")
        if not callable(getattr(provider_class, "prepare", None)) or not callable(
            getattr(provider_class, "build", None)
        ):
            raise ValueError(f"自定义上下文提供器 {name} 必须实现 prepare 和 build")
    return value


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoleSettings(ConfigModel):
    model: str = "gpt-6.1-sol"
    reasoning_effort: str = "medium"

    @field_validator("model")
    @classmethod
    def validate_model_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("模型名称不能为空")
        return value

    @field_validator("reasoning_effort")
    @classmethod
    def validate_reasoning_effort(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in SUPPORTED_REASONING_EFFORTS:
            allowed = "、".join(sorted(SUPPORTED_REASONING_EFFORTS))
            raise ValueError(f"推理强度必须为以下值之一：{allowed}")
        return value


class LLMSettings(ConfigModel):
    provider: str = "codex_exec"
    deep: RoleSettings = Field(default_factory=lambda: RoleSettings(reasoning_effort="xhigh"))
    quick: RoleSettings = Field(default_factory=RoleSettings)
    call_timeout_seconds: int = 600
    max_retries: int = 3
    max_concurrent_calls: int = 4
    log_prompts: bool = False

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("provider 不能为空")
        return value

    @field_validator("call_timeout_seconds", "max_retries", "max_concurrent_calls")
    @classmethod
    def validate_positive_values(cls, value: int, info: Any) -> int:
        if value < 1:
            raise ValueError(f"{info.field_name} 必须大于 0")
        return value


class CodexSettings(ConfigModel):
    binary: str | None = None
    min_version: str = "0.159.3"

    @field_validator("binary")
    @classmethod
    def normalize_binary(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("min_version")
    @classmethod
    def validate_min_version(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("min_version 不能为空")
        return value


class TradingAgentsSettings(ConfigModel):
    earnings_expectations_enabled: bool = True
    position_structure_enabled: bool = True
    sentiment_min_social_posts: int = Field(default=3, ge=0)
    lesson_min_settled_same_ticker: int = Field(default=10, ge=0)
    cross_ticker_lessons: Literal["off", "stats", "text"] = "stats"
    risk_layer_direction_lock: bool = True
    rating_timing_decoupled: bool = True
    price_plan_alt_target: bool = True
    debate_mode: Literal['structured', 'legacy'] = 'structured'
    research_manager_reads_reports: bool = True
    context_compaction: bool = True
    context_profiles: dict[str, Literal['full', 'brief']] = Field(default_factory=lambda: {
        'news_analyst': 'full', 'research_manager': 'full', 'portfolio_manager': 'full',
        'market_analyst': 'brief', 'fundamentals_analyst': 'brief', 'sentiment_analyst': 'brief',
        'bull_researcher': 'brief', 'bear_researcher': 'brief', 'trader': 'brief',
        'aggressive_debator': 'brief', 'conservative_debator': 'brief', 'neutral_debator': 'brief',
    })
    output_language: str = "Chinese"
    max_debate_rounds: int = 1
    max_risk_discuss_rounds: int = 1
    stocktwits_enabled: bool = False
    late_news_refresh: bool = True

    @field_validator("output_language")
    @classmethod
    def validate_output_language(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("output_language 不能为空")
        return value

    @field_validator("max_debate_rounds", "max_risk_discuss_rounds")
    @classmethod
    def validate_nonnegative_rounds(cls, value: int, info: Any) -> int:
        if value < 0:
            raise ValueError(f"{info.field_name} 不能小于 0")
        return value


class RunSettings(ConfigModel):
    max_parallel_tickers: int = 3
    max_duration_minutes: int = 180
    min_start_after_anchor_seconds: int = 60

    @field_validator("max_parallel_tickers")
    @classmethod
    def validate_parallelism(cls, value: int) -> int:
        if not 1 <= value <= 4:
            raise ValueError("取值范围为 1–4")
        return value

    @field_validator("max_duration_minutes")
    @classmethod
    def validate_duration(cls, value: int) -> int:
        if value < 1:
            raise ValueError("必须大于 0")
        return value

    @field_validator("min_start_after_anchor_seconds")
    @classmethod
    def validate_anchor_delay(cls, value: int) -> int:
        if value < 0:
            raise ValueError("不能小于 0")
        return value


class ScheduleSettings(ConfigModel):
    anchor: str = "08:30 America/New_York"

    @field_validator("anchor")
    @classmethod
    def validate_anchor(cls, value: str) -> str:
        value = value.strip()
        match = re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d\s+(\S+)", value)
        if not match:
            raise ValueError(
                "格式必须为 HH:MM <IANA 时区>，例如 08:30 America/New_York"
            )
        try:
            ZoneInfo(match.group(2))
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"未知 IANA 时区：{match.group(2)}") from exc
        return value


class FutuSettings(ConfigModel):
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 11111
    max_subscriptions: int = 40

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("host 不能为空")
        return value

    @field_validator("port")
    @classmethod
    def validate_port(cls, value: int) -> int:
        if not 1 <= value <= 65535:
            raise ValueError("取值范围为 1–65535")
        return value

    @field_validator("max_subscriptions")
    @classmethod
    def validate_max_subscriptions(cls, value: int) -> int:
        if value < 1:
            raise ValueError("必须大于 0")
        return value


class AlpacaSettings(ConfigModel):
    requests_per_minute: int = 180

    @field_validator("requests_per_minute")
    @classmethod
    def validate_request_rate(cls, value: int) -> int:
        if not 1 <= value <= 200:
            raise ValueError("取值范围为 1–200")
        return value


class DecisionSettings(ConfigModel):
    """中短期方向周期与点位有效期，单位均为交易日。"""

    horizon_trading_days: tuple[int, int] = (5, 20)
    plan_validity_trading_days: int = Field(default=5, ge=1)

    @field_validator("horizon_trading_days")
    @classmethod
    def validate_horizon(cls, value: tuple[int, int]) -> tuple[int, int]:
        if not 0 < value[0] <= value[1]:
            raise ValueError("决策周期必须满足0 < 下沿 ≤ 上沿，单位为交易日")
        return value


class PricePlanSettings(ConfigModel):
    """价格方案的ATR止损与最低盈亏比规则。"""

    stop_atr_min: FiniteFloat = Field(default=1.0, gt=0)
    stop_atr_normal: tuple[FiniteFloat, FiniteFloat] = (1.5, 2.0)
    stop_atr_max: FiniteFloat = Field(default=2.5, gt=0)
    min_reward_risk: FiniteFloat = Field(default=1.5, gt=0)

    @model_validator(mode="after")
    def validate_distances(self) -> PricePlanSettings:
        if not 0 < self.stop_atr_min <= self.stop_atr_normal[0] <= self.stop_atr_normal[1] <= self.stop_atr_max:
            raise ValueError("ATR距离必须满足0 < stop_atr_min ≤ stop_atr_normal下沿 ≤ 上沿 ≤ stop_atr_max")
        return self


class EvaluationSettings(ConfigModel):
    """独立评估的资产主口径与结算窗口。"""

    broad_market_etfs: list[str] = Field(default_factory=lambda: ["SPY", "QQQ", "IWM", "DIA", "VOO", "IVV", "VTI"])
    settlement_windows: list[int] = Field(default_factory=lambda: [5, 10, 20])

    @field_validator("broad_market_etfs")
    @classmethod
    def normalize_broad_etfs(cls, value: list[str]) -> list[str]:
        normalized = [symbol.strip().upper() for symbol in value]
        if any(not symbol for symbol in normalized) or len(set(normalized)) != len(normalized):
            raise ValueError("宽基ETF代码必须非空且不重复")
        return normalized

    @field_validator("settlement_windows")
    @classmethod
    def validate_windows(cls, value: list[int]) -> list[int]:
        if not value or any(day not in {5, 10, 20} for day in value) or len(set(value)) != len(value):
            raise ValueError("结算窗口须为5、10、20的非空不重复子集")
        return sorted(value)


class Settings(ConfigModel):
    evaluation: EvaluationSettings = Field(default_factory=EvaluationSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    codex: CodexSettings = Field(default_factory=CodexSettings)
    tradingagents: TradingAgentsSettings = Field(default_factory=TradingAgentsSettings)
    decision: DecisionSettings = Field(default_factory=DecisionSettings)
    price_plan: PricePlanSettings = Field(default_factory=PricePlanSettings)
    context_providers: list[str] = Field(
        default_factory=lambda: [
            "market_regime",
            "sector_strength",
            "extended_hours",
            "macro_releases",
            "price_anchors",
        ]
    )
    run: RunSettings = Field(default_factory=RunSettings)
    schedule: ScheduleSettings = Field(default_factory=ScheduleSettings)
    futu: FutuSettings = Field(default_factory=FutuSettings)
    alpaca: AlpacaSettings = Field(default_factory=AlpacaSettings)

    @field_validator("context_providers")
    @classmethod
    def validate_context_providers(cls, value: list[str]) -> list[str]:
        checked = _validate_context_provider_names(value)
        return checked or []


class WatchlistItem(ConfigModel):
    symbol: str
    type: str
    name: str | None = None
    enabled: bool = True
    analysts: list[str] | None = None
    context_providers: list[str] | None = None
    sector_etf: str | None = None
    proxy: str | None = None
    note: str | None = None

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError("symbol 不能为空")
        return value

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        if value not in {"stock", "etf", "index"}:
            raise ValueError("只能是 stock、etf 或 index")
        return value

    @field_validator("analysts")
    @classmethod
    def validate_analysts(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        if not value:
            raise ValueError("analysts 不能为空")
        invalid = [name for name in value if name not in SUPPORTED_ANALYSTS]
        if invalid:
            names = "、".join(invalid)
            raise ValueError(
                f"{names} 不是上游分析师；板块维度应通过 context_providers 配置"
            )
        return value

    @field_validator("context_providers")
    @classmethod
    def validate_item_context_providers(
        cls, value: list[str] | None
    ) -> list[str] | None:
        return _validate_context_provider_names(value)

    @field_validator("sector_etf", "proxy")
    @classmethod
    def normalize_optional_symbol(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().upper()
        if not value:
            raise ValueError("标的代码不能为空")
        return value

    @model_validator(mode="after")
    def apply_defaults_and_proxy(self) -> WatchlistItem:
        if self.analysts is None:
            self.analysts = list(DEFAULT_ANALYSTS[self.type])
        if self.type == "index":
            if self.proxy is None:
                self.proxy = DEFAULT_INDEX_PROXIES.get(self.symbol)
            if self.proxy is None:
                raise ValueError(
                    f"symbol {self.symbol} 没有内置指数代理，请配置 proxy"
                )
        return self

    @property
    def analysis_symbol(self) -> str:
        return self.proxy if self.type == "index" and self.proxy else self.symbol


class WatchlistConfig(ConfigModel):
    items: list[WatchlistItem]

    @model_validator(mode="after")
    def validate_unique_symbols(self) -> WatchlistConfig:
        seen: dict[str, int] = {}
        for index, item in enumerate(self.items):
            if item.symbol in seen:
                first = seen[item.symbol]
                raise ValueError(
                    f"items[{index}].symbol：代码 {item.symbol} 与第 {first + 1} 项重复"
                )
            seen[item.symbol] = index
        return self

    @property
    def active_items(self) -> list[WatchlistItem]:
        return [item for item in self.items if item.enabled]


class PortfolioPosition(ConfigModel):
    ticker: str
    quantity: float
    average_price: float | None = None

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError("ticker 不能为空")
        return value


class PortfolioConfig(ConfigModel):
    cash: float | None = None
    currency: str | None = None
    positions: list[PortfolioPosition] = Field(default_factory=list)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().upper()
        if not value:
            raise ValueError("currency 不能为空")
        return value


class DataCredentials(BaseModel):
    """SecretStr 确保常规 repr 不会暴露密钥值。"""

    model_config = ConfigDict(extra="forbid")
    alpaca_key_id: SecretStr | None = None
    alpaca_secret_key: SecretStr | None = None
    alpha_vantage_api_key: SecretStr | None = None
    fred_api_key: SecretStr | None = None

    @property
    def alpaca_configured(self) -> bool:
        return self.alpaca_key_id is not None and self.alpaca_secret_key is not None


@dataclass(frozen=True)
class ProjectConfig:
    settings: Settings
    watchlist: WatchlistConfig
    portfolio: PortfolioConfig | None
    credentials: DataCredentials


def _validate_model(model_type: type[BaseModel], data: Any, source: str) -> Any:
    try:
        return model_type.model_validate(data)
    except ValidationError as exc:
        raise _raise_validation_error(exc, source) from exc


def parse_settings(data: Any = None, source: str = "settings.yaml") -> Settings:
    if data is None:
        data = {}
    return _validate_model(Settings, data, source)


def parse_watchlist(data: Any, source: str = "watchlist.yaml") -> WatchlistConfig:
    return _validate_model(WatchlistConfig, data, source)


def parse_portfolio(data: Any, source: str = "portfolio.yaml") -> PortfolioConfig:
    return _validate_model(PortfolioConfig, data, source)


def apply_llm_overrides(
    settings: Settings, model: str | None = None, effort: str | None = None
) -> Settings:
    """返回应用 CLI 覆盖的新对象，不改写调用方的配置。"""
    values = settings.model_dump(mode="python")
    for role in ("deep", "quick"):
        if model is not None:
            values["llm"][role]["model"] = model
        if effort is not None:
            values["llm"][role]["reasoning_effort"] = effort
    return parse_settings(values)


def _project_local_path(project_root: str | Path, relative_path: str) -> tuple[Path, Path]:
    root = Path(project_root).expanduser().resolve()
    target = root / relative_path
    try:
        resolved = target.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ConfigurationError(
            f"项目文件路径超出项目目录：{relative_path}"
        ) from exc
    return root, target


def _read_yaml(
    project_root: str | Path,
    relative_path: str,
    optional: bool,
    missing_hint: str | None = None,
) -> Any:
    _, target = _project_local_path(project_root, relative_path)
    if not target.exists():
        if optional:
            return None
        suffix = f"；{missing_hint}" if missing_hint else ""
        raise ConfigurationError(f"缺少配置文件 {relative_path}{suffix}")
    try:
        with open(target, encoding="utf-8") as stream:
            value = yaml.safe_load(stream)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = f"第 {mark.line + 1} 行" if mark is not None else "文件"
        raise ConfigurationError(f"{relative_path} {line} 的 YAML 格式错误") from exc
    except OSError as exc:
        raise ConfigurationError(f"无法读取配置文件 {relative_path}") from exc
    return {} if value is None and relative_path.endswith("settings.yaml") else value


def load_settings(project_root: str | Path) -> Settings:
    data = _read_yaml(project_root, "config/settings.yaml", optional=True)
    return parse_settings(data, "config/settings.yaml")


def load_watchlist(project_root: str | Path) -> WatchlistConfig:
    data = _read_yaml(
        project_root,
        "config/watchlist.yaml",
        optional=False,
        missing_hint="请从 config/watchlist.example.yaml 复制后填写",
    )
    return parse_watchlist(data, "config/watchlist.yaml")


def load_portfolio(project_root: str | Path) -> PortfolioConfig | None:
    data = _read_yaml(project_root, "config/portfolio.yaml", optional=True)
    if data is None:
        return None
    return parse_portfolio(data, "config/portfolio.yaml")


def load_credentials(
    project_root: str | Path,
    environ: Mapping[str, str] | None = None,
    require_alpaca: bool = False,
) -> DataCredentials:
    """合并进程环境与项目本地 secrets.env，进程环境优先。"""
    root, path = _project_local_path(project_root, "config/secrets.env")
    environment = os.environ if environ is None else environ
    file_values: dict[str, str | None] = {}

    if path.exists():
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
            mode = stat.S_IMODE(path.stat().st_mode)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ConfigurationError("无法安全读取项目内 config/secrets.env") from exc
        if mode != 0o600:
            raise ConfigurationError(
                "config/secrets.env 权限必须为 0600，请执行 chmod 600 config/secrets.env"
            )
        try:
            with open(path, encoding="utf-8") as stream:
                file_values = dotenv_values(stream=stream)
        except OSError as exc:
            raise ConfigurationError("无法读取项目内 config/secrets.env") from exc

    def value_for(name: str) -> SecretStr | None:
        value = environment.get(name)
        if value is None or not str(value).strip():
            value = file_values.get(name)
        if value is None or not str(value).strip():
            return None
        return SecretStr(str(value))

    credentials = DataCredentials(
        alpaca_key_id=value_for("APCA_API_KEY_ID"),
        alpaca_secret_key=value_for("APCA_API_SECRET_KEY"),
        alpha_vantage_api_key=value_for("ALPHA_VANTAGE_API_KEY"),
        fred_api_key=value_for("FRED_API_KEY"),
    )
    if require_alpaca and not credentials.alpaca_configured:
        raise ConfigurationError(
            "配置字段 config.secrets.env：缺少 APCA_API_KEY_ID 或 "
            "APCA_API_SECRET_KEY；请补充项目内 Alpaca 凭据"
        )
    return credentials


def load_project_config(
    project_root: str | Path,
    environ: Mapping[str, str] | None = None,
    require_alpaca: bool = False,
) -> ProjectConfig:
    return ProjectConfig(
        settings=load_settings(project_root),
        watchlist=load_watchlist(project_root),
        portfolio=load_portfolio(project_root),
        credentials=load_credentials(
            project_root, environ=environ, require_alpaca=require_alpaca
        ),
    )


def to_tradingagents_portfolio(
    portfolio: PortfolioConfig | None,
) -> Any | None:
    """将项目 YAML 模型转换为 TradingAgents 的真实 PortfolioContext。"""
    if portfolio is None:
        return None
    try:
        from tradingagents.portfolio import PortfolioContext, Position
    except ImportError as exc:
        raise ConfigurationError(
            "无法导入 TradingAgents PortfolioContext；请先执行子模块可编辑安装"
        ) from exc
    positions = [
        Position(
            ticker=item.ticker,
            quantity=item.quantity,
            average_price=item.average_price,
        )
        for item in portfolio.positions
    ]
    return PortfolioContext(
        cash=portfolio.cash,
        currency=portfolio.currency,
        positions=positions,
    )

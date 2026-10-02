from __future__ import annotations

import builtins
import sys
import subprocess
from types import ModuleType
from pathlib import Path

import pytest

import daily_analyzer.config as config_module
from daily_analyzer.config import (
    ConfigurationError,
    PortfolioConfig,
    Settings,
    apply_llm_overrides,
    load_credentials,
    load_portfolio,
    load_project_config,
    load_settings,
    load_watchlist,
    parse_portfolio,
    parse_settings,
    parse_watchlist,
    to_tradingagents_portfolio,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _project(tmp_path: Path) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    return tmp_path


def _secrets_file(root: Path, mode: int = 0o600) -> Path:
    path = root / "config" / "secrets.env"
    path.write_text(
        "APCA_API_KEY_ID=file-id\nAPCA_API_SECRET_KEY=file-secret\n",
        encoding="utf-8",
    )
    path.chmod(mode)
    return path


def test_empty_settings_file_uses_documented_defaults(tmp_path: Path) -> None:
    root = _project(tmp_path)
    (root / "config" / "settings.yaml").write_text("", encoding="utf-8")
    settings = load_settings(root)
    assert settings.llm.provider == "codex_exec"
    assert settings.llm.deep.model == "gpt-6.1-sol"
    assert settings.llm.deep.reasoning_effort == "medium"
    assert settings.llm.quick.model == "gpt-6.1-sol"
    assert settings.run.max_parallel_tickers == 3
    assert settings.alpaca.requests_per_minute == 180
    assert settings.schedule.anchor == "08:30 America/New_York"


def test_settings_range_and_anchor_errors_include_chinese_field_paths() -> None:
    with pytest.raises(ConfigurationError) as parallel:
        parse_settings({"run": {"max_parallel_tickers": 6}})
    assert "run.max_parallel_tickers" in str(parallel.value)
    assert "取值范围为 1–4" in str(parallel.value)

    with pytest.raises(ConfigurationError) as anchor:
        parse_settings({"schedule": {"anchor": "8:30pm"}})
    assert "schedule.anchor" in str(anchor.value)
    assert "HH:MM" in str(anchor.value)


def test_invalid_watchlist_type_names_allowed_values_and_field_path() -> None:
    with pytest.raises(ConfigurationError) as caught:
        parse_watchlist({"items": [{"symbol": "NVDA", "type": "fund"}]})
    message = str(caught.value)
    assert "items[0].type" in message
    assert "只能是 stock、etf 或 index" in message


def test_missing_watchlist_points_to_example_file(tmp_path: Path) -> None:
    root = _project(tmp_path)
    with pytest.raises(ConfigurationError) as caught:
        load_watchlist(root)
    assert "config/watchlist.example.yaml" in str(caught.value)


def test_watchlist_normalizes_and_rejects_case_insensitive_duplicates() -> None:
    normalized = parse_watchlist(
        {"items": [{"symbol": "nvda", "type": "stock"}]}
    )
    assert normalized.items[0].symbol == "NVDA"
    with pytest.raises(ConfigurationError) as caught:
        parse_watchlist(
            {
                "items": [
                    {"symbol": "nvda", "type": "stock"},
                    {"symbol": "NVDA", "type": "etf"},
                ]
            }
        )
    assert "items[1].symbol" in str(caught.value)
    assert "重复" in str(caught.value)


def test_type_specific_analysts_and_disabled_items() -> None:
    watchlist = parse_watchlist(
        {
            "items": [
                {"symbol": "NVDA", "type": "stock"},
                {"symbol": "SPY", "type": "etf", "enabled": False},
                {"symbol": "^NDX", "type": "index"},
            ]
        }
    )
    assert watchlist.items[0].analysts == [
        "market",
        "social",
        "news",
        "fundamentals",
    ]
    assert watchlist.items[1].analysts == ["market", "news"]
    assert watchlist.items[2].analysts == ["market", "news"]
    assert watchlist.items[2].analysis_symbol == "QQQ"
    assert [item.symbol for item in watchlist.active_items] == ["NVDA", "^NDX"]


def test_custom_analysts_must_be_supported_and_nonempty() -> None:
    custom = parse_watchlist(
        {
            "items": [
                {
                    "symbol": "NVDA",
                    "type": "stock",
                    "analysts": ["market", "news"],
                }
            ]
        }
    )
    assert custom.items[0].analysts == ["market", "news"]

    for analysts in ([], ["market", "sector"]):
        with pytest.raises(ConfigurationError) as caught:
            parse_watchlist(
                {"items": [{"symbol": "NVDA", "type": "stock", "analysts": analysts}]}
            )
        assert "items[0].analysts" in str(caught.value)
    assert "板块维度应通过 context_providers 配置" in str(caught.value)


@pytest.mark.parametrize("requests_per_minute", [1, 200])
def test_alpaca_request_rate_accepts_inclusive_bounds(
    requests_per_minute: int,
) -> None:
    settings = parse_settings(
        {"alpaca": {"requests_per_minute": requests_per_minute}}
    )
    assert settings.alpaca.requests_per_minute == requests_per_minute


@pytest.mark.parametrize("requests_per_minute", [0, 201])
def test_alpaca_request_rate_rejects_values_outside_bounds(
    requests_per_minute: int,
) -> None:
    with pytest.raises(ConfigurationError) as caught:
        parse_settings({"alpaca": {"requests_per_minute": requests_per_minute}})
    assert "alpaca.requests_per_minute" in str(caught.value)
    assert "取值范围为 1–200" in str(caught.value)


def test_global_context_providers_and_watchlist_override_load_from_yaml(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    (root / "config" / "settings.yaml").write_text(
        "context_providers: [market_regime, sector_strength]\n", encoding="utf-8"
    )
    (root / "config" / "watchlist.yaml").write_text(
        "items:\n"
        "  - symbol: NVDA\n"
        "    type: stock\n"
        "    context_providers: [market_regime, extended_hours]\n"
        "  - symbol: SPY\n"
        "    type: etf\n",
        encoding="utf-8",
    )

    config = load_project_config(root, environ={})
    assert config.settings.context_providers == ["market_regime", "sector_strength"]
    assert config.watchlist.items[0].context_providers == [
        "market_regime",
        "extended_hours",
    ]
    assert config.watchlist.items[1].context_providers is None


@pytest.mark.parametrize("scope", ["global", "item"])
def test_context_providers_reject_unknown_names_with_field_path(scope: str) -> None:
    if scope == "global":
        with pytest.raises(ConfigurationError) as caught:
            parse_settings({"context_providers": ["sector"]})
        field_path = "context_providers"
    else:
        with pytest.raises(ConfigurationError) as caught:
            parse_watchlist(
                {
                    "items": [
                        {
                            "symbol": "NVDA",
                            "type": "stock",
                            "context_providers": ["sector"],
                        }
                    ]
                }
            )
        field_path = "items[0].context_providers"
    assert field_path in str(caught.value)
    assert "module.path:ClassName" in str(caught.value)


def test_dynamic_context_provider_import_uses_in_memory_stub_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_name = "test_context_provider_stub"
    module = ModuleType(module_name)

    class StubContextProvider:
        def prepare(self, batch: object) -> None:
            return None

        def build(self, item: object, cutoff: object) -> None:
            return None

    module.StubContextProvider = StubContextProvider
    monkeypatch.setitem(sys.modules, module_name, module)
    provider = f"{module_name}:StubContextProvider"

    settings = parse_settings({"context_providers": [provider]})
    watchlist = parse_watchlist(
        {
            "items": [
                {
                    "symbol": "NVDA",
                    "type": "stock",
                    "context_providers": [provider],
                }
            ]
        }
    )
    assert settings.context_providers == [provider]
    assert watchlist.items[0].context_providers == [provider]


def test_unimportable_dynamic_context_provider_fails_without_external_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_name = "missing_test_context_provider"
    attempted: list[str] = []

    def fail_import(name: str) -> ModuleType:
        attempted.append(name)
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(config_module.importlib, "import_module", fail_import)
    with pytest.raises(ConfigurationError) as caught:
        parse_settings({"context_providers": [f"{module_name}:Provider"]})

    assert attempted == [module_name]
    assert "context_providers" in str(caught.value)
    assert "无法导入自定义上下文提供器" in str(caught.value)


def test_unknown_index_requires_proxy_and_known_index_uses_default() -> None:
    with pytest.raises(ConfigurationError) as caught:
        parse_watchlist({"items": [{"symbol": "^FTW5000", "type": "index"}]})
    assert "^FTW5000" in str(caught.value)
    assert "配置 proxy" in str(caught.value)

    known = parse_watchlist({"items": [{"symbol": "^GSPC", "type": "index"}]})
    assert known.items[0].analysis_symbol == "SPY"
    explicit = parse_watchlist(
        {"items": [{"symbol": "^FTW5000", "type": "index", "proxy": "abc"}]}
    )
    assert explicit.items[0].analysis_symbol == "ABC"


def test_cli_model_and_effort_overrides_are_merged_without_mutation() -> None:
    original = parse_settings({})
    changed = apply_llm_overrides(original, model="gpt-6-sol", effort="xhigh")
    assert changed.llm.deep.model == "gpt-6-sol"
    assert changed.llm.quick.model == "gpt-6-sol"
    assert changed.llm.deep.reasoning_effort == "xhigh"
    assert changed.llm.quick.reasoning_effort == "xhigh"
    assert original.llm.deep.model == "gpt-6.1-sol"
    assert original.llm.quick.reasoning_effort == "medium"


def test_project_config_loads_settings_watchlist_and_optional_portfolio(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    (root / "config" / "watchlist.yaml").write_text(
        "items:\n  - symbol: NVDA\n    type: stock\n", encoding="utf-8"
    )
    config = load_project_config(root, environ={})
    assert config.settings == Settings()
    assert config.watchlist.items[0].symbol == "NVDA"
    assert config.portfolio is None
    assert not config.credentials.alpaca_configured


def test_optional_portfolio_matches_upstream_portfolio_context(tmp_path: Path) -> None:
    root = _project(tmp_path)
    (root / "config" / "portfolio.yaml").write_text(
        "cash: 25000\ncurrency: USD\npositions:\n"
        "  - ticker: nvda\n    quantity: 120\n    average_price: 150\n",
        encoding="utf-8",
    )
    portfolio = load_portfolio(root)
    assert portfolio is not None
    upstream = to_tradingagents_portfolio(portfolio)
    assert upstream.cash == 25000
    assert upstream.currency == "USD"
    assert upstream.position_in("NVDA").ticker == "NVDA"
    assert upstream.position_in("NVDA").average_price == 150

    assert parse_portfolio({"cash": None, "currency": "USD", "positions": []})


def test_credentials_merge_environment_over_local_file_and_mask_repr(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _secrets_file(root)
    credentials = load_credentials(
        root,
        environ={"APCA_API_KEY_ID": "env-id"},
        require_alpaca=True,
    )
    assert credentials.alpaca_key_id.get_secret_value() == "env-id"
    assert credentials.alpaca_secret_key.get_secret_value() == "file-secret"
    assert "file-secret" not in repr(credentials)
    assert "env-id" not in repr(credentials)


def test_credentials_can_come_from_environment_without_a_file(tmp_path: Path) -> None:
    root = _project(tmp_path)
    credentials = load_credentials(
        root,
        environ={
            "APCA_API_KEY_ID": "environment-id",
            "APCA_API_SECRET_KEY": "environment-secret",
        },
        require_alpaca=True,
    )
    assert credentials.alpaca_configured


def test_required_credentials_fail_without_printing_values(tmp_path: Path) -> None:
    root = _project(tmp_path)
    with pytest.raises(ConfigurationError) as caught:
        load_credentials(root, environ={}, require_alpaca=True)
    assert "APCA_API_KEY_ID" in str(caught.value)
    assert "APCA_API_SECRET_KEY" in str(caught.value)


def test_credentials_reject_file_permissions_other_than_0600(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _secrets_file(root, 0o644)
    with pytest.raises(ConfigurationError) as caught:
        load_credentials(root, environ={})
    assert "权限必须为 0600" in str(caught.value)
    assert "chmod 600" in str(caught.value)


def test_credentials_open_only_project_local_secrets_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    secret_path = _secrets_file(root)
    opened: list[Path] = []
    real_open = builtins.open

    def record_open(file: object, *args: object, **kwargs: object):
        opened.append(Path(file).resolve())
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", record_open)
    load_credentials(root, environ={})
    assert opened == [secret_path.resolve()]


def test_credentials_refuse_a_secret_symlink_outside_project(tmp_path: Path) -> None:
    root = _project(tmp_path / "project")
    outside = tmp_path / "outside.env"
    outside.write_text("APCA_API_KEY_ID=outside\n", encoding="utf-8")
    outside.chmod(0o600)
    (root / "config" / "secrets.env").symlink_to(outside)
    with pytest.raises(ConfigurationError) as caught:
        load_credentials(root, environ={})
    assert "超出项目目录" in str(caught.value)


def test_secrets_file_is_ignored_by_git() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "-q", "config/secrets.env"],
        cwd=PROJECT_ROOT,
        check=False,
    )
    assert result.returncode == 0


def test_project_source_has_no_cross_project_import_or_sys_path_hack() -> None:
    source_dir = PROJECT_ROOT / "src" / "daily_analyzer"
    source = "\n".join(path.read_text(encoding="utf-8") for path in source_dir.rglob("*.py"))
    assert "import us_stock_trading" not in source
    assert "from us_stock_trading" not in source
    assert "import quant_trading" not in source
    assert "from quant_trading" not in source
    assert "sys.path" not in source
    assert "quant_trading" not in source
    assert "us_stock_trading" not in source


def test_settings_and_watchlist_files_must_stay_inside_project(tmp_path: Path) -> None:
    root = _project(tmp_path / "project")
    outside = tmp_path / "outside.yaml"
    outside.write_text("items: []\n", encoding="utf-8")
    (root / "config" / "watchlist.yaml").symlink_to(outside)
    with pytest.raises(ConfigurationError):
        load_watchlist(root)

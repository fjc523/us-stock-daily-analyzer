from __future__ import annotations

import builtins

import pytest

from daily_analyzer import cli
from daily_analyzer.config import Settings


def test_top_level_help_lists_all_commands_without_reading_files(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail_open(*args: object, **kwargs: object):
        raise AssertionError("help must not read configuration or credentials")

    monkeypatch.setattr(builtins, "open", fail_open)
    with pytest.raises(SystemExit) as caught:
        cli.main(["--help"])
    assert caught.value.code == 0
    output = capsys.readouterr().out
    for command in ("run", "build-site", "doctor", "schedule"):
        assert command in output


@pytest.mark.parametrize(
    "argv",
    [
        ["run", "--date", "2026-10-01", "--tickers", "NVDA", "--model", "gpt-6-sol", "--effort", "xhigh"],
        ["build-site"],
        ["doctor", "--ping"],
        ["schedule", "install"],
        ["schedule", "uninstall"],
        ["schedule", "status"],
    ],
)
def test_unimplemented_commands_exit_nonzero_and_say_so(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(argv) == 2
    assert "尚未实现" in capsys.readouterr().err


def test_run_merges_cli_overrides_before_reporting_unimplemented(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    observed: dict[str, object] = {}

    def capture(settings: Settings, model: str | None, effort: str | None) -> Settings:
        observed["model"] = model
        observed["effort"] = effort
        return settings

    monkeypatch.setattr(cli, "load_settings", lambda project_root: Settings())
    monkeypatch.setattr(cli, "apply_llm_overrides", capture)
    assert cli.main(
        ["run", "--model", "gpt-6-luna", "--effort", "medium"]
    ) == 2
    assert observed == {"model": "gpt-6-luna", "effort": "medium"}
    assert "尚未实现" in capsys.readouterr().err

from __future__ import annotations

import builtins
from pathlib import Path
from types import SimpleNamespace

import pytest

from daily_analyzer import cli


def test_top_level_help_lists_commands_without_reading_files(
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


def test_run_passes_options_and_returns_runner_exit_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    observed: dict[str, object] = {}

    def run(root: Path, args: object):
        observed["root"] = root
        observed["args"] = args
        return SimpleNamespace(exit_code=3, message="当前没有可分析的交易日")

    monkeypatch.setattr(cli, "_run_analysis", run)
    assert cli.main(
        ["run", "--date", "2026-10-01", "--tickers", "NVDA,SPY", "--force", "--model", "gpt-6-sol", "--effort", "xhigh"]
    ) == 3
    output = capsys.readouterr().err
    assert "当前没有可分析的交易日" in output
    args = observed["args"]
    assert args.date == "2026-10-01"
    assert args.tickers == "NVDA,SPY"
    assert args.force is True
    assert args.model == "gpt-6-sol"
    assert args.effort == "xhigh"


@pytest.mark.parametrize(
    ("argv", "method", "expected"),
    [
        (["build-site"], "_build_site", "站点已生成"),
        (["doctor", "--ping"], "_doctor", "自检完成"),
        (["schedule", "install"], "_schedule", "定时任务已安装"),
        (["schedule", "uninstall"], "_schedule", "定时任务已卸载"),
        (["schedule", "status"], "_schedule", "定时任务状态"),
    ],
)
def test_other_commands_call_implementation(
    argv: list[str],
    method: str,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed: list[object] = []

    def build_site(root: Path):
        observed.append(root)
        return {"ok": True, "site_path": str(root / "site")}

    def doctor(root: Path, ping: bool):
        observed.extend((root, ping))
        return {
            "ok": True,
            "exit_code": 0,
            "checks": [{"status": "pass", "name": "检查项", "detail": "正常"}],
            "summary": "自检完成",
        }

    def schedule(root: Path, action: str):
        observed.extend((root, action))
        return {"ok": True, "plist_path": "/tmp/test.plist"}

    monkeypatch.setattr(cli, "_build_site", build_site)
    monkeypatch.setattr(cli, "_doctor", doctor)
    monkeypatch.setattr(cli, "_schedule", schedule)
    assert cli.main(argv) == 0
    output = capsys.readouterr().out
    assert expected in output
    assert observed


def test_build_site_failure_returns_nonzero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        cli, "_build_site", lambda root: {"ok": False, "error": "模板错误"}
    )
    assert cli.main(["build-site"]) == 1
    assert "模板错误" in capsys.readouterr().err

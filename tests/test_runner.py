from __future__ import annotations

import json
import os
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from daily_analyzer.config import parse_settings
from daily_analyzer.context import ContextBlock
from daily_analyzer.runner import (
    _analyze_item,
    _manifest_usage,
    _progress_value,
    _recompute_manifest,
    _wait_until_first_start,
    run_analysis,
)
from daily_analyzer.time_utils import RunWindow

NEW_YORK = ZoneInfo("America/New_York")


def _project(
    root: Path,
    symbols: tuple[str, ...] = ("NVDA", "SPY"),
    parallelism: int = 2,
) -> Path:
    config = root / "config"
    config.mkdir(parents=True)
    (config / "settings.yaml").write_text(
        "context_providers: []\n"
        "run:\n"
        f"  max_parallel_tickers: {parallelism}\n"
        "  max_duration_minutes: 10\n"
        "schedule:\n"
        '  anchor: "08:30 America/New_York"\n',
        encoding="utf-8",
    )
    rows = []
    for symbol in symbols:
        kind = "etf" if symbol in {"SPY", "QQQ", "DIA", "IWM"} else "stock"
        rows.append(f"  - symbol: {symbol}\n    type: {kind}\n")
    (config / "watchlist.yaml").write_text("items:\n" + "".join(rows), encoding="utf-8")
    return root


class _ContextManager:
    def __init__(self) -> None:
        self.prepared: dict[str, object] | None = None
        self.prepared_key_id: str | None = None
        self.prepare_error: BaseException | None = None
        self.closed = False
        self.built_symbols: list[str] = []
        self.build_threads: list[int] = []

    def prepare(self, batch: dict[str, object]) -> dict[str, ContextBlock]:
        self.prepared = batch
        self.prepared_key_id = os.environ.get("APCA_API_KEY_ID")
        if self.prepare_error is not None:
            raise self.prepare_error
        return {
            "batch": ContextBlock(
                "批次上下文", "批次信息", {"market": "稳定"}, batch["context_as_of"], ["fake"]
            )
        }

    def build(self, item: object, cutoff: datetime) -> dict[str, ContextBlock]:
        self.built_symbols.append(item.symbol)
        self.build_threads.append(threading.get_ident())
        return {
            f"ticker_{item.symbol}": ContextBlock(
                "标的上下文", f"仅供 {item.symbol} 使用", {"symbol": item.symbol}, cutoff, ["fake"]
            )
        }

    def close(self) -> None:
        self.closed = True


class _ToolTrace:
    def snapshot(self) -> list[dict[str, str]]:
        stamp = "2026-10-02T10:16:00-04:00"
        return [{"name": "get_news", "started_at": stamp, "finished_at": stamp}]


class _FakeGraph:
    fail_symbols: set[str] = set()
    errors_by_symbol: dict[str, BaseException] = {}
    configs: list[dict[str, object]] = []
    analyzed: list[str] = []
    key_ids: list[str | None] = []
    context_as_of_values: list[datetime] = []
    report_threads: list[int] = []

    def __init__(self, *, item: object, config: dict[str, object], **kwargs: object) -> None:
        self.item = item
        self.analysis_symbol = item.analysis_symbol
        self.config = config
        self.configs.append(config)
        self.key_ids.append(os.environ.get("APCA_API_KEY_ID"))
        self.context_as_of_values.append(kwargs["context_as_of"])
        self.tool_trace = _ToolTrace()

    def propagate(self, company_name: str, trade_date: str, **kwargs: object):
        self.analyzed.append(self.item.symbol)
        if self.item.symbol in self.errors_by_symbol:
            raise self.errors_by_symbol[self.item.symbol]
        if self.item.symbol in self.fail_symbols:
            raise RuntimeError("fixture analysis failure")
        state = {
            "company_of_interest": company_name,
            "trade_date": trade_date,
            "market_report": "market",
            "sentiment_report": "sentiment",
            "news_report": "news",
            "fundamentals_report": "fundamentals",
            "final_trade_decision": "买入",
            "trader_investment_plan": "plan",
            "investment_plan": "investment",
            "investment_debate_state": {},
            "risk_debate_state": {},
        }
        return state, "BUY"

    def save_reports(self, state: object, *, ticker: str, save_path: Path) -> None:
        self.report_threads.append(threading.get_ident())
        save_path.mkdir(parents=True, exist_ok=True)
        (save_path / "report.txt").write_text(ticker, encoding="utf-8")


def _run(
    root: Path,
    *,
    clock,
    scheduled: bool = False,
    force: bool = False,
    tickers: str | None = None,
    context_manager: _ContextManager | None = None,
    monotonic=None,
    sleeper=None,
    analyzer_factory=None,
    site_builder=None,
):
    _FakeGraph.configs = []
    _FakeGraph.analyzed = []
    _FakeGraph.key_ids = []
    _FakeGraph.context_as_of_values = []
    _FakeGraph.report_threads = []
    return run_analysis(
        root,
        scheduled=scheduled,
        force=force,
        tickers=tickers,
        clock=clock,
        monotonic=monotonic or (lambda: 100.0),
        sleeper=sleeper or (lambda seconds: None),
        context_manager_factory=lambda *args: context_manager or _ContextManager(),
        analyzer_factory=analyzer_factory or _FakeGraph,
        site_builder=site_builder or (lambda *args, **kwargs: {"ok": True}),
    )


def test_runner_writes_batch_results_and_uses_one_shared_config(
    tmp_path: Path, monkeypatch
) -> None:
    import daily_analyzer.runner as runner

    monkeypatch.setattr(runner, "_codex_version", lambda settings: "test")
    monkeypatch.setattr(runner, "_fork_state", lambda root: {"tradingagents_commit": "abc", "tradingagents_dirty": False})
    _FakeGraph.fail_symbols = set()
    now = datetime(2026, 10, 2, 10, 15, tzinfo=NEW_YORK)
    manager = _ContextManager()
    result = _run(_project(tmp_path), clock=lambda: now, context_manager=manager)

    assert result.exit_code == 0
    assert result.status == "completed"
    assert manager.closed
    assert len(_FakeGraph.configs) == 2
    assert _FakeGraph.configs[0] is _FakeGraph.configs[1]
    assert _FakeGraph.configs[0]["trade_date"] == "2026-10-02"
    assert _FakeGraph.configs[0]["price_data_end_date"] == "2026-10-01"
    batch_dir = tmp_path / "data" / "runs" / "2026-10-02" / "batches" / result.run_id
    batch = json.loads((batch_dir / "batch.json").read_text(encoding="utf-8"))
    context = json.loads((batch_dir / "context.json").read_text(encoding="utf-8"))
    assert set(context) == {"batch"}
    assert all(item["status"] == "success" for item in batch["items"].values())
    for symbol in ("NVDA", "SPY"):
        payload = json.loads(
            (batch_dir / "results" / f"{symbol}.json").read_text(encoding="utf-8")
        )
        assert f"仅供 {symbol} 使用" in payload["injected_context"]
        assert payload["data_queries"][0]["name"] == "get_news"
        assert payload["information_through"] == "2026-10-02T10:16:00-04:00"


def test_project_credentials_are_available_to_prepare_and_workers(
    tmp_path: Path, monkeypatch
) -> None:
    import daily_analyzer.runner as runner

    monkeypatch.setattr(runner, "_codex_version", lambda settings: None)
    monkeypatch.setattr(runner, "_fork_state", lambda root: {})
    root = _project(tmp_path, ("NVDA",))
    secrets = root / "config" / "secrets.env"
    secrets.write_text(
        "APCA_API_KEY_ID=fixture-id\nAPCA_API_SECRET_KEY=fixture-secret\n",
        encoding="utf-8",
    )
    secrets.chmod(0o600)
    monkeypatch.setenv("APCA_API_KEY_ID", "")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "")
    manager = _ContextManager()
    now = datetime(2026, 10, 2, 10, 15, tzinfo=NEW_YORK)

    result = _run(root, clock=lambda: now, context_manager=manager)

    assert result.exit_code == 0
    assert manager.prepared_key_id == "fixture-id"
    assert _FakeGraph.key_ids == ["fixture-id"]
    assert os.environ["APCA_API_KEY_ID"] == ""


def test_prepare_failure_finalizes_batch_instead_of_leaving_it_running(
    tmp_path: Path, monkeypatch
) -> None:
    import daily_analyzer.runner as runner

    monkeypatch.setattr(runner, "_codex_version", lambda settings: None)
    monkeypatch.setattr(runner, "_fork_state", lambda root: {})
    manager = _ContextManager()
    manager.prepare_error = RuntimeError("fixture prepare failure")
    root = _project(tmp_path, ("NVDA",))
    now = datetime(2026, 10, 2, 10, 15, tzinfo=NEW_YORK)

    result = _run(root, clock=lambda: now, context_manager=manager)

    assert result.exit_code == 1
    assert manager.closed
    batch = json.loads(
        (root / "data" / "runs" / "2026-10-02" / "batches" / result.run_id / "batch.json").read_text(encoding="utf-8")
    )
    assert batch["status"] == "failed"
    assert batch["items"]["NVDA"]["status"] == "failed"
    assert batch["finished_at"] is not None


def test_failed_forced_attempt_keeps_previous_success_and_records_retry(
    tmp_path: Path, monkeypatch
) -> None:
    import daily_analyzer.runner as runner

    monkeypatch.setattr(runner, "_codex_version", lambda settings: None)
    monkeypatch.setattr(runner, "_fork_state", lambda root: {})
    root = _project(tmp_path, ("NVDA",))
    current = datetime(2026, 10, 2, 10, 15, tzinfo=NEW_YORK)
    outcome = _run(root, clock=lambda: current)
    assert outcome.exit_code == 0
    first_run_id = outcome.run_id

    _FakeGraph.fail_symbols = {"NVDA"}
    retry = _run(root, clock=lambda: current + timedelta(seconds=1), force=True)
    assert retry.exit_code == 1
    assert retry.status == "failed"
    current_file = root / "data" / "runs" / "2026-10-02" / "current" / "NVDA.json"
    assert json.loads(current_file.read_text(encoding="utf-8"))["run_id"] == first_run_id
    manifest = json.loads(
        (root / "data" / "runs" / "2026-10-02" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["items"]["NVDA"]["recent_retry_failure"]["status"] == "failed"
    assert len(manifest["items"]["NVDA"]["attempts"]) == 2
    _FakeGraph.fail_symbols = set()


def test_quota_stops_dispatch_and_marks_remaining_tickers(
    tmp_path: Path, monkeypatch
) -> None:
    import daily_analyzer.runner as runner

    class CodexQuotaError(Exception):
        pass

    monkeypatch.setattr(runner, "_codex_version", lambda settings: None)
    monkeypatch.setattr(runner, "_fork_state", lambda root: {})
    _FakeGraph.fail_symbols = set()
    _FakeGraph.errors_by_symbol = {"NVDA": CodexQuotaError("fixture quota")}
    root = _project(tmp_path, parallelism=1)
    now = datetime(2026, 10, 2, 10, 15, tzinfo=NEW_YORK)

    result = _run(root, clock=lambda: now)

    assert result.exit_code == 1
    assert _FakeGraph.analyzed == ["NVDA"]
    batch = json.loads(
        (root / "data" / "runs" / "2026-10-02" / "batches" / result.run_id / "batch.json").read_text(encoding="utf-8")
    )
    assert batch["items"]["NVDA"]["failure_category"] == "quota"
    assert batch["items"]["SPY"]["status"] == "skipped_quota"
    skipped = json.loads(
        (root / "data" / "runs" / "2026-10-02" / "batches" / result.run_id / "results" / "SPY.json").read_text(encoding="utf-8")
    )
    assert skipped["started_at"] is None
    assert skipped["started_after_open"] is False
    assert skipped["finished_after_open"] is False
    _FakeGraph.errors_by_symbol = {}


def test_fatal_configuration_stops_dispatch_and_resets_abort_state(
    tmp_path: Path, monkeypatch
) -> None:
    import daily_analyzer.runner as runner
    from tradingagents.llm_clients.codex_exec.runner import reset_abort

    class CodexFatalConfigError(Exception):
        pass

    monkeypatch.setattr(runner, "_codex_version", lambda settings: None)
    monkeypatch.setattr(runner, "_fork_state", lambda root: {})
    _FakeGraph.fail_symbols = set()
    _FakeGraph.errors_by_symbol = {"NVDA": CodexFatalConfigError("fixture config")}
    root = _project(tmp_path, parallelism=1)
    now = datetime(2026, 10, 2, 10, 15, tzinfo=NEW_YORK)

    result = _run(root, clock=lambda: now)

    assert result.exit_code == 1
    batch = json.loads(
        (root / "data" / "runs" / "2026-10-02" / "batches" / result.run_id / "batch.json").read_text(encoding="utf-8")
    )
    assert batch["items"]["NVDA"]["status"] == "failed"
    assert batch["items"]["SPY"]["status"] == "skipped_fatal"
    reset_abort()
    _FakeGraph.errors_by_symbol = {}


def test_batch_timeout_skips_all_not_yet_dispatched_tickers(
    tmp_path: Path, monkeypatch
) -> None:
    import daily_analyzer.runner as runner

    monkeypatch.setattr(runner, "_codex_version", lambda settings: None)
    monkeypatch.setattr(runner, "_fork_state", lambda root: {})
    _FakeGraph.fail_symbols = set()
    _FakeGraph.errors_by_symbol = {}
    root = _project(tmp_path)
    settings_path = root / "config" / "settings.yaml"
    settings_path.write_text(
        "context_providers: []\nrun:\n  max_parallel_tickers: 2\n  max_duration_minutes: 1\n",
        encoding="utf-8",
    )
    ticks = iter((0.0, 60.0))
    now = datetime(2026, 10, 2, 10, 15, tzinfo=NEW_YORK)

    result = _run(root, clock=lambda: now, monotonic=lambda: next(ticks))

    assert result.exit_code == 1
    assert _FakeGraph.analyzed == []
    batch = json.loads(
        (root / "data" / "runs" / "2026-10-02" / "batches" / result.run_id / "batch.json").read_text(encoding="utf-8")
    )
    assert {item["status"] for item in batch["items"].values()} == {"skipped_timeout"}


def test_scheduled_recovery_marks_dead_running_batch_and_only_analyzes_missing_symbols(
    tmp_path: Path, monkeypatch
) -> None:
    import daily_analyzer.runner as runner

    monkeypatch.setattr(runner, "_codex_version", lambda settings: None)
    monkeypatch.setattr(runner, "_fork_state", lambda root: {})
    monkeypatch.setattr(runner, "_pid_alive", lambda pid: False)
    root = _project(tmp_path, ("NVDA", "SPY"))
    day_dir = root / "data" / "runs" / "2026-10-02"
    old_batch = day_dir / "batches" / "old" / "batch.json"
    old_batch.parent.mkdir(parents=True)
    old_batch.write_text(
        json.dumps(
            {
                "run_id": "old",
                "pid": 99999999,
                "trade_date": "2026-10-02",
                "scheduled": True,
                "status": "running",
                "items": {"NVDA": {"status": "success"}, "SPY": {"status": "running"}},
            }
        ),
        encoding="utf-8",
    )
    current_dir = day_dir / "current"
    current_dir.mkdir()
    (current_dir / "NVDA.json").write_text(
        json.dumps({"status": "success", "symbol": "NVDA", "run_id": "old"}),
        encoding="utf-8",
    )
    now = datetime(2026, 10, 2, 9, 0, tzinfo=NEW_YORK)
    _FakeGraph.fail_symbols = set()
    result = _run(root, clock=lambda: now, scheduled=True)
    assert result.exit_code == 0
    assert _FakeGraph.analyzed == ["SPY"]
    recovered_batch = json.loads(old_batch.read_text(encoding="utf-8"))
    assert recovered_batch["status"] == "interrupted"
    assert recovered_batch["items"]["NVDA"]["status"] == "success"
    assert recovered_batch["items"]["SPY"]["status"] == "interrupted"
    status = json.loads((root / "data" / "status.json").read_text(encoding="utf-8"))
    assert status["last_schedule_event"]["result"] == "recovery_started"


def test_scheduled_failed_fatal_batch_is_skipped_without_retry_or_context_start(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path, ("NVDA",))
    day_dir = root / "data" / "runs" / "2026-10-02"
    old_batch = day_dir / "batches" / "fatal-attempt" / "batch.json"
    old_batch.parent.mkdir(parents=True)
    old_batch.write_text(
        json.dumps(
            {
                "run_id": "fatal-attempt",
                "pid": os.getpid(),
                "trade_date": "2026-10-02",
                "scheduled": True,
                "status": "failed",
                "finished_at": "2026-10-02T09:02:00-04:00",
                "items": {
                    "NVDA": {
                        "symbol": "NVDA",
                        "status": "failed",
                        "failure_category": "fatal_config",
                        "error": "Codex 配置无效",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    previous_last_run = {
        "run_id": "fatal-attempt",
        "trade_date": "2026-10-02",
        "status": "failed",
        "last_error": "Codex 配置无效",
    }
    status_path = root / "data" / "status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps({"last_run": previous_last_run}), encoding="utf-8")
    manager = _ContextManager()

    result = _run(
        root,
        clock=lambda: datetime(2026, 10, 2, 9, 5, tzinfo=NEW_YORK),
        scheduled=True,
        context_manager=manager,
    )

    assert result.exit_code == 0
    assert "已有已结束的定时批次" in result.message
    assert manager.prepared is None
    assert manager.built_symbols == []
    assert manager.closed is False
    assert _FakeGraph.analyzed == []
    assert list((day_dir / "batches").glob("*/batch.json")) == [old_batch]
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["last_run"] == previous_last_run
    assert status["last_schedule_event"]["result"] == "skipped_already_done"


def test_schedule_skip_updates_event_without_replacing_last_run(
    tmp_path: Path, monkeypatch
) -> None:
    import daily_analyzer.runner as runner

    root = _project(tmp_path, ("NVDA",))
    status_path = root / "data" / "status.json"
    status_path.parent.mkdir()
    status_path.write_text(json.dumps({"last_run": {"run_id": "existing", "status": "partial"}}))
    before_anchor = datetime(2026, 10, 2, 8, 0, tzinfo=NEW_YORK)
    outcome = _run(root, clock=lambda: before_anchor, scheduled=True)
    assert outcome.exit_code == 0
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["last_run"] == {"run_id": "existing", "status": "partial"}
    assert status["last_schedule_event"]["result"] == "skipped_before_anchor"


def test_first_live_ticker_waits_until_configured_anchor_delay() -> None:
    settings = parse_settings(
        {"run": {"min_start_after_anchor_seconds": 60}, "schedule": {"anchor": "08:30 America/New_York"}}
    )
    window = RunWindow(
        trade_date=date(2026, 10, 2),
        price_data_end_date=date(2026, 10, 1),
        mode="live",
        news_cutoff_utc=None,
    )
    now = [datetime(2026, 10, 2, 8, 30, tzinfo=NEW_YORK)]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += timedelta(seconds=seconds)

    _wait_until_first_start(settings, window, lambda: now[0], sleep)
    assert sleeps == [60.0]
    assert now[0] == datetime(2026, 10, 2, 8, 31, tzinfo=NEW_YORK)


def test_run_waits_after_batch_prepare_before_starting_first_ticker(
    tmp_path: Path, monkeypatch
) -> None:
    import daily_analyzer.runner as runner

    monkeypatch.setattr(runner, "_codex_version", lambda settings: None)
    monkeypatch.setattr(runner, "_fork_state", lambda root: {})
    root = _project(tmp_path, ("NVDA",))
    now = [datetime(2026, 10, 2, 8, 30, tzinfo=NEW_YORK)]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += timedelta(seconds=seconds)

    manager = _ContextManager()
    result = _run(
        root,
        clock=lambda: now[0],
        context_manager=manager,
        sleeper=sleep,
    )

    assert result.exit_code == 0
    assert sleeps == [60.0]
    assert manager.prepared["context_as_of"] == datetime(2026, 10, 2, 8, 30, tzinfo=NEW_YORK)
    assert _FakeGraph.context_as_of_values == [datetime(2026, 10, 2, 8, 31, tzinfo=NEW_YORK)]


def test_running_items_are_not_counted_as_completed() -> None:
    now = datetime(2026, 10, 2, 10, 0, tzinfo=NEW_YORK)
    progress = _progress_value(
        {"parallelism": 2, "items": {"A": {"status": "success"}, "B": {"status": "running"}, "C": {"status": "pending"}}},
        now,
    )
    assert progress["completed"] == 1
    assert progress["total"] == 3


def test_aborted_outcome_stops_dispatch_before_concurrent_fatal_config_returns(
    tmp_path: Path, monkeypatch
) -> None:
    import daily_analyzer.runner as runner
    from tradingagents.llm_clients.codex_exec.runner import reset_abort

    class CodexAbortedError(Exception):
        pass

    class CodexFatalConfigError(Exception):
        pass

    fatal_started = threading.Event()
    release_fatal = threading.Event()
    submitted: list[str] = []
    manager = _ContextManager()
    real_executor = runner.ThreadPoolExecutor
    real_wait = runner.wait
    wait_calls = 0

    class StagedGraph(_FakeGraph):
        def propagate(self, company_name: str, trade_date: str, **kwargs: object):
            if self.item.symbol == "NVDA":
                assert fatal_started.wait(5), "致命错误线程未进入图调用"
                raise CodexAbortedError("fixture aborted")
            if self.item.symbol == "SPY":
                fatal_started.set()
                assert release_fatal.wait(5), "测试未释放致命错误线程"
                raise CodexFatalConfigError("fixture fatal config")
            return super().propagate(company_name, trade_date, **kwargs)

    class RecordingExecutor(real_executor):
        def submit(self, fn, *args, **kwargs):
            submitted.append(kwargs["item"].symbol)
            return super().submit(fn, *args, **kwargs)

    def staged_wait(futures, timeout=None, return_when=None):
        nonlocal wait_calls
        wait_calls += 1
        if wait_calls == 2:
            release_fatal.set()
        return real_wait(futures, timeout=timeout, return_when=return_when)

    monkeypatch.setattr(runner, "ThreadPoolExecutor", RecordingExecutor)
    monkeypatch.setattr(runner, "wait", staged_wait)
    monkeypatch.setattr(runner, "_codex_version", lambda settings: None)
    monkeypatch.setattr(runner, "_fork_state", lambda root: {})
    root = _project(tmp_path, ("NVDA", "SPY", "TSLA"), parallelism=2)
    now = datetime(2026, 10, 2, 10, 15, tzinfo=NEW_YORK)

    try:
        result = _run(
            root,
            clock=lambda: now,
            context_manager=manager,
            analyzer_factory=StagedGraph,
        )
    finally:
        release_fatal.set()
        reset_abort()

    assert result.exit_code == 1
    assert submitted == ["NVDA", "SPY"]
    assert set(manager.built_symbols) == {"NVDA", "SPY"}
    assert "TSLA" not in manager.built_symbols
    batch = json.loads(
        (root / "data" / "runs" / "2026-10-02" / "batches" / result.run_id / "batch.json").read_text(encoding="utf-8")
    )
    assert batch["items"]["NVDA"]["status"] == "skipped_fatal"
    assert batch["items"]["SPY"]["status"] == "failed"
    assert batch["items"]["TSLA"]["status"] == "skipped_fatal"


def test_failed_attempt_records_open_times_and_keeps_macro_or_tool_truncation(
    tmp_path: Path,
) -> None:
    class FailedGraph:
        def __init__(self, *, tool_truncated: bool, **kwargs: object) -> None:
            stamp = "2026-10-02T09:36:00-04:00"
            self.tool_trace = type(
                "Trace",
                (),
                {
                    "snapshot": lambda self: [
                        {
                            "name": "get_news",
                            "started_at": stamp,
                            "finished_at": stamp,
                            "truncated": tool_truncated,
                        }
                    ]
                },
            )()

        def propagate(self, *args: object, **kwargs: object):
            raise RuntimeError("fixture analysis failure")

    item = type(
        "WatchItem",
        (),
        {"symbol": "NVDA", "analysis_symbol": "NVDA", "type": "stock"},
    )()
    trade_day = date(2026, 10, 2)
    window = RunWindow(trade_day, date(2026, 10, 1), "live", None)
    start = datetime(2026, 10, 2, 9, 31, tzinfo=NEW_YORK)
    finish = datetime(2026, 10, 2, 9, 37, tzinfo=NEW_YORK)

    for index, (macro_truncated, tool_truncated, expected) in enumerate(
        ((True, False, True), (False, True, True), (False, False, False))
    ):
        batch_dir = tmp_path / str(index)
        (batch_dir / "results").mkdir(parents=True)

        class MacroContext:
            def build(self, item: object, cutoff: datetime):
                return {
                    "macro_releases": ContextBlock(
                        "宏观发布", "fixture", {"truncated": macro_truncated}, cutoff, ["fixture"]
                    )
                }

        clock_values = iter((start, finish))
        outcome = _analyze_item(
            item=item,
            run_id=f"failure-{index}",
            root=tmp_path,
            batch_dir=batch_dir,
            window=window,
            shared_config={"llm_provider": "test"},
            context_manager=MacroContext(),
            context_build_lock=threading.Lock(),
            portfolio=None,
            clock=lambda: next(clock_values),
            monotonic=iter((1.0, 2.0)).__next__,
            secrets=(),
            analyzer_factory=lambda **kwargs: FailedGraph(
                tool_truncated=tool_truncated, **kwargs
            ),
        )
        assert not outcome.succeeded
        assert outcome.result["started_at"] == start.isoformat(timespec="seconds")
        assert outcome.result["finished_at"] == finish.isoformat(timespec="seconds")
        assert outcome.result["started_after_open"] is True
        assert outcome.result["finished_after_open"] is True
        assert outcome.result["news_truncated"] is expected


def test_run_lock_rejects_a_concurrent_start(tmp_path: Path, monkeypatch) -> None:
    import daily_analyzer.runner as runner

    root = _project(tmp_path, ("NVDA",))
    now = datetime(2026, 10, 2, 10, 15, tzinfo=NEW_YORK)
    acquired = threading.Event()
    release = threading.Event()

    def hold_lock() -> None:
        with runner.run_lock(root):
            acquired.set()
            release.wait(5)

    holder = threading.Thread(target=hold_lock)
    holder.start()
    try:
        assert acquired.wait(5), "测试线程未持有运行锁"
        result = _run(root, clock=lambda: now)
    finally:
        release.set()
        holder.join(timeout=5)

    assert not holder.is_alive()
    assert result.exit_code == 1
    assert "已有运行中的实例" in result.message
    assert not (root / "data" / "runs" / "2026-10-02" / "batches").exists()


def test_held_position_is_dispatched_first(tmp_path: Path, monkeypatch) -> None:
    import daily_analyzer.runner as runner

    monkeypatch.setattr(runner, "_codex_version", lambda settings: None)
    monkeypatch.setattr(runner, "_fork_state", lambda root: {})
    root = _project(tmp_path, ("AAPL", "MSFT", "NVDA"), parallelism=1)
    (root / "config" / "portfolio.yaml").write_text(
        "cash: 1000\ncurrency: USD\npositions:\n  - ticker: NVDA\n    quantity: 2\n    average_price: 100\n",
        encoding="utf-8",
    )
    now = datetime(2026, 10, 2, 10, 15, tzinfo=NEW_YORK)

    result = _run(root, clock=lambda: now)

    assert result.exit_code == 0
    assert _FakeGraph.analyzed == ["NVDA", "AAPL", "MSFT"]


def test_shared_state_and_site_writes_stay_on_main_thread(tmp_path: Path, monkeypatch) -> None:
    import daily_analyzer.runner as runner

    monkeypatch.setattr(runner, "_codex_version", lambda settings: None)
    monkeypatch.setattr(runner, "_fork_state", lambda root: {})
    root = _project(tmp_path, ("NVDA", "SPY"), parallelism=2)
    main_thread = threading.get_ident()
    writes: list[tuple[Path, int]] = []
    site_threads: list[int] = []
    writes_lock = threading.Lock()
    original_write = runner.atomic_write_json

    def record_write(path, value) -> None:
        with writes_lock:
            writes.append((Path(path), threading.get_ident()))
        original_write(path, value)

    def record_site(*args, **kwargs):
        site_threads.append(threading.get_ident())
        return {"ok": True}

    monkeypatch.setattr(runner, "atomic_write_json", record_write)
    manager = _ContextManager()
    result = _run(
        root,
        clock=lambda: datetime(2026, 10, 2, 10, 15, tzinfo=NEW_YORK),
        context_manager=manager,
        site_builder=record_site,
    )

    assert result.exit_code == 0
    assert manager.build_threads and all(thread_id != main_thread for thread_id in manager.build_threads)
    assert _FakeGraph.report_threads and all(thread_id != main_thread for thread_id in _FakeGraph.report_threads)
    assert site_threads and set(site_threads) == {main_thread}
    worker_results = [
        thread_id
        for path, thread_id in writes
        if "results" in path.parts and path.suffix == ".json"
    ]
    assert len(worker_results) == 2
    assert all(thread_id != main_thread for thread_id in worker_results)
    main_state = [
        thread_id
        for path, thread_id in writes
        if path.name in {"batch.json", "manifest.json", "status.json"}
        or "current" in path.parts
    ]
    assert main_state and set(main_state) == {main_thread}


def test_site_failure_does_not_change_analysis_result_or_exit_code(
    tmp_path: Path, monkeypatch
) -> None:
    import daily_analyzer.runner as runner

    monkeypatch.setattr(runner, "_codex_version", lambda settings: None)
    monkeypatch.setattr(runner, "_fork_state", lambda root: {})
    root = _project(tmp_path, ("NVDA",))
    result = _run(
        root,
        clock=lambda: datetime(2026, 10, 2, 10, 15, tzinfo=NEW_YORK),
        site_builder=lambda *args, **kwargs: {"ok": False, "error": "fixture site failure"},
    )

    assert result.exit_code == 0
    assert result.status == "completed"
    current = json.loads(
        (root / "data" / "runs" / "2026-10-02" / "current" / "NVDA.json").read_text(encoding="utf-8")
    )
    assert current["status"] == "success"
    log = (root / "logs" / "2026-10-02.log").read_text(encoding="utf-8")
    assert "站点构建失败：fixture site failure" in log


def test_manifest_usage_sums_batches_and_recompute_is_idempotent(tmp_path: Path) -> None:
    trade_day = date(2026, 10, 2)
    batches_dir = tmp_path / "data" / "runs" / trade_day.isoformat() / "batches"
    for run_id, input_tokens, output_tokens in (("first", 10, 4), ("second", 20, 8)):
        batch_dir = batches_dir / run_id
        batch_dir.mkdir(parents=True)
        (batch_dir / "batch.json").write_text(
            json.dumps({"run_id": run_id, "status": "completed", "items": {}}),
            encoding="utf-8",
        )
        (batch_dir / "llm_calls.jsonl").write_text(
            json.dumps(
                {
                    "tokens": {
                        "input_tokens": input_tokens,
                        "cached_input_tokens": 1,
                        "output_tokens": output_tokens,
                        "reasoning_output_tokens": 2,
                    }
                }
            )
            + "\n",
            encoding="utf-8",
        )

    expected = {
        "calls": 2,
        "input_tokens": 30,
        "cached_input_tokens": 2,
        "output_tokens": 12,
        "reasoning_output_tokens": 4,
    }
    assert _manifest_usage(tmp_path, trade_day) == expected
    now = datetime(2026, 10, 2, 12, 0, tzinfo=NEW_YORK)
    first = _recompute_manifest(tmp_path, trade_day, now)
    second = _recompute_manifest(tmp_path, trade_day, now)
    assert first["llm_usage"] == expected
    assert second["llm_usage"] == expected
    assert json.loads(
        (tmp_path / "data" / "runs" / trade_day.isoformat() / "manifest.json").read_text(encoding="utf-8")
    )["llm_usage"] == expected

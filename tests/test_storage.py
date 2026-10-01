"""存储辅助函数回归。"""

import json
from pathlib import Path

import pytest

import daily_analyzer.storage as storage


def test_atomic_json_failure_preserves_existing_complete_file(
    tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "state.json"
    original = {"status": "previous", "items": [1, 2, 3]}
    original_bytes = json.dumps(original, ensure_ascii=False, indent=2).encode() + b"\n"
    target.write_bytes(original_bytes)

    def fail_replace(source, destination) -> None:
        raise OSError("fixture replace failure")

    monkeypatch.setattr(storage.os, "replace", fail_replace)
    with pytest.raises(OSError, match="fixture replace failure"):
        storage.atomic_write_json(target, {"status": "new", "items": [4, 5]})

    assert target.read_bytes() == original_bytes
    assert json.loads(target.read_text(encoding="utf-8")) == original
    assert list(tmp_path.glob(".state.json.*")) == []

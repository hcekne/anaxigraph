"""A failed detached child keeps the cause its progress heartbeat reported."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import anaxigraph.semantic_background as background

_LEAF_ERROR = "RuntimeError: AnaxiMCP could not claim semantic work: database is locked"


class _FailedChild:
    pid = 4322
    returncode = 1

    def poll(self):
        return self.returncode


def _record(progress_path: Path) -> dict:
    return {
        "run_id": "run-1",
        "status": "starting",
        "command": ["understand"],
        "progress_path": str(progress_path),
        "heartbeat_at": "2026-08-25T10:00:00+00:00",
        "progress_at": None,
        "last_error": None,
    }


@pytest.mark.parametrize(
    ("progress", "expected_error"),
    [
        (
            {
                "heartbeat_at": "2026-08-25T10:00:01+00:00",
                "stage": "failed",
                "last_error": _LEAF_ERROR,
            },
            _LEAF_ERROR,
        ),
        (
            {"heartbeat_at": "2026-08-25T10:00:01+00:00", "stage": "claiming"},
            "Semantic command exited with status 1",
        ),
    ],
)
def test_child_failure_keeps_the_progress_reported_cause(
    tmp_path, monkeypatch, progress, expected_error
):
    progress_path = tmp_path / "run.progress.json"
    record_path = tmp_path / "run.json"
    latest_path = tmp_path / "latest.json"
    record_path.write_text(json.dumps(_record(progress_path)), encoding="utf-8")
    progress_path.write_text(json.dumps(progress), encoding="utf-8")
    monkeypatch.setattr(background.subprocess, "Popen", lambda *_a, **_k: _FailedChild())
    monkeypatch.setattr(background.time, "sleep", lambda _seconds: None)

    exit_code = background._run_worker(record_path, latest_path, tmp_path / "active.lock")

    saved = json.loads(latest_path.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert saved["status"] == "failed"
    assert saved["exit_code"] == 1
    assert saved["last_error"] == expected_error
    assert "TaskGroup" not in saved["last_error"]

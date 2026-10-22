"""Real detached-worker output and retained run files stay bounded."""

import json
import os
import sys
import uuid

from anaxigraph.semantic_background import _spawn_wrapper
from anaxigraph.semantic_background_slots import prune_completed_runs


def test_real_worker_trims_oversized_output_and_keeps_terminal_result(tmp_path):
    identifier = str(uuid.uuid4())
    record = tmp_path / f"{identifier}.json"
    latest = tmp_path / "latest.json"
    log = tmp_path / f"{identifier}.log"
    value = {
        "run_id": identifier,
        "command": [sys.executable, "-c", "print('x' * 1500000)"],
        "progress_path": str(tmp_path / f"{identifier}.progress.json"),
        "log_path": str(log),
        "status": "starting",
        "active": True,
    }
    record.write_text(json.dumps(value))
    latest.write_text(json.dumps(value))
    child = _spawn_wrapper(record, latest, tmp_path / "active.lock", log)
    assert child.wait(timeout=15) == 0
    assert json.loads(latest.read_text())["status"] == "completed"
    assert log.stat().st_size <= 1_000_000
    assert "ended with status completed" in log.read_text()


def test_run_retention_preserves_live_worker_and_latest_pointer(tmp_path):
    for number in range(9):
        identifier = str(uuid.uuid4())
        record = tmp_path / f"{identifier}.json"
        record.write_text(json.dumps({"status": "completed", "pid": 0}))
        record.with_suffix(".log").write_text("finished")
        os.utime(record, (number, number))
    identifier = str(uuid.uuid4())
    active = tmp_path / f"{identifier}.json"
    active.write_text(json.dumps({"status": "running", "pid": os.getpid()}))
    latest = tmp_path / "latest.json"
    latest.write_text(json.dumps({"run_id": identifier}))
    prune_completed_runs(tmp_path)
    assert active.exists()
    assert latest.exists()
    assert len(list(tmp_path.glob("*.log"))) == 4
    assert len(list(tmp_path.glob("*.json"))) == 6

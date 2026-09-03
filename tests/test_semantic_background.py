from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import anaxigraph.semantic_background as background
import anaxigraph.semantic_background_progress as background_progress
import anaxigraph.semantic_background_slots as slots


def _spec(repository: Path) -> background.SemanticBackgroundSpec:
    return background.SemanticBackgroundSpec(
        repository=repository,
        executor="codex",
        model="gpt-5.6-terra",
        reasoning_effort="medium",
        index={"authority": "service", "service_url": "http://127.0.0.1:8765"},
        parallel_jobs=30,
        timeout_seconds=420,
        service_url="http://127.0.0.1:8765",
    )


def _args(**overrides):
    values = {
        "limit": None,
        "plan_only": False,
        "db": None,
        "config": None,
        "force": False,
        "retry_failed": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_background_command_returns_complete_handoff_for_service(repository, monkeypatch):
    target = SimpleNamespace(
        base_url="http://127.0.0.1:8765",
        identity=lambda: {"authority": "service", "repository_id": 1},
    )
    execution = SimpleNamespace(
        model="gpt-5.6-terra",
        reasoning_effort="medium",
        max_parallel_jobs=30,
        timeout_seconds=420,
    )
    captured = {}

    def launch(spec):
        captured["spec"] = spec
        return {"status": "running", "run_id": "run-1"}

    monkeypatch.setattr(background, "launch_semantic_background", launch)

    result = background.launch_understand_background(
        _args(force=True, retry_failed=True), repository, execution, "codex", target
    )

    assert result["status"] == "running"
    assert result["execution"] == {
        "mode": "codex",
        "model": "gpt-5.6-terra",
        "reasoning_effort": "medium",
        "parallel_jobs": 30,
        "timeout_seconds": 420,
        "background": True,
    }
    assert result["index"]["authority"] == "service"
    assert captured["spec"].service_url == target.base_url
    assert captured["spec"].force is True
    assert captured["spec"].retry_failed is True


def test_background_command_pins_local_database(repository, tmp_path, monkeypatch):
    database = tmp_path / "index.db"
    execution = SimpleNamespace(model="", reasoning_effort="")
    monkeypatch.setattr(background, "local_database_path", lambda *_a, **_k: database)
    monkeypatch.setattr(
        background,
        "launch_semantic_background",
        lambda spec: {"status": "running", "database": str(spec.database_path)},
    )

    result = background.launch_understand_background(_args(), repository, execution, "claude", None)

    assert result["index"] == {"authority": "local", "database": str(database)}
    assert result["execution"]["model"] is None


@pytest.mark.parametrize(
    ("args", "execution", "mode", "message"),
    [
        (_args(limit=1), SimpleNamespace(), "codex", "complete queue"),
        (_args(), None, "mcp", "requires --executor"),
    ],
)
def test_background_command_rejects_non_durable_combinations(
    repository, args, execution, mode, message
):
    with pytest.raises(ValueError, match=message):
        background.launch_understand_background(args, repository, execution, mode, None)


def test_background_launch_pins_authority_model_and_effort(repository, tmp_path, monkeypatch):
    monkeypatch.setattr(slots, "local_state_root", lambda: tmp_path)
    monkeypatch.setattr(
        background,
        "_spawn_wrapper",
        lambda *_args: SimpleNamespace(pid=4321),
    )

    launched = background.launch_semantic_background(_spec(repository))
    record = json.loads(Path(launched["record_path"]).read_text(encoding="utf-8"))

    assert launched["status"] == "running"
    assert launched["pid"] == 4321
    assert launched["model"] == "gpt-5.6-terra"
    assert launched["reasoning_effort"] == "medium"
    assert launched["parallel_jobs"] == 30
    assert launched["timeout_seconds"] == 420
    assert launched["elapsed_ms"] >= 0
    assert "--service-url" in record["command"]
    assert "http://127.0.0.1:8765" in record["command"]
    assert record["command"][record["command"].index("--model") + 1] == "gpt-5.6-terra"
    assert record["command"][record["command"].index("--reasoning-effort") + 1] == "medium"
    assert record["command"][record["command"].index("--parallel-jobs") + 1] == "30"
    assert record["command"][record["command"].index("--timeout-seconds") + 1] == "420"
    assert "--until-complete" in record["command"]
    assert "--background" not in record["command"]
    assert "command" not in launched

    repeated = background.launch_semantic_background(_spec(repository))
    assert repeated["status"] == "already_running"
    assert repeated["active"] is True


def test_background_wrapper_records_terminal_result(repository, tmp_path, monkeypatch):
    monkeypatch.setattr(slots, "local_state_root", lambda: tmp_path)
    monkeypatch.setattr(background, "_spawn_wrapper", lambda *_args: SimpleNamespace(pid=4321))
    launched = background.launch_semantic_background(_spec(repository))
    record_path = Path(launched["record_path"])
    latest_path = record_path.parent / "latest.json"
    lock_path = record_path.parent / "active.lock"
    monkeypatch.setattr(background, "_run_child", lambda *_args: 0)

    assert background._run_worker(record_path, latest_path, lock_path) == 0

    status = background.semantic_background_status(repository)
    assert status["status"] == "completed"
    assert status["active"] is False
    assert status["exit_code"] == 0
    assert status["elapsed_ms"] >= 0
    assert not lock_path.exists()


def test_background_wrapper_keeps_healthy_child_alive_without_model_progress(tmp_path, monkeypatch):
    class Child:
        pid = 4322
        returncode = 0
        polls = 0

        def poll(self):
            self.polls += 1
            return None if self.polls == 1 else self.returncode

    record_path = tmp_path / "run.json"
    latest_path = tmp_path / "latest.json"
    record = {
        "run_id": "run-1",
        "command": ["understand"],
        "progress_path": str(tmp_path / "missing-progress.json"),
        "heartbeat_at": "2020-01-01T00:00:00+00:00",
    }
    latest_path.write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(background.subprocess, "Popen", lambda *_a, **_k: Child())
    monkeypatch.setattr(background.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(background.time, "monotonic", lambda: 100.0)

    assert background._run_child(record, record_path, latest_path) == 0

    saved = json.loads(record_path.read_text(encoding="utf-8"))
    assert saved["heartbeat_at"] != "2020-01-01T00:00:00+00:00"
    assert saved["worker_pid"] == 4322


def test_background_wrapper_records_progress_without_replacing_its_liveness(tmp_path):
    progress_path = tmp_path / "progress.json"
    record_path = tmp_path / "run.json"
    latest_path = tmp_path / "latest.json"
    progress_path.write_text(
        json.dumps(
            {
                "heartbeat_at": "2026-08-25T10:00:00+00:00",
                "stage": "taxonomy_review",
                "completed": 17,
                "last_error": "retrying one review",
            }
        ),
        encoding="utf-8",
    )
    record = {
        "run_id": "run-1",
        "progress_path": str(progress_path),
        "heartbeat_at": "2026-08-25T10:00:05+00:00",
        "progress_at": None,
    }
    latest_path.write_text(json.dumps(record), encoding="utf-8")

    background._sync_progress(record, record_path, latest_path)

    saved = json.loads(record_path.read_text(encoding="utf-8"))
    assert saved["heartbeat_at"] == "2026-08-25T10:00:05+00:00"
    assert saved["progress_at"] == "2026-08-25T10:00:00+00:00"
    assert (saved["stage"], saved["completed"], saved["last_error"]) == (
        "taxonomy_review",
        17,
        "retrying one review",
    )


def test_background_launch_records_spawn_failure(repository, tmp_path, monkeypatch):
    monkeypatch.setattr(slots, "local_state_root", lambda: tmp_path)

    def fail(*_args):
        raise OSError("cannot detach")

    monkeypatch.setattr(background, "_spawn_wrapper", fail)

    with pytest.raises(RuntimeError, match="cannot detach"):
        background.launch_semantic_background(_spec(repository))

    status = background.semantic_background_status(repository)
    assert status["status"] == "failed"
    assert status["error"] == "cannot detach"
    assert status["active"] is False


def test_background_status_handles_missing_corrupt_and_orphaned_state(
    repository, tmp_path, monkeypatch
):
    monkeypatch.setattr(slots, "local_state_root", lambda: tmp_path)
    assert background.semantic_background_status(repository) is None
    directory = slots.slot_directory(repository)
    directory.mkdir(parents=True)
    latest = directory / "latest.json"
    latest.write_text("not-json", encoding="utf-8")
    assert background.semantic_background_status(repository)["status"] == "unreadable"
    latest.write_text(
        json.dumps(
            {
                "status": "running",
                "pid": 987654,
                "started_at": (datetime.now(UTC) - timedelta(minutes=2)).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(slots, "pid_exists", lambda _pid: False)

    status = background.semantic_background_status(repository)
    assert status["status"] == "interrupted"
    assert status["active"] is False


def test_background_command_includes_all_optional_local_flags(repository, tmp_path):
    spec = background.SemanticBackgroundSpec(
        repository=repository,
        executor="codex",
        model="test-model",
        reasoning_effort="high",
        index={"authority": "local"},
        config_path=repository / ".anaxigraph.yml",
        database_path=tmp_path / "index.db",
        force=True,
        retry_failed=True,
    )

    command = background._understand_command(spec)

    assert "--config" in command
    assert "--db" in command
    assert "--force" in command
    assert "--retry-failed" in command


def test_spawn_wrapper_detaches_and_redirects_to_private_log(tmp_path, monkeypatch):
    captured = {}
    sentinel = object()

    def popen(command, **options):
        captured.update(command=command, options=options)
        return sentinel

    monkeypatch.setattr(background.subprocess, "Popen", popen)
    record = tmp_path / "run.json"
    latest = tmp_path / "latest.json"
    lock = tmp_path / "active.lock"
    log = tmp_path / "run.log"

    assert background._spawn_wrapper(record, latest, lock, log) is sentinel
    assert captured["command"][2] == "anaxigraph.semantic_background"
    assert captured["options"]["start_new_session"] is True
    assert captured["options"]["stderr"] == background.subprocess.STDOUT
    assert log.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code"),
    [(OSError("worker broke"), "failed", 1), (KeyboardInterrupt(), "interrupted", 130)],
)
def test_background_wrapper_records_execution_failures(
    repository, tmp_path, monkeypatch, error, expected_status, expected_code
):
    monkeypatch.setattr(slots, "local_state_root", lambda: tmp_path)
    monkeypatch.setattr(background, "_spawn_wrapper", lambda *_args: SimpleNamespace(pid=4321))
    launched = background.launch_semantic_background(_spec(repository))
    record_path = Path(launched["record_path"])
    latest_path = record_path.parent / "latest.json"
    lock_path = record_path.parent / "active.lock"

    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(background, "_run_child", fail)

    assert background._run_worker(record_path, latest_path, lock_path) == expected_code
    status = background.semantic_background_status(repository)
    assert status["status"] == expected_status
    assert status["exit_code"] == expected_code
    assert "error" in status


def test_background_lock_recovers_stale_reservation_and_preserves_fresh_one(tmp_path):
    lock = tmp_path / "active.lock"
    latest = tmp_path / "latest.json"
    lock.write_text("first", encoding="utf-8")
    assert background._reserve(lock, latest, "second") is False
    os.utime(lock, (0, 0))
    assert background._reserve(lock, latest, "second") is True
    assert lock.read_text(encoding="utf-8") == "second"
    background._release(lock, "someone-else")
    assert lock.exists()
    background._release(lock, "second")
    assert not lock.exists()
    background._release(lock, "second")


def test_background_process_and_time_helpers_cover_failure_modes(monkeypatch):
    assert slots.pid_exists(0) is False

    def missing(_pid, _signal):
        raise ProcessLookupError

    monkeypatch.setattr(background.os, "kill", missing)
    assert slots.pid_exists(99) is False

    def forbidden(_pid, _signal):
        raise PermissionError

    monkeypatch.setattr(background.os, "kill", forbidden)
    assert slots.pid_exists(99) is True
    assert slots.recent({}) is False
    assert slots.recent({"started_at": datetime.now(UTC).isoformat()}) is True


def test_background_status_marks_live_process_with_expired_heartbeat_stalled(
    repository, tmp_path, monkeypatch
):
    monkeypatch.setattr(slots, "local_state_root", lambda: tmp_path)
    directory = slots.slot_directory(repository)
    directory.mkdir(parents=True)
    latest = directory / "latest.json"
    latest.write_text(
        json.dumps(
            {
                "run_id": "stalled-run",
                "status": "running",
                "pid": 123,
                "worker_pid": 124,
                "heartbeat_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
                "heartbeat_timeout_seconds": 60,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(slots, "pid_exists", lambda _pid: True)
    monkeypatch.setattr(slots, "_process_state", lambda _pid: "S")

    status = background.semantic_background_status(repository)

    assert status["status"] == "stalled"
    assert status["active"] is False


def test_background_relaunch_terminates_stalled_process(repository, tmp_path, monkeypatch):
    monkeypatch.setattr(slots, "local_state_root", lambda: tmp_path)
    directory = slots.slot_directory(repository, "codex")
    directory.mkdir(parents=True)
    (directory / "latest.json").write_text(
        json.dumps(
            {
                "run_id": "old-run",
                "status": "running",
                "pid": 123,
                "heartbeat_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
                "heartbeat_timeout_seconds": 60,
            }
        ),
        encoding="utf-8",
    )
    (directory / "active.lock").write_text("old-run", encoding="utf-8")
    terminated = []
    monkeypatch.setattr(slots, "pid_exists", lambda _pid: True)
    monkeypatch.setattr(slots, "_process_state", lambda _pid: "S")
    monkeypatch.setattr(
        background,
        "_terminate_stalled_run",
        lambda record: terminated.append(record) or True,
    )
    monkeypatch.setattr(background, "_spawn_wrapper", lambda *_args: SimpleNamespace(pid=4321))

    relaunched = background.launch_semantic_background(_spec(repository))

    assert terminated[0]["run_id"] == "old-run"
    assert relaunched["status"] == "running"
    assert relaunched["run_id"] != "old-run"


def test_stalled_termination_requires_the_exact_background_wrapper(monkeypatch):
    terminated = []
    monkeypatch.setattr(background.os, "killpg", lambda *args: terminated.append(args))
    monkeypatch.setattr(background, "_matches_background_wrapper", lambda _record: False)

    assert not background._terminate_stalled_run({"pid": 123, "record_path": "/runs/old.json"})

    assert terminated == []

    monkeypatch.setattr(background, "_matches_background_wrapper", lambda _record: True)
    assert background._terminate_stalled_run({"pid": 123, "record_path": "/runs/old.json"})

    assert terminated == [(123, background.signal.SIGTERM)]


def test_background_wrapper_identity_uses_module_and_record_path(monkeypatch):
    class ProcCommandLine:
        def read_bytes(self):
            return (
                b"python\0-m\0anaxigraph.semantic_background\0run\0"
                b"/runs/current.json\0/runs/latest.json\0/runs/active.lock\0"
            )

    monkeypatch.setattr(background, "Path", lambda _value: ProcCommandLine())

    assert background._matches_background_wrapper({"pid": 123, "record_path": "/runs/current.json"})
    assert not background._matches_background_wrapper(
        {"pid": 123, "record_path": "/runs/other.json"}
    )


def test_background_progress_heartbeat_records_stage_count_and_error(tmp_path, monkeypatch):
    progress_path = tmp_path / "progress.json"
    monkeypatch.setenv(background_progress.PROGRESS_PATH_ENV, str(progress_path))

    background_progress.report_background_progress(
        stage="context", completed=17, last_error="transient transport error"
    )

    value = background_progress.read_background_progress(progress_path)
    assert value["stage"] == "context"
    assert value["completed"] == 17
    assert value["last_error"] == "transient transport error"
    assert value["heartbeat_at"]


def test_background_module_entrypoint_validates_and_dispatches(tmp_path, monkeypatch):
    with pytest.raises(SystemExit, match="usage"):
        background.main([])
    monkeypatch.setattr(background, "_run_worker", lambda *_args: 7)

    with pytest.raises(SystemExit) as stopped:
        background.main(["run", str(tmp_path / "a"), str(tmp_path / "b"), str(tmp_path / "c")])

    assert stopped.value.code == 7

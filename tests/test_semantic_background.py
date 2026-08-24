from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import anaxigraph.semantic_background as background


def _spec(repository: Path) -> background.SemanticBackgroundSpec:
    return background.SemanticBackgroundSpec(
        repository=repository,
        executor="codex",
        model="gpt-5.6-terra",
        reasoning_effort="medium",
        index={"authority": "service", "service_url": "http://127.0.0.1:8765"},
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
    execution = SimpleNamespace(model="gpt-5.6-terra", reasoning_effort="medium")
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
    monkeypatch.setattr(background, "local_state_root", lambda: tmp_path)
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
    assert "--service-url" in record["command"]
    assert "http://127.0.0.1:8765" in record["command"]
    assert record["command"][record["command"].index("--model") + 1] == "gpt-5.6-terra"
    assert record["command"][record["command"].index("--reasoning-effort") + 1] == "medium"
    assert "--until-complete" in record["command"]
    assert "--background" not in record["command"]
    assert "command" not in launched

    repeated = background.launch_semantic_background(_spec(repository))
    assert repeated["status"] == "already_running"
    assert repeated["active"] is True


def test_background_wrapper_records_terminal_result(repository, tmp_path, monkeypatch):
    monkeypatch.setattr(background, "local_state_root", lambda: tmp_path)
    monkeypatch.setattr(background, "_spawn_wrapper", lambda *_args: SimpleNamespace(pid=4321))
    launched = background.launch_semantic_background(_spec(repository))
    record_path = Path(launched["record_path"])
    latest_path = record_path.parent / "latest.json"
    lock_path = record_path.parent / "active.lock"
    monkeypatch.setattr(
        background.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0),
    )

    assert background._run_worker(record_path, latest_path, lock_path) == 0

    status = background.semantic_background_status(repository)
    assert status["status"] == "completed"
    assert status["active"] is False
    assert status["exit_code"] == 0
    assert not lock_path.exists()


def test_background_launch_records_spawn_failure(repository, tmp_path, monkeypatch):
    monkeypatch.setattr(background, "local_state_root", lambda: tmp_path)

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
    monkeypatch.setattr(background, "local_state_root", lambda: tmp_path)
    assert background.semantic_background_status(repository) is None
    directory = background._run_directory(repository)
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
    monkeypatch.setattr(background, "_pid_exists", lambda _pid: False)

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
    monkeypatch.setattr(background, "local_state_root", lambda: tmp_path)
    monkeypatch.setattr(background, "_spawn_wrapper", lambda *_args: SimpleNamespace(pid=4321))
    launched = background.launch_semantic_background(_spec(repository))
    record_path = Path(launched["record_path"])
    latest_path = record_path.parent / "latest.json"
    lock_path = record_path.parent / "active.lock"

    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(background.subprocess, "run", fail)

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
    assert background._pid_exists(0) is False

    def missing(_pid, _signal):
        raise ProcessLookupError

    monkeypatch.setattr(background.os, "kill", missing)
    assert background._pid_exists(99) is False

    def forbidden(_pid, _signal):
        raise PermissionError

    monkeypatch.setattr(background.os, "kill", forbidden)
    assert background._pid_exists(99) is True
    assert background._recent({}) is False
    assert background._recent({"started_at": datetime.now(UTC).isoformat()}) is True


def test_background_module_entrypoint_validates_and_dispatches(tmp_path, monkeypatch):
    with pytest.raises(SystemExit, match="usage"):
        background.main([])
    monkeypatch.setattr(background, "_run_worker", lambda *_args: 7)

    with pytest.raises(SystemExit) as stopped:
        background.main(["run", str(tmp_path / "a"), str(tmp_path / "b"), str(tmp_path / "c")])

    assert stopped.value.code == 7

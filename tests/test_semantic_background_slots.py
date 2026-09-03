"""One background run slot per executor, so two host workers share one repository."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import anaxigraph.semantic_background as background
import anaxigraph.semantic_background_slots as slots
from anaxigraph.cli import main


def _spec(repository: Path, executor: str) -> background.SemanticBackgroundSpec:
    return background.SemanticBackgroundSpec(
        repository=repository,
        executor=executor,
        model="",
        reasoning_effort="",
        index={"authority": "local", "database": "/tmp/anaxi.db"},
    )


def _write_legacy_run(repository: Path, executor: str, **overrides) -> Path:
    """Write a record in the repository-only slot used before per-executor slots existed."""

    directory = slots.slot_directory(repository)
    directory.mkdir(parents=True, exist_ok=True)
    record = {
        "run_id": "legacy-run",
        "status": "running",
        "executor": executor,
        "pid": 4242,
        "started_at": datetime.now(UTC).isoformat(),
        "heartbeat_at": datetime.now(UTC).isoformat(),
        "heartbeat_timeout_seconds": 600,
        **overrides,
    }
    (directory / "latest.json").write_text(json.dumps(record), encoding="utf-8")
    return directory


def test_each_executor_owns_its_own_run_directory(repository: Path, tmp_path, monkeypatch):
    monkeypatch.setattr(slots, "local_state_root", lambda: tmp_path)

    codex = slots.slot_directory(repository, "codex")
    claude = slots.slot_directory(repository, "claude")

    assert codex != claude
    assert codex.name.endswith("-codex")
    assert claude.name.endswith("-claude")
    assert codex.parent == claude.parent == slots.slot_directory(repository).parent
    assert slots.slot_directory(repository, "Codex Agent").name.endswith("-codex-agent")


def test_a_second_executor_starts_beside_the_first(repository: Path, tmp_path, monkeypatch):
    monkeypatch.setattr(slots, "local_state_root", lambda: tmp_path)
    monkeypatch.setattr(background, "_spawn_wrapper", lambda *_args: SimpleNamespace(pid=4321))

    codex = background.launch_semantic_background(_spec(repository, "codex"))
    claude = background.launch_semantic_background(_spec(repository, "claude"))

    assert codex["status"] == "running"
    assert claude["status"] == "running"
    assert codex["run_id"] != claude["run_id"]
    assert Path(codex["record_path"]).parent != Path(claude["record_path"]).parent
    assert background.semantic_background_status(repository, "codex")["run_id"] == codex["run_id"]
    assert background.semantic_background_status(repository, "claude")["run_id"] == claude["run_id"]
    runs = background.semantic_background_runs(repository)
    assert {run["executor"] for run in runs} == {"codex", "claude"}
    assert all(run["active"] for run in runs)
    refused = background.launch_semantic_background(_spec(repository, "claude"))
    assert refused["status"] == "already_running"


def test_semantic_status_lists_every_executor_slot(repository: Path, tmp_path, monkeypatch):
    monkeypatch.setattr(slots, "local_state_root", lambda: tmp_path)
    monkeypatch.setattr(background, "_spawn_wrapper", lambda *_args: SimpleNamespace(pid=4321))
    background.launch_semantic_background(_spec(repository, "codex"))
    background.launch_semantic_background(_spec(repository, "claude"))
    assert [run["executor"] for run in background.semantic_background_runs(repository)] == [
        "claude",
        "codex",
    ]

    _finish_slot(repository, "claude")

    runs = background.semantic_background_runs(repository)
    assert [(run["executor"], run["active"]) for run in runs] == [
        ("codex", True),
        ("claude", False),
    ]
    assert background.semantic_background_status(repository)["executor"] == "codex"
    assert background.semantic_background_status(repository, "claude")["status"] == "completed"


def _finish_slot(repository: Path, executor: str) -> None:
    latest = slots.slot_directory(repository, executor) / "latest.json"
    record = json.loads(latest.read_text(encoding="utf-8"))
    record.update(status="completed", active=False, exit_code=0)
    latest.write_text(json.dumps(record), encoding="utf-8")


def test_a_run_recorded_before_slots_existed_still_belongs_to_its_executor(
    repository: Path, tmp_path, monkeypatch
):
    monkeypatch.setattr(slots, "local_state_root", lambda: tmp_path)
    monkeypatch.setattr(slots, "pid_exists", lambda _pid: True)
    _write_legacy_run(repository, "codex")

    assert background.semantic_background_status(repository, "codex")["run_id"] == "legacy-run"
    assert background.semantic_background_status(repository, "claude") is None
    assert [run["executor"] for run in background.semantic_background_runs(repository)] == ["codex"]


def test_a_new_slot_record_replaces_the_legacy_one_for_that_executor(
    repository: Path, tmp_path, monkeypatch
):
    monkeypatch.setattr(slots, "local_state_root", lambda: tmp_path)
    monkeypatch.setattr(background, "_spawn_wrapper", lambda *_args: SimpleNamespace(pid=4321))
    _write_legacy_run(
        repository,
        "codex",
        status="running",
        heartbeat_at=(datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        heartbeat_timeout_seconds=60,
    )

    launched = background.launch_semantic_background(_spec(repository, "codex"))

    runs = background.semantic_background_runs(repository)
    assert launched["status"] == "running"
    assert [run["run_id"] for run in runs] == [launched["run_id"]]


def test_semantic_status_reports_one_execution_run_per_executor(
    repository: Path, tmp_path, capsys, monkeypatch
):
    monkeypatch.setattr(slots, "local_state_root", lambda: tmp_path)
    monkeypatch.setattr(background, "_spawn_wrapper", lambda *_args: SimpleNamespace(pid=4321))
    database_path = tmp_path / "slots.db"
    common = [str(repository), "--db", str(database_path), "--json"]
    main(["scan", *common])
    capsys.readouterr()
    background.launch_semantic_background(_spec(repository, "codex"))
    background.launch_semantic_background(_spec(repository, "claude"))

    main(["semantic-status", *common])

    status = json.loads(capsys.readouterr().out)
    assert [run["executor"] for run in status["execution_runs"]] == ["claude", "codex"]
    assert status["execution_run"] == status["execution_runs"][0]

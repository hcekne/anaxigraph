from __future__ import annotations

import subprocess
import time
from argparse import Namespace
from pathlib import Path

from anaxigraph.cli_workflows import history as run_history_cli
from anaxigraph.history_jobs import HistoryJobService
from anaxigraph.registry import RepositoryTarget
from anaxigraph.scanner import RepositoryScanner


def _commit(root: Path, message: str) -> str:
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", message], check=True)
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _target(repository: Path) -> RepositoryTarget:
    return RepositoryTarget("test", repository, history_snapshots="auto")


def _add_history(repository: Path, count: int = 2) -> None:
    for index in range(count):
        path = repository / "pkg" / "util.py"
        path.write_text(
            path.read_text(encoding="utf-8") + f"\nVALUE_{index} = {index}\n",
            encoding="utf-8",
        )
        _commit(repository, f"history change {index}")


def _wait_for(service: HistoryJobService, repository_id: int, *statuses: str) -> dict:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = service.status(repository_id)
        if result["status"] in statuses:
            return result
        time.sleep(0.02)
    raise AssertionError(f"history job did not reach {statuses}: {service.status(repository_id)}")


def test_inline_history_job_persists_progress_and_result(repository, database):
    _add_history(repository)
    result = HistoryJobService(database).run_inline(_target(repository), every_commit=True)

    assert result["status"] == "complete"
    assert result["result"]["total_commits"] == 3
    assert result["completed_frames"] == result["total_frames"] == 3
    assert result["current_commit_subject"] == "history change 1"
    assert result["current_commit_date"]
    assert result["last_complete_snapshot_id"] == result["snapshot_id"]
    assert result["rows_added"] > 0
    assert result["bytes_added"] >= 0
    assert result["elapsed_seconds"] >= 0
    assert result["eta_seconds"] == 0
    assert result["work"]["source_reads"] > 0

    with database.connect() as connection:
        row = connection.execute(
            "SELECT status, completed_at FROM analysis_runs WHERE run_type = 'history_import'"
        ).fetchone()
    assert tuple(row) == ("complete", result["completed_at"])


def test_cancelled_history_job_keeps_frames_and_retries(repository, database):
    _add_history(repository, 3)
    RepositoryScanner(database).scan(repository)
    service = HistoryJobService(database)
    record = service.start_record(_target(repository))
    row = database.repository(repository)
    assert row is not None
    repository_id = int(row["id"])

    assert service.cancel(repository_id)["cancelled"] is True
    cancelled = service.run_inline(_target(repository), every_commit=True)
    assert cancelled["id"] == record["job_id"]
    assert cancelled["status"] == "cancelled"
    assert cancelled["last_complete_snapshot_id"] is not None

    completed = service.run_inline(_target(repository), every_commit=True)
    assert completed["status"] == "complete"
    assert completed["id"] != cancelled["id"]
    assert completed["completed_frames"] == 4


def test_recover_resumes_durable_active_job(repository, database):
    _add_history(repository)
    RepositoryScanner(database).scan(repository)
    original = HistoryJobService(database)
    record = original.start_record(_target(repository))
    restarted = HistoryJobService(database)

    assert restarted.recover([_target(repository)]) == 1
    row = database.repository(repository)
    assert row is not None
    result = _wait_for(restarted, int(row["id"]), "complete")
    assert result["id"] == record["job_id"]
    assert result["resume_count"] == 1
    assert result["completed_frames"] == 3


def test_remote_worker_claim_is_recovered_only_after_its_heartbeat_expires(repository, database):
    RepositoryScanner(database).scan(repository)
    original = HistoryJobService(database)
    job_id = int(original.start_record(_target(repository))["job_id"])
    assert original._claim(job_id) is True
    original._update(
        job_id,
        worker_host="another-container",
        heartbeat_at="2999-01-01T00:00:00+00:00",
    )

    restarted = HistoryJobService(database)
    assert restarted._claim(job_id) is False
    original._update(job_id, heartbeat_at="2000-01-01T00:00:00+00:00")
    assert restarted._claim(job_id) is True


def test_start_is_idempotent_while_job_is_active(repository, database, monkeypatch):
    RepositoryScanner(database).scan(repository)
    service = HistoryJobService(database)

    def held_import(*args, job_progress, should_cancel, **kwargs):
        job_progress({"stage": "enumerated", "total_commits": 1, "total_frames": 1})
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not should_cancel():
            time.sleep(0.01)
        from anaxigraph.history import HistoryImportCancelled

        raise HistoryImportCancelled("cancelled in test")

    monkeypatch.setattr("anaxigraph.history_jobs.import_git_history", held_import)
    first = service.start(_target(repository))
    second = HistoryJobService(database).start(_target(repository))
    row = database.repository(repository)
    assert row is not None

    assert first["started"] is True
    assert second["started"] is False
    assert second["resumed"] is False
    assert second["already_running"] is True
    assert first["job"]["id"] == second["job"]["id"]
    service.cancel(int(row["id"]))
    assert _wait_for(service, int(row["id"]), "cancelled")["status"] == "cancelled"


def test_cli_runs_and_reads_the_same_durable_job(repository, database):
    _add_history(repository)
    arguments = Namespace(
        db=database.path,
        repository=repository,
        config=None,
        status=False,
        cancel=False,
        limit="auto",
        all=True,
        since=None,
        json=True,
    )
    completed = run_history_cli(arguments)
    arguments.status = True

    assert completed["status"] == "complete"
    assert run_history_cli(arguments)["id"] == completed["id"]

"""Structural scan progress, cancellation, and semantic separation contracts."""

from __future__ import annotations

import pytest
import yaml

from anaxigraph.scanner import RepositoryScanner, ScanCancelled
from anaxigraph.understanding import SemanticEngine


def test_scan_reports_per_file_progress_and_cancels_before_snapshot_commit(repository, database):
    progress = []

    def cancel_during_analysis() -> bool:
        return any(item["phase"] == "analyzing" and item["completed"] >= 2 for item in progress)

    with pytest.raises(ScanCancelled):
        RepositoryScanner(database).scan(
            repository,
            progress=progress.append,
            is_cancelled=cancel_during_analysis,
        )

    assert any(item["phase"] == "discovering" and item["total"] for item in progress)
    assert any(item["phase"] == "analyzing" and item["completed"] == 2 for item in progress)
    row = database.repository(repository)
    assert row is not None
    assert database.latest_snapshot(int(row["id"])) is None
    with database.connect() as connection:
        run = connection.execute(
            "SELECT status FROM analysis_runs WHERE repository_id = ? ORDER BY id DESC LIMIT 1",
            (row["id"],),
        ).fetchone()
    assert run["status"] == "cancelled"


def test_structural_scan_does_not_implicitly_prepare_semantic_work(repository, database):
    policy_path = repository / ".anaxigraph.yml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    policy["semantic"] = {"enabled": True, "provider": "agent"}
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")

    stats = RepositoryScanner(database).scan(repository)
    status = SemanticEngine(database).status(stats.repository_id)

    assert sum(status["jobs"].values()) == 0
    assert status["total_modules"] == 0
    assert status["coverage"] is None


def test_new_scan_marks_abandoned_structural_run_interrupted(repository, database):
    first = RepositoryScanner(database).scan(repository)
    abandoned_id = database.start_run(first.repository_id, "watch")

    current = RepositoryScanner(database).scan(repository, run_type="watch")

    with database.connect() as connection:
        abandoned = connection.execute(
            "SELECT status, completed_at, error FROM analysis_runs WHERE id = ?",
            (abandoned_id,),
        ).fetchone()
        latest = connection.execute(
            "SELECT status FROM analysis_runs WHERE id = ?",
            (current.analysis_run_id,),
        ).fetchone()
    assert abandoned["status"] == "interrupted"
    assert abandoned["completed_at"]
    assert abandoned["error"] == "Previous scan process ended before completion"
    assert latest["status"] == "unchanged"


def test_watch_retains_only_latest_unchanged_poll(repository, database):
    scanner = RepositoryScanner(database)
    first = scanner.scan(repository)
    explicit_unchanged = scanner.scan(repository)

    changed_path = repository / "pkg" / "util.py"
    changed_path.write_text(changed_path.read_text(encoding="utf-8") + "\nVALUE = 1\n")
    changed_watch = scanner.scan(repository, run_type="watch")
    old_unchanged = scanner.scan(repository, run_type="watch")
    latest_unchanged = scanner.scan(repository, run_type="watch")

    with database.connect() as connection:
        rows = connection.execute(
            "SELECT id, run_type, status FROM analysis_runs WHERE repository_id = ? ORDER BY id",
            (first.repository_id,),
        ).fetchall()

    assert [(row["id"], row["status"]) for row in rows if row["run_type"] == "scan"] == [
        (first.analysis_run_id, "completed"),
        (explicit_unchanged.analysis_run_id, "unchanged"),
    ]
    assert [(row["id"], row["status"]) for row in rows if row["run_type"] == "watch"] == [
        (changed_watch.analysis_run_id, "completed"),
        (latest_unchanged.analysis_run_id, "unchanged"),
    ]
    assert old_unchanged.analysis_run_id != latest_unchanged.analysis_run_id

"""Working-tree drift detection, bounded rediscovery, and the scan-consistency verdict."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from anaxigraph import git
from anaxigraph.models import GitMetadata
from anaxigraph.operational_health import served_map_status
from anaxigraph.scan_consistency import (
    CHANGED_DURING_SCAN,
    COMMIT_CHANGED,
    WORKING_TREE_CHANGED,
    discover_consistent_frame,
    working_tree_drift,
)
from anaxigraph.scanner import RepositoryScanner

PUBLISHED_PHASES = {
    "starting",
    "discovering",
    "fingerprinting",
    "analyzing",
    "invalidating",
    "git_history",
    "persisting",
    "complete",
}
PROVENANCE_KEYS = {
    "anaxigraph_version",
    "analysis_version",
    "analysis_signature",
    "config_path",
    "working_tree_fingerprint",
}


def _unflagged(metadata: dict[str, Any]) -> bool:
    """A snapshot keeps its usual provenance keys and names no scan-consistency verdict."""

    return PROVENANCE_KEYS <= set(metadata) and "scan_consistency" not in metadata


def _metadata(commit: str = "a" * 40, fingerprint: str | None = "f1") -> GitMetadata:
    return GitMetadata(
        commit_sha=commit,
        parent_commit_sha=None,
        branch="main",
        commit_timestamp=None,
        dirty=False,
        remote_url=None,
        default_branch=None,
        working_tree_fingerprint=fingerprint,
    )


def _snapshot_metadata(database: Any, repository_id: int) -> dict[str, Any]:
    snapshot = database.latest_snapshot(repository_id)
    assert snapshot is not None
    return json.loads(snapshot["metadata_json"])


def _run_metadata(database: Any, run_id: int) -> dict[str, Any]:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT status, metadata_json FROM analysis_runs WHERE id = ?", (run_id,)
        ).fetchone()
    return {"status": row["status"], **json.loads(row["metadata_json"])}


def _mutating_progress(path: Path, *, once: bool) -> tuple[list[dict[str, Any]], Any]:
    """Append a line to a not-yet-read tracked file when a discovery pass starts."""

    events: list[dict[str, Any]] = []

    def progress(event: dict[str, Any]) -> None:
        events.append(event)
        starting_pass = event["phase"] == "discovering" and event["completed"] == 1
        mutations = sum(1 for item in events if item.get("mutated"))
        if starting_pass and not (once and mutations):
            current = path.read_text(encoding="utf-8")
            path.write_text(f"{current}VALUE_{mutations} = 1\n", encoding="utf-8")
            event["mutated"] = True

    return events, progress


def test_working_tree_drift_names_commit_and_content_moves():
    before = _metadata()

    assert working_tree_drift(before, before) is None
    assert working_tree_drift(before, _metadata(commit="b" * 40)) == COMMIT_CHANGED
    assert working_tree_drift(before, _metadata(fingerprint="f2")) == WORKING_TREE_CHANGED
    assert working_tree_drift(before, _metadata(fingerprint=None)) is None
    assert working_tree_drift(_metadata(fingerprint=None), before) is None


def test_discover_consistent_frame_skips_the_recheck_without_a_comparable_tree():
    rechecks: list[str] = []

    def metadata() -> GitMetadata:
        rechecks.append("read")
        return _metadata()

    revision_scan = discover_consistent_frame(
        lambda: "frame", None, before=_metadata(fingerprint=None)
    )
    unversioned = discover_consistent_frame(
        lambda: "frame", metadata, before=_metadata(fingerprint=None)
    )

    assert revision_scan.discovery == "frame"
    assert revision_scan.metadata.working_tree_fingerprint is None
    assert (revision_scan.rediscoveries, revision_scan.drift) == (0, None)
    assert (unversioned.rediscoveries, unversioned.drift) == (0, None)
    assert rechecks == []


def test_discover_consistent_frame_retries_once_and_then_records_drift():
    retries: list[str] = []
    observed = [_metadata(fingerprint="f2"), _metadata(fingerprint="f3")]
    passes: list[int] = []

    def metadata() -> GitMetadata:
        return observed[len(passes) - 1]

    def discover() -> str:
        passes.append(len(passes))
        return f"frame-{len(passes)}"

    persistent = discover_consistent_frame(
        discover,
        metadata,
        before=_metadata(),
        on_retry=lambda: retries.append("rediscovering"),
    )

    assert persistent.discovery == "frame-2"
    assert persistent.rediscoveries == 1
    assert persistent.drift == WORKING_TREE_CHANGED
    assert persistent.metadata.working_tree_fingerprint is None
    assert persistent.metadata.scan_consistency == CHANGED_DURING_SCAN
    assert retries == ["rediscovering"]


def test_scan_rediscovers_once_when_a_tracked_file_changes_during_discovery(repository, database):
    scanner = RepositoryScanner(database)
    events, progress = _mutating_progress(repository / "pkg" / "util.py", once=True)

    stats = scanner.scan(repository, progress=progress)

    run = _run_metadata(database, stats.analysis_run_id)
    assert run["status"] == "completed"
    assert run["working_tree_rediscoveries"] == 1
    assert run["working_tree_drift"] is None
    phases = [item["phase"] for item in events]
    assert phases.count("rediscovering") == 1
    assert PUBLISHED_PHASES <= set(phases)
    metadata = _snapshot_metadata(database, stats.repository_id)
    assert metadata["working_tree_fingerprint"] == git.working_tree_fingerprint(repository)
    assert _unflagged(metadata)
    snapshot = database.latest_snapshot(stats.repository_id)
    assert served_map_status(repository, snapshot)["state"] == "current"

    unchanged = scanner.scan(repository)

    assert unchanged.snapshot_id == stats.snapshot_id
    assert _run_metadata(database, unchanged.analysis_run_id)["status"] == "unchanged"


def test_persistent_drift_marks_the_snapshot_uncertain_until_a_settled_rescan(repository, database):
    scanner = RepositoryScanner(database)
    _events, progress = _mutating_progress(repository / "pkg" / "util.py", once=False)

    stats = scanner.scan(repository, progress=progress)

    run = _run_metadata(database, stats.analysis_run_id)
    assert run["status"] == "completed"
    assert run["working_tree_rediscoveries"] == 1
    assert run["working_tree_drift"] == WORKING_TREE_CHANGED
    metadata = _snapshot_metadata(database, stats.repository_id)
    assert metadata["working_tree_fingerprint"] is None
    assert metadata["scan_consistency"] == CHANGED_DURING_SCAN
    snapshot = database.latest_snapshot(stats.repository_id)
    status = served_map_status(repository, snapshot)
    assert status["state"] == "uncertain"
    assert status["safe_to_plan"] is False
    assert status["scan_recommended"] is True
    assert "scanned" in status["plain_language"]["summary"]

    settled = scanner.scan(repository)

    assert settled.snapshot_id == stats.snapshot_id
    assert _run_metadata(database, settled.analysis_run_id)["status"] == "unchanged"
    refreshed = _snapshot_metadata(database, stats.repository_id)
    assert "scan_consistency" not in refreshed
    assert refreshed["working_tree_fingerprint"] == git.working_tree_fingerprint(repository)
    assert (
        served_map_status(repository, database.latest_snapshot(stats.repository_id))["state"]
        == "current"
    )


def test_revision_and_unversioned_scans_skip_the_working_tree_recheck(
    repository, database, tmp_path, monkeypatch
):
    fingerprints: list[Path] = []
    original = git.working_tree_fingerprint

    def counted(root: Path) -> str | None:
        fingerprints.append(root)
        return original(root)

    monkeypatch.setattr(git, "working_tree_fingerprint", counted)
    scanner = RepositoryScanner(database)
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "module.py").write_text('"""Plain module."""\n', encoding="utf-8")

    revision = scanner.scan(repository, revision="HEAD~0", run_type="history")
    unversioned = scanner.scan(plain)

    assert fingerprints == []
    revision_metadata = _snapshot_metadata(database, revision.repository_id)
    assert _unflagged(revision_metadata)
    assert revision_metadata["working_tree_fingerprint"] is None
    assert _unflagged(_snapshot_metadata(database, unversioned.repository_id))
    assert _run_metadata(database, revision.analysis_run_id)["working_tree_rediscoveries"] == 0
    assert _run_metadata(database, unversioned.analysis_run_id)["working_tree_drift"] is None


def test_map_state_reports_a_torn_scan_as_uncertain_even_after_a_revert(repository, database):
    stats = RepositoryScanner(database).scan(repository)
    snapshot = dict(database.latest_snapshot(stats.repository_id))
    metadata = json.loads(snapshot["metadata_json"])
    metadata["working_tree_fingerprint"] = None
    metadata["scan_consistency"] = CHANGED_DURING_SCAN
    snapshot["metadata_json"] = json.dumps(metadata)

    status = served_map_status(repository, snapshot)

    assert status["state"] == "uncertain"
    assert status["safe_to_plan"] is False
    assert status["scan_recommended"] is True
    assert status["plain_language"]["summary"] == "Files changed while this map was being scanned."
    moved = {**snapshot, "commit_sha": "f" * 40}
    assert served_map_status(repository, moved)["state"] == "stale"


def test_a_second_commit_during_discovery_is_reported_as_a_commit_move(repository, database):
    scanner = RepositoryScanner(database)
    committed: list[str] = []

    def progress(event: dict[str, Any]) -> None:
        if event["phase"] != "discovering" or event["completed"] != 1 or committed:
            return
        committed.append("commit")
        path = repository / "pkg" / "util.py"
        path.write_text(f"{path.read_text(encoding='utf-8')}LATER = 2\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repository), "add", "pkg/util.py"], check=True)
        subprocess.run(["git", "-C", str(repository), "commit", "-qm", "Mid-scan"], check=True)

    stats = scanner.scan(repository, progress=progress)

    run = _run_metadata(database, stats.analysis_run_id)
    assert run["working_tree_rediscoveries"] == 1
    assert run["working_tree_drift"] is None
    snapshot = database.latest_snapshot(stats.repository_id)
    assert snapshot["commit_sha"] == git.metadata(repository).commit_sha
    assert json.loads(snapshot["metadata_json"])[
        "working_tree_fingerprint"
    ] == git.working_tree_fingerprint(repository)

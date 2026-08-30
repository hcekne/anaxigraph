from __future__ import annotations

import json
import subprocess
from pathlib import Path

from anaxigraph.history import import_git_history
from anaxigraph.persistence import (
    inspect_index,
    snapshot_files,
    snapshot_relationship_edges,
    temporal_counts,
)
from anaxigraph.persistence.temporal_reads import artifact_types_for_files
from anaxigraph.scanner import RepositoryScanner


def _commit_change(repository: Path) -> None:
    target = repository / "pkg" / "util.py"
    target.write_text(
        target.read_text(encoding="utf-8")
        + "\ndef triple(value: int) -> int:\n    return value * 3\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-qm", "Add triple helper"],
        check=True,
    )


def test_artifact_type_lookup_batches_large_snapshots(database):
    with database.transaction() as connection:
        repository_id = connection.execute(
            """
            INSERT INTO repositories(name, path, created_at, updated_at)
            VALUES ('large', '/large', '2026-01-01', '2026-01-01')
            """
        ).lastrowid
        connection.executemany(
            """
            INSERT INTO artifacts(
                repository_id, canonical_path, artifact_type, created_at
            ) VALUES (?, ?, ?, '2026-01-01')
            """,
            [(repository_id, f"module-{index}.py", "source") for index in range(1_001)],
        )
        files = [
            {"artifact_id": row["id"]}
            for row in connection.execute(
                "SELECT id FROM artifacts WHERE repository_id = ? ORDER BY id",
                (repository_id,),
            )
        ]
        artifact_types = artifact_types_for_files(connection, files)

    assert len(artifact_types) == 1_001
    assert set(artifact_types.values()) == {"source"}


def test_canonical_frames_reconstruct_and_deduplicate_facts(repository, database):
    _commit_change(repository)
    import_git_history(database, repository, every_commit=True)

    with database.connect() as connection:
        snapshots = connection.execute(
            "SELECT id, sequence FROM snapshots ORDER BY sequence"
        ).fetchall()
        frame_sizes = [
            len(snapshot_files(connection, int(snapshot["id"]))) for snapshot in snapshots
        ]
        counts = temporal_counts(connection)
        compatibility_tables = {
            row["name"]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        } & {"file_versions", "symbols", "relationships", "group_memberships"}

    assert len(snapshots) == 2
    assert [int(snapshot["sequence"]) for snapshot in snapshots] == [0, 1]
    assert frame_sizes == [8, 8]
    assert counts["file_facts"] < sum(frame_sizes)
    assert counts["snapshot_file_changes"] < sum(frame_sizes)
    assert compatibility_tables == set()


def test_compact_fact_metadata_expands_at_the_snapshot_boundary(repository, database):
    stats = RepositoryScanner(database).scan(repository)

    with database.connect() as connection:
        stored = connection.execute(
            """
            SELECT ff.metadata_json
            FROM file_facts ff JOIN artifacts a ON a.id = ff.artifact_id
            WHERE a.canonical_path = 'pkg/util.py'
            """
        ).fetchone()
        projected = next(
            item
            for item in snapshot_files(connection, stats.snapshot_id)
            if item["path"] == "pkg/util.py"
        )

    stored_ir = json.loads(stored["metadata_json"])["ir"]
    projected_ir = json.loads(projected["metadata_json"])["ir"]
    assert "module_identity" not in stored_ir
    assert "symbols" not in stored_ir
    assert projected_ir["module_identity"]["path"] == "pkg/util.py"
    assert projected_ir["exports"] == json.loads(projected["public_interfaces_json"])
    assert projected_ir["analyzer_capabilities"]["fingerprint"]


def test_history_import_rebases_an_existing_current_snapshot(repository, database):
    _commit_change(repository)
    current = RepositoryScanner(database).scan(repository)

    import_git_history(database, repository, every_commit=True)

    with database.connect() as connection:
        snapshots = connection.execute(
            """
            SELECT id, commit_sha, base_snapshot_id, sequence
            FROM snapshots ORDER BY sequence, id
            """
        ).fetchall()
    assert len(snapshots) == 2
    assert [row["sequence"] for row in snapshots] == [0, 1]
    assert snapshots[0]["base_snapshot_id"] is None
    assert snapshots[1]["base_snapshot_id"] == snapshots[0]["id"]
    assert snapshots[1]["id"] == current.snapshot_id
    with database.connect() as connection:
        assert len(snapshot_files(connection, current.snapshot_id)) == current.discovered
    assert inspect_index(database.path, database.connect)["parity"]["status"] == "canonical_only"


def test_single_commit_history_reuses_current_frame_without_erasing_it(repository, database):
    current = RepositoryScanner(database).scan(repository)
    with database.connect() as connection:
        files_before = snapshot_files(connection, current.snapshot_id)
        edges_before = snapshot_relationship_edges(connection, current.snapshot_id)

    result = import_git_history(database, repository, max_snapshots="auto")

    with database.connect() as connection:
        files_after = snapshot_files(connection, current.snapshot_id)
        edges_after = snapshot_relationship_edges(connection, current.snapshot_id)
        file_deltas = connection.execute(
            "SELECT COUNT(*) FROM snapshot_file_changes WHERE snapshot_id = ?",
            (current.snapshot_id,),
        ).fetchone()[0]
    assert result.current_snapshot_id == current.snapshot_id
    assert files_after == files_before
    assert edges_after == edges_before
    assert file_deltas == current.discovered
    assert len(database.modules(current.repository_id)) == current.discovered

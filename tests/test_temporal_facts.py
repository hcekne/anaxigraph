from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from anaxigraph.history import import_git_history
from anaxigraph.persistence import (
    snapshot_files,
    snapshot_relationship_edges,
    snapshot_symbols,
    temporal_counts,
)
from anaxigraph.storage import AnaxiIndex

FILE_FIELDS = (
    "artifact_id",
    "path",
    "language",
    "runtime",
    "declared_group",
    "inferred_group",
    "raw_hash",
    "structural_hash",
    "lines_of_code",
    "comment_lines",
    "complexity",
    "summary",
    "responsibilities_json",
    "inputs_json",
    "outputs_json",
    "side_effects_json",
    "public_interfaces_json",
    "analyzer",
    "parse_error",
    "first_seen_at",
    "last_changed_at",
)
SYMBOL_FIELDS = (
    "artifact_id",
    "path",
    "symbol_type",
    "name",
    "qualified_name",
    "start_line",
    "end_line",
    "signature",
    "summary",
    "complexity",
    "logical_lines",
)
EDGE_FIELDS = (
    "source_artifact_id",
    "target_artifact_id",
    "target_external",
    "relationship_type",
    "source",
    "confidence",
    "evidence",
    "source_line",
    "weight",
    "metadata_json",
)


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


def _values(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> list[tuple[Any, ...]]:
    return sorted(
        [tuple(row[field] for field in fields) for row in rows],
        key=repr,
    )


def _legacy_files(connection, snapshot_id: int) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM file_versions WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchall()
    ]


def _legacy_symbols(connection, snapshot_id: int) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in connection.execute(
            """
            SELECT fv.artifact_id, fv.path, s.*
            FROM symbols s
            JOIN file_versions fv ON fv.id = s.artifact_version_id
            WHERE fv.snapshot_id = ?
            """,
            (snapshot_id,),
        ).fetchall()
    ]


def _legacy_edges(connection, snapshot_id: int) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM relationships WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchall()
    ]


def _assert_frame_equivalence(connection, snapshot_id: int) -> None:
    assert _values(_legacy_files(connection, snapshot_id), FILE_FIELDS) == _values(
        snapshot_files(connection, snapshot_id),
        FILE_FIELDS,
    )
    assert _values(_legacy_symbols(connection, snapshot_id), SYMBOL_FIELDS) == _values(
        snapshot_symbols(connection, snapshot_id),
        SYMBOL_FIELDS,
    )
    assert _values(_legacy_edges(connection, snapshot_id), EDGE_FIELDS) == _values(
        snapshot_relationship_edges(connection, snapshot_id),
        EDGE_FIELDS,
    )


def _drop_v7_state(database: AnaxiIndex) -> None:
    with database.transaction() as connection:
        for table in (
            "snapshot_relationship_changes",
            "relationship_edges",
            "relationship_sets",
            "snapshot_file_changes",
            "fact_symbols",
            "file_facts",
        ):
            connection.execute(f"DROP TABLE {table}")
        connection.execute("ALTER TABLE snapshots DROP COLUMN sequence")
        connection.execute("ALTER TABLE snapshots DROP COLUMN base_snapshot_id")
        connection.execute("UPDATE schema_meta SET value = '6' WHERE key = 'schema_version'")


def test_dual_write_reconstructs_every_frame_and_deduplicates_facts(repository, database):
    _commit_change(repository)
    import_git_history(database, repository, every_commit=True)

    with database.connect() as connection:
        snapshots = connection.execute("SELECT id FROM snapshots ORDER BY sequence").fetchall()
        for snapshot in snapshots:
            _assert_frame_equivalence(connection, int(snapshot["id"]))
        counts = temporal_counts(connection)
        legacy_files = connection.execute("SELECT COUNT(*) FROM file_versions").fetchone()[0]
        legacy_symbols = connection.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]

    assert len(snapshots) == 2
    assert counts["file_facts"] < legacy_files
    assert counts["fact_symbols"] < legacy_symbols
    assert counts["snapshot_file_changes"] < legacy_files


def test_schema_six_backfill_reconstructs_identical_frames(repository, database):
    _commit_change(repository)
    import_git_history(database, repository, every_commit=True)
    _drop_v7_state(database)

    migrated = AnaxiIndex(database.path)

    with migrated.connect() as connection:
        snapshots = connection.execute("SELECT id FROM snapshots ORDER BY sequence").fetchall()
        for snapshot in snapshots:
            _assert_frame_equivalence(connection, int(snapshot["id"]))

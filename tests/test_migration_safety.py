from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

import pytest

import anaxigraph.persistence.index_initialization as initialization_module
from anaxigraph.history import import_git_history
from anaxigraph.persistence import (
    backup_path,
    create_schema_backup,
    inspect_index,
    restore_schema_backup,
    transactional_schema_change,
    validate_schema_backup,
)
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.storage import AnaxiIndex


def _commit_change(repository: Path) -> None:
    target = repository / "pkg" / "util.py"
    target.write_text(target.read_text(encoding="utf-8") + "\nTRIPLE = 3\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-qm", "Add a second architecture frame"],
        check=True,
    )


def _canonical_frames(database: AnaxiIndex) -> dict:
    with database.connect() as connection:
        snapshots = connection.execute(
            "SELECT id, commit_sha, snapshot_kind FROM snapshots ORDER BY id"
        ).fetchall()
        files = connection.execute(
            """
            SELECT snapshot_id, artifact_id, path, raw_hash, structural_hash, summary,
                   declared_group, inferred_group
            FROM file_versions ORDER BY snapshot_id, artifact_id
            """
        ).fetchall()
        symbols = connection.execute(
            """
            SELECT fv.snapshot_id, fv.artifact_id, s.qualified_name, s.symbol_type, s.signature
            FROM symbols s JOIN file_versions fv ON fv.id = s.artifact_version_id
            ORDER BY fv.snapshot_id, fv.artifact_id, s.qualified_name
            """
        ).fetchall()
        edges = connection.execute(
            """
            SELECT snapshot_id, source_artifact_id, target_artifact_id, target_external,
                   relationship_type, source, evidence, metadata_json
            FROM relationships
            ORDER BY snapshot_id, source_artifact_id, target_artifact_id, target_external
            """
        ).fetchall()
    return {
        "snapshots": [tuple(row) for row in snapshots],
        "files": [tuple(row) for row in files],
        "symbols": [tuple(row) for row in symbols],
        "edges": [tuple(row) for row in edges],
    }


def _version(database: AnaxiIndex) -> int:
    with database.connect() as connection:
        return int(
            connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()[0]
        )


def _downgrade_to_schema_six(database: AnaxiIndex) -> None:
    """Remove additive v7 state to reproduce the released schema-6 shape."""

    with database.transaction() as connection:
        for table in (
            "schema_migrations",
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


def test_schema_change_rolls_back_every_ddl_and_fact_on_failure(repository, database):
    _commit_change(repository)
    import_git_history(database, repository, every_commit=True)
    before = _canonical_frames(database)

    def fail_halfway(connection):
        connection.execute("CREATE TABLE migration_probe(value TEXT NOT NULL)")
        connection.execute("INSERT INTO migration_probe(value) VALUES ('partial')")
        connection.execute("UPDATE schema_meta SET value = '8' WHERE key = 'schema_version'")
        raise RuntimeError("injected migration failure")

    with database.connect() as connection:
        with pytest.raises(RuntimeError, match="injected migration failure"):
            transactional_schema_change(connection, fail_halfway)
        probe = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'migration_probe'"
        ).fetchone()

    assert probe is None
    assert _version(database) == 7
    assert _canonical_frames(database) == before


def test_real_schema_six_index_has_idempotent_backup_and_exact_restore(repository, database):
    _commit_change(repository)
    RepositoryScanner(database).scan(repository)
    import_git_history(database, repository, every_commit=True)
    before = _canonical_frames(database)
    _downgrade_to_schema_six(database)

    reopened = AnaxiIndex(database.path)
    created_path = backup_path(database.path, 6)
    created = validate_schema_backup(created_path, expected_version=6)
    report = inspect_index(reopened.path, reopened.connect)
    assert report["status"] == "healthy"
    assert report["migration"]["from_version"] == 6
    assert report["migration"]["to_version"] == 7
    assert report["backup"]["status"] == "valid"
    reused = create_schema_backup(database.path, schema_version=6)
    assert reused.reused is True
    assert reused.path == created.path
    assert reused.sha256 == created.sha256
    assert validate_schema_backup(created.path, expected_version=6).sha256 == created.sha256

    with database.transaction() as connection:
        connection.execute("UPDATE file_versions SET summary = 'deliberately corrupted'")
    assert _canonical_frames(database) != before

    restored = restore_schema_backup(
        database.path,
        created.path,
        expected_version=6,
    )
    reopened = AnaxiIndex(database.path)
    assert restored.sha256
    assert _version(reopened) == 7
    assert _canonical_frames(reopened) == before
    assert created.path.exists(), "recovery backup must survive a restore"


def test_backup_validation_fails_closed_for_wrong_schema(database):
    backup = create_schema_backup(database.path, schema_version=7)

    with pytest.raises(RuntimeError, match="expected 6"):
        validate_schema_backup(backup.path, expected_version=6)


def test_schema_six_upgrade_is_restartable_after_injected_failure(
    repository,
    database,
    monkeypatch,
):
    _commit_change(repository)
    import_git_history(database, repository, every_commit=True)
    before = _canonical_frames(database)
    _downgrade_to_schema_six(database)
    real_migrate = initialization_module.migrate_schema

    def migrate_then_fail(connection, **kwargs):
        real_migrate(connection, **kwargs)
        raise RuntimeError("injected post-backfill failure")

    monkeypatch.setattr(initialization_module, "migrate_schema", migrate_then_fail)
    with pytest.raises(RuntimeError, match="post-backfill"):
        AnaxiIndex(database.path)

    with sqlite3.connect(database.path) as connection:
        version = int(
            connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()[0]
        )
        temporal_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'file_facts'"
        ).fetchone()
    assert version == 6
    assert temporal_table is None
    validate_schema_backup(backup_path(database.path, 6), expected_version=6)

    monkeypatch.setattr(initialization_module, "migrate_schema", real_migrate)
    reopened = AnaxiIndex(database.path)
    assert _version(reopened) == 7
    assert _canonical_frames(reopened) == before

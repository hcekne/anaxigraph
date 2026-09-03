from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

import pytest

import anaxigraph.persistence.index_initialization as initialization_module
import anaxigraph.persistence.migrations as migrations_module
import anaxigraph.persistence.temporal_files as temporal_files
import anaxigraph.persistence.temporal_relationships as temporal_relationships
from anaxigraph.history import import_git_history
from anaxigraph.persistence import (
    backup_path,
    create_schema_backup,
    inspect_index,
    restore_schema_backup,
    snapshot_files,
    snapshot_relationship_edges,
    snapshot_symbols,
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
        files = []
        symbols = []
        edges = []
        for snapshot in snapshots:
            snapshot_id = int(snapshot["id"])
            files.extend(
                (
                    snapshot_id,
                    row["artifact_id"],
                    row["path"],
                    row["raw_hash"],
                    row["structural_hash"],
                    row["summary"],
                    row["declared_group"],
                    row["inferred_group"],
                )
                for row in snapshot_files(connection, snapshot_id)
            )
            symbols.extend(
                (
                    snapshot_id,
                    row["artifact_id"],
                    row["qualified_name"],
                    row["symbol_type"],
                    row["signature"],
                )
                for row in snapshot_symbols(connection, snapshot_id)
            )
            edges.extend(
                (
                    snapshot_id,
                    row["source_artifact_id"],
                    row["target_artifact_id"],
                    row["target_external"],
                    row["relationship_type"],
                    row["source"],
                    row["evidence"],
                    row["metadata_json"],
                )
                for row in snapshot_relationship_edges(connection, snapshot_id)
            )
    return {
        "snapshots": [tuple(row) for row in snapshots],
        "files": sorted(files, key=repr),
        "symbols": sorted(symbols, key=repr),
        "edges": sorted(edges, key=repr),
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
        fixture = Path(__file__).parent / "fixtures" / "schema-v6-compatibility.sql"
        for statement in initialization_module.schema_statements(
            fixture.read_text(encoding="utf-8")
        ):
            connection.execute(statement)
        _materialize_schema_six_frames(connection)
        for table in (
            "schema_migrations",
            "checkpoint_relationships",
            "checkpoint_files",
            "snapshot_checkpoints",
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


def _materialize_schema_six_frames(connection: sqlite3.Connection) -> None:
    """Recreate the released materialized-frame rows from canonical facts."""

    connection.execute("DELETE FROM relationships")
    connection.execute("DELETE FROM symbols")
    connection.execute("DELETE FROM file_versions")
    snapshots = connection.execute("SELECT id FROM snapshots ORDER BY id").fetchall()
    for snapshot in snapshots:
        snapshot_id = int(snapshot["id"])
        versions: dict[int, int] = {}
        for row in snapshot_files(connection, snapshot_id):
            cursor = connection.execute(
                """
                INSERT INTO file_versions(
                    artifact_id, snapshot_id, path, language, runtime, declared_group,
                    inferred_group, raw_hash, structural_hash, lines_of_code, comment_lines,
                    complexity, summary, responsibilities_json, inputs_json, outputs_json,
                    side_effects_json, public_interfaces_json, analyzer, analysis_status,
                    parse_error, metadata_json, first_seen_at, last_changed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["artifact_id"],
                    snapshot_id,
                    row["path"],
                    row["language"],
                    row["runtime"],
                    row["declared_group"],
                    row["inferred_group"],
                    row["raw_hash"],
                    row["structural_hash"],
                    row["lines_of_code"],
                    row["comment_lines"],
                    row["complexity"],
                    row["summary"],
                    row["responsibilities_json"],
                    row["inputs_json"],
                    row["outputs_json"],
                    row["side_effects_json"],
                    row["public_interfaces_json"],
                    row["analyzer"],
                    row["analysis_status"],
                    row["parse_error"],
                    row["metadata_json"],
                    row["first_seen_at"],
                    row["last_changed_at"],
                ),
            )
            versions[int(row["artifact_id"])] = int(cursor.lastrowid)
        for row in snapshot_symbols(connection, snapshot_id):
            connection.execute(
                """
                INSERT INTO symbols(
                    artifact_version_id, symbol_type, name, qualified_name, start_line,
                    end_line, signature, summary, complexity, logical_lines
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    versions[int(row["artifact_id"])],
                    row["symbol_type"],
                    row["name"],
                    row["qualified_name"],
                    row["start_line"],
                    row["end_line"],
                    row["signature"],
                    row["summary"],
                    row["complexity"],
                    row["logical_lines"],
                ),
            )
        connection.executemany(
            """
            INSERT INTO relationships(
                snapshot_id, source_artifact_id, target_artifact_id, target_external,
                relationship_type, source, confidence, evidence, source_line, weight,
                metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    snapshot_id,
                    row["source_artifact_id"],
                    row["target_artifact_id"],
                    row["target_external"],
                    row["relationship_type"],
                    row["source"],
                    row["confidence"],
                    row["evidence"],
                    row["source_line"],
                    row["weight"],
                    row["metadata_json"],
                )
                for row in snapshot_relationship_edges(connection, snapshot_id)
            ],
        )


def test_schema_change_rolls_back_every_ddl_and_fact_on_failure(repository, database):
    _commit_change(repository)
    import_git_history(database, repository, every_commit=True)
    before = _canonical_frames(database)

    def fail_halfway(connection):
        connection.execute("CREATE TABLE migration_probe(value TEXT NOT NULL)")
        connection.execute("INSERT INTO migration_probe(value) VALUES ('partial')")
        connection.execute("UPDATE schema_meta SET value = '9' WHERE key = 'schema_version'")
        raise RuntimeError("injected migration failure")

    with database.connect() as connection:
        with pytest.raises(RuntimeError, match="injected migration failure"):
            transactional_schema_change(connection, fail_halfway)
        probe = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'migration_probe'"
        ).fetchone()

    assert probe is None
    assert _version(database) == 11
    assert _canonical_frames(database) == before


def test_schema_change_checks_foreign_keys_before_commit(database):
    def violate_foreign_key(connection):
        connection.execute("CREATE TABLE migration_parent(id INTEGER PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE migration_child(parent_id INTEGER REFERENCES migration_parent(id))"
        )
        connection.execute("INSERT INTO migration_child(parent_id) VALUES (404)")

    with database.connect() as connection:
        assert int(connection.execute("PRAGMA foreign_keys").fetchone()[0]) == 1
        with pytest.raises(RuntimeError, match="1 FK violations"):
            transactional_schema_change(connection, violate_foreign_key)
        assert int(connection.execute("PRAGMA foreign_keys").fetchone()[0]) == 1
        leaked_tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE 'migration_%'"
        ).fetchall()

    assert leaked_tables == []


def test_current_schema_retires_legacy_coverage_foreign_key(repository, database):
    RepositoryScanner(database).scan(repository)
    with database.transaction() as connection:
        connection.execute(
            "ALTER TABLE coverage_measurements ADD COLUMN relationship_id INTEGER "
            "REFERENCES relationships(id) ON DELETE CASCADE"
        )

    reopened = AnaxiIndex(database.path)
    RepositoryScanner(reopened).scan(repository)
    with reopened.connect() as connection:
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(coverage_measurements)")
        }
        foreign_tables = {
            str(row["table"])
            for row in connection.execute("PRAGMA foreign_key_list(coverage_measurements)")
        }

    assert "relationship_id" not in columns
    assert "relationships" not in foreign_tables


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
    assert report["migration"]["to_version"] == 11
    assert report["backup"]["status"] == "valid"
    reused = create_schema_backup(database.path, schema_version=6)
    assert reused.reused is True
    assert reused.path == created.path
    assert reused.sha256 == created.sha256
    assert validate_schema_backup(created.path, expected_version=6).sha256 == created.sha256

    with database.transaction() as connection:
        connection.execute("UPDATE file_facts SET summary = 'deliberately corrupted'")
    assert _canonical_frames(database) != before

    restored = restore_schema_backup(
        database.path,
        created.path,
        expected_version=6,
    )
    reopened = AnaxiIndex(database.path)
    assert restored.sha256
    assert _version(reopened) == 11
    assert _canonical_frames(reopened) == before
    assert created.path.exists(), "recovery backup must survive a restore"


def test_backup_validation_fails_closed_for_wrong_schema(database):
    backup = create_schema_backup(database.path, schema_version=11)

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
    assert _version(reopened) == 11
    assert _canonical_frames(reopened) == before


def test_schema_six_migration_reuses_unchanged_file_and_relationship_facts(
    repository,
    database,
    monkeypatch,
):
    _commit_change(repository)
    import_git_history(database, repository, every_commit=True)
    _downgrade_to_schema_six(database)
    file_facts: list[int] = []
    symbolized: list[int] = []
    relationship_sets: list[int] = []
    with database.connect() as connection:
        initial_secure_delete = int(connection.execute("PRAGMA secure_delete").fetchone()[0])
        materialized_source_frames = connection.execute(
            "SELECT COUNT(*) FROM (SELECT DISTINCT snapshot_id, source_artifact_id FROM relationships)"
        ).fetchone()[0]
        materialized_file_frames = connection.execute(
            "SELECT COUNT(*) FROM file_versions"
        ).fetchone()[0]
    upsert_file_fact = temporal_files._upsert_file_fact
    insert_symbols = temporal_files._upsert_symbols
    upsert_relationship_set = temporal_relationships._upsert_relationship_set

    def record_file_fact(connection, row, analysis_signature, **kwargs):
        file_facts.append(int(row["artifact_id"]))
        return upsert_file_fact(connection, row, analysis_signature, **kwargs)

    def record_symbols(connection, legacy_version_id, fact_id):
        symbolized.append(fact_id)
        insert_symbols(connection, legacy_version_id, fact_id)

    def record_relationship_set(connection, repository_id, source_fact_id, *args, **kwargs):
        relationship_sets.append(source_fact_id)
        return upsert_relationship_set(connection, repository_id, source_fact_id, *args, **kwargs)

    monkeypatch.setattr(temporal_files, "_upsert_file_fact", record_file_fact)
    monkeypatch.setattr(temporal_files, "_upsert_symbols", record_symbols)
    monkeypatch.setattr(
        temporal_relationships,
        "_upsert_relationship_set",
        record_relationship_set,
    )
    monkeypatch.setattr(
        migrations_module,
        "compact_duplicate_relationship_sets",
        lambda _connection: (_ for _ in ()).throw(
            AssertionError("newly content-addressed relationship sets were compacted again")
        ),
    )
    monkeypatch.setattr(
        migrations_module,
        "parity_report",
        lambda _connection: (_ for _ in ()).throw(
            AssertionError("freshly constructed canonical frames were read back in full")
        ),
    )
    reopened = AnaxiIndex(database.path)
    with reopened.connect() as connection:
        fact_count = connection.execute("SELECT COUNT(*) FROM file_facts").fetchone()[0]
        secure_delete = int(connection.execute("PRAGMA secure_delete").fetchone()[0])
        migration_indexes = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' "
            "AND name LIKE 'anaxigraph_migration_%'"
        ).fetchall()
        compatibility_tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN "
            "('file_versions', 'symbols', 'relationships', 'group_memberships')"
        ).fetchall()

    assert len(symbolized) == len(set(symbolized)) == fact_count
    assert len(file_facts) < materialized_file_frames
    assert len(relationship_sets) < materialized_source_frames
    assert secure_delete == initial_secure_delete
    assert migration_indexes == []
    assert compatibility_tables == []

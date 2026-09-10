from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from semantic_support import _agent_dossier, _enable_agent_semantics
from test_migration_safety import _materialize_schema_six_frames

from anaxigraph.config import load_config
from anaxigraph.persistence import inspect_index, transactional_schema_change
from anaxigraph.persistence.index_initialization import schema_statements
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.storage import AnaxiIndex
from anaxigraph.understanding import SemanticEngine

TABLES = ("semantic_documents", "semantic_jobs", "semantic_scope_states")


def _legacy_schema(database: AnaxiIndex, version: int) -> None:
    """Reproduce released inline FKs, including the already-compacted 0.5.0 defect."""
    with closing(database.connect()) as connection, connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        fixture = Path(__file__).parent / "fixtures/schema-v6-compatibility.sql"
        for statement in schema_statements(fixture.read_text()):
            connection.execute(statement)
        _materialize_schema_six_frames(connection)
        for table in TABLES:
            connection.execute(f"ALTER TABLE {table} DROP COLUMN artifact_version_id")
            connection.execute(
                f"ALTER TABLE {table} ADD COLUMN artifact_version_id "
                "INTEGER REFERENCES file_versions(id) ON DELETE CASCADE"
            )
            connection.execute(
                f"UPDATE {table} SET artifact_version_id = (SELECT fv.id FROM file_versions fv "
                f"WHERE fv.snapshot_id = {table}.snapshot_id AND fv.artifact_id = {table}.artifact_id)"
            )
        if version == 11:
            for table in TABLES:
                connection.execute(f"UPDATE {table} SET artifact_version_id=NULL")
            for table in ("group_memberships", "relationships", "symbols", "file_versions"):
                connection.execute(f"DROP TABLE {table}")
        connection.execute(
            "UPDATE schema_meta SET value=? WHERE key='schema_version'", (str(version),)
        )


def _complete_one(engine, repository, repository_id, config):
    packet = engine.claim_agent_work(
        repository_id, repository, config, agent_id="migration-test", agent_model="fixture"
    )
    assert packet["status"] == "work"
    result = engine.submit_agent_work(
        repository_id,
        repository,
        config,
        job_id=packet["job"]["id"],
        lease_token=packet["lease"]["token"],
        dossier=_agent_dossier(packet["analysis_request"]),
    )
    assert result["status"] == "completed"


@pytest.mark.parametrize("version", [10, 11])
def test_legacy_upgrade_preserves_records_and_semantic_writes(repository, database, version):
    _enable_agent_semantics(repository)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    engine.bootstrap(stats.repository_id, repository, config)
    _complete_one(engine, repository, stats.repository_id, config)
    _legacy_schema(database, version)
    with closing(database.connect()) as connection:
        documents = [dict(row) for row in connection.execute("SELECT * FROM semantic_documents")]
        indexes = [
            tuple(row)
            for row in connection.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='index' AND tbl_name LIKE 'semantic_%' ORDER BY name"
            )
        ]
        assert any(
            row["table"] == "file_versions"
            for row in connection.execute("PRAGMA foreign_key_list(semantic_documents)")
        )

    upgraded = AnaxiIndex(database.path)
    engine = SemanticEngine(upgraded)
    engine.bootstrap(
        stats.repository_id, repository, config
    )  # Reuses the saved document and upserts state.
    _complete_one(
        engine, repository, stats.repository_id, config
    )  # Claims, job writes, and document insertion.
    report = inspect_index(upgraded.path, upgraded.connect)
    assert report["status"] == "healthy"
    assert report["missing_foreign_key_parents"] == []
    with closing(upgraded.connect()) as connection:
        assert indexes == [
            tuple(row)
            for row in connection.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='index' AND tbl_name LIKE 'semantic_%' ORDER BY name"
            )
        ]
        for old in documents:
            new = dict(
                connection.execute(
                    "SELECT * FROM semantic_documents WHERE id=?", (old["id"],)
                ).fetchone()
            )
            for key in ("id", "file_fact_id", "artifact_id", "snapshot_id", "value_json"):
                assert new[key] == old[key]
        for table in TABLES:
            assert not any(
                row["table"] == "file_versions"
                for row in connection.execute(f"PRAGMA foreign_key_list({table})")
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE semantic_documents SET file_fact_id=999999")
    AnaxiIndex(database.path)  # The repair is idempotent.


def test_doctor_detects_dangling_schema_even_when_no_row_violates_a_foreign_key(
    repository, database
):
    RepositoryScanner(database).scan(repository)
    _legacy_schema(database, 11)
    report = inspect_index(database.path, database.connect)
    assert report["foreign_key_violations"] == 0
    assert report["status"] == "blocked"
    assert "missing_foreign_key_parents" in report["blockers"]
    assert {row["table"] for row in report["missing_foreign_key_parents"]} == set(TABLES)


def test_schema_transaction_rejects_missing_parent_and_restores_foreign_keys(database):
    def invalid(connection):
        connection.execute(
            'CREATE TABLE "odd child" (parent INTEGER REFERENCES "missing parent"(id))'
        )
        connection.execute('INSERT INTO "odd child" VALUES(NULL)')

    with closing(database.connect()) as connection:
        with pytest.raises(RuntimeError, match="missing FK parent"):
            transactional_schema_change(connection, invalid)
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert (
            connection.execute("SELECT name FROM sqlite_master WHERE name='odd child'").fetchone()
            is None
        )


def test_same_version_repair_rolls_back_when_canonical_identity_is_missing(repository, database):
    _enable_agent_semantics(repository)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    SemanticEngine(database).bootstrap(stats.repository_id, repository, config)
    _legacy_schema(database, 11)
    with closing(database.connect()) as connection, connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("UPDATE semantic_scope_states SET file_fact_id=NULL")
    with pytest.raises(RuntimeError, match="without canonical file facts"):
        AnaxiIndex(database.path)
    with closing(database.connect()) as connection:
        for table in TABLES:
            assert any(
                row["table"] == "file_versions"
                for row in connection.execute(f"PRAGMA foreign_key_list({table})")
            )

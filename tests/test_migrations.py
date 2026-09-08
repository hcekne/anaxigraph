from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import yaml

import anaxigraph.persistence.index_initialization as initialization_module
import anaxigraph.persistence.migrations as migrations_module
from anaxigraph.config import load_config
from anaxigraph.persistence import SUPPORTED_SCHEMA_VERSIONS
from anaxigraph.persistence.temporal_hashing import digest
from anaxigraph.persistence.temporal_reconstruction import (
    _insert_checkpoint,
    reconstruct_files,
    reconstruct_relationships,
)
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic import SemanticResult
from anaxigraph.storage import SCHEMA_VERSION, AnaxiIndex
from anaxigraph.understanding import SemanticEngine

USAGE_PROVENANCE_COLUMNS = {
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
    "usage_source",
    "executor_effort",
}


def _schema_version(database: AnaxiIndex) -> int:
    with database.connect() as connection:
        return int(
            connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()[0]
        )


def _columns(database: AnaxiIndex, table: str) -> set[str]:
    with database.connect() as connection:
        return {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}


def test_fresh_and_current_schema_initialization_is_idempotent(tmp_path, monkeypatch):
    path = tmp_path / "current.db"

    first = AnaxiIndex(path)

    def unexpected_migration(*_args, **_kwargs):
        raise AssertionError("a current schema must not rerun data migration")

    monkeypatch.setattr(initialization_module, "migrate_schema", unexpected_migration)
    second = AnaxiIndex(path)

    assert SUPPORTED_SCHEMA_VERSIONS == frozenset({2, 6, 7, 8, 9, 10, 11})
    assert _schema_version(first) == _schema_version(second) == SCHEMA_VERSION == 11
    assert {"base_snapshot_id", "sequence"} <= _columns(first, "snapshots")
    assert _columns(first, "file_facts")
    assert _columns(first, "snapshot_file_changes")
    assert _columns(first, "relationship_sets")
    assert "file_fact_id" in _columns(first, "semantic_jobs")
    assert USAGE_PROVENANCE_COLUMNS <= _columns(first, "semantic_jobs")
    assert USAGE_PROVENANCE_COLUMNS <= _columns(first, "semantic_documents")


def test_reopening_current_schema_preserves_canonical_snapshot(repository, tmp_path):
    path = tmp_path / "reopen.db"
    first = AnaxiIndex(path)
    stats = RepositoryScanner(first).scan(repository)

    reopened = AnaxiIndex(path)

    assert reopened.overview(stats.repository_id)["files"] == stats.discovered
    assert reopened.graph(stats.repository_id)["nodes"]


_RELATIONSHIP_LOOKUPS = (
    ("relationship_edges", "relationship_set_id", "idx_relationship_edges_set"),
    ("snapshot_relationship_changes", "relationship_set_id", "idx_relationship_changes_set"),
    ("checkpoint_relationships", "relationship_set_id", "idx_checkpoint_relationships_set"),
    ("coverage_measurements", "relationship_edge_id", "idx_coverage_relationship_edge"),
)


def _assert_indexed_relationship_lookup(connection):
    for table, column, index in _RELATIONSHIP_LOOKUPS:
        plan = connection.execute(
            f"EXPLAIN QUERY PLAN SELECT * FROM {table} WHERE {column} = 1"
        ).fetchall()
        assert index in " ".join(str(row[3]) for row in plan)


@pytest.mark.parametrize("version", [10, 11])
def test_relationship_lookup_index_precedes_upgrade_compaction_and_survives_reopen(
    repository, tmp_path, monkeypatch, version
):
    path = tmp_path / "edge-lookup.db"
    first = AnaxiIndex(path)
    stats = RepositoryScanner(first).scan(repository)
    with first.connect() as connection:
        _assert_indexed_relationship_lookup(connection)
        for _table, _column, index in _RELATIONSHIP_LOOKUPS:
            connection.execute(f"DROP INDEX {index}")
        connection.execute(
            "UPDATE schema_meta SET value = ? WHERE key = 'schema_version'", (str(version),)
        )
    compact = migrations_module.compact_duplicate_relationship_sets
    calls = []

    def checked_compaction(connection):
        _assert_indexed_relationship_lookup(connection)
        calls.append(True)
        return compact(connection)

    monkeypatch.setattr(
        migrations_module, "compact_duplicate_relationship_sets", checked_compaction
    )
    reopened = AnaxiIndex(path)
    with reopened.connect() as connection:
        _assert_indexed_relationship_lookup(connection)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert len(calls) == (1 if version == 10 else 0)
    assert reopened.overview(stats.repository_id)["files"] == stats.discovered
    assert reopened.graph(stats.repository_id)["nodes"]


def _duplicate_record(connection, table, row, **changes):
    values = {key: value for key, value in dict(row).items() if key != "id"}
    values.update(changes)
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    return connection.execute(
        f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(values.values())
    ).lastrowid


def _legacy_duplicate_edges(connection, stats):
    edge = connection.execute("SELECT * FROM relationship_edges ORDER BY id LIMIT 1").fetchone()
    original = connection.execute(
        "SELECT * FROM relationship_sets WHERE id = ?", (edge["relationship_set_id"],)
    ).fetchone()
    duplicate = _duplicate_record(connection, "relationship_sets", original, set_key="legacy-copy")
    for row in connection.execute(
        "SELECT * FROM relationship_edges WHERE relationship_set_id = ?", (original["id"],)
    ).fetchall():
        duplicate_edge = _duplicate_record(
            connection, "relationship_edges", row, relationship_set_id=duplicate
        )
        connection.execute(
            "INSERT INTO coverage_measurements(snapshot_id, relationship_edge_id, provider, "
            "covered_lines, total_lines) VALUES (?, ?, 'fixture', 7, 10)",
            (stats.snapshot_id, duplicate_edge),
        )
    connection.execute(
        "UPDATE snapshot_relationship_changes SET relationship_set_id = ? WHERE relationship_set_id = ?",
        (duplicate, original["id"]),
    )
    connection.execute("UPDATE snapshots SET sequence = 15 WHERE id = ?", (stats.snapshot_id,))
    _insert_checkpoint(
        connection,
        stats.snapshot_id,
        stats.repository_id,
        15,
        1,
        reconstruct_files(connection, stats.snapshot_id),
        reconstruct_relationships(connection, stats.snapshot_id),
    )
    connection.execute("UPDATE schema_meta SET value = '10' WHERE key = 'schema_version'")
    return duplicate


def test_schema_10_duplicate_cleanup_preserves_references_without_cascade(repository, tmp_path):
    path = tmp_path / "duplicate-edges.db"
    first = AnaxiIndex(path)
    stats = RepositoryScanner(first).scan(repository)
    with first.connect() as connection:
        duplicate = _legacy_duplicate_edges(connection, stats)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        coverage = connection.execute("SELECT COUNT(*) FROM coverage_measurements").fetchone()[0]
    reopened = AnaxiIndex(path)
    with reopened.connect() as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert (
            connection.execute(
                "SELECT 1 FROM relationship_edges WHERE relationship_set_id = ?", (duplicate,)
            ).fetchone()
            is None
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM coverage_measurements").fetchone()[0]
            == coverage
        )
        assert all(
            row[0] == 7
            for row in connection.execute(
                "SELECT covered_lines FROM coverage_measurements WHERE provider = 'fixture'"
            )
        )
        checkpoint = connection.execute(
            "SELECT relationship_state_hash FROM snapshot_checkpoints WHERE snapshot_id = ?",
            (stats.snapshot_id,),
        ).fetchone()
        assert checkpoint is not None
        assert checkpoint[0] == digest(
            sorted(reconstruct_relationships(connection, stats.snapshot_id).items())
        )
    assert reopened.overview(stats.repository_id)["files"] == stats.discovered


def test_released_v2_schema_migrates_without_losing_repository_data(tmp_path):
    path = tmp_path / "v2.db"
    fixture = Path(__file__).parent / "fixtures" / "schema-v2.sql"
    with sqlite3.connect(path) as connection:
        connection.executescript(fixture.read_text(encoding="utf-8"))

    database = AnaxiIndex(path)

    assert _schema_version(database) == 11
    assert database.repository(1)["name"] == "Preserved v2 repository"
    assert {"worker_id", "lease_expires_at", "lease_token_hash", "executor_id"} <= _columns(
        database, "semantic_jobs"
    )
    assert {"previous_document_id", "executor_id", "executor_model"} <= _columns(
        database, "semantic_documents"
    )
    assert {"executor_id", "executor_model"} <= _columns(database, "semantic_claims")
    assert USAGE_PROVENANCE_COLUMNS <= _columns(database, "semantic_jobs")
    assert USAGE_PROVENANCE_COLUMNS <= _columns(database, "semantic_documents")


def _write_schema_10_usage_rows(path: Path, repository_id: int, snapshot_id: int) -> None:
    """Write jobs and documents the way schema 10 wrote them, then hide the schema-11 columns."""

    rows = (
        ("reported-cost", "completed", "codex", 0.5),
        ("estimated-only", "completed", "codex", None),
        ("agent-unknown", "completed", "agent", None),
        ("failed-attempt", "failed", "codex", None),
    )
    with sqlite3.connect(path) as connection:
        for scope_key, status, provider, cost in rows:
            connection.execute(
                """
                INSERT INTO semantic_jobs(
                    repository_id, snapshot_id, scope_type, scope_key, job_kind, reason, status,
                    input_hash, provider, model, prompt_version, schema_version, input_tokens,
                    available_at, actual_cost_usd
                ) VALUES (?, ?, 'module', ?, 'intrinsic', 'legacy row', ?, 'hash', ?,
                    'test-model', 'v1', 'v1', 7, '2026-09-01T00:00:00+00:00', ?)
                """,
                (repository_id, snapshot_id, scope_key, status, provider, cost),
            )
            if status != "completed":
                continue
            connection.execute(
                """
                INSERT INTO semantic_documents(
                    repository_id, snapshot_id, scope_type, scope_key, document_kind, input_hash,
                    intent_fingerprint, value_json, source, provider, model, prompt_version,
                    schema_version, confidence, input_tokens, actual_cost_usd, created_at
                ) VALUES (?, ?, 'module', ?, 'intrinsic', 'hash', 'intent', '{}', 'llm', ?,
                    'test-model', 'v1', 'v1', 0.8, 7, ?, '2026-09-01T00:00:00+00:00')
                """,
                (repository_id, snapshot_id, scope_key, provider, cost),
            )
        for table in ("semantic_jobs", "semantic_documents"):
            for name in sorted(USAGE_PROVENANCE_COLUMNS):
                connection.execute(f"ALTER TABLE {table} DROP COLUMN {name}")
        connection.execute("UPDATE schema_meta SET value = '10' WHERE key = 'schema_version'")


def _usage_sources(database: AnaxiIndex, table: str) -> dict[str, str]:
    with database.connect() as connection:
        return {
            str(row["scope_key"]): str(row["usage_source"])
            for row in connection.execute(f"SELECT scope_key, usage_source FROM {table}")
        }


def test_schema_11_backfills_usage_source_on_rows_written_before_the_column(repository, tmp_path):
    path = tmp_path / "v10-usage.db"
    stats = RepositoryScanner(AnaxiIndex(path)).scan(repository)
    _write_schema_10_usage_rows(path, stats.repository_id, stats.snapshot_id)

    database = AnaxiIndex(path)

    assert _schema_version(database) == 11
    assert _usage_sources(database, "semantic_jobs") == {
        "reported-cost": "reported",
        "estimated-only": "estimated",
        "agent-unknown": "unknown",
        "failed-attempt": "unknown",
    }
    assert _usage_sources(database, "semantic_documents") == {
        "reported-cost": "reported",
        "estimated-only": "estimated",
        "agent-unknown": "unknown",
    }
    with database.connect() as connection:
        totals = connection.execute("SELECT SUM(input_tokens) FROM semantic_jobs").fetchone()[0]
    assert totals == 28


@pytest.mark.parametrize("version", [1, 3, 4, 5, 12])
def test_untested_or_future_schema_versions_fail_closed(tmp_path, version):
    path = tmp_path / f"unsupported-{version}.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute(
            "INSERT INTO schema_meta(key, value) VALUES ('schema_version', ?)",
            (str(version),),
        )

    with pytest.raises(RuntimeError, match="newer than supported|no tested migration path"):
        AnaxiIndex(path)


def _additive_columns() -> dict[str, dict[str, str]]:
    """Record every column ``_ensure_legacy_columns`` adds without touching a database."""

    recorded: dict[str, dict[str, str]] = {}

    def record(_connection, table: str, definitions: dict[str, str]) -> None:
        recorded.setdefault(table, {}).update(definitions)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(migrations_module, "_ensure_columns", record)
        migrations_module._ensure_legacy_columns(None)
    return recorded


def _drop_columns(path: Path, columns: dict[str, dict[str, str]]) -> None:
    """Turn a current-version index into one built before these columns existed."""

    with sqlite3.connect(path) as connection:
        for table, definitions in columns.items():
            for name in definitions:
                connection.execute(f"ALTER TABLE {table} DROP COLUMN {name}")


def _enable_agent_provider(repository: Path) -> None:
    config_path = repository / ".anaxigraph.yml"
    policy = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    policy["semantic"] = {"enabled": True, "provider": "agent", "max_parallel_jobs": 1}
    config_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")


def test_current_schema_open_reconciles_columns_added_after_the_index_was_built(
    repository, tmp_path
):
    path = tmp_path / "live-v10.db"
    AnaxiIndex(path)
    additive = _additive_columns()
    assert additive
    _drop_columns(path, additive)

    database = AnaxiIndex(path)

    assert _schema_version(database) == SCHEMA_VERSION
    for table, definitions in additive.items():
        assert set(definitions) <= _columns(database, table)
    _enable_agent_provider(repository)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    engine.plan(stats.repository_id, repository, config)
    job = engine._services.leases.claim_job(
        stats.repository_id, config.semantic, worker_id="live-v10"
    )
    assert job is not None
    engine._services.persistence.complete_job(
        job,
        SemanticResult({"summary": "Reconciled index"}, 0.8, ("pkg/core.py",)),
        "agent",
        config.semantic,
    )
    with database.connect() as connection:
        completed = connection.execute(
            "SELECT status FROM semantic_jobs WHERE id = ?", (job["id"],)
        ).fetchone()
    assert completed["status"] == "completed"


def test_column_reconciliation_releases_its_write_lock_on_failure(tmp_path, monkeypatch):
    database = AnaxiIndex(tmp_path / "locked.db")

    def failing_columns(_connection):
        raise sqlite3.OperationalError("injected column failure")

    monkeypatch.setattr(migrations_module, "_ensure_legacy_columns", failing_columns)
    with database.connect() as connection:
        with pytest.raises(sqlite3.OperationalError, match="injected column failure"):
            migrations_module.reconcile_additive_columns(connection)
        assert not connection.in_transaction

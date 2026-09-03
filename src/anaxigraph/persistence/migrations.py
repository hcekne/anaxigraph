"""Explicit, idempotent migrations for released AnaxiIndex schemas."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from anaxigraph.persistence.compatibility_compaction import (
    backfill_relationship_coverage,
    compact_compatibility_rows,
    prepare_semantic_claims_for_compaction,
    retire_coverage_compatibility_reference,
)
from anaxigraph.persistence.index_parity import parity_report
from anaxigraph.persistence.semantic_fact_references import (
    backfill_semantic_fact_references,
)
from anaxigraph.persistence.temporal_facts import migrate_legacy_temporal_facts
from anaxigraph.persistence.temporal_files import (
    backfill_fact_symbol_details,
    compact_file_fact_metadata,
    compact_file_placement_metadata,
)
from anaxigraph.persistence.temporal_reconstruction import ensure_checkpoint_policy
from anaxigraph.persistence.temporal_relationships import compact_duplicate_relationship_sets
from anaxigraph.persistence.temporal_schema import install_temporal_schema

SUPPORTED_SCHEMA_VERSIONS = frozenset({2, 6, 7, 8, 9, 10, 11})

# Schema 11 records how a semantic result was paid for and how hard its executor was asked to
# think. ``input_tokens`` keeps meaning the whole prompt; the two cache columns are a breakdown of
# that total, never an addition to it. See docs/adr/0007-semantic-usage-and-executor-provenance.md.
_USAGE_PROVENANCE_COLUMNS = {
    "cache_read_input_tokens": "INTEGER NOT NULL DEFAULT 0",
    "cache_creation_input_tokens": "INTEGER NOT NULL DEFAULT 0",
    "usage_source": "TEXT NOT NULL DEFAULT 'unknown'",
    "executor_effort": "TEXT",
}


def migrate_schema(
    connection: sqlite3.Connection,
    *,
    current_version: int | None,
    target_version: int,
) -> None:
    """Bring a fresh or explicitly supported schema to the current version."""

    validate_schema_version(current_version, target_version)
    _ensure_legacy_columns(connection)
    if current_version is not None and current_version < 11:
        _backfill_usage_source(connection)
    install_temporal_schema(connection)
    _ensure_semantic_fact_schema(connection)
    _ensure_columns(
        connection,
        "coverage_measurements",
        {"relationship_edge_id": "INTEGER REFERENCES relationship_edges(id) ON DELETE CASCADE"},
    )
    compatibility_frames = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'file_versions'"
    ).fetchone()
    migrated_materialized_frames = _requires_materialized_frame_migration(
        current_version, compatibility_frames
    )
    if migrated_materialized_frames:
        _legacy_migration_indexes(connection, create=True)
        migrate_legacy_temporal_facts(connection)
    backfill_fact_symbol_details(connection)
    compact_file_placement_metadata(connection)
    compact_file_fact_metadata(connection)
    ensure_checkpoint_policy(connection)
    if current_version is not None:
        backfill_semantic_fact_references(connection)
        _compact_validated_compatibility(
            connection,
            validate_existing_projection=not migrated_materialized_frames,
        )
        if migrated_materialized_frames:
            _legacy_migration_indexes(connection, create=False)
    _ensure_semantic_fact_indexes(connection)
    connection.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('schema_version', ?)",
        (str(target_version),),
    )


def reconcile_additive_columns(connection: sqlite3.Connection) -> None:
    """Add the nullable columns an index already at the current version may lack.

    Column additions land in ``_ensure_legacy_columns`` without a schema-version
    bump, and ``migrate_schema`` never runs for a same-version index, so
    ``initialize_index`` calls this on every open. The check is one
    ``PRAGMA table_info`` per table and each addition is a metadata-only
    ``ALTER TABLE ... ADD COLUMN``; one write lock keeps concurrent openers
    from adding the same column twice.
    """

    connection.execute("BEGIN IMMEDIATE")
    try:
        _ensure_legacy_columns(connection)
    except BaseException:
        connection.rollback()
        raise
    connection.commit()


def _ensure_legacy_columns(connection: sqlite3.Connection) -> None:
    _ensure_columns(
        connection,
        "repositories",
        {"current_snapshot_id": "INTEGER"},
    )
    _ensure_columns(
        connection,
        "semantic_jobs",
        {
            "worker_id": "TEXT",
            "lease_expires_at": "TEXT",
            "lease_token_hash": "TEXT",
            "executor_id": "TEXT",
            "executor_model": "TEXT",
            **_USAGE_PROVENANCE_COLUMNS,
        },
    )
    _ensure_columns(
        connection,
        "semantic_documents",
        {
            "previous_document_id": "INTEGER REFERENCES semantic_documents(id)",
            "executor_id": "TEXT",
            "executor_model": "TEXT",
            **_USAGE_PROVENANCE_COLUMNS,
        },
    )
    _ensure_columns(
        connection,
        "semantic_claims",
        {"executor_id": "TEXT", "executor_model": "TEXT"},
    )


def _backfill_usage_source(connection: sqlite3.Connection) -> None:
    """Classify rows written before ``usage_source`` existed. HEURISTIC, not ground truth.

    Nothing in a pre-schema-11 row records whether its executor reported usage, so the migration
    reads the only marker the completion path left behind: ``actual_cost_usd`` was set exactly when
    ``_completion`` treated the usage as reported, and left ``NULL`` when AnaxiGraph substituted its
    own estimate or an agent-funded submission carried no usage. Failed attempts never received a
    cost and therefore stay ``unknown``. Token totals are not changed.
    """

    for table in ("semantic_jobs", "semantic_documents"):
        completed = "status = 'completed' AND " if table == "semantic_jobs" else ""
        connection.execute(
            f"""
            UPDATE {table} SET usage_source = CASE
                WHEN actual_cost_usd IS NOT NULL THEN 'reported'
                WHEN {completed}provider != 'agent' THEN 'estimated'
                ELSE 'unknown' END
            WHERE usage_source = 'unknown'
            """
        )


def _ensure_semantic_fact_schema(connection: sqlite3.Connection) -> None:
    for table in (
        "semantic_claims",
        "semantic_documents",
        "semantic_jobs",
        "semantic_scope_states",
    ):
        _ensure_columns(
            connection,
            table,
            {"file_fact_id": "INTEGER REFERENCES file_facts(id) ON DELETE CASCADE"},
        )


def _compact_validated_compatibility(
    connection: sqlite3.Connection,
    *,
    validate_existing_projection: bool,
) -> None:
    if validate_existing_projection:
        report = parity_report(connection)
        if report["status"] not in {"exact", "canonical_only"}:
            raise RuntimeError(
                "Canonical facts do not match compatibility frames; compaction refused"
            )
    prepare_semantic_claims_for_compaction(connection)
    backfill_relationship_coverage(connection)
    retire_coverage_compatibility_reference(connection)
    if validate_existing_projection:
        compact_duplicate_relationship_sets(connection)
    compact_compatibility_rows(connection)


def transactional_schema_change(
    connection: sqlite3.Connection,
    operation: Callable[[sqlite3.Connection], None],
) -> None:
    """Apply one schema change atomically and reject damaged foreign-key state."""

    if connection.in_transaction:
        raise RuntimeError("Schema migration requires an idle SQLite connection")
    foreign_keys = int(connection.execute("PRAGMA foreign_keys").fetchone()[0])
    if foreign_keys:
        connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.execute("BEGIN IMMEDIATE")
        try:
            operation(connection)
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError(f"Schema migration introduced {len(violations)} FK violations")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
    finally:
        if foreign_keys:
            connection.execute("PRAGMA foreign_keys = ON")


def validate_schema_version(current_version: int | None, target_version: int) -> None:
    if current_version is not None and current_version > target_version:
        raise RuntimeError(
            f"Database schema {current_version} is newer than supported {target_version}"
        )
    if current_version is not None and current_version not in SUPPORTED_SCHEMA_VERSIONS:
        supported = ", ".join(str(item) for item in sorted(SUPPORTED_SCHEMA_VERSIONS))
        raise RuntimeError(
            f"Database schema {current_version} has no tested migration path; "
            f"supported versions are {supported}"
        )


def _ensure_columns(
    connection: sqlite3.Connection,
    table: str,
    definitions: dict[str, str],
) -> None:
    existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
    for name, definition in definitions.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _ensure_semantic_fact_indexes(connection: sqlite3.Connection) -> None:
    for statement in (
        "CREATE INDEX IF NOT EXISTS idx_semantic_claims_fact "
        "ON semantic_claims(file_fact_id, claim_type)",
        "CREATE INDEX IF NOT EXISTS idx_semantic_documents_fact "
        "ON semantic_documents(file_fact_id)",
        "CREATE INDEX IF NOT EXISTS idx_semantic_jobs_fact ON semantic_jobs(file_fact_id)",
        "CREATE INDEX IF NOT EXISTS idx_semantic_states_fact "
        "ON semantic_scope_states(file_fact_id)",
    ):
        connection.execute(statement)


def _legacy_migration_indexes(connection: sqlite3.Connection, *, create: bool) -> None:
    indexes = (
        (
            "anaxigraph_migration_relationships",
            "relationships",
            "snapshot_id, source_artifact_id, id",
        ),
        ("anaxigraph_migration_symbols", "symbols", "artifact_version_id, start_line, id"),
    )
    for name, table, columns in indexes:
        statement = (
            f"CREATE INDEX {name} ON {table}({columns})"
            if create
            else f"DROP INDEX IF EXISTS {name}"
        )
        connection.execute(statement)


def _requires_materialized_frame_migration(
    current_version: int | None, compatibility_frames: sqlite3.Row | None
) -> bool:
    return bool(
        current_version is not None
        and current_version not in {7, 8, 9, 10, 11}
        and compatibility_frames
    )

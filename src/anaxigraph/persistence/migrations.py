"""Explicit, idempotent migrations for released AnaxiIndex schemas."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from anaxigraph.persistence.compatibility_compaction import (
    backfill_relationship_coverage,
    compact_compatibility_rows,
    prepare_semantic_claims_for_compaction,
)
from anaxigraph.persistence.index_parity import parity_report
from anaxigraph.persistence.index_temporal_health import refresh_canonical_content_digest
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

SUPPORTED_SCHEMA_VERSIONS = frozenset({2, 6, 7, 8, 9, 10})


def migrate_schema(
    connection: sqlite3.Connection,
    *,
    current_version: int | None,
    target_version: int,
) -> None:
    """Bring a fresh or explicitly supported schema to the current version."""

    validate_schema_version(current_version, target_version)
    _ensure_legacy_columns(connection)
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
    if (
        current_version is not None
        and current_version not in {7, 8, 9, 10}
        and compatibility_frames
    ):
        migrate_legacy_temporal_facts(connection)
    canonical_metadata_changed = bool(backfill_fact_symbol_details(connection))
    canonical_metadata_changed = (
        bool(compact_file_placement_metadata(connection)) or canonical_metadata_changed
    )
    canonical_metadata_changed = (
        bool(compact_file_fact_metadata(connection)) or canonical_metadata_changed
    )
    ensure_checkpoint_policy(connection)
    if current_version is None:
        refresh_canonical_content_digest(connection)
    else:
        backfill_semantic_fact_references(connection)
        _compact_validated_compatibility(
            connection,
            canonical_changed=canonical_metadata_changed,
        )
    _ensure_semantic_fact_indexes(connection)
    connection.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('schema_version', ?)",
        (str(target_version),),
    )


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
        },
    )
    _ensure_columns(
        connection,
        "semantic_documents",
        {
            "previous_document_id": "INTEGER REFERENCES semantic_documents(id)",
            "executor_id": "TEXT",
            "executor_model": "TEXT",
        },
    )
    _ensure_columns(
        connection,
        "semantic_claims",
        {"executor_id": "TEXT", "executor_model": "TEXT"},
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
    canonical_changed: bool,
) -> None:
    report = parity_report(connection)
    if report["status"] not in {"exact", "canonical_only"}:
        raise RuntimeError("Canonical facts do not match compatibility frames; compaction refused")
    prepare_semantic_claims_for_compaction(connection)
    backfill_relationship_coverage(connection)
    relationship_sets_removed = compact_duplicate_relationship_sets(connection)
    compact_compatibility_rows(
        connection,
        canonical_changed=canonical_changed or relationship_sets_removed > 0,
    )


def transactional_schema_change(
    connection: sqlite3.Connection,
    operation: Callable[[sqlite3.Connection], None],
) -> None:
    """Apply one schema change atomically and reject damaged foreign-key state."""

    if connection.in_transaction:
        raise RuntimeError("Schema migration requires an idle SQLite connection")
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

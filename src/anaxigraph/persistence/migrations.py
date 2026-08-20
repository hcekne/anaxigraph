"""Explicit, idempotent migrations for released AnaxiIndex schemas."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from anaxigraph.persistence.temporal_facts import migrate_legacy_temporal_facts
from anaxigraph.persistence.temporal_schema import install_temporal_schema

SUPPORTED_SCHEMA_VERSIONS = frozenset({2, 6, 7})


def migrate_schema(
    connection: sqlite3.Connection,
    *,
    current_version: int | None,
    target_version: int,
) -> None:
    """Bring a fresh or explicitly supported schema to the current version."""

    validate_schema_version(current_version, target_version)
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
    install_temporal_schema(connection)
    if current_version != target_version:
        migrate_legacy_temporal_facts(connection)
    connection.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('schema_version', ?)",
        (str(target_version),),
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

"""Fail-closed, recoverable initialization of an AnaxiIndex database."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

from anaxigraph.persistence.index_backup import create_schema_backup
from anaxigraph.persistence.migrations import (
    migrate_schema,
    transactional_schema_change,
    validate_schema_version,
)


def initialize_index(
    database_path: Path,
    connection_factory: Callable[[], sqlite3.Connection],
    *,
    schema: str,
    target_version: int,
) -> None:
    """Install or upgrade the schema as one validated transaction."""

    current_version = existing_schema_version(database_path)
    validate_schema_version(current_version, target_version)
    if current_version is not None and current_version < target_version:
        create_schema_backup(database_path, schema_version=current_version)

    with connection_factory() as connection:

        def apply(current: sqlite3.Connection) -> None:
            for statement in schema_statements(schema):
                current.execute(statement)
            migrate_schema(
                current,
                current_version=current_version,
                target_version=target_version,
            )

        transactional_schema_change(connection, apply)


def existing_schema_version(database_path: Path) -> int | None:
    if not database_path.is_file() or database_path.stat().st_size == 0:
        return None
    with sqlite3.connect(database_path) as connection:
        table = connection.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'schema_meta'
            """
        ).fetchone()
        if table is None:
            return None
        row = connection.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
    return int(row[0]) if row is not None else None


def schema_statements(schema: str) -> Iterator[str]:
    """Yield complete SQLite statements without executescript's implicit commit."""

    pending: list[str] = []
    for line in schema.splitlines():
        pending.append(line)
        candidate = "\n".join(pending).strip()
        if candidate and sqlite3.complete_statement(candidate):
            yield candidate
            pending = []
    trailing = "\n".join(pending).strip()
    if trailing:
        raise RuntimeError("AnaxiIndex schema contains an incomplete SQL statement")

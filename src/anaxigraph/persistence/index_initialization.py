"""Fail-closed, recoverable initialization of an AnaxiIndex database."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from anaxigraph.persistence.compatibility_compaction import (
    compact_terminal_semantic_job_metadata,
    coverage_uses_compatibility_reference,
    retire_compatibility_references,
    semantic_compatibility_tables,
)
from anaxigraph.persistence.git_metrics import migrate_git_metrics
from anaxigraph.persistence.index_backup import create_schema_backup
from anaxigraph.persistence.index_compaction import (
    PAGE_BYTES,
    compact_closed_index,
    compact_identity_caches,
)
from anaxigraph.persistence.index_lifetime import locked_connection
from anaxigraph.persistence.migrations import (
    migrate_schema,
    reconcile_additive_columns,
    transactional_schema_change,
    validate_schema_version,
)
from anaxigraph.persistence.search_read import refresh_current_search_projections
from anaxigraph.persistence.semantic_payloads import register_semantic_payloads
from anaxigraph.persistence.temporal_files import compact_file_fact_metadata
from anaxigraph.persistence.temporal_reconstruction import ensure_checkpoint_policy
from anaxigraph.storage_policy import StoragePolicy, admit_index_write, repository_storage_policy
from anaxigraph.storage_usage import registered_record_usage


def configured_storage_policy(path, default):
    """Honor an existing repository's explicit budget before upgrading its local cache."""
    if not path.is_file() or not path.stat().st_size:
        return default
    with closing(
        locked_connection(path, database=f"{path.as_uri()}?mode=ro", uri=True)
    ) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if not {"repositories", "snapshots"}.issubset(tables):
            return default
        columns = {row[1] for row in connection.execute("PRAGMA table_info(repositories)")}
        if "current_snapshot_id" not in columns:
            return default
        rows = connection.execute(
            "SELECT r.path,s.metadata_json FROM repositories r JOIN snapshots s ON s.id=r.current_snapshot_id"
        ).fetchall()
    policies = []
    for root, metadata in rows:
        directory = Path(root)
        if directory.is_dir():
            config_path = json.loads(metadata or "{}").get("config_path")
            candidate = Path(config_path) if config_path else None
            policies.append(repository_storage_policy(directory, candidate))
    return max(policies, key=lambda policy: policy.index_bytes, default=default)


def initialize_index(
    database_path: Path,
    connection_factory: Callable[[], sqlite3.Connection],
    *,
    schema: str,
    target_version: int,
    storage_policy: StoragePolicy | None = None,
) -> None:
    """Install or upgrade the schema as one validated transaction."""

    current_version = existing_schema_version(database_path)
    validate_schema_version(current_version, target_version)
    if current_version == target_version:
        with closing(connection_factory()) as connection, connection:
            reconcile_additive_columns(connection)
            if coverage_uses_compatibility_reference(connection) or semantic_compatibility_tables(
                connection
            ):
                transactional_schema_change(connection, retire_compatibility_references)
            ensure_checkpoint_policy(connection)
            compact_terminal_semantic_job_metadata(connection)
        finish_index_storage(database_path, connection_factory, target_version, storage_policy)
        return
    backup = None
    if current_version is not None and current_version < target_version:
        backup = create_schema_backup(database_path, schema_version=current_version)

    with closing(connection_factory()) as connection, connection:

        def apply(current: sqlite3.Connection) -> None:
            for statement in schema_statements(schema):
                current.execute(statement)
            migrate_schema(
                current,
                current_version=current_version,
                target_version=target_version,
            )
            compact_terminal_semantic_job_metadata(current)
            if backup is not None:
                _record_migration(current, backup, target_version)

        transactional_schema_change(connection, apply)
    finish_index_storage(database_path, connection_factory, target_version, storage_policy)


def _compact_parser_cache(connection):
    key = "parser-cache-compaction-v2"
    if connection.execute("SELECT 1 FROM schema_meta WHERE key=?", (key,)).fetchone():
        return
    # The canonical migration is already committed with its verified recovery backup.
    # Bound each disposable IR rewrite so old pages and its WAL never accumulate.
    after = 0
    changed = 0
    while True:
        rows = connection.execute(
            "SELECT id FROM file_facts WHERE id>? ORDER BY id LIMIT 128", (after,)
        ).fetchall()
        if not rows:
            break
        rewritten = compact_file_fact_metadata(connection, after_id=after, limit=128)
        changed += rewritten
        if rewritten:
            connection.execute(
                "INSERT OR REPLACE INTO schema_meta VALUES ('index-compaction-pending','true')"
            )
        connection.commit()
        after = rows[-1][0]
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.execute(
        "INSERT OR IGNORE INTO schema_meta(key,value) VALUES (?, ?)", (key, "complete")
    )
    connection.commit()
    return changed


def finish_index_storage(path, connection_factory, target_version, storage_policy):
    with closing(connection_factory()) as connection, connection:
        metrics = migrate_git_metrics(connection)
        if metrics["pruned_rows"]:
            connection.execute(
                "INSERT OR REPLACE INTO schema_meta VALUES ('index-compaction-pending','true')"
            )
        pending = connection.execute(
            "SELECT 1 FROM schema_meta WHERE key='index-compaction-pending'"
        ).fetchone()
    if pending:
        _reclaim_closed_index(path, connection_factory, target_version, storage_policy)
    with closing(connection_factory()) as connection:
        changed = _compact_parser_cache(connection)
        identities_changed = compact_identity_caches(connection)
        connection.commit()
    if changed or identities_changed:
        _reclaim_closed_index(path, connection_factory, target_version, storage_policy)
    with closing(connection_factory()) as connection, connection:
        if connection.execute(
            "SELECT 1 FROM schema_meta WHERE key='graph-import-pending'"
        ).fetchone():
            return
        refresh_current_search_projections(connection)
        admit_index_write(connection, path, storage_policy or StoragePolicy())
        connection.execute("DELETE FROM schema_meta WHERE key='index-compaction-pending'")


def _reclaim_closed_index(path, connection_factory, target_version, storage_policy):
    with closing(connection_factory()) as connection:
        record_bytes = registered_record_usage(connection)["bytes"]
    compact_closed_index(path, schema_version=target_version, record_bytes=record_bytes)


def _record_migration(connection, backup, target_version: int) -> None:
    connection.execute(
        "INSERT OR REPLACE INTO schema_meta VALUES ('index-compaction-pending','true')"
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO schema_migrations(
            from_version, to_version, backup_path, backup_sha256,
            backup_bytes, completed_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            backup.schema_version,
            target_version,
            str(backup.path),
            backup.sha256,
            backup.bytes,
            datetime.now(UTC).isoformat(),
        ),
    )


def existing_schema_version(database_path: Path) -> int | None:
    if not database_path.is_file() or database_path.stat().st_size == 0:
        return None
    with closing(locked_connection(database_path)) as connection:
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


def connect_index(path, policy):
    connection = locked_connection(path, timeout=30)
    try:
        connection.row_factory = sqlite3.Row
        register_semantic_payloads(connection)
        connection.execute("PRAGMA temp_store=MEMORY")
        if not connection.execute("PRAGMA page_count").fetchone()[0]:
            connection.execute(f"PRAGMA page_size={PAGE_BYTES}")
        page_size = connection.execute("PRAGMA page_size").fetchone()[0]
        connection.execute(f"PRAGMA max_page_count = {policy.index_bytes // page_size}")
        connection.execute("PRAGMA journal_size_limit = 4000000")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection
    except BaseException:
        connection.close()
        raise

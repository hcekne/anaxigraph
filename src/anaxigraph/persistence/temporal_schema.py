"""Schema-7 immutable fact and snapshot-delta tables."""

from __future__ import annotations

import sqlite3

CANONICAL_CONTENT_TABLES = (
    "file_facts",
    "fact_symbols",
    "snapshot_file_changes",
    "relationship_sets",
    "relationship_edges",
    "snapshot_relationship_changes",
)
CHECKPOINT_TABLES = ("snapshot_checkpoints", "checkpoint_files", "checkpoint_relationships")
TEMPORAL_TABLES = (*CANONICAL_CONTENT_TABLES, *CHECKPOINT_TABLES)

TEMPORAL_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS file_facts (
        id INTEGER PRIMARY KEY,
        artifact_id INTEGER NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
        fact_key TEXT NOT NULL UNIQUE,
        analysis_signature TEXT NOT NULL,
        language TEXT NOT NULL,
        runtime TEXT,
        raw_hash TEXT NOT NULL,
        structural_hash TEXT NOT NULL,
        lines_of_code INTEGER NOT NULL,
        comment_lines INTEGER NOT NULL,
        complexity REAL NOT NULL,
        summary TEXT NOT NULL,
        responsibilities_json TEXT NOT NULL DEFAULT '[]',
        inputs_json TEXT NOT NULL DEFAULT '[]',
        outputs_json TEXT NOT NULL DEFAULT '[]',
        side_effects_json TEXT NOT NULL DEFAULT '[]',
        public_interfaces_json TEXT NOT NULL DEFAULT '[]',
        analyzer TEXT NOT NULL,
        parse_error TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS snapshot_file_changes (
        snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
        artifact_id INTEGER NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
        change_kind TEXT NOT NULL,
        file_fact_id INTEGER REFERENCES file_facts(id) ON DELETE CASCADE,
        path TEXT,
        declared_group TEXT,
        inferred_group TEXT,
        analysis_status TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        first_seen_at TEXT,
        last_changed_at TEXT,
        PRIMARY KEY(snapshot_id, artifact_id),
        CHECK(change_kind IN ('add', 'change', 'delete'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fact_symbols (
        id INTEGER PRIMARY KEY,
        file_fact_id INTEGER NOT NULL REFERENCES file_facts(id) ON DELETE CASCADE,
        symbol_type TEXT NOT NULL,
        name TEXT NOT NULL,
        qualified_name TEXT NOT NULL,
        start_line INTEGER NOT NULL,
        end_line INTEGER NOT NULL,
        signature TEXT NOT NULL DEFAULT '',
        summary TEXT NOT NULL DEFAULT '',
        complexity REAL NOT NULL DEFAULT 1,
        logical_lines INTEGER NOT NULL DEFAULT 0,
        visibility TEXT NOT NULL DEFAULT 'unknown',
        start_column INTEGER NOT NULL DEFAULT 0,
        end_column INTEGER NOT NULL DEFAULT 0,
        UNIQUE(file_fact_id, symbol_type, qualified_name, start_line, end_line)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS relationship_sets (
        id INTEGER PRIMARY KEY,
        repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
        source_artifact_id INTEGER NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
        source_file_fact_id INTEGER NOT NULL REFERENCES file_facts(id) ON DELETE CASCADE,
        set_key TEXT NOT NULL UNIQUE,
        resolver_context_hash TEXT NOT NULL,
        analysis_signature TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS relationship_edges (
        id INTEGER PRIMARY KEY,
        relationship_set_id INTEGER NOT NULL REFERENCES relationship_sets(id) ON DELETE CASCADE,
        target_artifact_id INTEGER REFERENCES artifacts(id) ON DELETE CASCADE,
        target_external TEXT,
        relationship_type TEXT NOT NULL,
        source TEXT NOT NULL,
        confidence REAL NOT NULL,
        evidence TEXT NOT NULL DEFAULT '',
        source_line INTEGER NOT NULL DEFAULT 0,
        weight REAL NOT NULL DEFAULT 1,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        CHECK(target_artifact_id IS NOT NULL OR target_external IS NOT NULL)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS snapshot_relationship_changes (
        snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
        source_artifact_id INTEGER NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
        change_kind TEXT NOT NULL,
        relationship_set_id INTEGER REFERENCES relationship_sets(id) ON DELETE CASCADE,
        PRIMARY KEY(snapshot_id, source_artifact_id),
        CHECK(change_kind IN ('set', 'retract'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        id INTEGER PRIMARY KEY,
        from_version INTEGER NOT NULL,
        to_version INTEGER NOT NULL,
        backup_path TEXT NOT NULL,
        backup_sha256 TEXT NOT NULL,
        backup_bytes INTEGER NOT NULL,
        completed_at TEXT NOT NULL,
        UNIQUE(from_version, to_version, backup_sha256)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS snapshot_checkpoints (
        snapshot_id INTEGER PRIMARY KEY REFERENCES snapshots(id) ON DELETE CASCADE,
        repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
        sequence INTEGER NOT NULL,
        source_delta_depth INTEGER NOT NULL,
        file_count INTEGER NOT NULL,
        relationship_source_count INTEGER NOT NULL,
        file_state_hash TEXT NOT NULL,
        relationship_state_hash TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS checkpoint_files (
        checkpoint_snapshot_id INTEGER NOT NULL
            REFERENCES snapshot_checkpoints(snapshot_id) ON DELETE CASCADE,
        artifact_id INTEGER NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
        file_fact_id INTEGER NOT NULL REFERENCES file_facts(id) ON DELETE CASCADE,
        path TEXT NOT NULL,
        declared_group TEXT,
        inferred_group TEXT,
        analysis_status TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        first_seen_at TEXT,
        last_changed_at TEXT,
        PRIMARY KEY(checkpoint_snapshot_id, artifact_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS checkpoint_relationships (
        checkpoint_snapshot_id INTEGER NOT NULL
            REFERENCES snapshot_checkpoints(snapshot_id) ON DELETE CASCADE,
        source_artifact_id INTEGER NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
        relationship_set_id INTEGER NOT NULL REFERENCES relationship_sets(id) ON DELETE CASCADE,
        PRIMARY KEY(checkpoint_snapshot_id, source_artifact_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_file_facts_artifact ON file_facts(artifact_id, id)",
    "CREATE INDEX IF NOT EXISTS idx_file_changes_snapshot ON snapshot_file_changes(snapshot_id)",
    "CREATE INDEX IF NOT EXISTS idx_file_changes_artifact ON snapshot_file_changes(artifact_id, snapshot_id)",
    "CREATE INDEX IF NOT EXISTS idx_relationship_sets_source ON relationship_sets(source_artifact_id, id)",
    "CREATE INDEX IF NOT EXISTS idx_relationship_changes_snapshot ON snapshot_relationship_changes(snapshot_id)",
    "CREATE INDEX IF NOT EXISTS idx_checkpoints_repository ON snapshot_checkpoints(repository_id, sequence)",
)


def install_temporal_schema(connection: sqlite3.Connection) -> None:
    _ensure_snapshot_columns(connection)
    for statement in TEMPORAL_SCHEMA:
        connection.execute(statement)
    _ensure_fact_symbol_columns(connection)
    _ensure_checkpoint_columns(connection)


def clear_temporal_facts(connection: sqlite3.Connection) -> None:
    for table in reversed(TEMPORAL_TABLES):
        connection.execute(f"DELETE FROM {table}")


def _ensure_snapshot_columns(connection: sqlite3.Connection) -> None:
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(snapshots)")}
    if "base_snapshot_id" not in columns:
        connection.execute("ALTER TABLE snapshots ADD COLUMN base_snapshot_id INTEGER")
    if "sequence" not in columns:
        connection.execute("ALTER TABLE snapshots ADD COLUMN sequence INTEGER NOT NULL DEFAULT 0")


def _ensure_checkpoint_columns(connection: sqlite3.Connection) -> None:
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(checkpoint_files)")}
    if "metadata_json" not in columns:
        connection.execute(
            "ALTER TABLE checkpoint_files ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'"
        )


def _ensure_fact_symbol_columns(connection: sqlite3.Connection) -> None:
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(fact_symbols)")}
    for name, definition in (
        ("visibility", "TEXT NOT NULL DEFAULT 'unknown'"),
        ("start_column", "INTEGER NOT NULL DEFAULT 0"),
        ("end_column", "INTEGER NOT NULL DEFAULT 0"),
    ):
        if name not in columns:
            connection.execute(f"ALTER TABLE fact_symbols ADD COLUMN {name} {definition}")

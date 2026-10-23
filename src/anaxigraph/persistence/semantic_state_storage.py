"""Copy-on-write scope values shared by compact snapshot-local bindings."""

from __future__ import annotations

import hashlib

STATE_COLUMNS = (
    "repository_id",
    "snapshot_id",
    "scope_type",
    "scope_key",
    "artifact_id",
    "artifact_version_id",
    "file_fact_id",
    "status",
    "reason",
    "intrinsic_input_hash",
    "context_input_hash",
    "interface_hash",
    "relationship_hash",
    "context_fingerprint",
    "intrinsic_document_id",
    "context_document_id",
    "last_checked_at",
)
VALUE_COLUMNS = (
    "status",
    "reason",
    "intrinsic_input_hash",
    "context_input_hash",
    "interface_hash",
    "relationship_hash",
    "context_fingerprint",
    "intrinsic_document_id",
    "context_document_id",
)
BINDING_COLUMNS = tuple(name for name in STATE_COLUMNS if name not in VALUE_COLUMNS)
_COALESCED = VALUE_COLUMNS[2:]
_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS semantic_state_records(
        id INTEGER PRIMARY KEY, value_key BLOB NOT NULL, status TEXT NOT NULL,
        reason TEXT NOT NULL DEFAULT '',intrinsic_input_hash TEXT,context_input_hash TEXT,
        interface_hash TEXT,relationship_hash TEXT,context_fingerprint TEXT,
        intrinsic_document_id INTEGER REFERENCES semantic_documents(id) ON DELETE SET NULL,
        context_document_id INTEGER REFERENCES semantic_documents(id) ON DELETE SET NULL)""",
    "CREATE INDEX IF NOT EXISTS semantic_state_record_key ON semantic_state_records(value_key)",
    """CREATE TABLE IF NOT EXISTS semantic_state_bindings(
        repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
        snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
        scope_type TEXT NOT NULL,scope_key TEXT NOT NULL,
        artifact_id INTEGER REFERENCES artifacts(id) ON DELETE CASCADE,
        artifact_version_id INTEGER,
        file_fact_id INTEGER REFERENCES file_facts(id) ON DELETE CASCADE,
        state_id INTEGER NOT NULL REFERENCES semantic_state_records(id),last_checked_at TEXT NOT NULL,
        PRIMARY KEY(snapshot_id,scope_type,scope_key))""",
    "CREATE INDEX IF NOT EXISTS semantic_state_binding_fact ON semantic_state_bindings(file_fact_id)",
    "CREATE INDEX IF NOT EXISTS semantic_state_binding_value ON semantic_state_bindings(state_id)",
)


def register_semantic_state_functions(connection):
    connection.create_function(
        "anaxigraph_state_key",
        1,
        lambda value: hashlib.sha256(value.encode()).digest(),
        deterministic=True,
    )


def install_semantic_state_storage(connection):
    current = connection.execute(
        "SELECT type FROM sqlite_master WHERE name='semantic_scope_states'"
    ).fetchone()
    if current is None or current[0] == "view":
        return
    if any(
        row["table"] == "file_versions"
        for row in connection.execute("PRAGMA foreign_key_list(semantic_scope_states)")
    ):
        return
    for statement in _SCHEMA:
        connection.execute(statement)
    connection.execute("ALTER TABLE semantic_scope_states RENAME TO semantic_scope_states_previous")
    projections = [f"{'v' if name in VALUE_COLUMNS else 'b'}.{name}" for name in STATE_COLUMNS]
    connection.execute(
        "CREATE VIEW semantic_scope_states AS SELECT "
        + ",".join(projections)
        + " FROM semantic_state_bindings b JOIN semantic_state_records v ON v.id=b.state_id"
    )
    for statement in _triggers():
        connection.execute(statement)
    columns = ",".join(STATE_COLUMNS)
    connection.execute(
        f"INSERT INTO semantic_scope_states({columns}) SELECT {columns} FROM semantic_scope_states_previous"
    )
    connection.execute("DROP TABLE semantic_scope_states_previous")
    connection.execute(
        "INSERT OR REPLACE INTO schema_meta VALUES ('index-compaction-pending','true')"
    )


def _triggers():
    values = [
        f"COALESCE(NEW.{name},'')" if name == "reason" else f"NEW.{name}" for name in VALUE_COLUMNS
    ]
    key = "anaxigraph_state_key(json_array(" + ",".join(values) + "))"
    matching = " AND ".join(
        f"{name} IS {value}" for name, value in zip(VALUE_COLUMNS, values, strict=True)
    )
    predicate = f"value_key={key} AND {matching}"
    identity = (
        "snapshot_id=OLD.snapshot_id AND scope_type=OLD.scope_type AND scope_key=OLD.scope_key"
    )
    return (
        "CREATE TRIGGER semantic_state_insert INSTEAD OF INSERT ON semantic_scope_states BEGIN "
        f"INSERT INTO semantic_state_records(value_key,{','.join(VALUE_COLUMNS)}) "
        f"SELECT {key},{','.join(values)} WHERE NOT EXISTS(SELECT 1 FROM semantic_state_records WHERE {predicate}); "
        f"INSERT INTO semantic_state_bindings({','.join(BINDING_COLUMNS)},state_id) "
        f"SELECT {','.join('NEW.' + name for name in BINDING_COLUMNS)},id "
        f"FROM semantic_state_records WHERE {predicate} LIMIT 1; END",
        "CREATE TRIGGER semantic_state_update INSTEAD OF UPDATE ON semantic_scope_states BEGIN "
        f"DELETE FROM semantic_state_bindings WHERE {identity}; "
        f"INSERT INTO semantic_scope_states({','.join(STATE_COLUMNS)}) "
        f"VALUES({','.join('NEW.' + name for name in STATE_COLUMNS)}); END",
        "CREATE TRIGGER semantic_state_delete INSTEAD OF DELETE ON semantic_scope_states BEGIN "
        f"DELETE FROM semantic_state_bindings WHERE {identity}; END",
    )


def upsert_semantic_state(connection, values):
    value = dict(zip(STATE_COLUMNS, values, strict=True))
    existing = connection.execute(
        "SELECT * FROM semantic_scope_states WHERE snapshot_id=? AND scope_type=? AND scope_key=?",
        (value["snapshot_id"], value["scope_type"], value["scope_key"]),
    ).fetchone()
    if existing:
        for name in _COALESCED:
            if value[name] is None:
                value[name] = existing[name]
    connection.execute(
        f"INSERT OR REPLACE INTO semantic_scope_states({','.join(STATE_COLUMNS)}) "
        f"VALUES({','.join('?' for _ in STATE_COLUMNS)})",
        [value[name] for name in STATE_COLUMNS],
    )


def collect_semantic_states(connection):
    return connection.execute(
        "DELETE FROM semantic_state_records WHERE id NOT IN (SELECT state_id FROM semantic_state_bindings)"
    ).rowcount

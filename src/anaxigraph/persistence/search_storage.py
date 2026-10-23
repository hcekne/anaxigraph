"""Contentless word index and small identity references, without copied descriptions."""

from __future__ import annotations

import json
import sqlite3
import zlib

SEARCH_CONTRACT_VERSION = "module-search-contentless-v2"
COLUMNS = (
    "repository_id",
    "snapshot_id",
    "artifact_id",
    "artifact_type",
    "path",
    "name",
    "symbols",
    "summary",
    "responsibilities",
    "contracts",
    "aliases",
    "provenance",
)
_KEY = "module_search_contract"
STATE_PREFIX = "module_search_state:"


def ensure_search_schema(connection):
    row = connection.execute("SELECT value FROM schema_meta WHERE key=?", (_KEY,)).fetchone()
    if row and row[0] == SEARCH_CONTRACT_VERSION:
        return
    connection.execute("DROP TABLE IF EXISTS module_search")
    connection.execute("DROP TABLE IF EXISTS module_search_rows")
    modern = sqlite3.sqlite_version_info >= (3, 43, 0)
    fields = ",".join(
        name + (" UNINDEXED" if index in {0, 1, 2, 3, 11} else "")
        for index, name in enumerate(COLUMNS)
    )
    options = ",contentless_delete=1" if modern else ""
    connection.execute(
        f"CREATE VIRTUAL TABLE module_search USING fts5({fields},content=''{options},tokenize='unicode61 remove_diacritics 2')"
    )
    connection.execute("""CREATE TABLE module_search_rows(
        rowid INTEGER PRIMARY KEY,repository_id INTEGER NOT NULL,snapshot_id INTEGER NOT NULL,
        artifact_id INTEGER NOT NULL,artifact_type TEXT,path TEXT,name TEXT,symbols TEXT,
        provenance TEXT,delete_payload BLOB,UNIQUE(repository_id,artifact_id))""")
    connection.execute("DELETE FROM schema_meta WHERE key LIKE ?", (STATE_PREFIX + "%",))
    connection.execute(
        "INSERT OR REPLACE INTO schema_meta VALUES (?,?)", (_KEY, SEARCH_CONTRACT_VERSION)
    )


def clear_search_cache(connection):
    """Release deterministic search pages before a bounded semantic import."""
    connection.execute("DROP TABLE IF EXISTS module_search")
    connection.execute("DROP TABLE IF EXISTS module_search_rows")
    connection.execute(
        "DELETE FROM schema_meta WHERE key=? OR key LIKE ?", (_KEY, STATE_PREFIX + "%")
    )


def delete_search_rows(connection, repository_id, artifact_ids=None):
    clause, parameters = "repository_id=?", [repository_id]
    if artifact_ids is not None:
        if not artifact_ids:
            return
        clause += " AND artifact_id IN (" + ",".join("?" for _ in artifact_ids) + ")"
        parameters.extend(artifact_ids)
    rows = connection.execute(
        "SELECT rowid,artifact_id,delete_payload FROM module_search_rows WHERE " + clause,
        parameters,
    ).fetchall()
    for row in rows:
        if row["delete_payload"] is None:
            connection.execute("DELETE FROM module_search WHERE rowid=?", (row["rowid"],))
        else:
            values = json.loads(zlib.decompress(row["delete_payload"]))
            markers = ",".join("?" for _ in COLUMNS)
            connection.execute(
                f"INSERT INTO module_search(module_search,rowid,{','.join(COLUMNS)}) VALUES ('delete',?,{markers})",
                (row["rowid"], *values),
            )
    connection.execute("DELETE FROM module_search_rows WHERE " + clause, parameters)
    return {row["artifact_id"]: row["rowid"] for row in rows}


def insert_search_rows(connection, rows, *, rowids=None):
    # SQLite before3.43 needs the exact old indexed values for its FTS delete command.
    # Keep that fallback compressed and count it as local rebuildable index storage.
    modern = sqlite3.sqlite_version_info >= (3, 43, 0)
    rowids = rowids or {}
    next_id = max(
        connection.execute("SELECT COALESCE(MAX(rowid),0) FROM module_search_rows").fetchone()[0],
        max(rowids.values(), default=0),
    )
    for values in rows:
        identifier = rowids.get(values[2])
        if identifier is None:
            next_id += 1
            identifier = next_id
        fallback = (
            None if modern else zlib.compress(json.dumps(values, separators=(",", ":")).encode())
        )
        cursor = connection.execute(
            "INSERT INTO module_search_rows(rowid,repository_id,snapshot_id,artifact_id,artifact_type,path,name,symbols,provenance,delete_payload) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (identifier, *values[:7], values[11], fallback),
        )
        markers = ",".join("?" for _ in COLUMNS)
        connection.execute(
            f"INSERT INTO module_search(rowid,{','.join(COLUMNS)}) VALUES (?,{markers})",
            (cursor.lastrowid, *values),
        )


def move_search_snapshot(connection, repository, snapshot):
    # Snapshot columns in FTS are unindexed. Its original compressed delete tuple
    # must remain unchanged until that exact token row is actually replaced.
    connection.execute(
        "UPDATE module_search_rows SET snapshot_id=? WHERE repository_id=? AND snapshot_id!=?",
        (snapshot, repository, snapshot),
    )

"""Shared, lossless cold legacy values with read-compatible SQL projections."""

from __future__ import annotations

import json
import sqlite3
from collections import OrderedDict

from anaxigraph.knowledge_schema import expand_edge_evidence
from anaxigraph.semantic_payload import (
    PAYLOAD_MARKER,
    decode_payload,
    encode_payload,
    modern_semantic_value,
    payload_reference,
)

_TABLE = """CREATE TABLE IF NOT EXISTS semantic_payloads(
    hash TEXT PRIMARY KEY, data BLOB NOT NULL, decoded_bytes INTEGER NOT NULL
)"""
_READ_TABLES = {
    "semantic_documents": "semantic_document_values",
    "semantic_claims": "semantic_claim_values",
    "semantic_taxonomies": "semantic_taxonomy_values",
    "semantic_taxonomy_nodes": "semantic_taxonomy_node_values",
    "semantic_taxonomy_memberships": "semantic_taxonomy_membership_values",
    "semantic_taxonomy_reviews": "semantic_taxonomy_review_values",
}
_FIELDS = {
    "semantic_documents": ("value_json", "supporting_evidence_json"),
    "semantic_claims": ("value_json", "supporting_evidence_json"),
    "semantic_taxonomies": ("validation_json", "facets_json", "change_json"),
    "semantic_taxonomy_nodes": (
        "description",
        "responsibility",
        "rationale",
        "evidence_json",
        "counter_evidence_json",
    ),
    "semantic_taxonomy_memberships": ("rationale", "evidence_json", "alternatives_json"),
    "semantic_taxonomy_reviews": ("issues_json", "validation_json"),
}


def register_semantic_payloads(connection: sqlite3.Connection) -> None:
    from anaxigraph.persistence.semantic_state_storage import register_semantic_state_functions

    register_semantic_state_functions(connection)
    connection.create_function(
        "anaxigraph_graph_evidence", 2, expand_edge_evidence, deterministic=True
    )
    cache: OrderedDict[str, tuple[str, int]] = OrderedDict()
    cached_bytes = 0

    def resolve(value: str | None, stored_key, data, size) -> str | None:
        nonlocal cached_bytes
        if value is None or not (key := payload_reference(value)):
            return value
        if key in cache:
            cache.move_to_end(key)
            return cache[key][0]
        if stored_key != key or data is None:
            raise ValueError("Saved semantic payload is missing")
        result = decode_payload(key, data, size)
        if size <= 64_000:
            cache[key] = (result, size)
            cached_bytes += size
            while cached_bytes > 4_000_000 or len(cache) > 128:
                _, (_, removed) = cache.popitem(last=False)
                cached_bytes -= removed
        return result

    connection.create_function("anaxigraph_semantic_value", 4, resolve, deterministic=True)


def install_semantic_payload_views(connection: sqlite3.Connection) -> None:
    connection.execute(_TABLE)
    for table, view in _READ_TABLES.items():
        columns = [row["name"] for row in connection.execute(f"PRAGMA table_info({table})")]
        if not columns:
            continue
        projections = [_payload_projection(name, _FIELDS[table]) for name in columns]
        sql = f"CREATE VIEW {view} AS SELECT {','.join(projections)} FROM {table} r"
        prior = connection.execute("SELECT sql FROM sqlite_master WHERE name=?", (view,)).fetchone()
        if prior and prior[0] == sql:
            continue
        connection.execute(f"DROP VIEW IF EXISTS {view}")
        connection.execute(sql)
    from anaxigraph.persistence.semantic_state_storage import install_semantic_state_storage

    install_semantic_state_storage(connection)


def _payload_projection(name: str, fields: tuple[str, ...]) -> str:
    value = f'r."{name}"'
    if name not in fields:
        return value
    key = (
        f"CASE WHEN json_valid({value}) THEN json_extract({value}, '$.\"$anaxigraph_payload\"') END"
    )
    data = f"(SELECT data FROM semantic_payloads WHERE hash={key})"
    size = f"(SELECT decoded_bytes FROM semantic_payloads WHERE hash={key})"
    return (
        f"CASE WHEN {key} IS NULL THEN {value} ELSE "
        f'anaxigraph_semantic_value({value},{key},{data},{size}) END AS "{name}"'
    )


def migrate_semantic_payloads(connection: sqlite3.Connection) -> dict[str, int]:
    install_semantic_payload_views(connection)
    documents = _archive_rows(connection, "semantic_documents")
    claims = _archive_rows(connection, "semantic_claims")
    archive_taxonomy_payloads(connection)
    collect_semantic_payloads(connection)
    return {"archived_documents": documents, "archived_claims": claims}


def _archive_rows(connection: sqlite3.Connection, table: str, taxonomy_id=None) -> int:
    columns = list(connection.execute(f"PRAGMA table_info({table})"))
    if not columns:
        return 0
    keys = [row["name"] for row in columns if row["pk"]]
    fields = [*keys, *_FIELDS[table]]
    if table == "semantic_documents":
        fields.append("document_kind")
    clause = ""
    parameters = ()
    if taxonomy_id is not None:
        clause = " WHERE " + ("id" if table == "semantic_taxonomies" else "taxonomy_id") + "=?"
        parameters = (taxonomy_id,)
    changed = 0
    for row in connection.execute(
        f"SELECT {','.join(fields)} FROM {table}{clause}", parameters
    ).fetchall():
        if (
            table == "semantic_documents"
            and not payload_reference(row["value_json"])
            and modern_semantic_value(row["document_kind"], row["value_json"])
        ):
            continue
        updated = False
        for field in _FIELDS[table]:
            value = row[field]
            if value is None:
                continue
            pointer = stored_semantic_value(connection, value)
            if pointer != value:
                where = " AND ".join(f'"{key}"=?' for key in keys)
                connection.execute(
                    f"UPDATE {table} SET {field}=? WHERE {where}",
                    (pointer, *(row[key] for key in keys)),
                )
                updated = True
        changed += int(updated)
    return changed


def archive_taxonomy_payloads(connection: sqlite3.Connection, taxonomy_id=None) -> int:
    """Share immutable cache text while preserving complete original decoded rows."""
    return sum(
        _archive_rows(connection, table, taxonomy_id)
        for table in _READ_TABLES
        if table.startswith("semantic_taxonom")
    )


def store_taxonomy_fields(connection: sqlite3.Connection, table: str, value: dict) -> None:
    if table.startswith("semantic_taxonom"):
        for field in _FIELDS[table]:
            if value.get(field) is not None:
                value[field] = stored_semantic_value(connection, value[field])


def stored_semantic_value(connection: sqlite3.Connection, value: str) -> str:
    if payload_reference(value) or len(value.encode()) < 256:
        return value
    key, data, size = encode_payload(value)
    pointer = json.dumps({PAYLOAD_MARKER: key}, separators=(",", ":"))
    if len(data) + len(pointer) + 96 >= size:
        return value
    connection.execute(
        "INSERT OR IGNORE INTO semantic_payloads(hash,data,decoded_bytes) VALUES (?,?,?)",
        (key, data, size),
    )
    return pointer


def collect_semantic_payloads(connection: sqlite3.Connection) -> int:
    selections = [
        f"SELECT json_extract({field}, '$.\"$anaxigraph_payload\"') FROM {table} "
        f"WHERE json_valid({field}) AND json_type({field}, '$.\"$anaxigraph_payload\"')='text'"
        for table in _READ_TABLES
        for field in _FIELDS[table]
    ]
    removed = connection.execute(
        "DELETE FROM semantic_payloads WHERE hash NOT IN (" + " UNION ".join(selections) + ")"
    ).rowcount
    from anaxigraph.persistence.semantic_state_storage import collect_semantic_states

    collect_semantic_states(connection)
    return removed


def semantic_read_table(table: str) -> str:
    return _READ_TABLES.get(table, table)

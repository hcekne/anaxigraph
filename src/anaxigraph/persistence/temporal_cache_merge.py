"""Reuse paid source identities for strictly compatible current deterministic caches."""

from __future__ import annotations

from anaxigraph.ir_codec import decode_metadata, storage_metadata

_CACHE_REFERENCES = {
    ("checkpoint_files", "file_fact_id"),
    ("snapshot_file_changes", "file_fact_id"),
    ("fact_symbols", "file_fact_id"),
    ("relationship_sets", "source_file_fact_id"),
    ("semantic_state_bindings", "file_fact_id"),
    ("graph_entities", "file_fact_id"),
}


def merge_current_fact_identities(connection, aliases, facts):
    """Keep every paid FK intact; merge only disposable, unreferenced new identities."""
    references = _references(connection)
    retained = {
        row[0]
        for row in connection.execute(
            "SELECT file_fact_id FROM checkpoint_files UNION SELECT file_fact_id "
            "FROM snapshot_file_changes WHERE file_fact_id IS NOT NULL"
        )
    }
    paid = {
        row[0]
        for row in connection.execute(
            "SELECT file_fact_id FROM semantic_documents UNION SELECT file_fact_id "
            "FROM semantic_claims UNION SELECT file_fact_id FROM semantic_jobs "
            "WHERE file_fact_id IS NOT NULL"
        )
    }
    merged = 0
    for old, (new, _path, _contract) in aliases.items():
        if old in retained or old not in paid or new in paid:
            continue
        if any(
            _has_reference(connection, table, field, new)
            for table, field in references
            if (table, field) not in _CACHE_REFERENCES
        ):
            continue
        current = connection.execute("SELECT * FROM file_facts WHERE id=?", (new,)).fetchone()
        if current is None or current["raw_hash"] != facts[old]["raw_hash"]:
            continue
        _merge_fact(connection, old, dict(current), facts[old], references)
        merged += 1
    return merged


def _references(connection):
    tables = [
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    return {
        (table, row["from"])
        for table in tables
        for row in connection.execute(f'PRAGMA foreign_key_list("{table}")')
        if row["table"] == "file_facts"
    }


def _has_reference(connection, table, field, identifier):
    return (
        connection.execute(
            f'SELECT 1 FROM "{table}" WHERE "{field}"=? LIMIT 1', (identifier,)
        ).fetchone()
        is not None
    )


def _merge_fact(connection, original_id, current, original, references):
    metadata = decode_metadata(current["metadata_json"])
    previous = decode_metadata(original["metadata_json"]).get("original_structural_identity")
    metadata["original_structural_identity"] = previous or {
        "fact_key": original["fact_key"],
        "analysis_signature": original["analysis_signature"],
        "analysis_version": decode_metadata(original["metadata_json"]).get("analysis_version"),
        "created_at": original["created_at"],
    }
    metadata["structural_cache_reindex"] = {
        "state": "current_cache_reuses_original_identity",
        "rule": "same_path_raw_hash_and_resolver_context",
        "effective_analysis_signature": current["analysis_signature"],
    }
    for table, field in sorted(references & _CACHE_REFERENCES):
        connection.execute(
            f'UPDATE "{table}" SET "{field}"=? WHERE "{field}"=?',
            (original_id, current["id"]),
        )
    connection.execute("DELETE FROM file_facts WHERE id=?", (current["id"],))
    columns = [name for name in current if name != "id"]
    current["metadata_json"] = storage_metadata(metadata)
    connection.execute(
        "UPDATE file_facts SET " + ",".join(f'"{name}"=?' for name in columns) + " WHERE id=?",
        [*(current[name] for name in columns), original_id],
    )

"""Read the existing index as portable logical rows and explicit content references."""

from __future__ import annotations

import json
from typing import Any

from anaxigraph.persistence.portable_current import (
    SEMANTIC_TABLES,
    current_rows,
    portable_file_references,
    preflight_rows,
)
from anaxigraph.persistence.portable_references import PortableReferences
from anaxigraph.persistence.portable_rows import (
    decoded_row,
    primary_columns,
    table_references,
)


def export_rows(
    connection: Any, repository_id: int, *, config: Any
) -> tuple[dict[str, Any], dict[str, Any]]:
    source = current_rows(connection, repository_id, config)
    repository = source["repositories"][0]
    root = repository["path"]
    preflight_rows(source, config.storage.record_bytes)
    rows = {table: [decoded_row(row, root) for row in items] for table, items in source.items()}
    _normalize_volatile(rows)
    references = {table: table_references(connection, table) for table in rows}
    primary = {table: primary_columns(connection, table) for table in rows}
    cached = connection.execute(
        "SELECT value FROM schema_meta WHERE key = ?", (f"portable-identities:{repository_id}",)
    ).fetchone()
    identities = PortableReferences(
        rows, references, primary, json.loads(cached[0]) if cached else {}
    )
    tables = {
        table: [identities.encode(table, row) for row in items]
        for table, items in rows.items()
        if table in SEMANTIC_TABLES
    }
    snapshot = source["snapshots"][0]
    metadata = _metadata(source, snapshot, identities)
    tables["source_files"] = [
        {"key": "source_files:" + item["fact"].split(":", 1)[1], "value": item}
        for item in portable_file_references(source, identities)
    ]
    metadata["repository"]["key"] = identities.key("repositories", rows["repositories"][0])
    metadata["contents"] = "current_understanding"
    metadata["saved_sources"] = [
        {
            "snapshot": identities.key("snapshots", row),
            "commit": row["commit_sha"],
            "branch": row["branch"],
            "fingerprint": row["content_fingerprint"],
        }
        for row in source["snapshots"]
        if row["id"] != snapshot["id"]
    ]
    selected = {
        (table, row["id"]) for table, items in source.items() for row in items if "id" in row
    }
    metadata["_cache_identities"] = {
        key: identifier
        for (table, identifier), key in identities.keys.items()
        if (table, identifier) in selected
    }
    return tables, metadata


def _normalize_volatile(rows: Any) -> None:
    documents = {row["id"]: row for row in rows["semantic_documents"]}
    for state in rows["semantic_scope_states"]:
        document = documents.get(
            state.get("context_document_id") or state.get("intrinsic_document_id")
        )
        if document:
            state["last_checked_at"] = document["created_at"]


def _metadata(source: Any, snapshot: Any, identities: Any) -> dict[str, Any]:
    if snapshot is None:
        raise ValueError("Scan the repository before saving its portable record")
    files = source["file_facts"]
    metadata = json.loads(snapshot["metadata_json"] or "{}")
    states = [
        row for row in source["semantic_scope_states"] if row["snapshot_id"] == snapshot["id"]
    ]
    return {
        "index_schema": 11,
        "repository": {
            "name": source["repositories"][0]["name"],
            "remote_url": source["repositories"][0]["remote_url"],
        },
        "source": {
            "commit": snapshot["commit_sha"],
            "branch": snapshot["branch"],
            "snapshot": identities.key("snapshots", snapshot),
            "fingerprint": snapshot["content_fingerprint"],
            "analysis_signature": metadata.get("analysis_signature"),
            "file_facts": len(files),
        },
        "readiness": {
            scope: {
                "current": sum(
                    row["status"] == "current" for row in states if row["scope_type"] == scope
                ),
                "total": sum(row["scope_type"] == scope for row in states),
            }
            for scope in sorted({row["scope_type"] for row in states})
        },
    }

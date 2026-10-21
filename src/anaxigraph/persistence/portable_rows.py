"""Select repository-owned durable facts; never transfer worker leases or credentials."""

from __future__ import annotations

import json
from typing import Any

REPOSITORY_TABLES = (
    "snapshots",
    "artifacts",
    "groups",
    "findings",
    "architecture_rules",
    "semantic_documents",
    "semantic_scope_states",
    "semantic_taxonomies",
    "git_changes",
    "relationship_sets",
    "snapshot_checkpoints",
)
RELATED_TABLES = {
    "file_facts": ("artifact_id", "artifacts"),
    "semantic_claims": ("file_fact_id", "file_facts"),
    "fact_symbols": ("file_fact_id", "file_facts"),
    "relationship_edges": ("relationship_set_id", "relationship_sets"),
    "snapshot_file_changes": ("snapshot_id", "snapshots"),
    "snapshot_relationship_changes": ("snapshot_id", "snapshots"),
    "metrics": ("snapshot_id", "snapshots"),
    "coverage_measurements": ("snapshot_id", "snapshots"),
    "finding_occurrences": ("snapshot_id", "snapshots"),
    "semantic_taxonomy_nodes": ("taxonomy_id", "semantic_taxonomies"),
    "semantic_taxonomy_memberships": ("taxonomy_id", "semantic_taxonomies"),
    "semantic_taxonomy_reviews": ("taxonomy_id", "semantic_taxonomies"),
    "checkpoint_files": ("checkpoint_snapshot_id", "snapshots"),
    "checkpoint_relationships": ("checkpoint_snapshot_id", "snapshots"),
}
TABLES = ("repositories", *REPOSITORY_TABLES, *RELATED_TABLES, "semantic_jobs", "analysis_runs")
EXTRA_REFERENCES = {
    "repositories": {"current_snapshot_id": "snapshots"},
    "snapshots": {"base_snapshot_id": "snapshots"},
}


def durable_rows(connection: Any, repository_id: int) -> dict[str, list[dict[str, Any]]]:
    result = {"repositories": _query(connection, "repositories", "id = ?", (repository_id,))}
    for table in REPOSITORY_TABLES:
        result[table] = _query(connection, table, "repository_id = ?", (repository_id,))
    for table, (column, parent) in RELATED_TABLES.items():
        identifiers = [row["id"] for row in result[parent]]
        result[table] = _selected(connection, table, column, identifiers)
    result["metrics"] = [
        row for row in result["metrics"] if row["entity_type"] != "semantic_plan_transaction"
    ]
    result["semantic_jobs"] = _query(
        connection, "semantic_jobs", "repository_id = ? AND status = 'completed'", (repository_id,)
    )
    result["analysis_runs"] = _query(
        connection,
        "analysis_runs",
        "repository_id = ? AND run_type IN ('scan', 'agent_context', 'watch', 'up') "
        "AND status IN ('completed', 'completed_with_errors')",
        (repository_id,),
    )
    for row in result["semantic_jobs"]:
        for field in ("worker_id", "lease_expires_at", "lease_token_hash", "error"):
            row[field] = None
    return result


def table_references(connection: Any, table: str) -> dict[str, str]:
    references = {
        row["from"]: "snapshots" if row["to"] == "snapshot_id" else row["table"]
        for row in connection.execute(f'PRAGMA foreign_key_list("{table}")')
        if row["to"] in {"id", "snapshot_id"}
    }
    return {**references, **EXTRA_REFERENCES.get(table, {})}


def primary_columns(connection: Any, table: str) -> list[str]:
    columns = list(connection.execute(f'PRAGMA table_info("{table}")'))
    return [row["name"] for row in sorted(columns, key=lambda row: row["pk"]) if row["pk"]]


def clean_runtime(value: Any, root: str) -> Any:
    if isinstance(value, list):
        return [clean_runtime(item, root) for item in value]
    if isinstance(value, dict):
        return {
            key: clean_runtime(item, root)
            for key, item in value.items()
            if key
            not in {
                "worker_id",
                "lease_token",
                "lease_token_hash",
                "lease_expires_at",
                "pid",
                "process_id",
                "log_path",
                "command",
                "config_path",
            }
        }
    return value.replace(root, "${CHECKOUT}") if isinstance(value, str) else value


def decoded_row(row: dict[str, Any], root: str) -> dict[str, Any]:
    result = {}
    for key, value in row.items():
        if key.endswith("_json") and isinstance(value, str):
            value = json.loads(value)
        result[key] = clean_runtime(value, root)
    return result


def _query(connection: Any, table: str, where: str, parameters: Any) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in connection.execute(f'SELECT * FROM "{table}" WHERE {where}', parameters)
    ]


def _selected(
    connection: Any, table: str, column: str, identifiers: list[int]
) -> list[dict[str, Any]]:
    rows = []
    for offset in range(0, len(identifiers), 500):
        chunk = identifiers[offset : offset + 500]
        rows.extend(
            _query(connection, table, f"{column} IN ({','.join('?' for _ in chunk)})", chunk)
        )
    return rows

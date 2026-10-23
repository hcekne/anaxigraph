"""Portable content identities and explicit references for the existing index schema."""

from __future__ import annotations

from typing import Any

from anaxigraph.portable_paths import record_hash

IDENTITY_FIELDS = {
    "semantic_claims": ("file_fact_id", "claim_type", "prompt_version", "created_at"),
    "fact_symbols": ("file_fact_id", "symbol_type", "qualified_name", "start_line", "end_line"),
    "relationship_edges": (
        "relationship_set_id",
        "target_artifact_id",
        "target_external",
        "relationship_type",
        "source_line",
        "evidence",
    ),
    "metrics": ("snapshot_id", "entity_type", "entity_id", "name", "value"),
    "coverage_measurements": ("snapshot_id", "artifact_id", "relationship_edge_id", "provider"),
    "analysis_runs": ("snapshot_id", "run_type", "started_at"),
    "repositories": ("name",),
    "snapshots": ("content_fingerprint",),
    "artifacts": ("canonical_path",),
    "file_facts": ("fact_key",),
    "relationship_sets": ("set_key",),
    "findings": ("stable_key",),
    "groups": ("name", "source"),
    "architecture_rules": ("rule_id",),
    "semantic_documents": (
        "snapshot_id",
        "scope_type",
        "scope_key",
        "document_kind",
        "input_hash",
        "created_at",
    ),
    "semantic_taxonomies": ("snapshot_id", "input_hash"),
    "git_changes": ("commit_sha", "path"),
    "semantic_jobs": (
        "snapshot_id",
        "scope_type",
        "scope_key",
        "job_kind",
        "input_hash",
        "completed_at",
    ),
}
JSON_REFERENCES = {
    "verified_against_snapshot_id": "snapshots",
    "repository_id": "repositories",
    "snapshot_id": "snapshots",
    "base_snapshot_id": "snapshots",
    "from_snapshot_id": "snapshots",
    "to_snapshot_id": "snapshots",
    "document_id": "semantic_documents",
    "document_ids": "semantic_documents",
    "intrinsic_document_id": "semantic_documents",
    "context_document_id": "semantic_documents",
    "candidate_document_id": "semantic_documents",
    "final_document_id": "semantic_documents",
    "assessment_document_id": "semantic_documents",
    "review_document_id": "semantic_documents",
    "adjudication_document_id": "semantic_documents",
    "comparison_document_id": "semantic_documents",
    "proposal_document_ids": "semantic_documents",
    "functional_brief_document_id": "semantic_documents",
    "parent_proposal_document_ids": "semantic_documents",
    "comparison_document_ids": "semantic_documents",
    "artifact_id": "artifacts",
    "file_fact_id": "file_facts",
    "job_id": "semantic_jobs",
    "job_ids": "semantic_jobs",
    "taxonomy_id": "semantic_taxonomies",
    "relationship_edge_id": "relationship_edges",
}


class PortableReferences:
    def __init__(self, rows: Any, references: Any, primary: Any, cached: Any = None) -> None:
        self.rows, self.references, self.primary = rows, references, primary
        self.by_id = {
            table: {row["id"]: row for row in items if "id" in row} for table, items in rows.items()
        }
        self.keys = {
            (key.split(":", 1)[0], int(identifier)): key
            for key, identifier in (cached or {}).items()
        }

    def key(self, table: str, row: dict[str, Any]) -> str:
        cache_key = (table, row.get("id"))
        if cache_key in self.keys:
            return self.keys[cache_key]
        fields = IDENTITY_FIELDS.get(table, tuple(self.primary[table]))
        identity = {field: self.reference(table, field, row.get(field)) for field in fields}
        key = f"{table}:{record_hash(identity)}"
        if row.get("id") is not None:
            self.keys[cache_key] = key
        return key

    def reference(self, table: str, column: str, value: Any) -> Any:
        parent = self.references[table].get(column)
        if parent and value is not None:
            return self.link(parent, value)
        return value

    def link(self, table: str, value: Any) -> Any:
        row = self.by_id.get(table, {}).get(value)
        return {"$ref": self.key(table, row)} if row is not None else None

    def nested(self, value: Any, field: str = "") -> Any:
        parent = JSON_REFERENCES.get(field)
        if parent and isinstance(value, int):
            return self.link(parent, value)
        if isinstance(value, list):
            return [self.nested(item, field) for item in value]
        if isinstance(value, dict):
            return {key: self.nested(item, key) for key, item in value.items()}
        return value

    def encode(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        key = self.key(table, row)
        result = {}
        for column, value in row.items():
            if column == "id":
                continue
            value = self.nested(value) if column.endswith("_json") else value
            result[column] = self.reference(table, column, value)
        if table in {"file_facts", "relationship_sets"}:
            result["fact_key" if table == "file_facts" else "set_key"] = key
        if row.get("scope_type") in {"repository", "taxonomy"}:
            prefix = str(row.get("repository_id"))
            if row.get("scope_key") == prefix:
                result["scope_key"] = "${REPOSITORY}"
            elif str(row.get("scope_key", "")).startswith(prefix + ":review:"):
                result["scope_key"] = "${REPOSITORY}" + row["scope_key"][len(prefix) :]
        return {"key": key, "value": result}

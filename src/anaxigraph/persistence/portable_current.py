"""Select present understanding, never a dump of historical structural SQL caches."""

from __future__ import annotations

import json
from typing import Any

from anaxigraph.persistence.portable_rows import _query, _selected
from anaxigraph.persistence.review_identity import normalize_review_export
from anaxigraph.persistence.temporal_reconstruction import reconstruct_files
from anaxigraph.portable_text import concise_module, filter_excluded

SEMANTIC_TABLES = (
    "semantic_documents",
    "semantic_scope_states",
    "semantic_jobs",
    "semantic_taxonomies",
    "semantic_taxonomy_nodes",
    "semantic_taxonomy_memberships",
    "semantic_taxonomy_reviews",
)


def current_rows(connection: Any, repository_id: int, config: Any) -> dict[str, Any]:
    repository = _query(connection, "repositories", "id = ?", (repository_id,))[0]
    snapshot_id = repository["current_snapshot_id"]
    if snapshot_id is None:
        raise ValueError("Scan the repository before saving its portable record")
    files = [row for row in current_file_evidence(connection, snapshot_id, config)]
    artifacts = [row["artifact_id"] for row in files]
    facts = [row["file_fact_id"] for row in files]
    result = {
        "repositories": [repository],
        "snapshots": _query(connection, "snapshots", "id = ?", (snapshot_id,)),
        "artifacts": _selected(connection, "artifacts", "id", artifacts),
        "file_facts": _selected(
            connection,
            "file_facts",
            "id",
            facts,
            columns="id,artifact_id,fact_key,raw_hash,analysis_signature",
        ),
    }
    result["snapshots"][0]["base_snapshot_id"] = None
    eligible = [row for row in files if config.semantic.includes_path(row["path"])]
    allowed = {row["artifact_id"] for row in eligible}
    _semantic_rows(connection, result, snapshot_id, allowed)
    _reuse_file_understanding(connection, repository_id, snapshot_id, eligible, result)
    _selected_reviews(connection, repository_id, snapshot_id, result)
    _validate_saved_prompt(connection, result, config.semantic.prompt_version)
    _select_documents(connection, result, snapshot_id, allowed, config)
    normalize_review_export(connection, result, config.semantic.prompt_version)
    return result


def _validate_saved_prompt(connection: Any, result: Any, prompt: str) -> None:
    fields = ("intrinsic_document_id", "context_document_id")
    identifiers = {
        row[field] for row in result["semantic_scope_states"] for field in fields if row.get(field)
    }
    versions = {
        row["id"]: row["prompt_version"]
        for row in _selected(
            connection, "semantic_documents", "id", sorted(identifiers), columns="id,prompt_version"
        )
    }
    for state in result["semantic_scope_states"]:
        if (
            state.get("intrinsic_document_id")
            and versions.get(state["intrinsic_document_id"]) != prompt
        ):
            state.update(intrinsic_document_id=None, context_document_id=None, status="stale")
        if (
            state.get("context_document_id")
            and versions.get(state["context_document_id"]) != prompt
        ):
            state["status"] = "stale"
            if state["scope_type"] == "module":
                state["context_document_id"] = None


def current_file_evidence(
    connection: Any, snapshot_id: int, config: Any = None
) -> list[dict[str, Any]]:
    placements = {
        key: row
        for key, row in reconstruct_files(connection, snapshot_id).items()
        if config is None or not config.is_ignored(row["path"])
    }
    facts = _selected(
        connection,
        "file_facts",
        "id",
        [row["file_fact_id"] for row in placements.values()],
        columns="id,artifact_id,fact_key,raw_hash,analysis_signature",
    )
    return [
        {**row, "file_fact_id": row["id"], "path": placements[row["artifact_id"]]["path"]}
        for row in facts
    ]


def _reuse_file_understanding(
    connection: Any, repository_id: int, snapshot_id: int, files: Any, result: Any
) -> None:
    current = {row["artifact_id"]: row for row in files}
    seen = {
        row["artifact_id"]
        for row in result["semantic_scope_states"]
        if row["scope_type"] == "module"
    }
    rows = connection.execute(
        "SELECT s.*,f.raw_hash,f.analysis_signature FROM semantic_scope_states s JOIN file_facts f ON s.file_fact_id=f.id JOIN semantic_documents d ON d.id=s.intrinsic_document_id AND d.input_hash=s.intrinsic_input_hash WHERE s.repository_id=? AND s.scope_type='module' ORDER BY s.snapshot_id DESC",
        (repository_id,),
    )
    for row in rows:
        identifier = row["artifact_id"]
        file = current.get(identifier)
        if (
            identifier in seen
            or file is None
            or file["raw_hash"] != row["raw_hash"]
            or file["analysis_signature"] != row["analysis_signature"]
        ):
            continue
        state = {
            key: row[key] for key in row.keys() if key not in {"raw_hash", "analysis_signature"}
        }
        state.update(
            snapshot_id=snapshot_id,
            file_fact_id=file["file_fact_id"],
            status="intrinsic_current" if state["intrinsic_document_id"] else "stale",
        )
        result["semantic_scope_states"].append(state)
        seen.add(identifier)


def _semantic_rows(connection: Any, result: Any, snapshot_id: int, allowed: set[int]) -> None:
    for table in SEMANTIC_TABLES[:4]:
        result[table] = _snapshot_semantics(connection, table, snapshot_id, allowed)
    result["semantic_taxonomies"] = sorted(
        result["semantic_taxonomies"], key=lambda row: row["id"]
    )[-2:]
    result["semantic_scope_states"] = [
        row
        for row in result["semantic_scope_states"]
        if row.get("intrinsic_document_id")
        or row.get("context_document_id")
        or (row["scope_type"] != "module" and row.get("interface_hash"))
    ]
    _validate_file_states(result)
    # Retain completed batch results for interrupted reviews, not queue payloads or workers.
    result["semantic_jobs"] = [
        row for row in result["semantic_jobs"] if row["status"] == "completed"
    ]
    for job in result["semantic_jobs"]:
        for field in ("worker_id", "lease_token_hash", "lease_expires_at", "error"):
            job[field] = None
    taxonomy_ids = [row["id"] for row in result["semantic_taxonomies"]]
    for table in SEMANTIC_TABLES[4:]:
        result[table] = _selected(connection, table, "taxonomy_id", taxonomy_ids)
    result["semantic_taxonomy_memberships"] = [
        row for row in result["semantic_taxonomy_memberships"] if row["artifact_id"] in allowed
    ]


def _validate_file_states(result: Any) -> None:
    for state in result["semantic_scope_states"]:
        if state["scope_type"] == "module" and state["status"] != "current":
            state["context_document_id"] = None
            if state["status"] in {"pending_intrinsic", "failed_intrinsic", "stale"}:
                state["intrinsic_document_id"] = None


def _snapshot_semantics(
    connection: Any, table: str, snapshot_id: int, allowed: set[int]
) -> list[Any]:
    if table == "semantic_taxonomies":
        return _query(connection, table, "snapshot_id = ?", (snapshot_id,))
    where = "snapshot_id = ?"
    if table == "semantic_documents":
        where += " AND id IN (SELECT MAX(id) FROM semantic_documents WHERE snapshot_id = ? GROUP BY scope_type,scope_key,document_kind)"
    parameters = (snapshot_id, snapshot_id) if table == "semantic_documents" else (snapshot_id,)
    rows = _query(
        connection, table, where + " AND artifact_id IS NULL AND scope_type != 'module'", parameters
    )
    identifiers = sorted(allowed)
    for offset in range(0, len(identifiers), 500):
        chunk = identifiers[offset : offset + 500]
        rows.extend(
            _query(
                connection,
                table,
                where + f" AND artifact_id IN ({','.join('?' for _ in chunk)})",
                (*parameters, *chunk),
            )
        )
    return rows


def _select_documents(
    connection: Any, result: Any, snapshot_id: int, allowed: set[int], config: Any
) -> None:
    # Current states may reuse a document from an earlier snapshot. Carry just those documents,
    # binding their evidence to this frame without following previous_document_id history.
    document_ids = {
        row[field]
        for table in ("semantic_scope_states", "semantic_taxonomies")
        for row in result[table]
        for field in (
            "intrinsic_document_id",
            "context_document_id",
            "candidate_document_id",
            "final_document_id",
        )
        if row.get(field) is not None
    }
    document_ids.update(row["document_id"] for row in result["semantic_taxonomy_reviews"])
    latest = {}
    for row in sorted(result["semantic_documents"], key=lambda row: row["id"]):
        if row["scope_type"] == "module" and row["id"] not in document_ids:
            continue
        latest[(row["scope_type"], row["scope_key"], row["document_kind"])] = row
    documents = {row["id"]: row for row in latest.values()}
    documents.update(
        {
            row["id"]: row
            for row in _selected(connection, "semantic_documents", "id", sorted(document_ids))
            if row.get("artifact_id") is None or row["artifact_id"] in allowed
        }
    )
    _format_documents(result, documents, snapshot_id, config)


def _format_documents(result: Any, documents: Any, snapshot_id: int, config: Any) -> None:
    origins = {document["id"]: snapshot_id for document in documents.values()}
    for state in result["semantic_scope_states"]:
        for field in ("intrinsic_document_id", "context_document_id"):
            if state.get(field):
                origins[state[field]] = state["snapshot_id"]
    facts_by_artifact = {row["artifact_id"]: row for row in result["file_facts"]}
    for document in documents.values():
        document["snapshot_id"] = origins[document["id"]]
        document["previous_document_id"] = None
        if document.get("artifact_id") is not None:
            fact = facts_by_artifact.get(document["artifact_id"])
            if fact:
                document["file_fact_id"] = fact["id"]
    result["semantic_documents"] = list(documents.values())
    _concise_documents(result, config)


def _concise_documents(result: Any, config: Any) -> None:
    for document in result["semantic_documents"]:
        value = filter_excluded(json.loads(document["value_json"]), config)
        if document["scope_type"] == "module" and not config.semantic.detailed_reviews:
            value = concise_module(value)
        document["value_json"] = json.dumps(value, sort_keys=True)
        document["supporting_evidence_json"] = json.dumps(value.get("evidence", [])[:8])
    fields = ("scope_type", "scope_key", "input_hash")
    inputs = {tuple(row[field] for field in fields) for row in result["semantic_documents"]}
    jobs = {
        tuple(row[field] for field in (*fields, "job_kind")): row
        for row in result["semantic_jobs"]
        if tuple(row[field] for field in fields) in inputs
    }
    result["semantic_jobs"] = list(jobs.values())


def _selected_reviews(connection: Any, repository_id: int, current: int, result: Any) -> None:
    sources = connection.execute(
        "SELECT scope_type,MAX(snapshot_id) AS snapshot_id FROM semantic_scope_states WHERE repository_id=? AND scope_type IN ('architecture_plan','fresh_eyes','pattern','pattern_plan') GROUP BY scope_type",
        (repository_id,),
    ).fetchall()
    identifiers = set()
    for source in sources:
        if source["snapshot_id"] == current:
            continue
        identifiers.add(source["snapshot_id"])
        result["semantic_scope_states"].extend(
            _query(
                connection,
                "semantic_scope_states",
                "snapshot_id=? AND scope_type=?",
                (source["snapshot_id"], source["scope_type"]),
            )
        )
    result["snapshots"].extend(_selected(connection, "snapshots", "id", sorted(identifiers)))
    for snapshot in result["snapshots"]:
        snapshot["base_snapshot_id"] = None


def portable_file_references(source: Any, identities: Any) -> list[dict[str, Any]]:
    artifacts = {row["id"]: row for row in source["artifacts"]}
    return sorted(
        (
            {
                "path": artifacts[row["artifact_id"]]["canonical_path"],
                "raw_hash": row["raw_hash"],
                "analysis_signature": row["analysis_signature"],
                "artifact": identities.key("artifacts", artifacts[row["artifact_id"]]),
                "fact": identities.key("file_facts", row),
            }
            for row in source["file_facts"]
        ),
        key=lambda item: item["path"],
    )


def preflight_rows(source: Any, limit: int) -> None:
    """Bound intermediate serialization before encoding or creating any output files."""
    total = 0
    for table in SEMANTIC_TABLES:
        for row in source.get(table, []):
            total += len(json.dumps(row, ensure_ascii=True, separators=(",", ":")).encode())
            if total > limit:
                raise ValueError(
                    "Current understanding exceeds the portable record budget; previous record retained. Reduce descriptions or export fewer saved analyses."
                )

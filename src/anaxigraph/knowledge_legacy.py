"""Reuse paid module understanding by exact source identity, without rewriting originals."""

import hashlib
import json

from anaxigraph.knowledge_nodes import entity_id, sentence
from anaxigraph.semantic_freshness import is_expired

_SCHEMAS = {
    "module-dossier-v4",
    "repository-understanding-v5",
    "repository-understanding-v6",
    "repository-understanding-v7",
}


def compatible_legacy(connection, arguments, module, semantic):
    rows = connection.execute(
        """SELECT d.* FROM semantic_document_values d JOIN file_facts f ON f.id=d.file_fact_id
        WHERE d.repository_id=? AND d.scope_type='module' AND d.scope_key=?
        AND d.document_kind IN ('intrinsic','context') AND d.prompt_version=?
        AND f.raw_hash=? ORDER BY d.document_kind='intrinsic' DESC,d.id DESC""",
        (
            arguments["repository_id"],
            arguments["scope_key"],
            semantic.prompt_version,
            module["raw_hash"],
        ),
    ).fetchall()
    return next(
        (
            dict(row)
            for row in rows
            if row["schema_version"] in _SCHEMAS
            and not is_expired(row["created_at"], semantic.max_age_days)
        ),
        None,
    )


def bound_legacy(connection, arguments, module, semantic):
    state = connection.execute(
        "SELECT * FROM semantic_scope_states WHERE snapshot_id=? AND scope_type='module' "
        "AND scope_key=? AND status='current' AND file_fact_id=?",
        (arguments["snapshot_id"], arguments["scope_key"], module["file_fact_id"]),
    ).fetchone()
    if state is None:
        return None
    ids = (state["intrinsic_document_id"], state["context_document_id"])
    rows = connection.execute(
        "SELECT d.id,d.document_kind,d.input_hash,d.schema_version,d.prompt_version,d.created_at,f.raw_hash "
        "FROM semantic_documents d JOIN file_facts f ON f.id=d.file_fact_id WHERE d.id IN (?,?)",
        ids,
    ).fetchall()
    documents = {row["id"]: dict(row) for row in rows}
    for identifier, key in zip(ids, ("intrinsic_input_hash", "context_input_hash"), strict=True):
        if identifier is None:
            continue
        document = documents.get(identifier)
        if document is None or not _binding_document(document, state[key], module, semantic):
            return None
    return documents.get(ids[1]) or documents.get(ids[0])


def _binding_document(document, fingerprint, module, semantic):
    return (
        document["document_kind"] in {"intrinsic", "context"}
        and document["schema_version"] in _SCHEMAS
        and document["input_hash"] == fingerprint
        and document["raw_hash"] == module["raw_hash"]
        and document["prompt_version"] == semantic.prompt_version
        and not is_expired(document["created_at"], semantic.max_age_days)
    )


def attach_legacy(connection, snapshot, path, document):
    connection.execute(
        "UPDATE graph_entities SET annotation_id=?,annotation_selector='$' WHERE snapshot_id=? "
        "AND entity_id=? AND (annotation_id IS NOT ? OR annotation_selector!='$')",
        (document["id"], snapshot, entity_id("module", path), document["id"]),
    )


def legacy_obligations(connection, snapshot, path, *, offset=0, limit=25):
    document = _legacy_document(connection, snapshot, path)
    entries = _entries(document)
    page = entries[offset : offset + limit]
    return {
        "items": [_obligation(document, path, index, text) for index, text in page],
        "total": len(entries),
        "returned": len(page),
        "offset": offset,
        "limit": limit,
        "next_offset": offset + len(page) if offset + len(page) < len(entries) else None,
        "readiness": "legacy_reused",
        "function_scope": "unknown",
        "source_document_id": document["id"] if document else None,
    }


def legacy_node(connection, snapshot, identifier, *, detail=False):
    parsed = _legacy_identity(identifier)
    if parsed is None:
        return None
    path, position = parsed
    document = _legacy_document(connection, snapshot, path)
    text = next((text for index, text in _entries(document) if index == position), None)
    return _obligation(document, path, position, text, detail=detail) if text is not None else None


def legacy_connections(connection, snapshot, identifiers, direction, relationship_type, limit):
    if relationship_type and relationship_type != "owns_contract":
        return []
    result, documents = {}, {}
    for identifier in identifiers:
        target = _legacy_target(identifier, direction)
        if target is None:
            continue
        path, position = target
        if path not in documents:
            documents[path] = _entries(_legacy_document(connection, snapshot, path))
        entries = documents[path]
        for index, _text in entries:
            if position is None or index == position:
                edge = _ownership(path, index)
                result[edge["edge_id"]] = edge
            if len(result) >= limit:
                return list(result.values())
    return list(result.values())


def _legacy_target(identifier, direction):
    if identifier.startswith("module:"):
        return None if direction == "incoming" else (identifier[len("module:") :], None)
    parsed = _legacy_identity(identifier)
    return None if direction == "outgoing" else parsed


def _legacy_document(connection, snapshot, path):
    row = connection.execute(
        """SELECT d.*,g.area,g.subsystem,g.language,g.properties_json AS owner_properties
        FROM graph_entities g JOIN semantic_document_values d ON d.id=g.annotation_id
        WHERE g.snapshot_id=? AND g.path=? AND g.kind='module'
        AND d.document_kind IN ('intrinsic','context')""",
        (snapshot, path),
    ).fetchone()
    return dict(row) if row else None


def _entries(document):
    if document is None:
        return []
    value = json.loads(document["value_json"])
    return [
        (index, text)
        for index, text in enumerate(value.get("public_contracts") or [])
        if isinstance(text, str)
    ]


def _legacy_identity(identifier):
    if not identifier.startswith("contract:"):
        return None
    path, marker, suffix = identifier[len("contract:") :].rpartition("#legacy-")
    if not marker or not suffix.isdigit():
        return None
    return path, int(suffix)


def _obligation(document, path, index, text, *, detail=False):
    overview = sentence(text)
    annotation = {
        key: document.get(key)
        for key in (
            "model",
            "provider",
            "created_at",
            "confidence",
            "executor_id",
            "executor_model",
        )
    }
    annotation.update(document_id=document["id"], verification="unverified")
    result = {
        "id": entity_id("contract", path, f"legacy-{index}"),
        "kind": "contract",
        "label": overview[:100] or "Undescribed legacy obligation",
        "overview": overview[:240],
        "path": path,
        "parent_id": entity_id("module", path),
        "readiness": "legacy_reused",
        "reference": False,
        "language": document["language"],
        "placement": {"area": document["area"], "subsystem": document["subsystem"]},
        "architecture_layers": json.loads(document["owner_properties"]).get(
            "architecture_layers", {}
        ),
        "metrics": {"fan_in": 0, "fan_out": 0},
        "properties": {"legacy_obligation": True, "function_scope": "unknown"},
        "provenance": {
            "method": "legacy_inference",
            "verification": "unverified",
            "function_scope": "unknown",
            "annotation": annotation,
        },
    }
    if detail:
        result["detail"] = text
        result["properties"]["statement"] = text
    return result


def _ownership(path, index):
    source, target = entity_id("module", path), entity_id("contract", path, f"legacy-{index}")
    key = hashlib.sha256(
        json.dumps([source, target, "owns_contract"], separators=(",", ":")).encode()
    ).hexdigest()[:24]
    return {
        "edge_id": key,
        "source_id": source,
        "target_id": target,
        "relationship_type": "owns_contract",
        "confidence": 1.0,
        "resolution": "resolved_internal",
        "evidence_json": "[]",
        "provenance_json": json.dumps({"method": "legacy_inference", "function_scope": "unknown"}),
    }

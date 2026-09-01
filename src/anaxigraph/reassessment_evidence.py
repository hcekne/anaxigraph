"""Bounded before/after evidence for continuous architecture reassessment."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Mapping

from anaxigraph.persistence.snapshot_catalog import resolve_snapshot
from anaxigraph.persistence.temporal_hashing import analysis_signature
from anaxigraph.persistence.temporal_reads import snapshot_files, snapshot_relationship_edges
from anaxigraph.relationships import resolution_status

REASSESSMENT_EVIDENCE_VERSION = "reassessment-evidence-v1"
_MAX_LINEAGE_DEPTH = 2_500


def reassessment_evidence(
    database: Any,
    repository_id: int,
    *,
    baseline_snapshot_id: int | None = None,
    target_snapshot_id: int | None = None,
) -> dict[str, Any]:
    """Read one compatible durable comparison without mutating the AnaxiIndex."""

    with database.connect() as connection:
        target = resolve_snapshot(connection, repository_id, target_snapshot_id)
        if target is None:
            return _empty(repository_id)
        baseline = _baseline(connection, repository_id, target, baseline_snapshot_id)
        target_value = _snapshot_identity(target)
        if baseline is None:
            return {
                **_empty(repository_id),
                "target_snapshot": target_value,
                "baseline_selection": "unavailable",
            }
        return _comparison_packet(
            connection,
            repository_id,
            baseline,
            target,
            requested=baseline_snapshot_id is not None,
        )


def _comparison_packet(
    connection: sqlite3.Connection,
    repository_id: int,
    baseline: Mapping[str, Any],
    target: Mapping[str, Any],
    *,
    requested: bool,
) -> dict[str, Any]:
    before = _snapshot_state(connection, int(baseline["id"]))
    after = _snapshot_state(connection, int(target["id"]))
    changes = _module_changes(before["files"], after["files"])
    affected = _affected_context({int(item["artifact_id"]) for item in changes}, before, after)
    return {
        "contract_version": REASSESSMENT_EVIDENCE_VERSION,
        "repository_id": repository_id,
        "baseline_snapshot": _snapshot_identity(baseline),
        "target_snapshot": _snapshot_identity(target),
        "baseline_selection": "requested" if requested else "last_compatible_lineage",
        "module_changes": changes,
        "relationship_changes": _relationship_changes(before["edges"], after["edges"]),
        "affected_context": affected,
        "semantic_scopes": _semantic_scopes(connection, int(target["id"]), changes, affected),
        "finding_changes": _finding_changes(connection, int(baseline["id"]), int(target["id"])),
        "work": _work(before, after, changes, affected),
    }


def _work(
    before: dict[str, Any],
    after: dict[str, Any],
    changes: list[dict[str, Any]],
    affected: dict[str, Any],
) -> dict[str, int]:
    return {
        "baseline_files": len(before["files"]),
        "target_files": len(after["files"]),
        "changed_modules": len(changes),
        "affected_context_modules": len(affected["module_paths"]),
        "affected_groups": len(affected["groups"]),
    }


def _empty(repository_id: int) -> dict[str, Any]:
    return {
        "contract_version": REASSESSMENT_EVIDENCE_VERSION,
        "repository_id": repository_id,
        "baseline_snapshot": None,
        "target_snapshot": None,
        "baseline_selection": "unavailable",
        "module_changes": [],
        "relationship_changes": {"added": [], "removed": [], "counts": {}},
        "affected_context": {"module_paths": [], "dependants": [], "groups": []},
        "semantic_scopes": {},
        "finding_changes": [],
        "work": {},
    }


def _baseline(
    connection: sqlite3.Connection,
    repository_id: int,
    target: Mapping[str, Any],
    requested: int | None,
) -> sqlite3.Row | None:
    if requested is not None:
        row = resolve_snapshot(connection, repository_id, requested)
        if row is None:
            raise ValueError("comparison snapshot does not belong to the selected repository")
        _require_compatible(row, target)
        return row
    signature = analysis_signature(str(target["metadata_json"] or "{}"))
    fingerprint = str(target["content_fingerprint"])
    current_id = target["base_snapshot_id"]
    depth = 0
    while current_id is not None and depth < _MAX_LINEAGE_DEPTH:
        row = connection.execute(
            "SELECT * FROM snapshots WHERE id = ? AND repository_id = ?",
            (int(current_id), repository_id),
        ).fetchone()
        if row is None:
            break
        if (
            analysis_signature(str(row["metadata_json"] or "{}")) == signature
            and str(row["content_fingerprint"]) != fingerprint
        ):
            return row
        current_id = row["base_snapshot_id"]
        depth += 1
    return None


def _require_compatible(baseline: Mapping[str, Any], target: Mapping[str, Any]) -> None:
    before = analysis_signature(str(baseline["metadata_json"] or "{}"))
    after = analysis_signature(str(target["metadata_json"] or "{}"))
    if before != after:
        raise ValueError(
            "comparison snapshots use different analysis contracts; choose a compatible snapshot"
        )


def _snapshot_identity(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: row[key]
        for key in (
            "id",
            "commit_sha",
            "parent_commit_sha",
            "branch",
            "commit_timestamp",
            "analysis_timestamp",
            "snapshot_kind",
            "dirty",
            "content_fingerprint",
        )
    }


def _snapshot_state(connection: sqlite3.Connection, snapshot_id: int) -> dict[str, Any]:
    files = snapshot_files(connection, snapshot_id, expand_metadata=False)
    semantic = _module_semantics(connection, snapshot_id)
    by_id: dict[int, dict[str, Any]] = {}
    for item in files:
        value = dict(item)
        value["semantic"] = semantic.get(str(item["path"]))
        by_id[int(item["artifact_id"])] = value
    edges = {
        _edge_identity(edge): _edge_value(edge, by_id)
        for edge in snapshot_relationship_edges(connection, snapshot_id)
    }
    return {"files": by_id, "edges": edges}


def _module_semantics(
    connection: sqlite3.Connection, snapshot_id: int
) -> dict[str, dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT ss.scope_key, ss.status, ss.reason, ss.intrinsic_input_hash,
               ss.context_input_hash, ss.interface_hash, ss.relationship_hash,
               sd.id AS document_id, sd.value_json, sd.confidence, sd.document_kind
        FROM semantic_scope_states ss
        LEFT JOIN semantic_documents sd
          ON sd.id = COALESCE(ss.context_document_id, ss.intrinsic_document_id)
        WHERE ss.snapshot_id = ? AND ss.scope_type = 'module'
        """,
        (snapshot_id,),
    ).fetchall()
    return {
        str(row["scope_key"]): {
            "status": row["status"],
            "reason": row["reason"],
            "intrinsic_input_hash": row["intrinsic_input_hash"],
            "context_input_hash": row["context_input_hash"],
            "interface_hash": row["interface_hash"],
            "relationship_hash": row["relationship_hash"],
            "document_id": row["document_id"],
            "document_kind": row["document_kind"],
            "confidence": row["confidence"],
            "value": _object(row["value_json"]),
        }
        for row in rows
    }


def _module_changes(
    before: dict[int, dict[str, Any]], after: dict[int, dict[str, Any]]
) -> list[dict[str, Any]]:
    result = []
    for artifact_id in sorted(before.keys() | after.keys()):
        left = before.get(artifact_id)
        right = after.get(artifact_id)
        fields = _changed_fields(left, right)
        if not fields:
            continue
        result.append(
            {
                "artifact_id": artifact_id,
                "change": "added" if left is None else "removed" if right is None else "changed",
                "path": str((right or left or {}).get("path") or ""),
                "changed_fields": fields,
                "before": _module_side(left),
                "after": _module_side(right),
            }
        )
    return result


def _changed_fields(before: dict[str, Any] | None, after: dict[str, Any] | None) -> list[str]:
    if before is None or after is None:
        return ["presence"]
    fields = (
        "path",
        "raw_hash",
        "structural_hash",
        "lines_of_code",
        "complexity",
        "declared_group",
        "inferred_group",
        "public_interfaces_json",
    )
    return [key for key in fields if before.get(key) != after.get(key)]


def _module_side(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if item is None:
        return None
    semantic = item.get("semantic") or {}
    value = semantic.get("value") or {}
    return {
        "path": item.get("path"),
        "language": item.get("language"),
        "raw_hash": item.get("raw_hash"),
        "structural_hash": item.get("structural_hash"),
        "lines_of_code": int(item.get("lines_of_code") or 0),
        "complexity": float(item.get("complexity") or 0),
        "group": item.get("declared_group") or item.get("inferred_group") or "ungrouped",
        "semantic": {
            "status": semantic.get("status"),
            "reason": semantic.get("reason"),
            "document_id": semantic.get("document_id"),
            "confidence": semantic.get("confidence"),
            "summary": value.get("summary"),
            "architecture_role": value.get("architecture_role"),
            "responsibilities": value.get("responsibilities") or [],
            "placement_guidance": value.get("placement_guidance"),
            "pattern_opportunities": value.get("pattern_opportunities") or [],
            "consolidation_assessment": value.get("consolidation_assessment"),
            "dead_code_candidates": value.get("dead_code_candidates") or [],
            "risks": value.get("risks") or [],
        },
    }


def _edge_identity(edge: Mapping[str, Any]) -> tuple[Any, ...]:
    """Identify an architectural link without treating source-location churn as a new link."""

    return tuple(
        value
        for value in (
            edge.get("source_artifact_id"),
            edge.get("target_artifact_id"),
            edge.get("target_external"),
            edge.get("relationship_type"),
            resolution_status(edge),
        )
    )


def _edge_value(edge: Mapping[str, Any], files: dict[int, dict[str, Any]]) -> dict[str, Any]:
    source_id = int(edge["source_artifact_id"])
    target_id = int(edge["target_artifact_id"]) if edge["target_artifact_id"] else None
    target_path = (files.get(target_id) or {}).get("path") if target_id is not None else None
    return {
        "source_artifact_id": source_id,
        "target_artifact_id": target_id,
        "source": str((files.get(source_id) or {}).get("path") or ""),
        "target": str(target_path or edge["target_external"] or ""),
        "type": edge["relationship_type"],
        "resolution_status": resolution_status(edge),
        "confidence": float(edge["confidence"]),
        "source_line": int(edge["source_line"]),
        "evidence": edge["evidence"],
    }


def _relationship_changes(
    before: dict[tuple[Any, ...], dict[str, Any]],
    after: dict[tuple[Any, ...], dict[str, Any]],
) -> dict[str, Any]:
    added = [after[key] for key in sorted(after.keys() - before.keys(), key=str)]
    removed = [before[key] for key in sorted(before.keys() - after.keys(), key=str)]
    return {
        "added": added[:100],
        "removed": removed[:100],
        "counts": {
            "added": len(added),
            "removed": len(removed),
            "returned": min(100, len(added)) + min(100, len(removed)),
            "omitted": max(0, len(added) - 100) + max(0, len(removed) - 100),
        },
    }


def _affected_context(
    changed_ids: set[int], before: dict[str, Any], after: dict[str, Any]
) -> dict[str, Any]:
    paths: set[str] = set()
    dependants: set[str] = set()
    groups: set[str] = set()
    for state in (before, after):
        for artifact_id in changed_ids:
            item = state["files"].get(artifact_id)
            if item:
                paths.add(str(item["path"]))
                groups.add(
                    str(item.get("declared_group") or item.get("inferred_group") or "ungrouped")
                )
        for edge in state["edges"].values():
            source_id = int(edge["source_artifact_id"])
            target_id = edge["target_artifact_id"]
            if source_id in changed_ids or target_id in changed_ids:
                paths.update(value for value in (edge["source"], edge["target"]) if value)
            if target_id in changed_ids and edge["source"]:
                dependants.add(str(edge["source"]))
    return {
        "module_paths": sorted(paths),
        "dependants": sorted(dependants),
        "groups": sorted(groups),
    }


def _semantic_scopes(
    connection: sqlite3.Connection,
    snapshot_id: int,
    changes: list[dict[str, Any]],
    affected: dict[str, Any],
) -> dict[str, Any]:
    paths = set(affected["module_paths"])
    rows = connection.execute(
        "SELECT scope_type, scope_key, status, reason FROM semantic_scope_states WHERE snapshot_id = ?",
        (snapshot_id,),
    ).fetchall()
    selected = [
        dict(row)
        for row in rows
        if (row["scope_type"] == "module" and row["scope_key"] in paths)
        or (row["scope_type"] == "group" and row["scope_key"] in affected["groups"])
        or row["scope_type"] == "repository"
    ]
    changed_paths = {str(item["path"]) for item in changes}
    return {
        "changed_modules": sorted(changed_paths),
        "affected_modules": sorted(paths - changed_paths),
        "affected_groups": list(affected["groups"]),
        "states": selected,
        "state_counts": _state_counts(selected),
    }


def _state_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        key = f"{row['scope_type']}:{row['status']}"
        result[key] = result.get(key, 0) + 1
    return dict(sorted(result.items()))


def _finding_changes(
    connection: sqlite3.Connection, baseline_snapshot_id: int, target_snapshot_id: int
) -> list[dict[str, Any]]:
    before = _findings_at(connection, baseline_snapshot_id)
    after = _findings_at(connection, target_snapshot_id)
    result = []
    for key in sorted(before.keys() | after.keys()):
        left = before.get(key)
        right = after.get(key)
        if left is not None and right is not None:
            continue
        item = dict(right or left or {})
        item["transition"] = "introduced" if right is not None else "resolved"
        result.append(item)
    return result


def _findings_at(connection: sqlite3.Connection, snapshot_id: int) -> dict[str, dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT f.* FROM finding_occurrences occurrence
        JOIN findings f ON f.id = occurrence.finding_id
        WHERE occurrence.snapshot_id = ?
        """,
        (snapshot_id,),
    ).fetchall()
    return {str(row["stable_key"]): _finding(row) for row in rows}


def _finding(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "stable_key": row["stable_key"],
        "finding_type": row["finding_type"],
        "severity": row["severity"],
        "confidence": float(row["confidence"]),
        "summary": row["summary"],
        "explanation": row["explanation"],
        "affected_artifacts": _list(row["affected_artifacts_json"]),
        "evidence": _list(row["evidence_json"]),
        "recommended_action": row["recommended_action"],
        "source": row["source"],
        "status": row["status"],
        "first_snapshot_id": int(row["first_snapshot_id"]),
        "last_snapshot_id": int(row["last_snapshot_id"]),
    }


def _object(value: Any) -> dict[str, Any]:
    try:
        decoded = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _list(value: Any) -> list[Any]:
    try:
        decoded = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    return decoded if isinstance(decoded, list) else []

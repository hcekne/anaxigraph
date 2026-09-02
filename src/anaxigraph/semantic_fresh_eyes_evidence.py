"""Evidence projections and stable identities for the fresh-eyes recipe."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from anaxigraph.architecture_charter_contract import CAPABILITY_BRIEF_VERSION
from anaxigraph.persistence.semantic_evidence import semantic_inventory
from anaxigraph.semantic_fresh_eyes_contract import (
    FRESH_EYES_PROTOCOL_VERSION,
    fresh_eyes_plan_options,
    semantic_digest,
    semantic_input_hash,
)
from anaxigraph.semantic_request_support import compact_dossier


def current_system_evidence(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
    charter: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    taxonomy = _current_taxonomy(connection, snapshot_id)
    groups = _scope_documents(connection, snapshot_id, "group", 30)
    modules = _scope_documents(connection, snapshot_id, "module", 80)
    patterns = _scope_documents(connection, snapshot_id, "pattern", 30)
    relationships = _relationship_evidence(connection, snapshot_id)
    findings = _finding_evidence(connection, repository_id, snapshot_id)
    history = _history_evidence(connection, repository_id)
    current = {
        "architecture_charter": charter["value"],
        "responsibility_map": taxonomy["value"] if taxonomy else None,
        "area_summaries": [_compact_scope(item) for item in groups],
        "module_dossiers": [_compact_scope(item) for item in modules],
        "pattern_reviews": [_compact_scope(item) for item in patterns],
        "dependency_evidence": relationships,
        "active_findings": findings,
        "recent_history": history,
    }
    manifest = {
        "snapshot_id": snapshot_id,
        "charter": document_identity(charter),
        "taxonomy": document_identity(taxonomy) if taxonomy else None,
        "groups": [document_identity(item) for item in groups],
        "modules": [document_identity(item) for item in modules],
        "patterns": [document_identity(item) for item in patterns],
        "relationships": {
            "fingerprint": semantic_digest(relationships),
            "included": len(relationships),
        },
        "findings": [item["stable_key"] for item in findings],
        "history": {
            "fingerprint": semantic_digest(history),
            "included": len(history),
        },
    }
    return current, manifest


def current_charter(connection: sqlite3.Connection, snapshot_id: int) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT sd.* FROM semantic_scope_states ss
        JOIN semantic_documents sd ON sd.id = ss.context_document_id
        WHERE ss.snapshot_id = ? AND ss.scope_type = 'repository' AND ss.status = 'current'
        LIMIT 1
        """,
        (snapshot_id,),
    ).fetchone()
    return parsed_document(dict(row)) if row else None


def review_context(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    snapshot_id: int,
    plan: dict[str, Any],
    semantic: Any,
    retry_failed: bool,
) -> dict[str, Any] | None:
    charter = current_charter(connection, snapshot_id)
    if charter is None:
        return None
    brief = dict(charter["value"].get("capability_brief") or {})
    if brief.get("contract_version") != CAPABILITY_BRIEF_VERSION:
        return None
    capability_identity = capability_fingerprint(brief, semantic.prompt_version)
    proposal_count, review_generation = fresh_eyes_plan_options(plan)
    return {
        "repository_id": repository_id,
        "snapshot_id": snapshot_id,
        "proposal_count": proposal_count,
        "review_generation": review_generation,
        "charter": charter,
        "brief": brief,
        "capability_fingerprint": capability_identity,
        "capability_changed": _capability_changed(
            connection, repository_id, snapshot_id, capability_identity
        ),
        "semantic": semantic,
        "retry_failed": retry_failed,
    }


def parsed_document(document: dict[str, Any]) -> dict[str, Any]:
    result = dict(document)
    if "value" not in result:
        result["value"] = json.loads(result.get("value_json") or "{}")
    return result


def document_identity(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "scope": document.get("scope_key"),
        "kind": document.get("document_kind"),
        "input_hash": document.get("input_hash"),
        "intent_fingerprint": document.get("intent_fingerprint"),
        "provider": document.get("provider"),
        "model": document.get("model"),
        "executor_id": document.get("executor_id"),
        "executor_model": document.get("executor_model"),
    }


def capability_fingerprint(brief: dict[str, Any], prompt_version: str) -> str:
    return semantic_input_hash(
        "fresh-eyes-capability-v1",
        prompt_version,
        {"capability_brief": brief, "protocol": FRESH_EYES_PROTOCOL_VERSION},
    )


def reference_fingerprint(proposals: list[dict[str, Any]], adjudication: dict[str, Any]) -> str:
    return semantic_digest(
        {
            "proposals": [document_identity(item) for item in proposals],
            "adjudication": document_identity(adjudication),
        }
    )


def comparison_inputs(
    connection: sqlite3.Connection, context: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], str]:
    current_system, current_manifest = current_system_evidence(
        connection,
        context["repository_id"],
        context["snapshot_id"],
        context["charter"],
    )
    comparison_fingerprint = semantic_digest(
        {
            "reference_fingerprint": context["reference_fingerprint"],
            "current_system": current_manifest,
        }
    )
    manifest = {
        "protocol": FRESH_EYES_PROTOCOL_VERSION,
        "stage": "as_built_comparison",
        "review_generation": context["review_generation"],
        "reference_fingerprint": context["reference_fingerprint"],
        "comparison_fingerprint": comparison_fingerprint,
        "current_system": current_manifest,
        "included": [
            "reference_design",
            "current_charter",
            "responsibility_map",
            "area_summaries",
            "module_dossiers",
            "patterns",
            "dependency_evidence",
            "findings",
            "history",
        ],
    }
    return current_system, manifest, comparison_fingerprint


def proposal_manifest(
    slot: str, capability_identity: str, review_generation: int
) -> dict[str, Any]:
    return {
        "protocol": FRESH_EYES_PROTOCOL_VERSION,
        "stage": "clean_sheet_proposal",
        "review_generation": review_generation,
        "slot": slot,
        "capability_fingerprint": capability_identity,
        "included": ["capability_brief", "external_constraints", "quality_priorities"],
        "withheld": list(proposal_boundary()["withheld"]),
    }


def proposal_boundary() -> dict[str, Any]:
    return {
        "mode": "implementation_blind",
        "withheld": (
            "repository_paths",
            "module_names",
            "current_frameworks",
            "current_responsibility_map",
            "current_findings",
            "repository_history",
            "other_proposals_during_proposal_stage",
        ),
        "caveat": (
            "AnaxiGraph proves only the supplied packet; unrelated model context cannot be proven absent."
        ),
    }


def external_constraints(brief: dict[str, Any]) -> dict[str, Any]:
    return {
        "non_functional_requirements": brief.get("non_functional_requirements") or [],
        "compatibility_obligations": brief.get("compatibility_obligations") or [],
        "non_goals": brief.get("non_goals") or [],
        "quality_priorities": [
            "architectural coherence",
            "operational simplicity",
            "safe extension",
            "minimum justified concepts",
        ],
    }


def _scope_documents(
    connection: sqlite3.Connection, snapshot_id: int, scope_type: str, limit: int
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT sd.* FROM semantic_scope_states ss
        JOIN semantic_documents sd ON sd.id = COALESCE(ss.context_document_id,
                                                        ss.intrinsic_document_id)
        WHERE ss.snapshot_id = ? AND ss.scope_type = ? AND ss.status = 'current'
        ORDER BY ss.scope_key LIMIT ?
        """,
        (snapshot_id, scope_type, limit),
    ).fetchall()
    return [parsed_document(dict(row)) for row in rows]


def _capability_changed(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
    capability: str,
) -> bool:
    row = connection.execute(
        """
        SELECT intrinsic_input_hash FROM semantic_scope_states
        WHERE repository_id = ? AND snapshot_id != ? AND scope_type = 'fresh_eyes'
          AND scope_key = 'plan' AND status = 'current' AND intrinsic_input_hash IS NOT NULL
        ORDER BY snapshot_id DESC LIMIT 1
        """,
        (repository_id, snapshot_id),
    ).fetchone()
    return bool(row and str(row["intrinsic_input_hash"]) != capability)


def _current_taxonomy(connection: sqlite3.Connection, snapshot_id: int) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT sd.* FROM semantic_taxonomies st
        JOIN semantic_documents sd ON sd.id = st.final_document_id
        WHERE st.snapshot_id = ? AND st.status = 'current' ORDER BY st.id DESC LIMIT 1
        """,
        (snapshot_id,),
    ).fetchone()
    return parsed_document(dict(row)) if row else None


def _finding_evidence(
    connection: sqlite3.Connection, repository_id: int, snapshot_id: int
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT stable_key, finding_type, severity, summary, recommended_action, status
        FROM findings WHERE repository_id = ? AND last_snapshot_id = ?
          AND status NOT IN ('resolved', 'dismissed')
        ORDER BY CASE severity WHEN 'error' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                 last_detected_at DESC LIMIT 40
        """,
        (repository_id, snapshot_id),
    ).fetchall()
    return [dict(row) for row in rows]


def _history_evidence(connection: sqlite3.Connection, repository_id: int) -> list[dict[str, Any]]:
    commits = connection.execute(
        """
        SELECT commit_sha, MAX(committed_at) AS committed_at, MAX(subject) AS subject,
               COUNT(*) AS changed_files,
               SUM(COALESCE(additions, 0)) AS additions,
               SUM(COALESCE(deletions, 0)) AS deletions
        FROM git_changes WHERE repository_id = ? GROUP BY commit_sha
        ORDER BY COALESCE(MAX(committed_at), '') DESC, commit_sha DESC LIMIT 12
        """,
        (repository_id,),
    ).fetchall()
    hotspots = connection.execute(
        """
        SELECT path, COUNT(*) AS change_count, MAX(committed_at) AS last_changed_at,
               SUM(COALESCE(additions, 0)) AS additions,
               SUM(COALESCE(deletions, 0)) AS deletions
        FROM git_changes WHERE repository_id = ? GROUP BY path
        ORDER BY COUNT(*) DESC, COALESCE(MAX(committed_at), '') DESC, path LIMIT 20
        """,
        (repository_id,),
    ).fetchall()
    return [{"evidence_kind": "recent_commit", **dict(row)} for row in commits] + [
        {"evidence_kind": "high_churn_module", **dict(row)} for row in hotspots
    ]


def _relationship_evidence(
    connection: sqlite3.Connection, snapshot_id: int
) -> list[dict[str, Any]]:
    _inventory, relationships = semantic_inventory(connection, snapshot_id)
    outbound = [
        {"source": source, **edge}
        for source, edges in sorted(relationships.items())
        for edge in edges
        if edge.get("direction") == "uses"
    ]
    return outbound[:120]


def _compact_scope(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "scope": document["scope_key"],
        "kind": document["document_kind"],
        "confidence": document["confidence"],
        "value": compact_dossier(document["value"]),
    }

"""File-level intelligence ledger over a canonical snapshot projection."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from anaxigraph.persistence.semantic_taxonomy_read import taxonomy_assignments
from anaxigraph.persistence.snapshot_projection import install_snapshot_projection

_MODULE_ROWS_SQL = """
SELECT a.id AS artifact_id, a.artifact_type, a.canonical_path,
       a.first_seen_commit, fv.id AS artifact_version_id, fv.path,
       fv.language, fv.runtime, fv.declared_group, fv.inferred_group,
       fv.raw_hash, fv.structural_hash, fv.lines_of_code, fv.comment_lines,
       fv.complexity, fv.summary, fv.responsibilities_json,
       fv.public_interfaces_json, fv.analyzer, fv.analysis_status,
       fv.parse_error, fv.first_seen_at, fv.last_changed_at,
       COALESCE(incoming.count, 0) AS fan_in,
       COALESCE(outgoing.count, 0) AS fan_out,
       coverage.line_coverage,
       COALESCE(history.change_count, 0) AS change_count,
       history.first_changed_at, history.last_changed_at AS last_commit_at,
       history.additions, history.deletions,
       (SELECT gc.commit_sha FROM git_changes gc
        WHERE gc.repository_id = ? AND gc.path = fv.path
        ORDER BY gc.committed_at ASC LIMIT 1) AS first_change_commit,
       (SELECT gc.commit_sha FROM git_changes gc
        WHERE gc.repository_id = ? AND gc.path = fv.path
        ORDER BY gc.committed_at DESC LIMIT 1) AS last_change_commit,
       (SELECT gc.subject FROM git_changes gc
        WHERE gc.repository_id = ? AND gc.path = fv.path
        ORDER BY gc.committed_at DESC LIMIT 1) AS last_change_subject
FROM projected_file_versions fv
JOIN artifacts a ON a.id = fv.artifact_id
LEFT JOIN (
    SELECT target_artifact_id, COUNT(*) AS count FROM projected_relationships
    WHERE target_artifact_id IS NOT NULL GROUP BY target_artifact_id
) incoming ON incoming.target_artifact_id = a.id
LEFT JOIN (
    SELECT source_artifact_id, COUNT(*) AS count FROM projected_relationships
    GROUP BY source_artifact_id
) outgoing ON outgoing.source_artifact_id = a.id
LEFT JOIN (
    SELECT artifact_id, MAX(line_coverage) AS line_coverage
    FROM coverage_measurements WHERE snapshot_id = ? AND artifact_id IS NOT NULL
    GROUP BY artifact_id
) coverage ON coverage.artifact_id = a.id
LEFT JOIN (
    SELECT repository_id, path, COUNT(*) AS change_count,
           MIN(committed_at) AS first_changed_at,
           MAX(committed_at) AS last_changed_at,
           SUM(COALESCE(additions, 0)) AS additions,
           SUM(COALESCE(deletions, 0)) AS deletions
    FROM git_changes WHERE repository_id = ? GROUP BY repository_id, path
) history ON history.repository_id = a.repository_id AND history.path = fv.path
ORDER BY fv.path
"""


def read_modules(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict[str, Any]]:
    install_snapshot_projection(connection, snapshot_id, include_symbols=False)
    rows = _module_rows(
        connection,
        repository_id,
        snapshot_id,
        limit=limit,
        offset=offset,
    )
    parents = _group_parents(connection, repository_id)
    claims = _claims_by_artifact(connection, snapshot_id)
    semantic_states = _semantic_states(connection, snapshot_id)
    semantic_assignments = taxonomy_assignments(connection, snapshot_id)
    findings = _findings_by_path(connection, repository_id)
    return [
        _materialize_module(
            dict(row),
            parents,
            claims,
            semantic_states,
            semantic_assignments,
            findings,
        )
        for row in rows
    ]


def _module_rows(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
    *,
    limit: int | None,
    offset: int,
) -> list[sqlite3.Row]:
    parameters: tuple[Any, ...] = (
        repository_id,
        repository_id,
        repository_id,
        snapshot_id,
        repository_id,
    )
    sql = _MODULE_ROWS_SQL
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        parameters = (*parameters, limit, offset)
    return connection.execute(
        sql,
        parameters,
    ).fetchall()


def _group_parents(
    connection: sqlite3.Connection,
    repository_id: int,
) -> dict[str, str | None]:
    rows = connection.execute(
        """
        SELECT name, parent_name FROM groups WHERE repository_id = ?
        ORDER BY CASE source WHEN 'declared' THEN 0 ELSE 1 END
        """,
        (repository_id,),
    ).fetchall()
    result: dict[str, str | None] = {}
    for row in rows:
        result.setdefault(str(row["name"]), row["parent_name"])
    return result


def _claims_by_artifact(
    connection: sqlite3.Connection,
    snapshot_id: int,
) -> dict[int, dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT sc.*, fv.artifact_id FROM semantic_claims sc
        JOIN projected_file_versions fv ON fv.id = sc.file_fact_id
        WHERE fv.snapshot_id = ? AND sc.claim_type IN ('module_analysis', 'module_context')
        ORDER BY CASE sc.claim_type WHEN 'module_analysis' THEN 0 ELSE 1 END
        """,
        (snapshot_id,),
    ).fetchall()
    return {
        int(row["artifact_id"]): {
            "value": json.loads(row["value_json"] or "{}"),
            "provider": row["provider"],
            "claim_type": row["claim_type"],
            "confidence": row["confidence"],
        }
        for row in rows
    }


def _semantic_states(
    connection: sqlite3.Connection,
    snapshot_id: int,
) -> dict[str, dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT ss.*, intrinsic.intent_fingerprint AS intrinsic_intent_fingerprint,
               intrinsic.created_at AS intrinsic_created_at,
               context.intent_fingerprint AS context_intent_fingerprint,
               context.created_at AS context_created_at,
               context.value_json AS context_value_json,
               context.confidence AS context_confidence,
               context.provider AS context_provider, context.model AS context_model,
               context.executor_id AS context_executor_id,
               context.executor_model AS context_executor_model
        FROM semantic_scope_states ss
        LEFT JOIN semantic_documents intrinsic ON intrinsic.id = ss.intrinsic_document_id
        LEFT JOIN semantic_documents context ON context.id = ss.context_document_id
        WHERE ss.snapshot_id = ? AND ss.scope_type = 'module'
        """,
        (snapshot_id,),
    ).fetchall()
    return {str(row["scope_key"]): dict(row) for row in rows}


def _findings_by_path(
    connection: sqlite3.Connection,
    repository_id: int,
) -> dict[str, list[dict[str, Any]]]:
    rows = connection.execute(
        """
        SELECT id, finding_type, severity, summary, status, affected_artifacts_json
        FROM findings WHERE repository_id = ? AND status NOT IN ('resolved', 'dismissed')
        """,
        (repository_id,),
    ).fetchall()
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        finding = dict(row)
        paths = json.loads(finding.pop("affected_artifacts_json") or "[]")
        for path in paths:
            result.setdefault(str(path), []).append(finding)
    return result


def _materialize_module(
    item: dict[str, Any],
    parents: dict[str, str | None],
    claims: dict[int, dict[str, Any]],
    semantic_states: dict[str, dict[str, Any]],
    semantic_assignments: dict[int, dict[str, Any]],
    findings: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    item["responsibilities"] = json.loads(item.pop("responsibilities_json") or "[]")
    item["public_interfaces"] = json.loads(item.pop("public_interfaces_json") or "[]")
    policy_group = item["declared_group"]
    inferred_group = item["inferred_group"] or "ungrouped"
    fallback_group = policy_group or inferred_group
    fallback_area = _architecture_area(str(fallback_group), parents)
    assignment = semantic_assignments.get(int(item["artifact_id"]))
    area = assignment["area"] if assignment else fallback_area
    group = assignment["subsystem"] if assignment else fallback_group
    item.update(
        name=Path(item["path"]).name,
        architecture_area=area,
        architecture_subsystem=group if group != area else None,
        architecture_group=group,
        architecture_source=(
            assignment["source"]
            if assignment
            else "configured policy"
            if policy_group
            else "deterministic fallback"
        ),
        architecture_layer="semantic" if assignment else "effective",
        architecture_layers={
            "semantic": assignment,
            "policy": (
                {
                    "area": _architecture_area(str(policy_group), parents),
                    "subsystem": policy_group,
                    "source": "configured policy",
                }
                if policy_group
                else None
            ),
            "inferred": {
                "area": inferred_group,
                "subsystem": inferred_group,
                "source": "deterministic fallback",
            },
        },
        semantic_taxonomy=assignment,
    )
    _apply_semantic_summary(item, claims.get(int(item["artifact_id"])))
    item["semantic"] = _semantic_payload(semantic_states.get(item["path"]))
    active_findings = findings.get(item["path"], [])
    item["active_findings"] = active_findings
    item["evaluation"] = module_evaluation(item, active_findings)
    return item


def _architecture_area(group: str, parents: dict[str, str | None]) -> str:
    area = group
    visited: set[str] = set()
    while parents.get(area) and area not in visited:
        visited.add(area)
        area = str(parents[area])
    return area


def _apply_semantic_summary(item: dict[str, Any], claim: dict[str, Any] | None) -> None:
    if claim:
        item["deterministic_summary"] = item["summary"]
        item["summary"] = claim["value"].get("summary") or item["summary"]
        phase = "contextual" if claim["claim_type"] == "module_context" else "intrinsic"
        item["summary_source"] = f"{claim['provider']} {phase} interpretation"
        item["summary_confidence"] = claim["confidence"]
    else:
        item["summary_source"] = "deterministic"
        item["summary_confidence"] = 1.0


def _semantic_payload(state: dict[str, Any] | None) -> dict[str, Any]:
    if state is None:
        return {"status": "not_started", "reason": "Semantic bootstrap has not run"}
    value = json.loads(state.get("context_value_json") or "{}")
    return {
        "status": state["status"],
        "reason": state["reason"],
        "intent_fingerprint": state["intrinsic_intent_fingerprint"],
        "context_intent_fingerprint": state["context_intent_fingerprint"],
        "context_fingerprint": state["context_fingerprint"],
        "intrinsic_created_at": state["intrinsic_created_at"],
        "context_created_at": state["context_created_at"],
        "provider": state["context_provider"],
        "model": state["context_model"],
        "executor_id": state["context_executor_id"],
        "executor_model": state["context_executor_model"],
        "confidence": state["context_confidence"],
        "architecture_role": value.get("architecture_role") or "",
        "pattern_opportunities": value.get("pattern_opportunities") or [],
        "consolidation_assessment": value.get("consolidation_assessment") or "",
        "dead_code_candidates": value.get("dead_code_candidates") or [],
        "placement_guidance": value.get("placement_guidance") or "",
        "change_summary": value.get("change_summary") or "",
    }


_PATTERN_REVIEWS = {
    "architecture_drift": "Architecture-role review",
    "architecture_violation": "Layer boundary or adapter review",
    "dependency_cycle": "Dependency inversion or boundary review",
    "high_fan_in": "Stable interface boundary review",
    "high_fan_out": "Facade or orchestration boundary review",
    "long_function": "Focused operation extraction review",
    "module_complexity": "Module cohesion and extraction review",
    "possible_dead_code": "Ownership or removal review",
    "symbol_complexity": "Strategy or decision-table review",
    "weak_test_coverage": "Test seam review",
}


def module_evaluation(item: dict[str, Any], findings: list[dict[str, Any]]) -> dict[str, Any]:
    artifact_type = str(item.get("artifact_type") or "source")
    if artifact_type not in {"source", "test"}:
        return _reference_evaluation(artifact_type)
    loc = int(item.get("lines_of_code") or 0)
    complexity = float(item.get("complexity") or 0)
    coupling = int(item.get("fan_in") or 0) + int(item.get("fan_out") or 0)
    changes = int(item.get("change_count") or 0)
    severity_points = {"critical": 8, "error": 7, "warning": 5, "info": 2}
    pressure = min(
        20,
        sum(severity_points.get(str(finding.get("severity")), 2) for finding in findings),
    )
    score = round(
        min(loc / 500, 1) * 25
        + min(complexity / 50, 1) * 20
        + min(coupling / 30, 1) * 20
        + min(changes / 20, 1) * 15
        + pressure
    )
    candidates = sorted(
        {
            _PATTERN_REVIEWS[finding["finding_type"]]
            for finding in findings
            if finding.get("finding_type") in _PATTERN_REVIEWS
        }
    )
    return {
        "monitored_by_default": True,
        "monitoring_reason": "Executable source or test module included in attention triage.",
        "attention_score": min(100, score),
        "attention_label": _attention_label(score),
        "attention_reasons": _attention_reasons(loc, complexity, coupling, changes, findings),
        "pattern_status": "candidate_review" if candidates else "not_evaluated",
        "pattern_candidates": candidates,
        "suitability_score": None,
        "note": (
            "Candidates are detector-grounded review prompts, not approved refactors. "
            "Pattern suitability scoring requires the semantic pattern-evaluation pipeline."
        ),
    }


def _reference_evaluation(artifact_type: str) -> dict[str, Any]:
    kind = {
        "documentation": "Documentation/reference file",
        "configuration": "Configuration/manifest file",
        "asset": "Presentation asset",
    }.get(artifact_type, f"{artifact_type.capitalize()} artifact")
    return {
        "monitored_by_default": False,
        "monitoring_reason": f"{kind}; retained in AnaxiIndex but excluded from source-code attention triage.",
        "attention_score": None,
        "attention_label": "Reference",
        "attention_reasons": [f"{kind}; size and churn are not source-module refactoring signals"],
        "pattern_status": "not_applicable",
        "pattern_candidates": [],
        "suitability_score": None,
        "note": (
            "Reference artifacts remain searchable and visible on demand, but are not "
            "ranked against executable modules."
        ),
    }


def _attention_label(score: int) -> str:
    if score >= 75:
        return "Priority"
    if score >= 50:
        return "Review"
    if score >= 25:
        return "Watch"
    return "Low"


def _attention_reasons(
    loc: int,
    complexity: float,
    coupling: int,
    changes: int,
    findings: list[dict[str, Any]],
) -> list[str]:
    reasons: list[str] = []
    if loc >= 500:
        reasons.append(f"Large module ({loc:,} LOC)")
    if complexity >= 25:
        reasons.append(f"High detected decision complexity ({complexity:g})")
    if coupling >= 20:
        reasons.append(f"Highly connected ({coupling} incoming + outgoing links)")
    if changes >= 10:
        reasons.append(f"Frequently changed ({changes} indexed commits)")
    if findings:
        reasons.append(f"{len(findings)} active architecture finding(s)")
    return reasons or ["No threshold-level deterministic signal"]

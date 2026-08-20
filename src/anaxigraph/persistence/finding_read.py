"""Finding ledger read models and behavioral priority ranking."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from anaxigraph.persistence.row_decoding import decode_json_columns
from anaxigraph.persistence.snapshot_projection import install_snapshot_projection


@dataclass(frozen=True, slots=True)
class _FindingRisk:
    severity: str
    confidence: float
    paths: list[str]
    changes: int
    degree: int
    complexity: float
    coverage: list[float]


def read_findings(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int | None,
    *,
    statuses: tuple[str, ...],
    limit: int,
) -> list[dict[str, Any]]:
    params: list[Any] = [repository_id]
    condition = "repository_id = ?"
    if statuses:
        placeholders = ",".join("?" for _ in statuses)
        condition += f" AND status IN ({placeholders})"
        params.extend(statuses)
    rows = connection.execute(
        f"SELECT * FROM findings WHERE {condition} ORDER BY last_detected_at DESC",
        params,
    ).fetchall()
    stats = _module_stats(connection, repository_id, snapshot_id) if snapshot_id is not None else {}
    ranked: list[dict[str, Any]] = []
    for row in rows:
        item = decode_json_columns(dict(row))
        item.update(finding_priority(item, stats))
        ranked.append(item)
    return sorted(
        ranked,
        key=lambda item: (-int(item["priority_score"]), -int(item["id"])),
    )[:limit]


def read_finding(
    connection: sqlite3.Connection,
    repository_id: int,
    finding_id: int,
) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT f.*,
               (SELECT COUNT(*) FROM finding_occurrences occurrence
                 WHERE occurrence.finding_id = f.id) AS occurrence_count
        FROM findings f WHERE f.repository_id = ? AND f.id = ?
        """,
        (repository_id, finding_id),
    ).fetchone()
    return decode_json_columns(dict(row)) if row else None


def _module_stats(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
) -> dict[str, dict[str, Any]]:
    install_snapshot_projection(connection, snapshot_id, include_symbols=False)
    rows = connection.execute(
        """
        SELECT fv.path, fv.complexity,
               COALESCE(incoming.count, 0) AS fan_in,
               COALESCE(outgoing.count, 0) AS fan_out,
               COALESCE(history.change_count, 0) AS change_count,
               coverage.line_coverage
        FROM projected_file_versions fv
        LEFT JOIN (
            SELECT target_artifact_id, COUNT(*) AS count FROM projected_relationships
            WHERE target_artifact_id IS NOT NULL GROUP BY target_artifact_id
        ) incoming ON incoming.target_artifact_id = fv.artifact_id
        LEFT JOIN (
            SELECT source_artifact_id, COUNT(*) AS count FROM projected_relationships
            GROUP BY source_artifact_id
        ) outgoing ON outgoing.source_artifact_id = fv.artifact_id
        LEFT JOIN (
            SELECT path, COUNT(*) AS change_count FROM git_changes
            WHERE repository_id = ? GROUP BY path
        ) history ON history.path = fv.path
        LEFT JOIN (
            SELECT artifact_id, MAX(line_coverage) AS line_coverage
            FROM coverage_measurements WHERE snapshot_id = ?
            AND artifact_id IS NOT NULL GROUP BY artifact_id
        ) coverage ON coverage.artifact_id = fv.artifact_id
        """,
        (repository_id, snapshot_id),
    ).fetchall()
    return {str(row["path"]): dict(row) for row in rows}


def finding_priority(
    finding: dict[str, Any],
    module_stats: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    risk = _risk_inputs(finding, module_stats)
    score = _risk_score(risk, regressed=finding.get("status") == "regressed")
    return {
        "priority_score": score,
        "priority_label": _priority_label(score),
        "priority_reasons": _priority_reasons(
            risk.severity,
            risk.confidence,
            risk.changes,
            risk.degree,
            risk.complexity,
            risk.paths,
            risk.coverage,
            finding,
        ),
        "priority_version": "risk-churn-blast-v1",
    }


def _risk_inputs(
    finding: dict[str, Any],
    module_stats: dict[str, dict[str, Any]],
) -> _FindingRisk:
    severity = str(finding.get("severity") or "info")
    confidence = max(0.0, min(1.0, float(finding.get("confidence") or 0)))
    paths = [str(path) for path in finding.get("affected_artifacts") or ()]
    affected = [module_stats[path] for path in paths if path in module_stats]
    changes = max((int(item.get("change_count") or 0) for item in affected), default=0)
    degree = max(
        (int(item.get("fan_in") or 0) + int(item.get("fan_out") or 0) for item in affected),
        default=0,
    )
    complexity = max((float(item.get("complexity") or 0) for item in affected), default=0)
    coverage = [
        float(item["line_coverage"]) for item in affected if item.get("line_coverage") is not None
    ]
    return _FindingRisk(severity, confidence, paths, changes, degree, complexity, coverage)


def _risk_score(risk: _FindingRisk, *, regressed: bool) -> int:
    score = {"critical": 45, "error": 38, "warning": 24, "info": 8}.get(risk.severity, 8)
    score += round(risk.confidence * 12)
    score += round(min(risk.changes / 20, 1) * 14)
    score += round(min(risk.degree / 30, 1) * 16)
    score += round(min(len(risk.paths) / 5, 1) * 8)
    if risk.changes and risk.complexity:
        score += round(min(risk.changes / 10, 1) * min(risk.complexity / 50, 1) * 10)
    if risk.coverage:
        score += round((1 - min(risk.coverage)) * 5)
    if regressed:
        score += 8
    return min(100, score)


def _priority_label(score: int) -> str:
    if score >= 80:
        return "Urgent"
    if score >= 60:
        return "High"
    if score >= 35:
        return "Medium"
    return "Low"


def _priority_reasons(
    severity: str,
    confidence: float,
    changes: int,
    degree: int,
    complexity: float,
    paths: list[str],
    coverage: list[float],
    finding: dict[str, Any],
) -> list[str]:
    reasons = [f"{severity.title()} severity · {confidence:.0%} confidence"]
    if changes:
        reasons.append(f"Hot path: up to {changes} indexed changes")
    if degree:
        reasons.append(f"Blast radius: up to {degree} incoming + outgoing links")
    if changes and complexity >= 10:
        reasons.append(f"Behavioral hotspot: churn × complexity {complexity:g}")
    if len(paths) > 1:
        reasons.append(f"Spans {len(paths)} modules")
    if coverage:
        reasons.append(f"Lowest imported line coverage {min(coverage):.0%}")
    if finding.get("status") == "regressed":
        reasons.append("Previously resolved condition has returned")
    return reasons

"""Finding ledger read models and behavioral priority ranking."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from anaxigraph.finding_language import (
    evidence_sentences,
    normalize_finding_copy,
    plain_language_contract,
)
from anaxigraph.persistence.row_decoding import decode_json_columns
from anaxigraph.persistence.snapshot_projection import install_snapshot_projection

PRIORITY_VERSION = "risk-churn-blast-v1"

_DEAD_CODE_LIMITS = [
    "The application loads the file by name from configuration, a framework, or generated code.",
    "The language analyzer could not see a runtime registration or another dynamic reference.",
]
_CYCLE_LIMITS = [
    "The loop exists only for type checking or building and does not connect runtime behavior.",
    "An unclear import was linked to the wrong module.",
]
_COVERAGE_LIMITS = [
    "The imported coverage report is old or does not include the relevant test run.",
    "The uncovered lines are generated, unreachable, or contain no behavior worth testing.",
]
_DEFAULT_LIMITS = [
    "The repository intentionally allows this structure.",
    "Missing or unclear dependency data changes what the finding appears to mean.",
]
_FINDING_LIMITS = {
    "long_function": [
        "The function tells one clear, step-by-step story even though it is long.",
        "Splitting it would make the order of the steps harder to see.",
    ],
    "symbol_complexity": [
        "Every branch answers part of one clear business decision.",
        (
            "Focused tests already cover each important outcome, and splitting the branches would "
            "hide the logic."
        ),
    ],
    "module_complexity": [
        "The file has one clear job even though that job needs a lot of code.",
        "Splitting it would force closely related code to jump between files.",
    ],
    "high_fan_out": [
        "The file is an intentional coordinator whose job is to connect the listed modules.",
        "Each dependency supports the same clear workflow rather than a separate responsibility.",
    ],
    "high_fan_in": [
        "The file is a stable shared contract that many callers are expected to use.",
        "Its public behavior changes rarely and has broad tests.",
    ],
    "architecture_drift": [
        "The path-based fallback guessed the wrong architecture area.",
        "The declared area intentionally owns the dependency that caused the different guess.",
    ],
    "architecture_violation": [
        "The repository rule is out of date or was written too broadly.",
        "The detected reference is build-only, type-only, or points to the wrong module.",
    ],
}


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
    return read_ranked_findings(
        connection,
        repository_id,
        snapshot_id,
        statuses=statuses,
    )[:limit]


def read_ranked_findings(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int | None,
    *,
    statuses: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Return the complete ranked ledger; presentation layers own pagination."""

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
        item = normalize_finding_copy(decode_json_columns(dict(row)))
        item.update(finding_priority(item, stats))
        ranked.append(item)
    return sorted(ranked, key=finding_sort_key)


def read_finding(
    connection: sqlite3.Connection,
    repository_id: int,
    finding_id: int,
    snapshot_id: int | None = None,
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
    if row is None:
        return None
    item = normalize_finding_copy(decode_json_columns(dict(row)))
    stats = _module_stats(connection, repository_id, snapshot_id) if snapshot_id else {}
    item.update(finding_priority(item, stats))
    return item


def finding_sort_key(item: dict[str, Any]) -> tuple[int, int, str, str]:
    """Stable queue order shared by page generation and cursor continuation."""

    return (
        -int(item.get("priority_score") or 0),
        -int(item.get("status") == "regressed"),
        str(item.get("first_detected_at") or ""),
        str(item.get("stable_key") or item.get("id") or ""),
    )


def _module_stats(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
) -> dict[str, dict[str, Any]]:
    install_snapshot_projection(connection, snapshot_id, include_symbols=False)
    rows = connection.execute(
        """
        SELECT fv.path, fv.complexity, fv.declared_group, fv.inferred_group,
               fv.public_interfaces_json,
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
    area_by_group = _group_areas(connection, repository_id)
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = decode_json_columns(dict(row))
        group = str(item.get("declared_group") or item.get("inferred_group") or "ungrouped")
        item["architecture_area"] = area_by_group.get(group, group)
        result[str(row["path"])] = item
    return result


def _group_areas(connection: sqlite3.Connection, repository_id: int) -> dict[str, str]:
    rows = connection.execute(
        """
        SELECT name, parent_name FROM groups WHERE repository_id = ?
        ORDER BY CASE source WHEN 'declared' THEN 0 ELSE 1 END
        """,
        (repository_id,),
    ).fetchall()
    parents: dict[str, str | None] = {}
    for row in rows:
        parents.setdefault(str(row["name"]), row["parent_name"])

    def root(name: str) -> str:
        seen: set[str] = set()
        current = name
        while current not in seen and parents.get(current):
            seen.add(current)
            current = str(parents[current])
        return current

    return {name: root(name) for name in parents}


def finding_priority(
    finding: dict[str, Any],
    module_stats: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    risk = _risk_inputs(finding, module_stats)
    score = _risk_score(risk, regressed=finding.get("status") == "regressed")
    reasons = _priority_reasons(
        risk.severity,
        risk.confidence,
        risk.changes,
        risk.degree,
        risk.complexity,
        risk.paths,
        risk.coverage,
        finding,
    )
    actionability = _actionability(finding, module_stats, risk, reasons)
    label = _priority_label(score)
    return {
        "priority_score": score,
        "priority_label": label,
        "priority_reasons": reasons,
        "priority_version": PRIORITY_VERSION,
        "actionability": actionability,
        "plain_language": plain_language_contract(
            finding,
            priority_score=score,
            priority_label=label,
            priority_reasons=reasons,
            false_positive_conditions=actionability["false_positive_conditions"],
        ),
    }


def _actionability(
    finding: dict[str, Any],
    module_stats: dict[str, dict[str, Any]],
    risk: _FindingRisk,
    reasons: list[str],
) -> dict[str, Any]:
    finding_type = str(finding.get("finding_type") or "observation")
    action_type = _action_type(finding_type)
    source = str(finding.get("source") or "deterministic")
    evidence = finding.get("evidence") or []
    semantic_source = source in {"semantic", "llm", "coding_agent"}
    return {
        "why_ranked": reasons,
        "evidence": {
            "deterministic": [] if semantic_source else evidence,
            "plain_language": evidence_sentences(finding),
            "semantic": {
                "status": "attached" if semantic_source else "not_attached",
                "items": evidence if semantic_source else [],
            },
        },
        "false_positive_conditions": _false_positive_conditions(finding_type),
        "affected": _affected_context(module_stats, risk),
        "action_type": action_type,
        "smallest_next_action": str(
            finding.get("recommended_action") or _fallback_action(action_type)
        ),
        "verification": (
            "Scan the repository again after the change. If AnaxiGraph no longer sees the same "
            "condition, it marks this finding resolved. If the condition comes back in a later "
            "scan, AnaxiGraph marks it as returned."
        ),
    }


def _affected_context(
    module_stats: dict[str, dict[str, Any]],
    risk: _FindingRisk,
) -> dict[str, Any]:
    affected = [module_stats[path] for path in risk.paths if path in module_stats]
    contracts = [
        {
            "module": path,
            "interfaces": list(module_stats[path].get("public_interfaces") or ())[:8],
        }
        for path in risk.paths
        if module_stats.get(path, {}).get("public_interfaces")
    ]
    return {
        "modules": risk.paths,
        "architecture_areas": sorted(
            {str(item.get("architecture_area") or "ungrouped") for item in affected}
        ),
        "contracts": contracts,
        "tests": [path for path in risk.paths if _looks_like_test(path)],
        "blast_radius": {
            "maximum_dependency_degree": risk.degree,
            "maximum_indexed_changes": risk.changes,
        },
    }


def _action_type(finding_type: str) -> str:
    if "dead" in finding_type or "unused" in finding_type:
        return "remove"
    if "coverage" in finding_type or "test" in finding_type:
        return "test"
    if any(token in finding_type for token in ("cycle", "boundary", "layer", "dependency")):
        return "constrain"
    if any(token in finding_type for token in ("long", "large", "complex", "duplicate")):
        return "refactor"
    return "investigate"


def _fallback_action(action_type: str) -> str:
    return {
        "remove": (
            "Search for runtime and configuration-based use first. Remove only the smallest piece "
            "that tests and a normal application start show is unused."
        ),
        "test": "Add a small test that checks the affected behavior or project boundary.",
        "constrain": (
            "Follow the dependency shown in the evidence and route it through the smallest clear "
            "boundary."
        ),
        "refactor": "Move one clearly named job without changing what users or callers observe.",
    }.get(action_type, "Read the evidence and decide whether this condition needs a code change.")


def _false_positive_conditions(finding_type: str) -> list[str]:
    if "dead" in finding_type or "unused" in finding_type:
        return _DEAD_CODE_LIMITS
    if "cycle" in finding_type:
        return _CYCLE_LIMITS
    if "coverage" in finding_type:
        return _COVERAGE_LIMITS
    return _FINDING_LIMITS.get(finding_type, _DEFAULT_LIMITS)


def _looks_like_test(path: str) -> bool:
    lowered = path.lower()
    return (
        lowered.startswith(("test/", "tests/"))
        or "/test/" in lowered
        or "/tests/" in lowered
        or ".test." in lowered
        or ".spec." in lowered
        or lowered.rsplit("/", 1)[-1].startswith("test_")
    )


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
    reasons = [
        f"The repository rule marks this as {severity}, and the detector reports "
        f"{confidence:.0%} measurement confidence."
    ]
    if changes:
        reasons.append(
            f"The most active affected file changed {changes} times in indexed Git history."
        )
    if degree:
        reasons.append(
            f"The most connected affected file has {degree} incoming and outgoing links in total."
        )
    if changes and complexity >= 10:
        reasons.append(
            f"An affected file both changes often and has a decision score of {complexity:g}."
        )
    if len(paths) > 1:
        reasons.append(f"The finding covers {len(paths)} modules.")
    if coverage:
        reasons.append(
            f"Tests ran only {min(coverage):.0%} of the least-covered affected file's lines."
        )
    if finding.get("status") == "regressed":
        reasons.append("A previous scan marked this resolved, but the condition has returned.")
    return reasons

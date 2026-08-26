"""Size-limited analysis of code that may be affected by a change."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anaxigraph.agent_graph import _projected_graph_maps, _related_tests, _reverse_reachable
from anaxigraph.agent_payload import (
    _branch_conflicts,
    _file_summary,
    _is_protected,
    _risk_explanation,
    _sorted_ids,
)
from anaxigraph.graph_contract import _with_response_telemetry
from anaxigraph.operational_health import served_map_status
from anaxigraph.persistence.snapshot_projection import resolve_projected_target


@dataclass(frozen=True, slots=True)
class _ImpactGraph:
    repository: dict[str, Any]
    snapshot_id: int
    map_status: dict[str, Any]
    files: dict[int, dict[str, Any]]
    outgoing: dict[int, set[int]]
    incoming: dict[int, set[int]]
    target_id: int


@dataclass(frozen=True, slots=True)
class _ImpactEvidence:
    direct: set[int]
    second: set[int]
    transitive: set[int]
    affected: set[int]
    tests: set[str]
    protected: list[str]
    migrations: list[str]


def build_impact_analysis(
    database: Any,
    *,
    repository_id: int,
    target: str,
    branch: str | None,
    config: Any,
) -> dict[str, Any]:
    started = time.perf_counter()
    graph = _impact_graph(database, repository_id, target)
    evidence = _impact_evidence(graph, target, config)
    return _with_response_telemetry(
        _impact_response(repository_id, branch, graph, evidence),
        started,
        action="impact",
    )


def _impact_graph(database: Any, repository_id: int, target: str) -> _ImpactGraph:
    repository = database.repository(repository_id)
    if repository is None:
        raise ValueError("Repository not found")
    snapshot = database.latest_snapshot(repository_id)
    if snapshot is None:
        raise ValueError("Repository has not been scanned")
    snapshot_id = int(snapshot["id"])
    map_status = served_map_status(Path(repository["path"]), snapshot)
    with database.connect() as connection:
        files, outgoing, incoming = _projected_graph_maps(connection, snapshot_id)
        target_id = resolve_projected_target(connection, snapshot_id, files, target)
    if target_id is None:
        raise ValueError(f"Target not found: {target}")
    return _ImpactGraph(repository, snapshot_id, map_status, files, outgoing, incoming, target_id)


def _impact_evidence(graph: _ImpactGraph, target: str, config: Any) -> _ImpactEvidence:
    direct = set(graph.incoming[graph.target_id])
    second = set().union(*(graph.incoming[item] for item in direct)) if direct else set()
    second.discard(graph.target_id)
    transitive = _reverse_reachable(graph.target_id, graph.incoming, limit=500)
    affected = {graph.target_id} | transitive
    tests = _related_tests(
        graph.files,
        graph.outgoing,
        graph.incoming,
        {graph.target_id},
        affected - {graph.target_id},
        target,
        limit=50,
    )
    protected = sorted(
        graph.files[item]["path"]
        for item in affected
        if _is_protected(graph.files[item]["path"], config)
    )
    migrations = sorted(
        graph.files[item]["path"]
        for item in affected
        if "migration" in graph.files[item]["path"].lower()
    )
    return _ImpactEvidence(direct, second, transitive, affected, tests, protected, migrations)


def _impact_response(
    repository_id: int,
    branch: str | None,
    graph: _ImpactGraph,
    evidence: _ImpactEvidence,
) -> dict[str, Any]:
    paths = {graph.files[item]["path"] for item in evidence.affected}
    conflicts = _branch_conflicts(Path(graph.repository["path"]), paths, branch)
    degree = len(graph.outgoing[graph.target_id]) + len(graph.incoming[graph.target_id])
    risk = _impact_risk(evidence, conflicts, degree)
    risk_reasons = _impact_risk_reasons(evidence, conflicts, degree)
    second_only = evidence.second - evidence.direct
    return {
        "repository_id": repository_id,
        "snapshot_id": graph.snapshot_id,
        "map_status": graph.map_status,
        "target": _file_summary(graph.files[graph.target_id]),
        "direct_dependants": [
            _file_summary(graph.files[item]) for item in _sorted_ids(graph.files, evidence.direct)
        ],
        "second_order_dependants": [
            _file_summary(graph.files[item]) for item in _sorted_ids(graph.files, second_only)
        ],
        "transitive_dependant_count": len(evidence.transitive),
        "outgoing_dependencies": [
            _file_summary(graph.files[item])
            for item in _sorted_ids(graph.files, graph.outgoing[graph.target_id])
        ],
        "critical_paths_affected": evidence.protected,
        "tests_relevant": sorted(evidence.tests),
        "database_migrations_possibly_affected": evidence.migrations,
        "active_feature_branches_affected": conflicts,
        "risk": risk,
        "risk_reasons": risk_reasons,
        "plain_language": _impact_language(graph, evidence, risk, risk_reasons),
        "metrics": _impact_metrics(evidence, second_only, degree),
    }


def _impact_language(
    graph: _ImpactGraph,
    evidence: _ImpactEvidence,
    risk: str,
    risk_reasons: list[str],
) -> dict[str, Any]:
    count = len(evidence.transitive)
    return {
        "conclusion": (
            f"Changing {graph.files[graph.target_id]['path']} may affect {count} other indexed "
            f"{'file' if count == 1 else 'files'} through direct or indirect code links."
        ),
        "how_to_use_this": (
            "Check direct users and focused tests first. Indirect users are possible follow-on "
            "effects, not a list of files that must change."
        ),
        "risk": _risk_explanation(risk, risk_reasons),
        "limits": (
            "The result uses saved source-code links. Settings, framework setup, generated "
            "names, and code that registers behavior when the application starts or runs can "
            "connect code that the map cannot see."
        ),
        "machine_key_note": (
            "snapshot_id identifies the saved scan used for this answer; it is not a score."
        ),
    }


def _impact_metrics(
    evidence: _ImpactEvidence, second_only: set[int], degree: int
) -> dict[str, int]:
    return {
        "direct_dependants": len(evidence.direct),
        "second_order_dependants": len(second_only),
        "transitive_dependants": len(evidence.transitive),
        "tests": len(evidence.tests),
        "degree": degree,
    }


def _impact_risk(evidence: _ImpactEvidence, conflicts: list[dict[str, str]], degree: int) -> str:
    if evidence.protected or conflicts or len(evidence.transitive) >= 25 or degree >= 20:
        return "high"
    if evidence.direct or evidence.migrations:
        return "medium"
    return "low"


def _impact_risk_reasons(
    evidence: _ImpactEvidence, conflicts: list[dict[str, str]], degree: int
) -> list[str]:
    reasons = []
    if evidence.protected:
        reasons.append("A project rule marks at least one possibly affected file for extra care.")
    if conflicts:
        reasons.append("Another branch also changes at least one possibly affected file.")
    if len(evidence.transitive) >= 25:
        reasons.append(
            f"At least {len(evidence.transitive)} files may be affected through one or more code links."
        )
    if degree >= 20:
        reasons.append(f"The target has {degree} direct incoming or outgoing code links.")
    if evidence.direct and not reasons:
        reasons.append(f"{len(evidence.direct)} files directly use the target.")
    if evidence.migrations:
        reasons.append("A possibly affected file appears to change stored database data.")
    return reasons or ["No indexed condition raised the change above low risk."]

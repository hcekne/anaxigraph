"""Bounded reverse-dependency impact analysis for coding agents."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anaxigraph.agent_graph import _projected_graph_maps, _related_tests, _reverse_reachable
from anaxigraph.agent_payload import (
    _branch_conflicts,
    _file_summary,
    _is_protected,
    _sorted_ids,
)
from anaxigraph.persistence.snapshot_projection import resolve_projected_target


@dataclass(frozen=True, slots=True)
class _ImpactGraph:
    repository: dict[str, Any]
    snapshot_id: int
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
    graph = _impact_graph(database, repository_id, target)
    evidence = _impact_evidence(graph, target, config)
    return _impact_response(repository_id, branch, graph, evidence)


def _impact_graph(database: Any, repository_id: int, target: str) -> _ImpactGraph:
    repository = database.repository(repository_id)
    if repository is None:
        raise ValueError("Repository not found")
    snapshot = database.latest_snapshot(repository_id)
    if snapshot is None:
        raise ValueError("Repository has not been scanned")
    snapshot_id = int(snapshot["id"])
    with database.connect() as connection:
        files, outgoing, incoming = _projected_graph_maps(connection, snapshot_id)
        target_id = resolve_projected_target(connection, snapshot_id, files, target)
    if target_id is None:
        raise ValueError(f"Target not found: {target}")
    return _ImpactGraph(repository, snapshot_id, files, outgoing, incoming, target_id)


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
    second_only = evidence.second - evidence.direct
    return {
        "repository_id": repository_id,
        "snapshot_id": graph.snapshot_id,
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
        "metrics": {
            "direct_dependants": len(evidence.direct),
            "second_order_dependants": len(second_only),
            "transitive_dependants": len(evidence.transitive),
            "tests": len(evidence.tests),
            "degree": degree,
        },
    }


def _impact_risk(evidence: _ImpactEvidence, conflicts: list[dict[str, str]], degree: int) -> str:
    if evidence.protected or conflicts or len(evidence.transitive) >= 25 or degree >= 20:
        return "high"
    if evidence.direct or evidence.migrations:
        return "medium"
    return "low"

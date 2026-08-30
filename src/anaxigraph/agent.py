"""Bounded agent task context and impact traversal."""

from __future__ import annotations

import time
from typing import Any

from anaxigraph.agent_decision import architecture_decision
from anaxigraph.agent_finding import build_finding_context
from anaxigraph.agent_graph import (
    _applicable_findings,
    _applicable_rules,
    _attach_architecture_map,
    _expand_relevant,
    _projected_graph_maps,
    _public_interfaces,
    _rank_files,
    _related_tests,
    _repository_map_state,
    _select_primary,
    _symbols,
)
from anaxigraph.agent_impact import build_impact_analysis
from anaxigraph.agent_payload import (
    _is_protected,
    _scope_payload,
    _ScopePayloadData,
)
from anaxigraph.config import AnaxiGraphConfig
from anaxigraph.storage import AnaxiIndex


def agent_scope(
    database: AnaxiIndex,
    *,
    repository_id: int,
    goal: str,
    config: AnaxiGraphConfig,
) -> dict[str, Any]:
    started = time.perf_counter()
    _repository, snapshot_id, map_status = _repository_map_state(database, repository_id)
    with database.connect() as connection:
        files, outgoing, incoming, hierarchy = _scope_graph(connection, repository_id, snapshot_id)
        ranked = _rank_files(connection, snapshot_id, files, goal)
        primary_ids = _select_primary(ranked, files, limit=min(8, config.agent.context_limit))
        if not primary_ids and files:
            primary_ids = [next(iter(files))]
        related_ids, related_scores = _expand_relevant(
            primary_ids,
            outgoing,
            incoming,
            files,
            lexical_scores={artifact_id: score for score, artifact_id in ranked},
            depth=config.agent.neighbor_depth,
            limit=config.agent.context_limit * 2,
        )
        relevant_ids = set(primary_ids) | related_ids
        tests = _related_tests(
            files,
            outgoing,
            incoming,
            set(primary_ids),
            related_ids,
            goal,
            limit=max(8, config.agent.context_limit // 2),
        )
        protected_ids = {
            artifact_id
            for artifact_id in relevant_ids
            if _is_protected(files[artifact_id]["path"], config)
        }
        rules = _applicable_rules(connection, repository_id, files, relevant_ids)
        findings = _applicable_findings(
            connection,
            repository_id,
            files,
            relevant_ids,
            set(primary_ids),
        )
        symbols, interfaces = _scope_symbols(connection, snapshot_id, primary_ids)
    decision = _scope_decision(
        database,
        repository_id,
        goal,
        snapshot_id,
        files,
        primary_ids,
        interfaces,
        symbols,
        hierarchy,
        tests,
        (findings, rules),
    )
    return _scope_payload(
        _ScopePayloadData(
            goal=goal,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            map_status=map_status,
            files=files,
            outgoing=outgoing,
            incoming=incoming,
            primary_ids=primary_ids,
            related_ids=related_ids,
            related_scores=related_scores,
            protected_ids=protected_ids,
            tests=tests,
            interfaces=interfaces,
            rules=rules,
            findings=findings,
            decision=decision,
            context_limit=config.agent.context_limit,
            payload_limit_bytes=config.agent.payload_limit_bytes,
            started_at=started,
        )
    )


def _scope_graph(
    connection: Any, repository_id: int, snapshot_id: int
) -> tuple[Any, Any, Any, list[dict[str, Any]]]:
    files, outgoing, incoming = _projected_graph_maps(connection, snapshot_id)
    hierarchy = _attach_architecture_map(connection, repository_id, snapshot_id, files)
    return files, outgoing, incoming, hierarchy


def _scope_symbols(
    connection: Any, snapshot_id: int, primary_ids: list[int]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    symbols = _symbols(connection, snapshot_id, primary_ids)
    return symbols, _public_interfaces(symbols)


def _scope_decision(
    database: AnaxiIndex,
    repository_id: int,
    goal: str,
    snapshot_id: int,
    files: dict[int, dict[str, Any]],
    primary_ids: list[int],
    interfaces: list[dict[str, Any]],
    symbols: list[dict[str, Any]],
    hierarchy: list[dict[str, Any]],
    tests: set[str],
    evidence: tuple[list[dict[str, Any]], list[dict[str, Any]]],
) -> dict[str, Any]:
    findings, rules = evidence
    return architecture_decision(
        database,
        repository_id=repository_id,
        goal=goal,
        snapshot_id=snapshot_id,
        primary_files=[files[item] for item in primary_ids],
        interfaces=interfaces,
        symbols=symbols,
        hierarchy=hierarchy,
        tests=sorted(tests),
        findings=findings,
        rules=rules,
    )


def finding_context(
    database: AnaxiIndex,
    *,
    repository_id: int,
    finding_id: int,
    config: AnaxiGraphConfig,
) -> dict[str, Any]:
    """Turn one reviewed finding into structured, agent-ready engineering context."""

    return build_finding_context(
        database,
        repository_id=repository_id,
        finding_id=finding_id,
        config=config,
        scope_builder=agent_scope,
        impact_builder=impact_analysis,
    )


def impact_analysis(
    database: AnaxiIndex,
    *,
    repository_id: int,
    target: str,
    config: AnaxiGraphConfig,
) -> dict[str, Any]:
    return build_impact_analysis(
        database,
        repository_id=repository_id,
        target=target,
        config=config,
    )

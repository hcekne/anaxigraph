"""Deterministic architecture evaluation facade."""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from typing import Any

from anaxigraph.architecture_dead_code import dead_code_findings
from anaxigraph.architecture_graph import _strongly_connected
from anaxigraph.architecture_models import DEFAULT_RULES, Finding
from anaxigraph.architecture_persistence import (
    _persist_rules,
    _record_evaluation,
)
from anaxigraph.architecture_rules import _evaluate_rule
from anaxigraph.config import AnaxiGraphConfig, path_matches

__all__ = ["DEFAULT_RULES", "Finding", "_dead_code_findings", "evaluate_architecture"]


def _dead_code_findings(*args: Any, **kwargs: Any) -> list[Finding]:
    return dead_code_findings(*args, path_matcher=path_matches, **kwargs)


def evaluate_architecture(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    snapshot_id: int,
    config: AnaxiGraphConfig,
    files: list[dict[str, Any]],
    symbols: list[dict[str, Any]],
    relationship_evidence: list[dict[str, Any]],
    manage_finding_lifecycle: bool = True,
) -> list[Finding]:
    relationships = [row for row in relationship_evidence if row["target_artifact_id"] is not None]
    file_by_id = {int(row["artifact_id"]): row for row in files}
    fan_out = Counter(int(row["source_artifact_id"]) for row in relationships)
    fan_in = Counter(int(row["target_artifact_id"]) for row in relationships)
    graph: dict[int, set[int]] = defaultdict(set)
    for row in relationships:
        graph[int(row["source_artifact_id"])].add(int(row["target_artifact_id"]))
    cycles = [component for component in _strongly_connected(graph) if len(component) > 1]

    configured_by_id = {rule.rule_id: rule for rule in config.architecture.rules}
    rules = tuple(configured_by_id.get(rule.rule_id, rule) for rule in DEFAULT_RULES)
    rules += tuple(
        rule
        for rule in config.architecture.rules
        if rule.rule_id not in {item.rule_id for item in DEFAULT_RULES}
    )
    _persist_rules(connection, repository_id, rules)

    findings: list[Finding] = []
    for rule in rules:
        if not rule.enabled:
            continue
        findings.extend(
            _evaluate_rule(
                connection,
                rule=rule,
                repository_id=repository_id,
                snapshot_id=snapshot_id,
                files=files,
                symbols=symbols,
                relationships=relationships,
                relationship_evidence=relationship_evidence,
                file_by_id=file_by_id,
                fan_in=fan_in,
                fan_out=fan_out,
                cycles=cycles,
            )
        )

    _record_evaluation(
        connection,
        repository_id=repository_id,
        snapshot_id=snapshot_id,
        files=files,
        relationships=relationships,
        symbols=symbols,
        fan_in=fan_in,
        fan_out=fan_out,
        cycles=cycles,
        findings=findings,
        manage_lifecycle=manage_finding_lifecycle,
    )
    return findings

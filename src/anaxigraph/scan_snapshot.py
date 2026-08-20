"""Finalize and read the canonical graph for one scan transaction."""

from __future__ import annotations

import sqlite3
from typing import Any

from anaxigraph.architecture import Finding, evaluate_architecture
from anaxigraph.persistence.architecture_evidence import architecture_evidence
from anaxigraph.persistence.semantic_claim_carry import carry_semantic_claims
from anaxigraph.relationship_builder import RelationshipBuildResult, build_relationships


def build_snapshot_graph(
    connection: sqlite3.Connection,
    *,
    snapshot_id: int,
    prepared: list[Any],
    artifacts: dict[str, int],
    version_ids: dict[str, int],
    config: Any,
) -> RelationshipBuildResult:
    result = build_relationships(
        connection,
        snapshot_id=snapshot_id,
        prepared=prepared,
        artifacts=artifacts,
        config=config,
    )
    carry_semantic_claims(
        connection,
        snapshot_id=snapshot_id,
        prepared=prepared,
        version_ids=version_ids,
        artifacts=artifacts,
    )
    return result


def evaluate_snapshot_architecture(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    snapshot_id: int,
    config: Any,
    manage_finding_lifecycle: bool,
) -> list[Finding]:
    files, symbols, relationships = architecture_evidence(connection, snapshot_id)
    return evaluate_architecture(
        connection,
        repository_id=repository_id,
        snapshot_id=snapshot_id,
        config=config,
        files=files,
        symbols=symbols,
        relationship_evidence=relationships,
        manage_finding_lifecycle=manage_finding_lifecycle,
    )

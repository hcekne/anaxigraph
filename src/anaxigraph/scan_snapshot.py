"""Finalize and read the canonical graph for one scan transaction."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from anaxigraph.architecture import Finding, evaluate_architecture
from anaxigraph.coverage import collect_coverage
from anaxigraph.persistence.architecture_evidence import architecture_evidence
from anaxigraph.persistence.semantic_claim_carry import carry_semantic_claims
from anaxigraph.persistence.temporal_reads import (
    snapshot_files,
    snapshot_relationship_edges,
    symbols_for_files,
)
from anaxigraph.relationship_builder import RelationshipBuildResult, build_relationships


def build_snapshot_graph(
    connection: sqlite3.Connection,
    *,
    snapshot_id: int,
    base_snapshot_id: int | None,
    prepared: list[Any],
    artifacts: dict[str, int],
    config: Any,
) -> RelationshipBuildResult:
    result = build_relationships(
        connection,
        snapshot_id=snapshot_id,
        base_snapshot_id=base_snapshot_id,
        prepared=prepared,
        artifacts=artifacts,
        config=config,
    )
    carry_semantic_claims(
        connection,
        snapshot_id=snapshot_id,
        prepared=prepared,
        artifacts=artifacts,
    )
    return result


def previous_analysis_records(
    connection: sqlite3.Connection,
    snapshot_id: int | None,
) -> dict[str, dict[str, Any]]:
    if snapshot_id is None:
        return {}
    files = snapshot_files(connection, snapshot_id)
    symbols_by_fact: dict[int, list[dict[str, Any]]] = {}
    for symbol in symbols_for_files(connection, files):
        symbols_by_fact.setdefault(int(symbol["file_fact_id"]), []).append(symbol)
    result: dict[str, dict[str, Any]] = {}
    for file in files:
        value = dict(file)
        value["id"] = int(value["file_fact_id"])
        value["symbols"] = symbols_by_fact.get(value["id"], [])
        result[str(value["path"])] = value
    return result


def snapshot_artifacts(
    connection: sqlite3.Connection,
    snapshot_id: int,
) -> dict[str, int]:
    return {
        str(file["path"]): int(file["artifact_id"])
        for file in snapshot_files(connection, snapshot_id)
    }


def snapshot_counts(connection: sqlite3.Connection, snapshot_id: int) -> dict[str, int]:
    relationships = len(snapshot_relationship_edges(connection, snapshot_id))
    findings = int(
        connection.execute(
            "SELECT COUNT(*) FROM finding_occurrences WHERE snapshot_id = ?", (snapshot_id,)
        ).fetchone()[0]
    )
    return {"relationships": relationships, "findings": findings}


def refresh_snapshot_intelligence(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    snapshot_id: int,
    config: Any,
    manage_finding_lifecycle: bool,
    root: Path | None,
    artifacts: dict[str, int],
) -> tuple[list[Finding], int]:
    files, symbols, relationships = architecture_evidence(connection, snapshot_id)
    coverage_count = 0
    if root is not None:
        coverage_count = collect_coverage(
            connection,
            root=root,
            config=config,
            snapshot_id=snapshot_id,
            artifacts_by_path=artifacts,
            artifact_types={int(file["artifact_id"]): str(file["artifact_type"]) for file in files},
            relationship_evidence=relationships,
        )
    findings = evaluate_architecture(
        connection,
        repository_id=repository_id,
        snapshot_id=snapshot_id,
        config=config,
        files=files,
        symbols=symbols,
        relationship_evidence=relationships,
        manage_finding_lifecycle=manage_finding_lifecycle,
    )
    return findings, coverage_count

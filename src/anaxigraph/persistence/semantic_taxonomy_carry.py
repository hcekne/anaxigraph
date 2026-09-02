"""Carry an unchanged finalized semantic map into a new snapshot."""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from typing import Any

from anaxigraph.clock import utc_now
from anaxigraph.semantic_freshness import legacy_input_matches


@dataclass(frozen=True, slots=True)
class TaxonomyCarry:
    row: sqlite3.Row
    mode: str
    unchanged_modules: int
    total_modules: int


@dataclass(frozen=True, slots=True)
class TaxonomyStability:
    policy_hash: str
    bias: float
    eligible_paths: list[str]
    settings: dict[str, Any]
    hints: tuple[str, ...]
    locks: dict[str, str]


def carry_taxonomy(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    snapshot_id: int,
    input_hash: str,
    legacy_evidence: dict[str, Any],
    prompt_version: str,
    stability: TaxonomyStability,
) -> TaxonomyCarry | None:
    match = _carry_source(
        connection,
        repository_id=repository_id,
        snapshot_id=snapshot_id,
        input_hash=input_hash,
        legacy_evidence=legacy_evidence,
        prompt_version=prompt_version,
        stability=stability,
    )
    if match is None:
        return None
    previous, mode, unchanged, total = match
    if int(previous["snapshot_id"]) == snapshot_id:
        return TaxonomyCarry(previous, mode, unchanged, total)
    row = _copy_taxonomy(
        connection,
        previous=previous,
        repository_id=repository_id,
        snapshot_id=snapshot_id,
        input_hash=input_hash,
        source=(
            "incrementally_validated_taxonomy"
            if mode == "incremental"
            else "carried_semantic_taxonomy"
        ),
    )
    return TaxonomyCarry(row, mode, unchanged, total)


def _carry_source(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    snapshot_id: int,
    input_hash: str,
    legacy_evidence: dict[str, Any],
    prompt_version: str,
    stability: TaxonomyStability,
) -> tuple[sqlite3.Row, str, int, int] | None:
    exact = _matching_taxonomy(
        connection,
        repository_id=repository_id,
        input_hash=input_hash,
        legacy_evidence=legacy_evidence,
        prompt_version=prompt_version,
    )
    if exact is not None:
        total = len(stability.eligible_paths)
        return exact, "exact", total, total
    incremental = _incremental_taxonomy(
        connection,
        repository_id=repository_id,
        snapshot_id=snapshot_id,
        prompt_version=prompt_version,
        stability=stability,
    )
    return (*incremental[:1], "incremental", *incremental[1:]) if incremental else None


def _copy_taxonomy(
    connection: sqlite3.Connection,
    *,
    previous: sqlite3.Row,
    repository_id: int,
    snapshot_id: int,
    input_hash: str,
    source: str,
) -> sqlite3.Row:
    now = utc_now()
    cursor = connection.execute(
        """
        INSERT INTO semantic_taxonomies(
            repository_id, snapshot_id, input_hash, status, source, provider, model,
            executor_id, executor_model, prompt_version, schema_version, confidence,
            candidate_document_id, final_document_id, review_passes, validation_json,
            facets_json, change_json, created_at, updated_at
        ) VALUES (?, ?, ?, 'current', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            repository_id,
            snapshot_id,
            input_hash,
            source,
            previous["provider"],
            previous["model"],
            previous["executor_id"],
            previous["executor_model"],
            previous["prompt_version"],
            previous["schema_version"],
            previous["confidence"],
            previous["candidate_document_id"],
            previous["final_document_id"],
            previous["review_passes"],
            previous["validation_json"],
            previous["facets_json"],
            previous["change_json"],
            now,
            now,
        ),
    )
    taxonomy_id = int(cursor.lastrowid)
    _copy_nodes(connection, taxonomy_id, int(previous["id"]))
    _copy_memberships(connection, taxonomy_id, int(previous["id"]))
    _copy_reviews(connection, taxonomy_id, int(previous["id"]))
    return connection.execute(
        "SELECT * FROM semantic_taxonomies WHERE id = ?", (taxonomy_id,)
    ).fetchone()


def _copy_nodes(connection: sqlite3.Connection, taxonomy_id: int, previous_id: int) -> None:
    connection.execute(
        """
        INSERT INTO semantic_taxonomy_nodes(
            taxonomy_id, node_key, name, level, parent_key, description, responsibility,
            confidence, rationale, evidence_json, counter_evidence_json, display_order
        )
        SELECT ?, node_key, name, level, parent_key, description, responsibility,
               confidence, rationale, evidence_json, counter_evidence_json, display_order
        FROM semantic_taxonomy_nodes WHERE taxonomy_id = ?
        """,
        (taxonomy_id, previous_id),
    )


def _copy_memberships(connection: sqlite3.Connection, taxonomy_id: int, previous_id: int) -> None:
    connection.execute(
        """
        INSERT INTO semantic_taxonomy_memberships(
            taxonomy_id, artifact_id, node_key, confidence, rationale,
            evidence_json, alternatives_json, locked
        )
        SELECT ?, artifact_id, node_key, confidence, rationale,
               evidence_json, alternatives_json, locked
        FROM semantic_taxonomy_memberships WHERE taxonomy_id = ?
        """,
        (taxonomy_id, previous_id),
    )


def _copy_reviews(connection: sqlite3.Connection, taxonomy_id: int, previous_id: int) -> None:
    connection.execute(
        """
        INSERT INTO semantic_taxonomy_reviews(
            taxonomy_id, pass_index, document_id, verdict, issues_json,
            validation_json, created_at
        )
        SELECT ?, pass_index, document_id, verdict, issues_json, validation_json, created_at
        FROM semantic_taxonomy_reviews WHERE taxonomy_id = ?
        """,
        (taxonomy_id, previous_id),
    )


def _incremental_taxonomy(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    snapshot_id: int,
    prompt_version: str,
    stability: TaxonomyStability,
) -> tuple[sqlite3.Row, int, int] | None:
    rows = connection.execute(
        """
        SELECT st.*, ss.interface_hash AS stability_hash
        FROM semantic_taxonomies st
        LEFT JOIN semantic_scope_states ss
          ON ss.snapshot_id = st.snapshot_id AND ss.scope_type = 'taxonomy'
         AND ss.scope_key = CAST(st.repository_id AS TEXT)
        WHERE st.repository_id = ? AND st.status = 'current' AND st.prompt_version = ?
          AND st.snapshot_id != ?
        ORDER BY st.snapshot_id DESC, st.id DESC
        """,
        (repository_id, prompt_version, snapshot_id),
    ).fetchall()
    current_paths = set(stability.eligible_paths)
    for row in rows:
        if not _compatible_policy(row, stability):
            continue
        if _membership_paths(connection, int(row["id"])) != current_paths:
            continue
        unchanged, total = _intent_stability(
            connection,
            previous_snapshot_id=int(row["snapshot_id"]),
            snapshot_id=snapshot_id,
            eligible_paths=current_paths,
        )
        if total and unchanged >= math.ceil(total * stability.bias):
            return row, unchanged, total
    return None


def _compatible_policy(
    taxonomy: sqlite3.Row,
    stability: TaxonomyStability,
) -> bool:
    saved_hash = str(taxonomy["stability_hash"] or "")
    if saved_hash:
        return saved_hash == stability.policy_hash
    if stability.hints or stability.locks:
        return False
    validation = json.loads(taxonomy["validation_json"] or "{}")
    return (
        int(taxonomy["review_passes"] or 0) >= int(stability.settings["review_passes"])
        and int(validation.get("areas") or 0) <= int(stability.settings["max_areas"])
        and int(validation.get("subsystems") or 0) <= int(stability.settings["max_subsystems"])
    )


def _membership_paths(connection: sqlite3.Connection, taxonomy_id: int) -> set[str]:
    return {
        str(row["canonical_path"])
        for row in connection.execute(
            """
            SELECT a.canonical_path
            FROM semantic_taxonomy_memberships stm
            JOIN artifacts a ON a.id = stm.artifact_id
            WHERE stm.taxonomy_id = ?
            """,
            (taxonomy_id,),
        ).fetchall()
    }


def _intent_stability(
    connection: sqlite3.Connection,
    *,
    previous_snapshot_id: int,
    snapshot_id: int,
    eligible_paths: set[str],
) -> tuple[int, int]:
    previous = _intrinsic_intents(connection, previous_snapshot_id)
    current = _intrinsic_intents(connection, snapshot_id)
    if set(previous) != eligible_paths or set(current) != eligible_paths:
        return 0, len(eligible_paths)
    unchanged = sum(previous[path] == current[path] for path in eligible_paths)
    return unchanged, len(eligible_paths)


def _intrinsic_intents(connection: sqlite3.Connection, snapshot_id: int) -> dict[str, str]:
    rows = connection.execute(
        """
        SELECT ss.scope_key, sd.intent_fingerprint
        FROM semantic_scope_states ss
        JOIN semantic_documents sd ON sd.id = ss.intrinsic_document_id
        WHERE ss.snapshot_id = ? AND ss.scope_type = 'module'
          AND ss.status = 'current'
        """,
        (snapshot_id,),
    ).fetchall()
    return {str(row["scope_key"]): str(row["intent_fingerprint"]) for row in rows}


def _matching_taxonomy(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    input_hash: str,
    legacy_evidence: dict[str, Any],
    prompt_version: str,
) -> sqlite3.Row | None:
    rows = connection.execute(
        """
        SELECT * FROM semantic_taxonomies
        WHERE repository_id = ? AND status = 'current' AND prompt_version = ?
        ORDER BY snapshot_id DESC, id DESC
        """,
        (repository_id, prompt_version),
    ).fetchall()
    for row in rows:
        taxonomy = dict(row)
        if taxonomy["input_hash"] == input_hash or legacy_input_matches(
            taxonomy,
            legacy_evidence,
            prompt_version=prompt_version,
        ):
            return row
    return None

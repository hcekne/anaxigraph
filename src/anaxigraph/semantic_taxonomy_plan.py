"""Plan autonomous taxonomy proposal and independent agent review stages."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from anaxigraph.config import AnaxiGraphConfig, SemanticConfig
from anaxigraph.persistence.semantic_taxonomy_carry import (
    TaxonomyCarry,
    TaxonomyStability,
    carry_taxonomy,
)
from anaxigraph.semantic_freshness import (
    TAXONOMY_PROPOSAL_CONTRACT,
    TAXONOMY_REVIEW_CONTRACT,
    TAXONOMY_STABILITY_CONTRACT,
    semantic_input_hash,
)
from anaxigraph.semantic_records import _ensure_job, _member_documents, _states, _upsert_state


@dataclass(frozen=True, slots=True)
class _TaxonomyInputs:
    paths: list[str]
    documents: list[dict[str, Any]]
    missing: list[str]
    settings: dict[str, Any]
    stability_hash: str
    evidence: dict[str, Any]
    input_hash: str


class SemanticTaxonomyPlanner:
    def plan_taxonomy(
        self,
        connection: sqlite3.Connection,
        *,
        repository_id: int,
        snapshot_id: int,
        relationships: dict[str, list[dict[str, Any]]],
        config: AnaxiGraphConfig,
        retry_failed: bool,
    ) -> tuple[int, bool]:
        semantic = config.semantic
        inputs = _taxonomy_inputs(
            connection, snapshot_id=snapshot_id, relationships=relationships, config=config
        )
        if not inputs.documents:
            return 0, not inputs.paths
        taxonomy, carry = _current_or_carried_taxonomy(
            connection,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            inputs=inputs,
            config=config,
        )
        if taxonomy is not None and taxonomy["status"] == "current":
            _mark_taxonomy_current(
                connection,
                repository_id=repository_id,
                snapshot_id=snapshot_id,
                inputs=inputs,
                taxonomy=taxonomy,
                carry=carry,
            )
            return 0, True
        metadata = _taxonomy_metadata(
            connection,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            input_hash=inputs.input_hash,
            paths=inputs.paths,
            documents=inputs.documents,
            settings=inputs.settings,
            config=config,
            stability_hash=inputs.stability_hash,
        )
        if taxonomy is None:
            return self._enqueue_proposal(
                connection,
                repository_id=repository_id,
                snapshot_id=snapshot_id,
                input_hash=inputs.input_hash,
                semantic=semantic,
                metadata=metadata,
                retry_failed=retry_failed,
                stability_hash=inputs.stability_hash,
            ), False
        return self._enqueue_review(
            connection,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            input_hash=inputs.input_hash,
            semantic=semantic,
            taxonomy=taxonomy,
            metadata=metadata,
            retry_failed=retry_failed,
            stability_hash=inputs.stability_hash,
        ), False

    def _enqueue_proposal(
        self,
        connection: sqlite3.Connection,
        *,
        repository_id: int,
        snapshot_id: int,
        input_hash: str,
        semantic: SemanticConfig,
        metadata: dict[str, Any],
        retry_failed: bool,
        stability_hash: str,
    ) -> int:
        scope_status, created, error = _ensure_job(
            connection,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            scope_type="taxonomy",
            scope_key=str(repository_id),
            artifact_id=None,
            artifact_version_id=None,
            job_kind="taxonomy_proposal",
            reason="semantic_taxonomy_missing_or_stale",
            priority=45,
            input_hash=input_hash,
            semantic=semantic,
            estimated_input_tokens=max(800, len(metadata["document_ids"]) * 180),
            metadata=metadata,
            retry_failed=retry_failed,
        )
        _upsert_state(
            connection,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            scope_type="taxonomy",
            scope_key=str(repository_id),
            status=scope_status,
            reason=error or "Agent taxonomy proposal is required before scope synthesis",
            context_input_hash=input_hash,
            context_fingerprint=input_hash,
            interface_hash=stability_hash,
        )
        return int(created)

    def _enqueue_review(
        self,
        connection: sqlite3.Connection,
        *,
        repository_id: int,
        snapshot_id: int,
        input_hash: str,
        semantic: SemanticConfig,
        taxonomy: sqlite3.Row,
        metadata: dict[str, Any],
        retry_failed: bool,
        stability_hash: str,
    ) -> int:
        latest_review = connection.execute(
            """
            SELECT str.document_id, str.pass_index
            FROM semantic_taxonomy_reviews str WHERE str.taxonomy_id = ?
            ORDER BY str.pass_index DESC LIMIT 1
            """,
            (int(taxonomy["id"]),),
        ).fetchone()
        candidate_document_id = int(
            latest_review["document_id"] if latest_review else taxonomy["candidate_document_id"]
        )
        review_pass = 1 + (int(latest_review["pass_index"]) if latest_review else 0)
        validation = json.loads(taxonomy["validation_json"] or "{}")
        review_input = {
            "taxonomy_input_hash": input_hash,
            "candidate_document_id": candidate_document_id,
            "review_pass": review_pass,
            "validation": validation,
        }
        review_hash = semantic_input_hash(
            TAXONOMY_REVIEW_CONTRACT,
            semantic.prompt_version,
            review_input,
        )
        review_metadata = {**metadata, **review_input}
        scope_status, created, error = _ensure_job(
            connection,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            scope_type="taxonomy",
            scope_key=str(repository_id),
            artifact_id=None,
            artifact_version_id=None,
            job_kind="taxonomy_review",
            reason="independent_agent_taxonomy_review",
            priority=44,
            input_hash=review_hash,
            semantic=semantic,
            estimated_input_tokens=max(900, len(metadata["document_ids"]) * 160),
            metadata=review_metadata,
            retry_failed=retry_failed,
        )
        _upsert_state(
            connection,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            scope_type="taxonomy",
            scope_key=str(repository_id),
            status=scope_status,
            reason=error or f"Independent taxonomy review pass {review_pass} is required",
            context_input_hash=input_hash,
            context_fingerprint=input_hash,
            interface_hash=stability_hash,
            context_document_id=candidate_document_id,
        )
        return int(created)


def _taxonomy_inputs(
    connection: sqlite3.Connection,
    *,
    snapshot_id: int,
    relationships: dict[str, list[dict[str, Any]]],
    config: AnaxiGraphConfig,
) -> _TaxonomyInputs:
    states = _states(connection, snapshot_id, "module")
    paths = sorted(path for path, state in states.items() if state["status"] == "current")
    documents, missing = _member_documents(connection, states, paths)
    settings = _taxonomy_settings(config.semantic)
    stability_evidence = _taxonomy_stability_evidence(
        settings=settings,
        paths=paths,
        hints=config.map.hints,
        locks=config.map.locked_memberships,
    )
    stability_hash = semantic_input_hash(
        TAXONOMY_STABILITY_CONTRACT,
        config.semantic.prompt_version,
        stability_evidence,
    )
    evidence = _taxonomy_evidence(
        settings=settings,
        documents=documents,
        missing=missing,
        relationships=relationships,
        hints=config.map.hints,
        locks=config.map.locked_memberships,
    )
    input_hash = semantic_input_hash(
        TAXONOMY_PROPOSAL_CONTRACT,
        config.semantic.prompt_version,
        evidence,
    )
    return _TaxonomyInputs(
        paths, documents, missing, settings, stability_hash, evidence, input_hash
    )


def _current_or_carried_taxonomy(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    snapshot_id: int,
    inputs: _TaxonomyInputs,
    config: AnaxiGraphConfig,
) -> tuple[sqlite3.Row | None, TaxonomyCarry | None]:
    taxonomy = connection.execute(
        """
        SELECT * FROM semantic_taxonomies
        WHERE snapshot_id = ? AND input_hash = ? ORDER BY id DESC LIMIT 1
        """,
        (snapshot_id, inputs.input_hash),
    ).fetchone()
    if taxonomy is not None:
        return taxonomy, None
    carry = carry_taxonomy(
        connection,
        repository_id=repository_id,
        snapshot_id=snapshot_id,
        input_hash=inputs.input_hash,
        legacy_evidence=inputs.evidence,
        prompt_version=config.semantic.prompt_version,
        stability=TaxonomyStability(
            policy_hash=inputs.stability_hash,
            bias=config.semantic.taxonomy.stability_bias,
            eligible_paths=inputs.paths,
            settings=inputs.settings,
            hints=config.map.hints,
            locks=config.map.locked_memberships,
        ),
    )
    return (carry.row if carry else None), carry


def _mark_taxonomy_current(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    snapshot_id: int,
    inputs: _TaxonomyInputs,
    taxonomy: sqlite3.Row,
    carry: TaxonomyCarry | None,
) -> None:
    _upsert_state(
        connection,
        repository_id=repository_id,
        snapshot_id=snapshot_id,
        scope_type="taxonomy",
        scope_key=str(repository_id),
        status="current",
        reason=_current_reason(
            connection,
            snapshot_id=snapshot_id,
            repository_id=repository_id,
            taxonomy=taxonomy,
            carry=carry,
        ),
        context_input_hash=inputs.input_hash,
        context_fingerprint=inputs.input_hash,
        interface_hash=inputs.stability_hash,
        context_document_id=int(taxonomy["final_document_id"]),
    )


def _taxonomy_settings(semantic: SemanticConfig) -> dict[str, Any]:
    taxonomy = semantic.taxonomy
    return {
        "review_passes": taxonomy.review_passes,
        "max_areas": taxonomy.max_areas,
        "max_subsystems": taxonomy.max_subsystems,
        "stability_bias": taxonomy.stability_bias,
    }


def _taxonomy_evidence(
    *,
    settings: dict[str, Any],
    documents: list[dict[str, Any]],
    missing: list[str],
    relationships: dict[str, list[dict[str, Any]]],
    hints: tuple[str, ...],
    locks: dict[str, str],
) -> dict[str, Any]:
    edges = sorted(
        (
            source,
            str(edge.get("path") or ""),
            str(edge.get("type") or ""),
            str(edge.get("resolution") or ""),
        )
        for source, values in relationships.items()
        for edge in values
        if edge.get("direction") == "uses"
    )
    return {
        "settings": settings,
        "hints": hints,
        "locks": locks,
        "documents": [
            (item["scope_key"], item["intent_fingerprint"], item["input_hash"])
            for item in documents
        ],
        "missing": missing,
        "relationships": edges,
    }


def _taxonomy_metadata(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    snapshot_id: int,
    input_hash: str,
    paths: list[str],
    documents: list[dict[str, Any]],
    settings: dict[str, Any],
    config: AnaxiGraphConfig,
    stability_hash: str,
) -> dict[str, Any]:
    previous = connection.execute(
        """
        SELECT id FROM semantic_taxonomies
        WHERE repository_id = ? AND snapshot_id != ? AND status = 'current'
        ORDER BY snapshot_id DESC, id DESC LIMIT 1
        """,
        (repository_id, snapshot_id),
    ).fetchone()
    return {
        "taxonomy_input_hash": input_hash,
        "taxonomy_stability_hash": stability_hash,
        "document_ids": [int(item["id"]) for item in documents],
        "eligible_paths": paths,
        "taxonomy_settings": settings,
        "map_hints": list(config.map.hints),
        "locked_memberships": config.map.locked_memberships,
        "previous_taxonomy_id": int(previous["id"]) if previous else None,
    }


def _taxonomy_stability_evidence(
    *,
    settings: dict[str, Any],
    paths: list[str],
    hints: tuple[str, ...],
    locks: dict[str, str],
) -> dict[str, Any]:
    return {
        "settings": settings,
        "paths": paths,
        "hints": hints,
        "locks": locks,
    }


def _current_reason(
    connection: sqlite3.Connection,
    *,
    snapshot_id: int,
    repository_id: int,
    taxonomy: sqlite3.Row,
    carry: TaxonomyCarry | None,
) -> str:
    if carry is None and taxonomy["source"] == "incrementally_validated_taxonomy":
        row = connection.execute(
            """
            SELECT reason FROM semantic_scope_states
            WHERE snapshot_id = ? AND scope_type = 'taxonomy' AND scope_key = ?
            """,
            (snapshot_id, str(repository_id)),
        ).fetchone()
        if row and str(row["reason"]).startswith("Incremental validation"):
            return str(row["reason"])
    if carry is None or carry.mode == "exact":
        return "Agent-reviewed semantic taxonomy matches current module understanding"
    percentage = round(100 * carry.unchanged_modules / max(1, carry.total_modules), 1)
    return (
        "Incremental validation kept the reviewed responsibility map: "
        f"{carry.unchanged_modules} of {carry.total_modules} intrinsic module roles "
        f"remain stable ({percentage}%)"
    )

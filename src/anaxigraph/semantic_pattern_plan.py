"""Plan bounded pattern assessments after the semantic repository map is current."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from anaxigraph.pattern_candidates import build_pattern_candidate_plan
from anaxigraph.pattern_catalog import bundled_pattern_catalog
from anaxigraph.persistence.pattern_evidence_read import read_pattern_evidence
from anaxigraph.semantic_config_port import SemanticConfig
from anaxigraph.semantic_freshness import is_expired
from anaxigraph.semantic_pattern_identity import (
    pattern_assessment_input_hash,
    pattern_plan_input_hash,
    pattern_review_input_hash,
    pattern_scope_key,
)
from anaxigraph.semantic_pattern_state import (
    PATTERN_PLAN_SCOPE,
    artifact_id,
    baseline_documents,
    cached_plan_size,
    estimated_tokens,
    patterns_complete,
    remove_obsolete_candidates,
    reset_changed_candidate,
    retry_failed_patterns,
    supersede_running_mismatch,
    upsert_pattern_state,
)
from anaxigraph.semantic_records import (
    _ensure_job,
    _latest_document,
    _matching_document,
    _upsert_state,
)


class SemanticPatternPlanner:
    def plan_patterns(
        self,
        connection: sqlite3.Connection,
        *,
        repository_id: int,
        snapshot_id: int,
        semantic: SemanticConfig,
        retry_failed: bool,
    ) -> tuple[int, bool]:
        catalog = bundled_pattern_catalog()
        plan_hash = pattern_plan_input_hash(
            semantic.prompt_version,
            snapshot_id=snapshot_id,
            catalog_fingerprint=catalog.fingerprint,
            baseline_documents=baseline_documents(connection, snapshot_id),
        )
        cached = cached_plan_size(connection, snapshot_id, plan_hash, semantic.max_age_days)
        if cached is not None:
            if retry_failed:
                retry_failed_patterns(connection, snapshot_id)
            return 0, patterns_complete(connection, snapshot_id, cached)

        projection = read_pattern_evidence(connection, repository_id, snapshot_id)
        plan = build_pattern_candidate_plan(catalog, projection)
        selected = {pattern_scope_key(item.as_dict()) for item in plan.candidates}
        remove_obsolete_candidates(connection, snapshot_id, selected)
        enqueued = self._plan_selected(
            connection,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            semantic=semantic,
            retry_failed=retry_failed,
            catalog=catalog,
            projection=projection,
            plan=plan,
        )
        _upsert_state(
            connection,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            scope_type="pattern_plan",
            scope_key=PATTERN_PLAN_SCOPE,
            status="current",
            reason=f"Sparse candidate plan selected {len(plan.candidates)} pattern pairs",
            context_input_hash=plan_hash,
            context_fingerprint=plan.fingerprint,
            interface_hash=str(len(plan.candidates)),
        )
        return enqueued, patterns_complete(connection, snapshot_id, len(plan.candidates))

    def _plan_selected(
        self,
        connection: sqlite3.Connection,
        *,
        repository_id: int,
        snapshot_id: int,
        semantic: SemanticConfig,
        retry_failed: bool,
        catalog: Any,
        projection: Any,
        plan: Any,
    ) -> int:
        evidence_by_target = {item.target.key: item for item in projection.items}
        return sum(
            self._plan_candidate(
                connection,
                repository_id=repository_id,
                snapshot_id=snapshot_id,
                semantic=semantic,
                retry_failed=retry_failed,
                candidate=item.as_dict(),
                pattern=catalog.card(item.pattern_key).as_dict(),
                target_evidence=evidence_by_target[item.target.key].as_dict(),
                plan_fingerprint=plan.fingerprint,
            )
            for item in plan.candidates
        )

    def _plan_candidate(
        self,
        connection: sqlite3.Connection,
        *,
        repository_id: int,
        snapshot_id: int,
        semantic: SemanticConfig,
        retry_failed: bool,
        candidate: dict[str, Any],
        pattern: dict[str, Any],
        target_evidence: dict[str, Any],
        plan_fingerprint: str,
    ) -> int:
        scope_key = pattern_scope_key(candidate)
        assessment_hash = pattern_assessment_input_hash(candidate, semantic.prompt_version)
        reset_changed_candidate(connection, snapshot_id, scope_key, assessment_hash)
        assessment, assessment_expired = _document_status(
            connection,
            repository_id,
            scope_key,
            "pattern_assessment",
            assessment_hash,
            semantic,
        )
        metadata = _candidate_metadata(candidate, pattern, target_evidence, plan_fingerprint)
        if assessment is None:
            return _ensure_assessment(
                connection,
                repository_id,
                snapshot_id,
                scope_key,
                assessment_hash,
                semantic,
                metadata,
                retry_failed,
                force_new=assessment_expired,
            )
        return _ensure_review(
            connection,
            repository_id,
            snapshot_id,
            scope_key,
            assessment,
            semantic,
            metadata,
            retry_failed,
        )


def _ensure_assessment(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
    scope_key: str,
    input_hash: str,
    semantic: SemanticConfig,
    metadata: dict[str, Any],
    retry_failed: bool,
    *,
    force_new: bool = False,
) -> int:
    previous = _latest_document(
        connection, repository_id, "pattern", scope_key, "pattern_assessment"
    )
    job_metadata = {**metadata, "previous_document_id": previous["id"] if previous else None}
    scope_status, created, error = _ensure_job(
        connection,
        repository_id=repository_id,
        snapshot_id=snapshot_id,
        scope_type="pattern",
        scope_key=scope_key,
        artifact_id=artifact_id(connection, repository_id, metadata["candidate"]),
        artifact_version_id=None,
        job_kind="pattern_assessment",
        reason="pattern_candidate_requires_assessment",
        priority=int(metadata["candidate"]["priority"]),
        input_hash=input_hash,
        semantic=semantic,
        estimated_input_tokens=estimated_tokens(job_metadata),
        metadata=job_metadata,
        retry_failed=retry_failed,
        force_new=force_new,
    )
    upsert_pattern_state(
        connection,
        repository_id,
        snapshot_id,
        scope_key,
        metadata["candidate"],
        status=scope_status,
        reason=error or "Sparse candidate awaits agent assessment",
        assessment_hash=input_hash,
    )
    return int(created)


def _ensure_review(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
    scope_key: str,
    assessment: dict[str, Any],
    semantic: SemanticConfig,
    metadata: dict[str, Any],
    retry_failed: bool,
) -> int:
    assessment_value = json.loads(assessment["value_json"])
    review_hash = pattern_review_input_hash(
        metadata["candidate"], assessment_value, semantic.prompt_version
    )
    supersede_running_mismatch(connection, snapshot_id, scope_key, "pattern_review", review_hash)
    review, review_expired = _document_status(
        connection,
        repository_id,
        scope_key,
        "pattern_review",
        review_hash,
        semantic,
    )
    if review is not None:
        return _reuse_review(
            connection,
            repository_id,
            snapshot_id,
            scope_key,
            assessment,
            review,
            review_hash,
            metadata,
        )
    return _ensure_review_job(
        connection,
        repository_id,
        snapshot_id,
        scope_key,
        assessment,
        review_hash,
        review_expired,
        semantic,
        metadata,
        retry_failed,
    )


def _reuse_review(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
    scope_key: str,
    assessment: dict[str, Any],
    review: dict[str, Any],
    review_hash: str,
    metadata: dict[str, Any],
) -> int:
    upsert_pattern_state(
        connection,
        repository_id,
        snapshot_id,
        scope_key,
        metadata["candidate"],
        status="current",
        reason="Pattern evaluation passed independent agent critique",
        assessment_hash=str(assessment["input_hash"]),
        review_hash=review_hash,
        assessment_document_id=int(assessment["id"]),
        review_document_id=int(review["id"]),
    )
    return 0


def _ensure_review_job(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
    scope_key: str,
    assessment: dict[str, Any],
    review_hash: str,
    review_expired: bool,
    semantic: SemanticConfig,
    metadata: dict[str, Any],
    retry_failed: bool,
) -> int:
    previous = _latest_document(connection, repository_id, "pattern", scope_key, "pattern_review")
    job_metadata = {
        **metadata,
        "assessment_document_id": int(assessment["id"]),
        "previous_document_id": previous["id"] if previous else None,
    }
    scope_status, created, error = _ensure_job(
        connection,
        repository_id=repository_id,
        snapshot_id=snapshot_id,
        scope_type="pattern",
        scope_key=scope_key,
        artifact_id=artifact_id(connection, repository_id, metadata["candidate"]),
        artifact_version_id=None,
        job_kind="pattern_review",
        reason="pattern_assessment_requires_independent_critique",
        priority=int(metadata["candidate"]["priority"]),
        input_hash=review_hash,
        semantic=semantic,
        estimated_input_tokens=estimated_tokens(job_metadata),
        metadata=job_metadata,
        retry_failed=retry_failed,
        force_new=review_expired,
    )
    upsert_pattern_state(
        connection,
        repository_id,
        snapshot_id,
        scope_key,
        metadata["candidate"],
        status=scope_status,
        reason=error or "Assessment awaits independent agent critique",
        assessment_hash=str(assessment["input_hash"]),
        review_hash=review_hash,
        assessment_document_id=int(assessment["id"]),
    )
    return int(created)


def _document_status(
    connection: sqlite3.Connection,
    repository_id: int,
    scope_key: str,
    kind: str,
    input_hash: str,
    semantic: SemanticConfig,
) -> tuple[dict[str, Any] | None, bool]:
    document = _matching_document(
        connection, repository_id, "pattern", scope_key, kind, input_hash, semantic
    )
    expired = bool(
        document is not None and is_expired(document["created_at"], semantic.max_age_days)
    )
    return (None if expired else document), expired


def _candidate_metadata(
    candidate: dict[str, Any],
    pattern: dict[str, Any],
    target_evidence: dict[str, Any],
    plan_fingerprint: str,
) -> dict[str, Any]:
    return {
        "candidate": candidate,
        "pattern": pattern,
        "target_evidence": target_evidence,
        "plan_fingerprint": plan_fingerprint,
    }

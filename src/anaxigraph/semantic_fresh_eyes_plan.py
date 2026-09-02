"""Plan the fixed fresh-eyes recipe on the existing durable semantic queue."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from anaxigraph.semantic_config_port import SemanticConfig
from anaxigraph.semantic_fresh_eyes_contract import (
    FRESH_EYES_PROTOCOL_VERSION,
    fresh_eyes_plan_token,
    semantic_input_hash,
)
from anaxigraph.semantic_fresh_eyes_evidence import (
    comparison_inputs,
    document_identity,
    external_constraints,
    parsed_document,
    proposal_boundary,
    proposal_manifest,
    reference_fingerprint,
    review_context,
)
from anaxigraph.semantic_records import (
    _ensure_job,
    _latest_document,
    _matching_document,
    _upsert_state,
)

FRESH_EYES_SCOPE = "fresh_eyes"
FRESH_EYES_PLAN_KEY = "plan"
_PROPOSAL_SLOTS = ("a", "b", "c")
_STAGE_CONTRACTS = {
    "fresh_proposal": "fresh-eyes-proposal-v1",
    "fresh_adjudication": "fresh-eyes-adjudication-v1",
    "fresh_comparison": "fresh-eyes-comparison-v1",
    "fresh_review": "fresh-eyes-review-v1",
}


class FreshEyesPlanner:
    """Advance one explicitly requested review; never start model work on its own."""

    def request(
        self,
        connection: sqlite3.Connection,
        *,
        repository_id: int,
        snapshot_id: int,
        proposal_count: int,
        generation: int = 1,
    ) -> bool:
        if proposal_count not in {1, 2, 3}:
            raise ValueError("Fresh-eyes review requires one, two, or three proposals")
        existing = _plan_state(connection, snapshot_id)
        if existing is not None:
            return False
        _upsert_state(
            connection,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            scope_type=FRESH_EYES_SCOPE,
            scope_key=FRESH_EYES_PLAN_KEY,
            status="requested",
            reason="Fresh-eyes review requested; waiting for current repository understanding",
            interface_hash=fresh_eyes_plan_token(proposal_count, generation),
        )
        return True

    def plan_active(
        self,
        connection: sqlite3.Connection,
        *,
        repository_id: int,
        snapshot_id: int,
        semantic: SemanticConfig,
        retry_failed: bool,
    ) -> tuple[int, str | None]:
        plan = _plan_state(connection, snapshot_id)
        if plan is None:
            return 0, None
        context = review_context(
            connection,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            plan=plan,
            semantic=semantic,
            retry_failed=retry_failed,
        )
        if context is None:
            return 0, "fresh_eyes_waiting"
        proposals, enqueued = self._proposals(connection, **context)
        _update_plan_identity(
            connection,
            snapshot_id,
            status="active",
            reason=(
                "Capability fingerprint changed; clean-sheet proposals and the reference design "
                "must be rebuilt"
                if context["capability_changed"]
                else "Independent clean-sheet proposals are being prepared"
            ),
            capability=context["capability_fingerprint"],
        )
        if len(proposals) != context["proposal_count"]:
            return enqueued, "fresh_eyes_proposals"
        return self._advance_reference(connection, context, proposals, enqueued)

    def _advance_reference(
        self,
        connection: sqlite3.Connection,
        context: dict[str, Any],
        proposals: list[dict[str, Any]],
        enqueued: int,
    ) -> tuple[int, str]:
        adjudication, created = self._adjudication(connection, proposals=proposals, **context)
        enqueued += created
        if adjudication is None:
            return enqueued, "fresh_eyes_adjudication"
        reference_identity = reference_fingerprint(proposals, adjudication)
        return self._advance_comparison(
            connection, context, adjudication, reference_identity, enqueued
        )

    def _advance_comparison(
        self,
        connection: sqlite3.Connection,
        context: dict[str, Any],
        adjudication: dict[str, Any],
        reference_identity: str,
        enqueued: int,
    ) -> tuple[int, str]:
        comparison, comparison_fingerprint, created = self._comparison(
            connection,
            adjudication=adjudication,
            reference_fingerprint=reference_identity,
            **context,
        )
        enqueued += created
        _update_plan_identity(
            connection,
            context["snapshot_id"],
            status="active",
            reason="Reference design is being compared with the current repository",
            capability=context["capability_fingerprint"],
            reference=reference_identity,
            comparison=comparison_fingerprint,
        )
        if comparison is None:
            return enqueued, "fresh_eyes_comparison"
        review, created = self._review(
            connection,
            comparison=comparison,
            comparison_fingerprint=comparison_fingerprint,
            **context,
        )
        enqueued += created
        if review is None:
            return enqueued, "fresh_eyes_mission_filter"
        _finish_plan(
            connection,
            snapshot_id=context["snapshot_id"],
            review_id=int(review["id"]),
            capability=context["capability_fingerprint"],
            reference=reference_identity,
            comparison=comparison_fingerprint,
            final=str(review["input_hash"]),
        )
        return enqueued, "fresh_eyes_complete"

    def _proposals(
        self,
        connection: sqlite3.Connection,
        **context: Any,
    ) -> tuple[list[dict[str, Any]], int]:
        documents: list[dict[str, Any]] = []
        enqueued = 0
        for slot in _PROPOSAL_SLOTS[: int(context["proposal_count"])]:
            manifest = proposal_manifest(
                slot, context["capability_fingerprint"], context["review_generation"]
            )
            metadata = {
                "stage": "proposal",
                "slot": slot,
                "capability_brief": context["brief"],
                "external_constraints": external_constraints(context["brief"]),
                "input_manifest": manifest,
                "information_boundary": proposal_boundary(),
            }
            document, created = _document_or_job(
                connection,
                repository_id=context["repository_id"],
                snapshot_id=context["snapshot_id"],
                scope_key=f"proposal:{slot}",
                job_kind="fresh_proposal",
                reason="independent_clean_sheet_architecture_proposal",
                priority=18,
                evidence=manifest,
                metadata=metadata,
                semantic=context["semantic"],
                retry_failed=context["retry_failed"],
            )
            if document is not None:
                documents.append(document)
            enqueued += created
        return documents, enqueued

    def _adjudication(
        self,
        connection: sqlite3.Connection,
        **context: Any,
    ) -> tuple[dict[str, Any] | None, int]:
        proposal_documents = [document_identity(item) for item in context["proposals"]]
        manifest = {
            "protocol": FRESH_EYES_PROTOCOL_VERSION,
            "stage": "blind_adjudication",
            "review_generation": context["review_generation"],
            "capability_fingerprint": context["capability_fingerprint"],
            "proposals": proposal_documents,
            "included": ["capability_brief", "clean_sheet_proposals"],
            "withheld": list(proposal_boundary()["withheld"]),
        }
        return _document_or_job(
            connection,
            repository_id=context["repository_id"],
            snapshot_id=context["snapshot_id"],
            scope_key="adjudication",
            job_kind="fresh_adjudication",
            reason="blind_adjudication_of_clean_sheet_proposals",
            priority=17,
            evidence=manifest,
            metadata={
                "stage": "adjudication",
                "capability_brief": context["brief"],
                "proposal_document_ids": [int(item["id"]) for item in context["proposals"]],
                "input_manifest": manifest,
                "information_boundary": proposal_boundary(),
            },
            semantic=context["semantic"],
            retry_failed=context["retry_failed"],
        )

    def _comparison(
        self,
        connection: sqlite3.Connection,
        **context: Any,
    ) -> tuple[dict[str, Any] | None, str, int]:
        current_system, manifest, comparison_fingerprint = comparison_inputs(connection, context)
        document, created = _document_or_job(
            connection,
            repository_id=context["repository_id"],
            snapshot_id=context["snapshot_id"],
            scope_key="comparison",
            job_kind="fresh_comparison",
            reason="compare_reference_design_with_current_repository",
            priority=16,
            evidence=manifest,
            metadata={
                "stage": "comparison",
                "capability_brief": context["brief"],
                "adjudication_document_id": int(context["adjudication"]["id"]),
                "current_system": current_system,
                "input_manifest": manifest,
                "information_boundary": {"mode": "repository_aware"},
            },
            semantic=context["semantic"],
            retry_failed=context["retry_failed"],
        )
        return document, comparison_fingerprint, created

    def _review(
        self,
        connection: sqlite3.Connection,
        **context: Any,
    ) -> tuple[dict[str, Any] | None, int]:
        manifest = {
            "protocol": FRESH_EYES_PROTOCOL_VERSION,
            "stage": "mission_filter",
            "review_generation": context["review_generation"],
            "comparison_fingerprint": context["comparison_fingerprint"],
            "comparison": document_identity(context["comparison"]),
            "included": ["capability_brief", "as_built_comparison", "engineering_economics"],
        }
        return _document_or_job(
            connection,
            repository_id=context["repository_id"],
            snapshot_id=context["snapshot_id"],
            scope_key="review",
            job_kind="fresh_review",
            reason="mission_filter_and_ranked_refactor_strategy",
            priority=15,
            evidence=manifest,
            metadata={
                "stage": "mission_filter",
                "capability_brief": context["brief"],
                "comparison_document_id": int(context["comparison"]["id"]),
                "input_manifest": manifest,
                "information_boundary": {"mode": "repository_aware_mission_filter"},
            },
            semantic=context["semantic"],
            retry_failed=context["retry_failed"],
        )


def _document_or_job(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    snapshot_id: int,
    scope_key: str,
    job_kind: str,
    reason: str,
    priority: int,
    evidence: dict[str, Any],
    metadata: dict[str, Any],
    semantic: SemanticConfig,
    retry_failed: bool,
) -> tuple[dict[str, Any] | None, int]:
    input_hash = semantic_input_hash(_STAGE_CONTRACTS[job_kind], semantic.prompt_version, evidence)
    document = _matching_document(
        connection,
        repository_id,
        FRESH_EYES_SCOPE,
        scope_key,
        job_kind,
        input_hash,
        semantic,
    )
    if document is not None:
        _upsert_stage(connection, repository_id, snapshot_id, scope_key, input_hash, document)
        return parsed_document(document), 0
    return _queue_stage_job(
        connection,
        repository_id=repository_id,
        snapshot_id=snapshot_id,
        scope_key=scope_key,
        job_kind=job_kind,
        reason=reason,
        priority=priority,
        input_hash=input_hash,
        metadata=metadata,
        semantic=semantic,
        retry_failed=retry_failed,
    )


def _queue_stage_job(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    snapshot_id: int,
    scope_key: str,
    job_kind: str,
    reason: str,
    priority: int,
    input_hash: str,
    metadata: dict[str, Any],
    semantic: SemanticConfig,
    retry_failed: bool,
) -> tuple[None, int]:
    previous = _latest_document(connection, repository_id, FRESH_EYES_SCOPE, scope_key, job_kind)
    scope_status, created, error = _ensure_job(
        connection,
        repository_id=repository_id,
        snapshot_id=snapshot_id,
        scope_type=FRESH_EYES_SCOPE,
        scope_key=scope_key,
        artifact_id=None,
        artifact_version_id=None,
        job_kind=job_kind,
        reason=reason,
        priority=priority,
        input_hash=input_hash,
        semantic=semantic,
        estimated_input_tokens=max(400, len(json.dumps(metadata, default=str)) // 4),
        metadata={**metadata, "previous_document_id": previous["id"] if previous else None},
        retry_failed=retry_failed,
    )
    _upsert_state(
        connection,
        repository_id=repository_id,
        snapshot_id=snapshot_id,
        scope_type=FRESH_EYES_SCOPE,
        scope_key=scope_key,
        status=scope_status,
        reason=error or reason,
        context_input_hash=input_hash,
        context_fingerprint=input_hash,
    )
    return None, int(created)


def _plan_state(connection: sqlite3.Connection, snapshot_id: int) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT * FROM semantic_scope_states WHERE snapshot_id = ? AND scope_type = ? "
        "AND scope_key = ?",
        (snapshot_id, FRESH_EYES_SCOPE, FRESH_EYES_PLAN_KEY),
    ).fetchone()
    return dict(row) if row else None


def _upsert_stage(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
    scope_key: str,
    input_hash: str,
    document: dict[str, Any],
) -> None:
    _upsert_state(
        connection,
        repository_id=repository_id,
        snapshot_id=snapshot_id,
        scope_type=FRESH_EYES_SCOPE,
        scope_key=scope_key,
        status="current",
        reason="Fresh-eyes stage matches its versioned evidence",
        context_input_hash=input_hash,
        context_fingerprint=input_hash,
        context_document_id=int(document["id"]),
    )


def _update_plan_identity(
    connection: sqlite3.Connection,
    snapshot_id: int,
    *,
    status: str,
    reason: str,
    capability: str,
    reference: str | None = None,
    comparison: str | None = None,
) -> None:
    connection.execute(
        """
        UPDATE semantic_scope_states SET status = ?, reason = ?, intrinsic_input_hash = ?,
            context_input_hash = COALESCE(?, context_input_hash),
            relationship_hash = COALESCE(?, relationship_hash)
        WHERE snapshot_id = ? AND scope_type = ? AND scope_key = ?
        """,
        (
            status,
            reason,
            capability,
            reference,
            comparison,
            snapshot_id,
            FRESH_EYES_SCOPE,
            FRESH_EYES_PLAN_KEY,
        ),
    )


def _finish_plan(
    connection: sqlite3.Connection,
    *,
    snapshot_id: int,
    review_id: int,
    capability: str,
    reference: str,
    comparison: str,
    final: str,
) -> None:
    connection.execute(
        """
        UPDATE semantic_scope_states SET status = 'current',
            reason = 'Fresh-eyes review completed through the fixed five-stage recipe',
            intrinsic_input_hash = ?, context_input_hash = ?, relationship_hash = ?,
            context_fingerprint = ?, context_document_id = ?
        WHERE snapshot_id = ? AND scope_type = ? AND scope_key = ?
        """,
        (
            capability,
            reference,
            comparison,
            final,
            review_id,
            snapshot_id,
            FRESH_EYES_SCOPE,
            FRESH_EYES_PLAN_KEY,
        ),
    )

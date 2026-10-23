"""Durable functional hierarchy exploration with three retained alternatives per scope."""

from __future__ import annotations

from typing import Any

from anaxigraph.semantic_fresh_eyes_evidence import current_charter
from anaxigraph.semantic_fresh_eyes_functional import (
    FUNCTIONAL_PROTOCOL,
    capability_projection,
    functional_boundary,
    functional_scope_packet,
    scope_key,
    semantic_digest,
    semantic_input_hash,
)
from anaxigraph.semantic_fresh_eyes_jobs import document_or_job

_SLOTS = ("a", "b", "c", "d", "e")


def plan_functional(connection: Any, context: dict[str, Any]) -> tuple[int, str]:
    charter = current_charter(connection, context["snapshot_id"])
    if charter is None:
        return 0, "fresh_eyes_waiting"
    projection = capability_projection(charter["value"].get("capability_brief") or {})
    if context.get("goal"):
        projection["non_functional_requirements"].append(context["goal"])
        projection = capability_projection(projection)
    if not projection["purpose"]:
        return 0, "fresh_eyes_waiting"
    _revise_changed_brief(connection, context, projection)
    hierarchy, queued = _hierarchy(connection, context, projection)
    if hierarchy is None:
        return queued, "fresh_eyes_functional_brief"
    return _plan_scopes(connection, context, hierarchy, queued)


def _hierarchy(connection: Any, context: Any, projection: Any) -> tuple[Any, int]:
    return _stage(
        connection,
        context,
        key="functional:brief",
        kind="fresh_adjudication",
        stage="hierarchy",
        evidence={"capability_projection": projection, "functional_goal": context.get("goal", "")},
        metadata={"capability_projection": projection},
        priority=19,
    )


def _plan_scopes(connection: Any, context: Any, hierarchy: Any, queued: int) -> tuple[int, str]:
    comparisons = []
    complete = True
    levels = {"product": 0, "capability": 1, "subsystem": 2}
    for scope in sorted(hierarchy["value"]["scopes"], key=lambda item: levels[item["level"]]):
        packet = functional_scope_packet(hierarchy["value"], scope["id"])
        parents = _parent_proposals(connection, context["snapshot_id"], scope)
        if scope["parent_id"] and len(parents) != context["proposal_count"]:
            complete = False
            continue
        proposals, created = _proposals(connection, context, hierarchy, packet, parents)
        queued += created
        if len(proposals) != context["proposal_count"]:
            complete = False
            continue
        comparison, created = _comparison(connection, context, hierarchy, packet, proposals)
        queued += created
        if comparison is None:
            complete = False
        else:
            comparisons.append(comparison)
    _record_progress(connection, context, hierarchy, complete=False)
    if not complete:
        return queued, "fresh_eyes_proposals"
    review, created = _review(connection, context, hierarchy, comparisons)
    queued += created
    if review is None:
        return queued, "fresh_eyes_functional_review"
    _record_progress(connection, context, hierarchy, complete=True, review=review)
    return queued, "fresh_eyes_complete"


def _proposals(
    connection: Any, context: Any, hierarchy: Any, packet: Any, parents: Any
) -> tuple[list, int]:
    result, queued = [], 0
    for slot in _SLOTS[: context["proposal_count"]]:
        document, created = _stage(
            connection,
            context,
            key=scope_key(packet["scope"]["id"], "proposal", slot),
            kind="fresh_proposal",
            stage="proposal",
            evidence={
                "scope_revision": packet["revision"],
                "slot": slot,
                "parent_alternatives": [item["input_hash"] for item in parents],
            },
            metadata={
                "functional_brief_document_id": hierarchy["id"],
                "scope_id": packet["scope"]["id"],
                "slot": slot,
                "parent_proposal_document_ids": [item["id"] for item in parents],
                "required_executor": _executor(context, slot),
            },
            priority=18,
        )
        queued += created
        if document is not None:
            result.append(document)
    return result, queued


def _comparison(
    connection: Any, context: Any, hierarchy: Any, packet: Any, proposals: Any
) -> tuple[Any, int]:
    identities = [
        {"scope": item["scope_key"], "input_hash": item["input_hash"]} for item in proposals
    ]
    return _stage(
        connection,
        context,
        key=scope_key(packet["scope"]["id"], "comparison"),
        kind="fresh_comparison",
        stage="comparison",
        evidence={"scope_revision": packet["revision"], "alternatives": identities},
        metadata={
            "functional_brief_document_id": hierarchy["id"],
            "scope_id": packet["scope"]["id"],
            "proposal_document_ids": [item["id"] for item in proposals],
        },
        priority=17,
    )


def _review(connection: Any, context: Any, hierarchy: Any, comparisons: Any) -> tuple[Any, int]:
    return _stage(
        connection,
        context,
        key="functional:review",
        kind="fresh_review",
        stage="review",
        evidence={"comparisons": [item["input_hash"] for item in comparisons]},
        metadata={
            "functional_brief_document_id": hierarchy["id"],
            "comparison_document_ids": [item["id"] for item in comparisons],
        },
        priority=16,
    )


def _stage(
    connection: Any,
    context: Any,
    *,
    key: str,
    kind: str,
    stage: str,
    evidence: Any,
    metadata: Any,
    priority: int,
) -> tuple[Any, int]:
    manifest = _manifest(context, stage, evidence)
    contract = f"functional-{stage}-v2"
    fingerprint = semantic_input_hash(contract, context["semantic"].prompt_version, manifest)
    return document_or_job(
        connection,
        repository_id=context["repository_id"],
        snapshot_id=context["snapshot_id"],
        scope_key=key,
        job_kind=kind,
        reason=f"implementation_blind_functional_{stage}",
        priority=priority,
        input_hash=fingerprint,
        scope="fresh_eyes",
        metadata={
            "functional_stage": stage,
            "input_manifest": manifest,
            "information_boundary": functional_boundary(),
            **metadata,
        },
        semantic=context["semantic"],
        retry_failed=context["retry_failed"],
    )


def _manifest(context: Any, stage: str, evidence: Any) -> dict:
    return {
        "protocol": FUNCTIONAL_PROTOCOL,
        "functional_stage": stage,
        "review_generation": context["generation"],
        **evidence,
    }


def _revise_changed_brief(connection: Any, context: Any, projection: Any) -> None:
    prior = connection.execute(
        "SELECT sd.input_hash FROM semantic_scope_states ss JOIN semantic_documents sd "
        "ON sd.id=ss.context_document_id WHERE ss.snapshot_id=? AND ss.scope_type='fresh_eyes' "
        "AND ss.scope_key='functional:brief' AND ss.status='current'",
        (context["snapshot_id"],),
    ).fetchone()
    manifest = _manifest(
        context,
        "hierarchy",
        {"capability_projection": projection, "functional_goal": context.get("goal", "")},
    )
    expected = semantic_input_hash(
        "functional-hierarchy-v2", context["semantic"].prompt_version, manifest
    )
    if prior is None or prior["input_hash"] == expected:
        return
    row = connection.execute(
        "SELECT interface_hash FROM semantic_scope_states WHERE snapshot_id=? "
        "AND scope_type='fresh_eyes' AND scope_key='plan'",
        (context["snapshot_id"],),
    ).fetchone()
    context["generation"] += 1
    parts = row["interface_hash"].split(":", 2)
    parts[1] = str(context["generation"])
    connection.execute(
        "UPDATE semantic_jobs SET status='superseded',error='Functional requirements changed' "
        "WHERE snapshot_id=? AND scope_type='fresh_eyes' AND status IN ('pending','retry','running')",
        (context["snapshot_id"],),
    )
    connection.execute(
        "DELETE FROM semantic_scope_states WHERE snapshot_id=? "
        "AND scope_type='fresh_eyes' AND scope_key!='plan'",
        (context["snapshot_id"],),
    )
    connection.execute(
        "UPDATE semantic_scope_states SET interface_hash=?,status='requested',context_document_id=NULL,"
        "reason='Functional requirements changed' WHERE snapshot_id=? AND scope_type='fresh_eyes' "
        "AND scope_key='plan'",
        (":".join(parts), context["snapshot_id"]),
    )


def _record_progress(
    connection: Any, context: Any, hierarchy: Any, *, complete: bool, review: Any = None
) -> None:
    fingerprint = semantic_digest(hierarchy["value"])
    connection.execute(
        "UPDATE semantic_scope_states SET status=?,reason=?,intrinsic_input_hash=?,"
        "context_document_id=?,context_fingerprint=? WHERE snapshot_id=? "
        "AND scope_type='fresh_eyes' AND scope_key='plan'",
        (
            "current" if complete else "active",
            "Functional alternatives reviewed"
            if complete
            else "Exploring functional scopes; saved alternatives are retained",
            fingerprint,
            review["id"] if review else None,
            review["input_hash"] if review else fingerprint,
            context["snapshot_id"],
        ),
    )


def _executor(context: Any, slot: str) -> str | None:
    executors = context.get("proposal_executors") or ()
    index = _SLOTS.index(slot)
    return executors[index] if index < len(executors) and executors[index] != "any" else None


def _parent_proposals(connection: Any, snapshot_id: int, scope: Any) -> list[dict]:
    if not scope["parent_id"]:
        return []
    prefix = scope_key(scope["parent_id"], "proposal") + ":*"
    return [
        dict(row)
        for row in connection.execute(
            "SELECT sd.id,sd.input_hash FROM semantic_scope_states ss "
            "JOIN semantic_document_values sd ON sd.id=ss.context_document_id WHERE ss.snapshot_id=? "
            "AND ss.scope_type='fresh_eyes' AND ss.scope_key GLOB ? AND ss.status='current' "
            "ORDER BY ss.scope_key",
            (snapshot_id, prefix),
        ).fetchall()
    ]

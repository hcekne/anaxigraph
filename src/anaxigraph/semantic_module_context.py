"""Architectural-context semantic planning for individual modules."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from anaxigraph.semantic_config_port import SemanticConfig
from anaxigraph.semantic_freshness import MODULE_CONTEXT_CONTRACT, semantic_input_hash
from anaxigraph.semantic_graph import _expired, _module_priority
from anaxigraph.semantic_records import (
    _ensure_job,
    _latest_document,
    _matching_document,
    _state_intents,
    _states,
    _supersede_duplicate_jobs,
    _upsert_state,
)


@dataclass(frozen=True, slots=True)
class _ContextPlan:
    connection: sqlite3.Connection
    repository_id: int
    snapshot_id: int
    semantic: SemanticConfig
    retry_failed: bool
    states: dict[str, dict[str, Any]]
    intents: dict[str, str]
    interfaces: dict[str, str]


@dataclass(frozen=True, slots=True)
class _ContextModule:
    path: str
    module: dict[str, Any]
    state: dict[str, Any]
    intrinsic_id: int
    neighbors: list[dict[str, Any]]
    evidence: dict[str, Any]
    input_hash: str


def plan_context_modules(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    snapshot_id: int,
    inventory: dict[str, dict[str, Any]],
    relationships: dict[str, list[dict[str, Any]]],
    semantic: SemanticConfig,
    retry_failed: bool,
) -> int:
    states = _states(connection, snapshot_id, "module")
    plan = _ContextPlan(
        connection=connection,
        repository_id=repository_id,
        snapshot_id=snapshot_id,
        semantic=semantic,
        retry_failed=retry_failed,
        states=states,
        intents=_state_intents(connection, states),
        interfaces={path: str(state.get("interface_hash") or "") for path, state in states.items()},
    )
    return sum(
        _plan_module(plan, item)
        for path, module in inventory.items()
        if (item := _module_inputs(plan, path, module, relationships)) is not None
    )


def _module_inputs(
    plan: _ContextPlan,
    path: str,
    module: dict[str, Any],
    relationships: dict[str, list[dict[str, Any]]],
) -> _ContextModule | None:
    state = plan.states.get(path)
    if state is None or state["status"] not in {"intrinsic_current", "current"}:
        return None
    intrinsic_id = state.get("intrinsic_document_id")
    if not intrinsic_id:
        return None
    neighbors = _neighbor_evidence(
        relationships.get(path, []),
        plan.states,
        plan.interfaces,
        plan.intents,
    )
    if neighbors is None:
        return None
    evidence = {
        "intrinsic_intent": plan.intents.get(path, ""),
        "group": module.get("declared_group") or module.get("inferred_group"),
        "relationships": neighbors,
    }
    return _ContextModule(
        path,
        module,
        state,
        int(intrinsic_id),
        neighbors,
        evidence,
        semantic_input_hash(MODULE_CONTEXT_CONTRACT, plan.semantic.prompt_version, evidence),
    )


def _plan_module(plan: _ContextPlan, item: _ContextModule) -> int:
    document = _matching_document(
        plan.connection,
        plan.repository_id,
        "module",
        item.path,
        "context",
        item.input_hash,
        plan.semantic,
        legacy_evidence=item.evidence,
    )
    expired = document is not None and _expired(document["created_at"], plan.semantic.max_age_days)
    if document is not None and not expired:
        _supersede_duplicate_jobs(plan.connection, plan.snapshot_id, "module", item.path, "context")
        _record(plan, item, "current", _CURRENT_REASON, int(document["id"]))
        return 0
    return _enqueue(plan, item, expired)


def _enqueue(plan: _ContextPlan, item: _ContextModule, expired: bool) -> int:
    latest = _latest_document(plan.connection, plan.repository_id, "module", item.path, "context")
    reason = "context_missing" if latest is None else "architectural_context_changed"
    if expired:
        reason = "age_expired"
    status, created, error = _ensure_job(
        plan.connection,
        repository_id=plan.repository_id,
        snapshot_id=plan.snapshot_id,
        scope_type="module",
        scope_key=item.path,
        artifact_id=int(item.module["artifact_id"]),
        artifact_version_id=None,
        job_kind="context",
        reason=reason,
        priority=_module_priority(item.module, reason) - 10,
        input_hash=item.input_hash,
        semantic=plan.semantic,
        estimated_input_tokens=max(300, len(item.neighbors) * 180 + 500),
        metadata={
            "path": item.path,
            "intrinsic_document_id": item.intrinsic_id,
            "neighbors": [value.get("path") for value in item.neighbors if value.get("path")],
            "previous_document_id": int(latest["id"]) if latest else None,
        },
        retry_failed=plan.retry_failed,
        force_new=expired,
    )
    state = "failed_context" if status == "failed" else "pending_context"
    _record(plan, item, state, error or reason)
    return int(created)


def _record(
    plan: _ContextPlan,
    item: _ContextModule,
    status: str,
    reason: str,
    document_id: int | None = None,
) -> None:
    _upsert_state(
        plan.connection,
        repository_id=plan.repository_id,
        snapshot_id=plan.snapshot_id,
        scope_type="module",
        scope_key=item.path,
        artifact_id=int(item.module["artifact_id"]),
        artifact_version_id=None,
        status=status,
        reason=reason,
        intrinsic_input_hash=item.state.get("intrinsic_input_hash"),
        context_input_hash=item.input_hash,
        interface_hash=item.state.get("interface_hash"),
        relationship_hash=item.state.get("relationship_hash"),
        context_fingerprint=item.input_hash,
        intrinsic_document_id=item.intrinsic_id,
        context_document_id=document_id,
    )


def _neighbor_evidence(
    relationships: list[dict[str, Any]],
    states: dict[str, dict[str, Any]],
    interfaces: dict[str, str],
    intents: dict[str, str],
) -> list[dict[str, Any]] | None:
    evidence = []
    for relation in relationships:
        neighbor = str(relation.get("path") or "")
        state = states.get(neighbor)
        if state is not None and state["status"] == "pending_intrinsic" and neighbor not in intents:
            return None
        evidence.append(
            {
                **relation,
                "neighbor_interface": interfaces.get(neighbor, ""),
                "neighbor_intent": intents.get(neighbor, ""),
            }
        )
    return evidence


_CURRENT_REASON = "Intrinsic and architectural context dossiers are current"

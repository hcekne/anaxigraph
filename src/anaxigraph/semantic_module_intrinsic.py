"""Intrinsic semantic planning for individual modules."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from anaxigraph.semantic_config_port import SemanticConfig
from anaxigraph.semantic_freshness import (
    MODULE_INTRINSIC_CONTRACT,
    is_expired,
    semantic_digest,
    semantic_input_hash,
)
from anaxigraph.semantic_graph import _interface_hash, _module_priority
from anaxigraph.semantic_records import (
    _active_job,
    _ensure_job,
    _latest_document,
    _matching_document,
    _supersede_duplicate_jobs,
    _upsert_state,
)


@dataclass(frozen=True, slots=True)
class _IntrinsicContext:
    connection: sqlite3.Connection
    repository_id: int
    snapshot_id: int
    semantic: SemanticConfig
    force: bool
    retry_failed: bool


@dataclass(frozen=True, slots=True)
class _IntrinsicModule:
    path: str
    module: dict[str, Any]
    interface_hash: str
    relationship_hash: str
    evidence: dict[str, Any]
    input_hash: str


def plan_intrinsic_modules(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    snapshot_id: int,
    inventory: dict[str, dict[str, Any]],
    relationships: dict[str, list[dict[str, Any]]],
    semantic: SemanticConfig,
    force: bool,
    retry_failed: bool,
) -> int:
    context = _IntrinsicContext(
        connection,
        repository_id,
        snapshot_id,
        semantic,
        force,
        retry_failed,
    )
    return sum(
        _plan_module(context, _module_inputs(path, module, relationships, semantic))
        for path, module in inventory.items()
    )


def _module_inputs(
    path: str,
    module: dict[str, Any],
    relationships: dict[str, list[dict[str, Any]]],
    semantic: SemanticConfig,
) -> _IntrinsicModule:
    interface_hash = _interface_hash(module)
    evidence = {
        "path": path,
        "language": module["language"],
        "analyzer": module["analyzer"],
        "structural_hash": module["structural_hash"],
        "interface_hash": interface_hash,
    }
    return _IntrinsicModule(
        path=path,
        module=module,
        interface_hash=interface_hash,
        relationship_hash=semantic_digest(relationships.get(path, [])),
        evidence=evidence,
        input_hash=semantic_input_hash(
            MODULE_INTRINSIC_CONTRACT,
            semantic.prompt_version,
            evidence,
        ),
    )


def _plan_module(context: _IntrinsicContext, item: _IntrinsicModule) -> int:
    if not context.semantic.includes_path(item.path):
        _record(
            context,
            item,
            "excluded",
            "Matched semantic.exclude or did not match semantic.include",
        )
        return 0
    handled, expired = _reuse_existing(context, item)
    return 0 if handled else _enqueue(context, item, expired)


def _reuse_existing(context: _IntrinsicContext, item: _IntrinsicModule) -> tuple[bool, bool]:
    active = _active_job(
        context.connection,
        repository_id=context.repository_id,
        snapshot_id=context.snapshot_id,
        scope_type="module",
        scope_key=item.path,
        job_kind="intrinsic",
        input_hash=item.input_hash,
    )
    if active is not None and not context.force:
        _record(context, item, "pending_intrinsic", str(active.get("error") or active["reason"]))
        return True, False
    document = _matching_document(
        context.connection,
        context.repository_id,
        "module",
        item.path,
        "intrinsic",
        item.input_hash,
        context.semantic,
        legacy_evidence=item.evidence,
    )
    expired = document is not None and is_expired(
        document["created_at"], context.semantic.max_age_days
    )
    if document is None or expired or context.force:
        return False, expired
    _supersede_duplicate_jobs(
        context.connection, context.snapshot_id, "module", item.path, "intrinsic"
    )
    _record(context, item, "intrinsic_current", _CURRENT_REASON, int(document["id"]))
    return True, False


def _enqueue(context: _IntrinsicContext, item: _IntrinsicModule, expired: bool) -> int:
    latest = _latest_document(
        context.connection, context.repository_id, "module", item.path, "intrinsic"
    )
    reason = _reason(context.force, expired, latest is not None)
    scope_status, created, error = _ensure_job(
        context.connection,
        repository_id=context.repository_id,
        snapshot_id=context.snapshot_id,
        scope_type="module",
        scope_key=item.path,
        artifact_id=int(item.module["artifact_id"]),
        artifact_version_id=None,
        file_fact_id=int(item.module["file_fact_id"]),
        job_kind="intrinsic",
        reason=reason,
        priority=_module_priority(item.module, reason),
        input_hash=item.input_hash,
        semantic=context.semantic,
        estimated_input_tokens=max(250, int(item.module["lines_of_code"]) * 12),
        metadata={
            "path": item.path,
            "interface_hash": item.interface_hash,
            "relationship_hash": item.relationship_hash,
            "previous_document_id": int(latest["id"]) if latest else None,
        },
        retry_failed=context.retry_failed,
        force_new=context.force or expired,
    )
    _record(context, item, scope_status, error or reason)
    return int(created)


def _record(
    context: _IntrinsicContext,
    item: _IntrinsicModule,
    status: str,
    reason: str,
    document_id: int | None = None,
) -> None:
    _upsert_state(
        context.connection,
        repository_id=context.repository_id,
        snapshot_id=context.snapshot_id,
        scope_type="module",
        scope_key=item.path,
        artifact_id=int(item.module["artifact_id"]),
        artifact_version_id=None,
        file_fact_id=int(item.module["file_fact_id"]),
        status=status,
        reason=reason,
        intrinsic_input_hash=item.input_hash,
        interface_hash=item.interface_hash,
        relationship_hash=item.relationship_hash,
        intrinsic_document_id=document_id,
    )


def _reason(force: bool, expired: bool, has_previous: bool) -> str:
    if force:
        return "manual_full_review"
    if expired:
        return "age_expired"
    if has_previous:
        return "source_or_semantic_policy_changed"
    return "bootstrap_missing"


_CURRENT_REASON = "Intrinsic dossier matches the current source and analysis contract"

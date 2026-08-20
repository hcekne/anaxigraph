"""Intrinsic and contextual module semantic-work planning."""

from __future__ import annotations

import sqlite3
from typing import Any

from anaxigraph.config import SemanticConfig
from anaxigraph.semantic import SEMANTIC_SCHEMA_VERSION
from anaxigraph.semantic_graph import _canonical_hash, _expired, _interface_hash, _module_priority
from anaxigraph.semantic_records import (
    _active_job,
    _ensure_job,
    _latest_document,
    _matching_document,
    _state_intents,
    _states,
    _supersede_duplicate_jobs,
    _upsert_state,
)


class SemanticModulePlanningMixin:
    def _plan_intrinsic(
        self,
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
        enqueued = 0
        for path, module in inventory.items():
            interface_hash = _interface_hash(module)
            relationship_hash = _canonical_hash(relationships.get(path, []))
            input_hash = _canonical_hash(
                {
                    "schema": SEMANTIC_SCHEMA_VERSION,
                    "prompt": semantic.prompt_version,
                    "provider": semantic.provider,
                    "model": semantic.model,
                    "path": path,
                    "language": module["language"],
                    "analyzer": module["analyzer"],
                    "structural_hash": module["structural_hash"],
                    "interface_hash": interface_hash,
                }
            )
            if not semantic.includes_path(path):
                _upsert_state(
                    connection,
                    repository_id=repository_id,
                    snapshot_id=snapshot_id,
                    scope_type="module",
                    scope_key=path,
                    artifact_id=int(module["artifact_id"]),
                    artifact_version_id=None,
                    status="excluded",
                    reason="Matched semantic.exclude or did not match semantic.include",
                    intrinsic_input_hash=input_hash,
                    interface_hash=interface_hash,
                    relationship_hash=relationship_hash,
                )
                continue

            active = _active_job(
                connection,
                repository_id=repository_id,
                snapshot_id=snapshot_id,
                scope_type="module",
                scope_key=path,
                job_kind="intrinsic",
                input_hash=input_hash,
            )
            if active is not None and not force:
                _upsert_state(
                    connection,
                    repository_id=repository_id,
                    snapshot_id=snapshot_id,
                    scope_type="module",
                    scope_key=path,
                    artifact_id=int(module["artifact_id"]),
                    artifact_version_id=None,
                    status="pending_intrinsic",
                    reason=str(active.get("error") or active["reason"]),
                    intrinsic_input_hash=input_hash,
                    interface_hash=interface_hash,
                    relationship_hash=relationship_hash,
                )
                continue

            document = _matching_document(
                connection,
                repository_id,
                "module",
                path,
                "intrinsic",
                input_hash,
                semantic,
            )
            expired = document is not None and _expired(
                document["created_at"], semantic.max_age_days
            )
            if document is not None and not expired and not force:
                _supersede_duplicate_jobs(connection, snapshot_id, "module", path, "intrinsic")
                _upsert_state(
                    connection,
                    repository_id=repository_id,
                    snapshot_id=snapshot_id,
                    scope_type="module",
                    scope_key=path,
                    artifact_id=int(module["artifact_id"]),
                    artifact_version_id=None,
                    status="intrinsic_current",
                    reason="Intrinsic dossier matches the current source and semantic policy",
                    intrinsic_input_hash=input_hash,
                    interface_hash=interface_hash,
                    relationship_hash=relationship_hash,
                    intrinsic_document_id=int(document["id"]),
                )
                continue

            latest = _latest_document(connection, repository_id, "module", path, "intrinsic")
            reason = "bootstrap_missing"
            if force:
                reason = "manual_full_review"
            elif expired:
                reason = "age_expired"
            elif latest is not None:
                reason = "source_or_semantic_policy_changed"
            job_status, created, job_error = _ensure_job(
                connection,
                repository_id=repository_id,
                snapshot_id=snapshot_id,
                scope_type="module",
                scope_key=path,
                artifact_id=int(module["artifact_id"]),
                artifact_version_id=None,
                job_kind="intrinsic",
                reason=reason,
                priority=_module_priority(module, reason),
                input_hash=input_hash,
                semantic=semantic,
                estimated_input_tokens=max(250, int(module["lines_of_code"]) * 12),
                metadata={
                    "path": path,
                    "interface_hash": interface_hash,
                    "relationship_hash": relationship_hash,
                    "previous_document_id": int(latest["id"]) if latest else None,
                },
                retry_failed=retry_failed,
                force_new=force or expired,
            )
            enqueued += int(created)
            state_status = "failed_intrinsic" if job_status == "failed" else "pending_intrinsic"
            _upsert_state(
                connection,
                repository_id=repository_id,
                snapshot_id=snapshot_id,
                scope_type="module",
                scope_key=path,
                artifact_id=int(module["artifact_id"]),
                artifact_version_id=None,
                status=state_status,
                reason=job_error or reason,
                intrinsic_input_hash=input_hash,
                interface_hash=interface_hash,
                relationship_hash=relationship_hash,
            )
        return enqueued

    def _plan_context(
        self,
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
        intent_by_path = _state_intents(connection, states)
        interface_by_path = {
            path: str(state.get("interface_hash") or "") for path, state in states.items()
        }
        enqueued = 0
        for path, module in inventory.items():
            state = states.get(path)
            if state is None or state["status"] in {"excluded", "failed_intrinsic"}:
                continue
            intrinsic_id = state.get("intrinsic_document_id")
            if not intrinsic_id:
                continue
            neighbor_evidence = []
            for relation in relationships.get(path, []):
                neighbor = relation.get("path")
                neighbor_evidence.append(
                    {
                        **relation,
                        "neighbor_interface": interface_by_path.get(str(neighbor), ""),
                        "neighbor_intent": intent_by_path.get(str(neighbor), ""),
                    }
                )
            context_hash = _canonical_hash(
                {
                    "schema": SEMANTIC_SCHEMA_VERSION,
                    "prompt": semantic.prompt_version,
                    "provider": semantic.provider,
                    "model": semantic.model,
                    "intrinsic_intent": intent_by_path.get(path, ""),
                    "group": module.get("declared_group") or module.get("inferred_group"),
                    "relationships": neighbor_evidence,
                }
            )
            document = _matching_document(
                connection,
                repository_id,
                "module",
                path,
                "context",
                context_hash,
                semantic,
            )
            expired = document is not None and _expired(
                document["created_at"], semantic.max_age_days
            )
            if document is not None and not expired:
                _supersede_duplicate_jobs(connection, snapshot_id, "module", path, "context")
                _upsert_state(
                    connection,
                    repository_id=repository_id,
                    snapshot_id=snapshot_id,
                    scope_type="module",
                    scope_key=path,
                    artifact_id=int(module["artifact_id"]),
                    artifact_version_id=None,
                    status="current",
                    reason="Intrinsic and architectural context dossiers are current",
                    intrinsic_input_hash=state.get("intrinsic_input_hash"),
                    context_input_hash=context_hash,
                    interface_hash=state.get("interface_hash"),
                    relationship_hash=state.get("relationship_hash"),
                    context_fingerprint=context_hash,
                    intrinsic_document_id=int(intrinsic_id),
                    context_document_id=int(document["id"]),
                )
                continue

            latest = _latest_document(connection, repository_id, "module", path, "context")
            reason = "context_missing" if latest is None else "architectural_context_changed"
            if expired:
                reason = "age_expired"
            job_status, created, job_error = _ensure_job(
                connection,
                repository_id=repository_id,
                snapshot_id=snapshot_id,
                scope_type="module",
                scope_key=path,
                artifact_id=int(module["artifact_id"]),
                artifact_version_id=None,
                job_kind="context",
                reason=reason,
                priority=_module_priority(module, reason) - 10,
                input_hash=context_hash,
                semantic=semantic,
                estimated_input_tokens=max(300, len(neighbor_evidence) * 180 + 500),
                metadata={
                    "path": path,
                    "intrinsic_document_id": int(intrinsic_id),
                    "neighbors": [
                        item.get("path") for item in neighbor_evidence if item.get("path")
                    ],
                    "previous_document_id": int(latest["id"]) if latest else None,
                },
                retry_failed=retry_failed,
                force_new=expired,
            )
            enqueued += int(created)
            _upsert_state(
                connection,
                repository_id=repository_id,
                snapshot_id=snapshot_id,
                scope_type="module",
                scope_key=path,
                artifact_id=int(module["artifact_id"]),
                artifact_version_id=None,
                status="failed_context" if job_status == "failed" else "pending_context",
                reason=job_error or reason,
                intrinsic_input_hash=state.get("intrinsic_input_hash"),
                context_input_hash=context_hash,
                interface_hash=state.get("interface_hash"),
                relationship_hash=state.get("relationship_hash"),
                context_fingerprint=context_hash,
                intrinsic_document_id=int(intrinsic_id),
            )
        return enqueued

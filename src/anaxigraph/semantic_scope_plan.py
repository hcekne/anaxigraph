"""Repository-, group-, and orchestration-level semantic-work planning."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from anaxigraph.config import AnaxiGraphConfig, SemanticConfig
from anaxigraph.persistence.semantic_evidence import semantic_inventory
from anaxigraph.semantic import SEMANTIC_SCHEMA_VERSION
from anaxigraph.semantic_graph import _canonical_hash, _expired
from anaxigraph.semantic_records import (
    _ensure_job,
    _has_active_module_stage,
    _has_active_scope,
    _latest_document,
    _matching_document,
    _member_documents,
    _states,
    _upsert_state,
)
from anaxigraph.storage import utc_now


@dataclass(frozen=True, slots=True)
class SemanticPlan:
    repository_id: int
    snapshot_id: int
    enqueued: int
    active_jobs: int
    stage: str
    status: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "repository_id": self.repository_id,
            "snapshot_id": self.snapshot_id,
            "enqueued": self.enqueued,
            "active_jobs": self.active_jobs,
            "stage": self.stage,
            "semantic": self.status,
        }


class SemanticScopePlanningMixin:
    def plan(
        self,
        repository_id: int,
        repository: str | Path,
        config: AnaxiGraphConfig,
        *,
        force: bool = False,
        retry_failed: bool = False,
    ) -> SemanticPlan:
        root = Path(repository).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"Repository does not exist or is not a directory: {root}")
        snapshot = self.database.latest_snapshot(repository_id)
        if snapshot is None:
            raise ValueError("Repository has not been scanned")
        snapshot_id = int(snapshot["id"])
        semantic = config.semantic
        if not semantic.enabled:
            status = self.status(repository_id, semantic)
            return SemanticPlan(repository_id, snapshot_id, 0, 0, "disabled", status)

        with self.database.transaction() as connection:
            now = utc_now()
            stale_before = (
                datetime.now(UTC) - timedelta(seconds=max(90, semantic.timeout_seconds + 60))
            ).isoformat()
            connection.execute(
                """
                UPDATE semantic_jobs SET status = 'retry', available_at = ?,
                    worker_id = NULL, lease_expires_at = NULL, lease_token_hash = NULL,
                    error = 'The previous worker lease expired; this job was safely requeued.'
                WHERE repository_id = ? AND status = 'running'
                  AND (lease_expires_at < ? OR (lease_expires_at IS NULL AND started_at < ?))
                """,
                (now, repository_id, now, stale_before),
            )
            connection.execute(
                """
                UPDATE semantic_jobs SET status = 'superseded', completed_at = ?,
                    worker_id = NULL, lease_expires_at = NULL, lease_token_hash = NULL,
                    error = 'A newer repository snapshot replaced this job.'
                WHERE repository_id = ? AND snapshot_id != ?
                  AND status IN ('pending', 'retry', 'running')
                """,
                (utc_now(), repository_id, snapshot_id),
            )
            inventory, relationships = semantic_inventory(connection, snapshot_id)
            enqueued = self._plan_intrinsic(
                connection,
                repository_id=repository_id,
                snapshot_id=snapshot_id,
                inventory=inventory,
                relationships=relationships,
                semantic=semantic,
                force=force,
                retry_failed=retry_failed,
            )
            stage = "intrinsic"
            if not _has_active_module_stage(connection, snapshot_id, "intrinsic"):
                enqueued += self._plan_context(
                    connection,
                    repository_id=repository_id,
                    snapshot_id=snapshot_id,
                    inventory=inventory,
                    relationships=relationships,
                    semantic=semantic,
                    retry_failed=retry_failed,
                )
                stage = "context"
            if not _has_active_module_stage(connection, snapshot_id, "context"):
                group_jobs = self._plan_groups(
                    connection,
                    repository_id=repository_id,
                    snapshot_id=snapshot_id,
                    inventory=inventory,
                    config=config,
                    semantic=semantic,
                    retry_failed=retry_failed,
                )
                enqueued += group_jobs
                stage = "groups"
                if not _has_active_scope(connection, snapshot_id, "group"):
                    enqueued += self._plan_repository(
                        connection,
                        repository_id=repository_id,
                        snapshot_id=snapshot_id,
                        inventory=inventory,
                        semantic=semantic,
                        retry_failed=retry_failed,
                    )
                    stage = "repository"
            active_jobs = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM semantic_jobs
                    WHERE repository_id = ? AND snapshot_id = ?
                      AND status IN ('pending', 'retry', 'running')
                    """,
                    (repository_id, snapshot_id),
                ).fetchone()[0]
            )
        return SemanticPlan(
            repository_id,
            snapshot_id,
            enqueued,
            active_jobs,
            stage,
            self.status(repository_id, semantic),
        )

    def _plan_groups(
        self,
        connection: sqlite3.Connection,
        *,
        repository_id: int,
        snapshot_id: int,
        inventory: dict[str, dict[str, Any]],
        config: AnaxiGraphConfig,
        semantic: SemanticConfig,
        retry_failed: bool,
    ) -> int:
        states = _states(connection, snapshot_id, "module")
        parent_by_group = {group.name: group.parent for group in config.groups}
        members: dict[str, set[str]] = {}
        for path, module in inventory.items():
            state = states.get(path)
            if state is None or state["status"] == "excluded":
                continue
            group = str(module.get("declared_group") or module.get("inferred_group") or "ungrouped")
            seen = set()
            while group and group not in seen:
                seen.add(group)
                members.setdefault(group, set()).add(path)
                group = str(parent_by_group.get(group) or "")

        enqueued = 0
        for group, paths in sorted(members.items()):
            documents, missing = _member_documents(connection, states, sorted(paths))
            input_hash = _canonical_hash(
                {
                    "schema": SEMANTIC_SCHEMA_VERSION,
                    "prompt": semantic.prompt_version,
                    "provider": semantic.provider,
                    "model": semantic.model,
                    "scope": group,
                    "documents": [
                        (
                            item["scope_key"],
                            item["intent_fingerprint"],
                            item["input_hash"],
                        )
                        for item in documents
                    ],
                    "missing": missing,
                }
            )
            document = _matching_document(
                connection,
                repository_id,
                "group",
                group,
                "synthesis",
                input_hash,
                semantic,
            )
            expired = document is not None and _expired(
                document["created_at"], semantic.max_age_days
            )
            if document is not None and not expired:
                _upsert_state(
                    connection,
                    repository_id=repository_id,
                    snapshot_id=snapshot_id,
                    scope_type="group",
                    scope_key=group,
                    status="current",
                    reason="Group synthesis matches current module dossiers",
                    context_input_hash=input_hash,
                    context_fingerprint=input_hash,
                    context_document_id=int(document["id"]),
                )
                continue
            job_status, created, job_error = _ensure_job(
                connection,
                repository_id=repository_id,
                snapshot_id=snapshot_id,
                scope_type="group",
                scope_key=group,
                artifact_id=None,
                artifact_version_id=None,
                job_kind="synthesis",
                reason="group_understanding_missing_or_stale",
                priority=30 + len(paths),
                input_hash=input_hash,
                semantic=semantic,
                estimated_input_tokens=max(400, len(documents) * 220),
                metadata={
                    "document_ids": [int(item["id"]) for item in documents],
                    "missing_members": missing,
                    "previous_document_id": (
                        int(latest["id"])
                        if (
                            latest := _latest_document(
                                connection, repository_id, "group", group, "synthesis"
                            )
                        )
                        else None
                    ),
                },
                retry_failed=retry_failed,
                force_new=expired,
            )
            enqueued += int(created)
            _upsert_state(
                connection,
                repository_id=repository_id,
                snapshot_id=snapshot_id,
                scope_type="group",
                scope_key=group,
                status="failed_synthesis" if job_status == "failed" else "pending_synthesis",
                reason=job_error or "group_understanding_missing_or_stale",
                context_input_hash=input_hash,
                context_fingerprint=input_hash,
            )
        return enqueued

    def _plan_repository(
        self,
        connection: sqlite3.Connection,
        *,
        repository_id: int,
        snapshot_id: int,
        inventory: dict[str, dict[str, Any]],
        semantic: SemanticConfig,
        retry_failed: bool,
    ) -> int:
        group_states = _states(connection, snapshot_id, "group")
        group_documents, missing = _member_documents(connection, group_states, sorted(group_states))
        if not group_documents and inventory:
            return 0
        input_hash = _canonical_hash(
            {
                "schema": SEMANTIC_SCHEMA_VERSION,
                "prompt": semantic.prompt_version,
                "provider": semantic.provider,
                "model": semantic.model,
                "documents": [
                    (
                        item["scope_key"],
                        item["intent_fingerprint"],
                        item["input_hash"],
                    )
                    for item in group_documents
                ],
                "missing": missing,
            }
        )
        document = _matching_document(
            connection,
            repository_id,
            "repository",
            str(repository_id),
            "synthesis",
            input_hash,
            semantic,
        )
        expired = document is not None and _expired(document["created_at"], semantic.max_age_days)
        if document is not None and not expired:
            _upsert_state(
                connection,
                repository_id=repository_id,
                snapshot_id=snapshot_id,
                scope_type="repository",
                scope_key=str(repository_id),
                status="current",
                reason="Repository synthesis matches current group understanding",
                context_input_hash=input_hash,
                context_fingerprint=input_hash,
                context_document_id=int(document["id"]),
            )
            return 0
        job_status, created, job_error = _ensure_job(
            connection,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            scope_type="repository",
            scope_key=str(repository_id),
            artifact_id=None,
            artifact_version_id=None,
            job_kind="synthesis",
            reason="repository_understanding_missing_or_stale",
            priority=20,
            input_hash=input_hash,
            semantic=semantic,
            estimated_input_tokens=max(500, len(group_documents) * 300),
            metadata={
                "document_ids": [int(item["id"]) for item in group_documents],
                "missing_members": missing,
                "previous_document_id": (
                    int(latest["id"])
                    if (
                        latest := _latest_document(
                            connection,
                            repository_id,
                            "repository",
                            str(repository_id),
                            "synthesis",
                        )
                    )
                    else None
                ),
            },
            retry_failed=retry_failed,
            force_new=expired,
        )
        _upsert_state(
            connection,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            scope_type="repository",
            scope_key=str(repository_id),
            status="failed_synthesis" if job_status == "failed" else "pending_synthesis",
            reason=job_error or "repository_understanding_missing_or_stale",
            context_input_hash=input_hash,
            context_fingerprint=input_hash,
        )
        return int(created)

"""Repository-, group-, and orchestration-level semantic-work planning."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anaxigraph.config import AnaxiGraphConfig, SemanticConfig
from anaxigraph.persistence.search_read import refresh_search_projection
from anaxigraph.persistence.semantic_evidence import semantic_inventory
from anaxigraph.semantic_freshness import (
    GROUP_SYNTHESIS_CONTRACT,
    REPOSITORY_SYNTHESIS_CONTRACT,
    is_expired,
    semantic_input_hash,
)
from anaxigraph.semantic_group_membership import synthesis_groups
from anaxigraph.semantic_leases import SemanticLeaseService
from anaxigraph.semantic_module_context import plan_context_modules
from anaxigraph.semantic_module_intrinsic import plan_intrinsic_modules
from anaxigraph.semantic_ports import (
    SemanticFreshEyesPlanningPort,
    SemanticIndex,
    SemanticPatternPlanningPort,
    SemanticReportingPort,
)
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
from anaxigraph.semantic_taxonomy_plan import SemanticTaxonomyPlanner


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


class SemanticPlanningService:
    def __init__(
        self,
        database: SemanticIndex,
        reporting: SemanticReportingPort,
        leases: SemanticLeaseService,
        taxonomy: SemanticTaxonomyPlanner,
        patterns: SemanticPatternPlanningPort,
        fresh_eyes: SemanticFreshEyesPlanningPort,
    ) -> None:
        self._database = database
        self._reporting = reporting
        self._leases = leases
        self._taxonomy = taxonomy
        self._patterns = patterns
        self._fresh_eyes = fresh_eyes

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
        if (snapshot := self._database.latest_snapshot(repository_id)) is None:
            raise ValueError("Repository has not been scanned")
        snapshot_id = int(snapshot["id"])
        semantic = config.semantic
        if not semantic.enabled:
            status = self._reporting.status(repository_id, semantic)
            return SemanticPlan(repository_id, snapshot_id, 0, 0, "disabled", status)

        with self._database.transaction() as connection:
            self._leases.reconcile(connection, repository_id, snapshot_id, semantic)
            inventory, relationships = semantic_inventory(connection, snapshot_id)
            enqueued = plan_intrinsic_modules(
                connection,
                repository_id=repository_id,
                snapshot_id=snapshot_id,
                inventory=inventory,
                relationships=relationships,
                semantic=semantic,
                force=force,
                retry_failed=retry_failed,
            )
            intrinsic_active = _has_active_module_stage(connection, snapshot_id, "intrinsic")
            enqueued += plan_context_modules(
                connection,
                repository_id=repository_id,
                snapshot_id=snapshot_id,
                inventory=inventory,
                relationships=relationships,
                semantic=semantic,
                retry_failed=retry_failed,
            )
            stage = "intrinsic" if intrinsic_active else "context"
            downstream_jobs, downstream_stage = self._plan_downstream(
                connection,
                repository_id=repository_id,
                snapshot_id=snapshot_id,
                inventory=inventory,
                relationships=relationships,
                config=config,
                retry_failed=retry_failed,
            )
            enqueued += downstream_jobs
            stage = downstream_stage or stage
            refresh_search_projection(connection, repository_id, snapshot_id, force=bool(enqueued))
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
            self._reporting.status(repository_id, semantic),
        )

    def _plan_downstream(
        self,
        connection: sqlite3.Connection,
        *,
        repository_id: int,
        snapshot_id: int,
        inventory: dict[str, dict[str, Any]],
        relationships: dict[str, list[dict[str, Any]]],
        config: AnaxiGraphConfig,
        retry_failed: bool,
    ) -> tuple[int, str | None]:
        if _has_active_module_stage(connection, snapshot_id, "context"):
            return 0, None
        semantic = config.semantic
        enqueued = 0
        if semantic.taxonomy.enabled:
            taxonomy_jobs, taxonomy_current = self._taxonomy.plan_taxonomy(
                connection,
                repository_id=repository_id,
                snapshot_id=snapshot_id,
                relationships=relationships,
                config=config,
                retry_failed=retry_failed,
            )
            if not taxonomy_current:
                return taxonomy_jobs, "taxonomy"
            enqueued += taxonomy_jobs
        aggregate_jobs, stage = self._plan_aggregates_and_patterns(
            connection,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            inventory=inventory,
            config=config,
            retry_failed=retry_failed,
        )
        return enqueued + aggregate_jobs, stage

    def _plan_aggregates_and_patterns(
        self,
        connection: sqlite3.Connection,
        *,
        repository_id: int,
        snapshot_id: int,
        inventory: dict[str, dict[str, Any]],
        config: AnaxiGraphConfig,
        retry_failed: bool,
    ) -> tuple[int, str]:
        semantic = config.semantic
        enqueued = self._plan_groups(
            connection,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            inventory=inventory,
            config=config,
            semantic=semantic,
            retry_failed=retry_failed,
        )
        if _has_active_scope(connection, snapshot_id, "group"):
            return enqueued, "groups"
        enqueued += self._plan_repository(
            connection,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            inventory=inventory,
            semantic=semantic,
            retry_failed=retry_failed,
        )
        if not _scope_is_current(connection, snapshot_id, "repository"):
            return enqueued, "repository"
        pattern_jobs, patterns_current = self._patterns.plan_patterns(
            connection,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            semantic=semantic,
            retry_failed=retry_failed,
        )
        enqueued += pattern_jobs
        if not patterns_current:
            return enqueued, "patterns"
        review_jobs, review_stage = self._fresh_eyes.plan_active(
            connection,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            semantic=semantic,
            retry_failed=retry_failed,
        )
        return enqueued + review_jobs, review_stage or "complete"

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
        members, group_metadata = synthesis_groups(
            connection,
            snapshot_id=snapshot_id,
            inventory=inventory,
            config=config,
        )

        enqueued = 0
        for group, paths in sorted(members.items()):
            active_paths = [
                path
                for path in sorted(paths)
                if states.get(path) and states[path]["status"] != "excluded"
            ]
            documents, missing = _member_documents(connection, states, active_paths)
            metadata = group_metadata.get(group) or {"node_key": group, "name": group}
            taxonomy_fingerprint = {
                key: value for key, value in metadata.items() if key != "taxonomy_id"
            }
            evidence = _group_synthesis_evidence(group, taxonomy_fingerprint, documents, missing)
            input_hash = semantic_input_hash(
                GROUP_SYNTHESIS_CONTRACT,
                semantic.prompt_version,
                evidence,
            )
            document = _matching_document(
                connection,
                repository_id,
                "group",
                group,
                "synthesis",
                input_hash,
                semantic,
                legacy_evidence=evidence,
            )
            expired = document is not None and is_expired(
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
            scope_status, created, job_error = _ensure_job(
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
                    "taxonomy": metadata,
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
                status=scope_status,
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
        evidence = {
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
        input_hash = semantic_input_hash(
            REPOSITORY_SYNTHESIS_CONTRACT,
            semantic.prompt_version,
            evidence,
        )
        document = _matching_document(
            connection,
            repository_id,
            "repository",
            str(repository_id),
            "synthesis",
            input_hash,
            semantic,
            legacy_evidence=evidence,
        )
        expired = document is not None and is_expired(document["created_at"], semantic.max_age_days)
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
        scope_status, created, job_error = _ensure_job(
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
            status=scope_status,
            reason=job_error or "repository_understanding_missing_or_stale",
            context_input_hash=input_hash,
            context_fingerprint=input_hash,
        )
        return int(created)


def _group_synthesis_evidence(
    group: str,
    taxonomy: dict[str, Any],
    documents: list[dict[str, Any]],
    missing: list[str],
) -> dict[str, Any]:
    return {
        "scope": group,
        "taxonomy": taxonomy,
        "documents": [
            (item["scope_key"], item["intent_fingerprint"], item["input_hash"])
            for item in documents
        ],
        "missing": missing,
    }


def _scope_is_current(connection: sqlite3.Connection, snapshot_id: int, scope_type: str) -> bool:
    row = connection.execute(
        """
        SELECT status FROM semantic_scope_states
        WHERE snapshot_id = ? AND scope_type = ? LIMIT 1
        """,
        (snapshot_id, scope_type),
    ).fetchone()
    return bool(row and row["status"] == "current")

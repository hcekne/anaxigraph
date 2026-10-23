"""Repository-, group-, and orchestration-level semantic-work planning."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from anaxigraph.architecture_plan import plan_requested
from anaxigraph.knowledge_annotation_plan import plan_annotations
from anaxigraph.knowledge_grouping import refresh_grouping
from anaxigraph.persistence.lock_holds import measured_plan_transaction
from anaxigraph.persistence.search_read import defer_search_projection, refresh_search_projection
from anaxigraph.persistence.semantic_evidence import semantic_inventory
from anaxigraph.semantic_freshness import (
    GROUP_SYNTHESIS_CONTRACT,
    REPOSITORY_SYNTHESIS_CONTRACT,
    is_expired,
    semantic_input_hash,
)
from anaxigraph.semantic_group_membership import group_synthesis_evidence, synthesis_groups
from anaxigraph.semantic_leases import SemanticLeaseService
from anaxigraph.semantic_plan_result import SemanticPlan as SemanticPlan
from anaxigraph.semantic_ports import (
    AnaxiGraphConfig,
    SemanticConfig,
    SemanticFreshEyesPlanningPort,
    SemanticIndex,
    SemanticPatternPlanningPort,
    SemanticReportingPort,
    SemanticTaxonomyPlanningPort,
)
from anaxigraph.semantic_records import (
    _ensure_job,
    _has_active_module_stage,
    _has_active_scope,
    _latest_document,
    _matching_document,
    _member_documents,
    _states,
    _supersede_duplicate_jobs,
    _upsert_state,
)


class SemanticPlanningService:
    def __init__(
        self,
        database: SemanticIndex,
        reporting: SemanticReportingPort,
        leases: SemanticLeaseService,
        taxonomy: SemanticTaxonomyPlanningPort,
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
        preserve_patterns: bool = False,
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

        options = dict(force=force, retry_failed=retry_failed, preserve_patterns=preserve_patterns)
        try:
            enqueued, active_jobs, stage = self._plan_work(
                repository_id, snapshot_id, config, **options
            )
        except sqlite3.OperationalError as error:
            if getattr(error, "sqlite_errorcode", None) != sqlite3.SQLITE_FULL:
                raise
            enqueued, active_jobs, stage = self._plan_work(
                repository_id, snapshot_id, config, defer_search=True, **options
            )
            self._database.finish_cache_maintenance()
        return SemanticPlan(
            repository_id,
            snapshot_id,
            enqueued,
            active_jobs,
            stage,
            self._reporting.status(repository_id, semantic),
        )

    def _plan_work(
        self,
        repository_id,
        snapshot_id,
        config,
        *,
        force,
        retry_failed,
        preserve_patterns,
        defer_search=False,
    ):
        with measured_plan_transaction(self._database.connect, snapshot_id) as connection:
            if defer_search:
                defer_search_projection(connection)
            self._leases.reconcile(
                connection,
                repository_id,
                snapshot_id,
                config.semantic,
                preserve_patterns=preserve_patterns,
            )
            enqueued, stage = self._plan_scopes(
                connection,
                repository_id,
                snapshot_id,
                config,
                force=force,
                retry_failed=retry_failed,
            )
            if not defer_search:
                refresh_search_projection(
                    connection, repository_id, snapshot_id, force=bool(enqueued)
                )
            active = self._leases.unfinished_job_count(connection, repository_id, snapshot_id)
        return enqueued, active, stage

    def _plan_scopes(self, connection, repository_id, snapshot_id, config, *, force, retry_failed):
        inventory, relationships = semantic_inventory(connection, snapshot_id)
        enqueued = plan_annotations(
            connection,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            inventory=inventory,
            relationships=relationships,
            semantic=config.semantic,
            force=force,
            retry_failed=retry_failed,
        )
        downstream, stage = self._plan_downstream(
            connection,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            inventory=inventory,
            relationships=relationships,
            config=config,
            retry_failed=retry_failed,
        )
        return enqueued + downstream, stage or "annotation"

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
        if _has_active_module_stage(connection, snapshot_id, "annotation"):
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
        refresh_grouping(connection, snapshot_id)
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
        optional_jobs, stage = self._plan_optional_reviews(
            connection, repository_id, snapshot_id, semantic, retry_failed
        )
        return enqueued + optional_jobs, stage

    def _plan_optional_reviews(
        self,
        connection: Any,
        repository_id: int,
        snapshot_id: int,
        semantic: Any,
        retry_failed: bool,
    ) -> tuple[int, str]:
        pattern_jobs, patterns_current = self._patterns.plan_patterns(
            connection,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            semantic=semantic,
            retry_failed=retry_failed,
        )
        review_jobs, review_stage = self._fresh_eyes.plan_active(
            connection,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            semantic=semantic,
            retry_failed=retry_failed,
        )
        plan_jobs = plan_requested(
            connection,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            semantic=semantic,
            retry_failed=retry_failed,
        )
        return pattern_jobs + review_jobs + plan_jobs, review_stage or (
            "architecture_plan" if plan_jobs else "patterns" if not patterns_current else "complete"
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
            evidence = group_synthesis_evidence(group, taxonomy_fingerprint, documents, missing)
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
                _supersede_duplicate_jobs(connection, snapshot_id, "group", group, "synthesis")
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
            _supersede_duplicate_jobs(
                connection, snapshot_id, "repository", str(repository_id), "synthesis"
            )
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


def _scope_is_current(connection: sqlite3.Connection, snapshot_id: int, scope_type: str) -> bool:
    row = connection.execute(
        """
        SELECT status FROM semantic_scope_states
        WHERE snapshot_id = ? AND scope_type = ? LIMIT 1
        """,
        (snapshot_id, scope_type),
    ).fetchone()
    return bool(row and row["status"] == "current")

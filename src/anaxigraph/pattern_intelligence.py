"""Application service for current pattern-intelligence projections."""

from __future__ import annotations

from typing import Any

from anaxigraph.pattern_candidate_query import (
    PatternCandidateQuery,
    empty_pattern_candidates,
    query_pattern_candidates,
)
from anaxigraph.pattern_catalog import bundled_pattern_catalog
from anaxigraph.pattern_query import PatternEvaluationQuery
from anaxigraph.persistence.pattern_candidate_read import pattern_selection_state
from anaxigraph.persistence.pattern_evaluation_read import (
    empty_pattern_evaluations,
    read_pattern_evaluations,
)
from anaxigraph.persistence.pattern_evidence_read import read_pattern_evidence


class PatternIntelligenceService:
    def __init__(self, database: Any) -> None:
        self.database = database

    def query(
        self,
        repository_id: int,
        snapshot_id: int | None = None,
        *,
        request: PatternEvaluationQuery | None = None,
    ) -> dict[str, Any]:
        query = request or PatternEvaluationQuery()
        snapshot = self.database._resolve_snapshot(repository_id, snapshot_id)
        if snapshot is None:
            return empty_pattern_evaluations(repository_id, query)
        with self.database.connect() as connection:
            return read_pattern_evaluations(
                connection,
                repository_id,
                int(snapshot["id"]),
                query,
            )

    def candidates(
        self,
        repository_id: int,
        snapshot_id: int | None = None,
        *,
        request: PatternCandidateQuery,
    ) -> dict[str, Any]:
        catalog = bundled_pattern_catalog()
        if catalog.card(request.pattern) is None:
            raise ValueError(f"unknown pattern key: {request.pattern}")
        snapshot = self.database._resolve_snapshot(repository_id, snapshot_id)
        if snapshot is None:
            return empty_pattern_candidates(repository_id, request)
        selected, plan_ready, projection = self._candidate_inputs(
            repository_id, int(snapshot["id"]), request.pattern, request.target
        )
        return query_pattern_candidates(
            catalog,
            projection,
            request,
            selected_target_keys=selected,
            plan_ready=plan_ready,
        )

    def query_targets(
        self,
        repository_id: int,
        snapshot_id: int,
        targets: list[str],
        *,
        limit_per_target: int = 20,
    ) -> list[dict[str, Any]]:
        items = []
        for target in targets:
            page = self.query(
                repository_id,
                snapshot_id,
                request=PatternEvaluationQuery(
                    target=target,
                    sort_by="opportunity",
                    limit=limit_per_target,
                    include_evidence=True,
                ),
            )
            items.extend(page.get("items") or [])
        return items

    def _candidate_inputs(
        self,
        repository_id: int,
        snapshot_id: int,
        pattern_key: str,
        target: str,
    ) -> tuple[set[str], bool, Any]:
        with self.database.connect() as connection:
            selected, plan_ready = pattern_selection_state(connection, snapshot_id, pattern_key)
            projection = read_pattern_evidence(
                connection,
                repository_id,
                snapshot_id,
                target=target,
            )
        return selected, plan_ready, projection

"""Application service for current pattern-intelligence projections."""

from __future__ import annotations

from typing import Any

from anaxigraph.pattern_query import PatternEvaluationQuery
from anaxigraph.persistence.pattern_evaluation_read import (
    empty_pattern_evaluations,
    read_pattern_evaluations,
)


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

"""Bounded REST projection for finalized pattern evaluations."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from anaxigraph.pattern_intelligence import PatternIntelligenceService
from anaxigraph.pattern_query import (
    PATTERN_QUERY_LIMIT,
    PATTERN_QUERY_MAX_LIMIT,
    PatternEvaluationQuery,
)


class PatternRoutes:
    def __init__(self, database: Any, selected_repository: Any) -> None:
        self.service = PatternIntelligenceService(database)
        self.selected_repository = selected_repository
        self.router = APIRouter()
        self.router.add_api_route("/api/patterns", self.query, methods=["GET"])

    def query(
        self,
        repository_id: int | None = None,
        snapshot_id: int | None = Query(default=None, ge=1),
        target: str = Query(default="", max_length=2_000),
        pattern: str = Query(default="", max_length=2_000),
        level: str = Query(default="", max_length=100),
        recommendation: str = Query(default="", max_length=100),
        presence: str = Query(default="", max_length=100),
        sort_by: str = Query(default="opportunity", max_length=100),
        minimum_score: int = Query(default=0, ge=0, le=100),
        limit: int = Query(default=PATTERN_QUERY_LIMIT, ge=1, le=PATTERN_QUERY_MAX_LIMIT),
        offset: int = Query(default=0, ge=0),
        include_evidence: bool = False,
    ) -> dict[str, Any]:
        row = self.selected_repository(repository_id)
        try:
            request = PatternEvaluationQuery(
                target=target,
                pattern=pattern,
                level=level,
                recommendation=recommendation,
                presence=presence,
                sort_by=sort_by,
                minimum_score=minimum_score,
                limit=limit,
                offset=offset,
                include_evidence=include_evidence,
            )
            return self.service.query(int(row["id"]), snapshot_id, request=request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

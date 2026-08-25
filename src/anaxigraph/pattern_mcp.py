"""Read-only MCP access to finalized and skipped pattern intelligence."""

from __future__ import annotations

from typing import Any

from mcp.types import ToolAnnotations

from anaxigraph.pattern_candidate_query import PatternCandidateQuery
from anaxigraph.pattern_intelligence import PatternIntelligenceService
from anaxigraph.pattern_query import PatternEvaluationQuery


def register_pattern_tool(server: Any, database: Any, context: Any) -> None:
    PatternTool(server, database, context).register()


class PatternTool:
    def __init__(self, server: Any, database: Any, context: Any) -> None:
        self.server = server
        self.service = PatternIntelligenceService(database)
        self.context = context

    def register(self) -> None:
        self.server.tool(
            name="ANAXIGRAPH_PATTERNS",
            title="Read coding-pattern results",
            description=(
                "Read pattern results that completed a separate AI check. Use mode='candidates' "
                "with an exact pattern-library key to explain why a file, function, class, or code "
                "area was selected or skipped before AI work. Both modes use one saved scan, "
                "return one page at a time, and keep responses short unless evidence is requested."
            ),
            annotations=ToolAnnotations(
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )(self.query)

    def query(
        self,
        mode: str = "evaluations",
        repository: str = "",
        snapshot_id: int = 0,
        target: str = "",
        pattern: str = "",
        level: str = "",
        recommendation: str = "",
        presence: str = "",
        sort_by: str = "opportunity",
        minimum_score: int = 0,
        selection: str = "skipped",
        limit: int = 20,
        offset: int = 0,
        include_evidence: bool = False,
    ) -> dict[str, Any]:
        row, _root = self.context(repository)
        repository_id = int(row["id"])
        snapshot = snapshot_id or None
        if mode == "candidates":
            request = _candidate_request(
                pattern, target, level, selection, limit, offset, include_evidence
            )
            return self.service.candidates(repository_id, snapshot, request=request)
        if mode != "evaluations":
            raise ValueError("pattern mode must be evaluations or candidates")
        request = _evaluation_request(
            target,
            pattern,
            level,
            recommendation,
            presence,
            sort_by,
            minimum_score,
            limit,
            offset,
            include_evidence,
        )
        return self.service.query(repository_id, snapshot, request=request)


def _candidate_request(
    pattern: str,
    target: str,
    level: str,
    selection: str,
    limit: int,
    offset: int,
    include_evidence: bool,
) -> PatternCandidateQuery:
    return PatternCandidateQuery(
        pattern=pattern,
        target=target,
        level=level,
        selection=selection,
        limit=limit,
        offset=offset,
        include_evidence=include_evidence,
    )


def _evaluation_request(
    target: str,
    pattern: str,
    level: str,
    recommendation: str,
    presence: str,
    sort_by: str,
    minimum_score: int,
    limit: int,
    offset: int,
    include_evidence: bool,
) -> PatternEvaluationQuery:
    return PatternEvaluationQuery(
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

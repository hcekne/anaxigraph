"""Read-only MCP access to finalized pattern intelligence."""

from __future__ import annotations

from typing import Any

from mcp.types import ToolAnnotations

from anaxigraph.pattern_intelligence import PatternIntelligenceService
from anaxigraph.pattern_query import PatternEvaluationQuery


def register_pattern_tool(server: Any, database: Any, context: Any) -> None:
    service = PatternIntelligenceService(database)

    @server.tool(
        name="ANAXIGRAPH_PATTERNS",
        title="Query finalized coding-pattern evaluations",
        description=(
            "Read independently critiqued pattern evaluations in either direction: filter by "
            "target to find suitable patterns, or by pattern to find suitable targets. Results "
            "are current-snapshot only, score-ranked, paginated, and compact unless detailed "
            "evidence is requested."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def patterns(
        repository: str = "",
        snapshot_id: int = 0,
        target: str = "",
        pattern: str = "",
        level: str = "",
        recommendation: str = "",
        presence: str = "",
        sort_by: str = "opportunity",
        minimum_score: int = 0,
        limit: int = 20,
        offset: int = 0,
        include_evidence: bool = False,
    ) -> dict[str, Any]:
        row, _root = context(repository)
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
        return service.query(int(row["id"]), snapshot_id or None, request=request)

"""MCP registration for bounded finding review and agent handoff."""

from __future__ import annotations

from typing import Any

from anaxigraph.agent import finding_context
from anaxigraph.finding_transport import query_findings


def register_finding_tools(
    server: Any,
    database: Any,
    context: Any,
    config_for: Any,
) -> None:
    _register_query_tool(server, database, context, config_for)
    _register_context_tool(server, database, context, config_for)


def _register_query_tool(
    server: Any,
    database: Any,
    context: Any,
    config_for: Any,
) -> None:
    @server.tool(
        name="ANAXIGRAPH_FINDINGS",
        description=(
            "Read a bounded attention queue or the complete diagnostic ledger. Responses include "
            "exact totals, stable cursors, omitted counts, and actionability. Use status='planned' "
            "for work a human explicitly approved; active signals are not permission to refactor."
        ),
    )
    def findings(
        view: str = "attention",
        status: str = "",
        severity: str = "",
        finding_type: str = "",
        module: str = "",
        architecture_area: str = "",
        cursor: str = "",
        page_size: int = 0,
        token_budget: int = 5_000,
        repository: str = "",
    ) -> dict[str, Any]:
        row, root = context(repository)
        return query_findings(
            database,
            int(row["id"]),
            config_for(row, root),
            view=view,
            cursor=cursor,
            page_size=max(1, min(page_size, 200)) if page_size else None,
            statuses=_comma_values(status),
            severities=_comma_values(severity),
            finding_types=_comma_values(finding_type),
            module=module,
            architecture_area=architecture_area,
            token_budget=max(500, min(token_budget, 20_000)),
            compact=True,
        )


def _register_context_tool(
    server: Any,
    database: Any,
    context: Any,
    config_for: Any,
) -> None:
    @server.tool(
        name="ANAXIGRAPH_FINDING_CONTEXT",
        description=(
            "Turn one finding into an actionable handoff with affected files, impact, tests, "
            "protected paths, risk, and verification steps. Planned status means human-approved."
        ),
    )
    def finding_work(
        finding_id: int,
        branch: str = "",
        repository: str = "",
    ) -> dict[str, Any]:
        row, root = context(repository)
        return finding_context(
            database,
            repository_id=int(row["id"]),
            finding_id=finding_id,
            branch=branch or None,
            config=config_for(row, root),
        )


def _comma_values(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())

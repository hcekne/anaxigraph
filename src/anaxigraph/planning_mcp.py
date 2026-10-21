"""Architecture planning journey behind the existing Guide MCP tool."""

from __future__ import annotations

from typing import Any

from anaxigraph.agent_response import small_agent_response
from anaxigraph.architecture_plan_read import architecture_plan_status, steer_plan
from anaxigraph.planning_service import prepare_architecture_plan


def planning_journey(
    database: Any,
    row: Any,
    config: Any,
    *,
    goal: str = "",
    start: bool = False,
    option: str = "",
    milestone: str = "",
    status: str = "",
    evidence: list[str] | None = None,
    details: bool = False,
) -> dict[str, Any]:
    repository_id = int(row["id"])
    if start:
        prepare_architecture_plan(database, repository_id, row["path"], config, goal)
    if option or milestone:
        steer_plan(
            database,
            repository_id,
            option=option,
            milestone=milestone,
            status=status,
            evidence=evidence or [],
            actor="agent",
        )
    result = architecture_plan_status(database, repository_id)
    result["next_action"] = (
        "Use the selected target and next milestone to guide code changes; report verification evidence after focused tests."
        if result["ready"]
        else "Request planning with start=true and run the existing background worker to complete prepared work. Direction is optional."
    )
    return (
        result
        if details
        else small_agent_response(result, limit=min(8000, config.agent.payload_limit_bytes))
    )

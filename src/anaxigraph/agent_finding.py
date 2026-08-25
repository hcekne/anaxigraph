"""Focused assembly for architecture-finding coding handoffs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

AgentOperation = Callable[..., dict[str, Any]]


@dataclass(frozen=True, slots=True)
class _HandoffContext:
    recommended: list[str]
    tests: list[str]
    protected: list[str]
    risk: str


def build_finding_context(
    database: Any,
    *,
    repository_id: int,
    finding_id: int,
    branch: str | None,
    config: Any,
    scope_builder: AgentOperation,
    impact_builder: AgentOperation,
) -> dict[str, Any]:
    """Turn one finding into a bounded, source-editing handoff."""

    repository, finding = _finding(database, repository_id, finding_id)
    affected = [str(path) for path in finding.get("affected_artifacts") or []]
    goal = _goal(finding_id, finding, affected)
    scope = scope_builder(
        database,
        repository_id=repository_id,
        goal=goal,
        branch=branch,
        config=config,
    )
    impact = _first_impact(
        database,
        repository_id,
        affected,
        branch,
        config,
        impact_builder,
    )
    context = _handoff_context(affected, scope, impact)
    return _response(repository, finding, finding_id, goal, scope, impact, context)


def _finding(
    database: Any, repository_id: int, finding_id: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    repository = database.repository(repository_id)
    if repository is None:
        raise ValueError("Repository not found")
    finding = database.finding(repository_id, finding_id)
    if finding is None:
        raise ValueError(f"Finding not found: {finding_id}")
    return repository, finding


def _goal(finding_id: int, finding: dict[str, Any], affected: list[str]) -> str:
    result = f"Address architecture finding #{finding_id}: {finding['summary']}"
    if affected:
        result += f". Start with {', '.join(affected[:4])}"
    return result


def _first_impact(
    database: Any,
    repository_id: int,
    affected: list[str],
    branch: str | None,
    config: Any,
    impact_builder: AgentOperation,
) -> dict[str, Any] | None:
    for path in affected:
        if database.file_details(repository_id, path) is not None:
            return impact_builder(
                database,
                repository_id=repository_id,
                target=path,
                branch=branch,
                config=config,
            )
    return None


def _handoff_context(
    affected: list[str], scope: dict[str, Any], impact: dict[str, Any] | None
) -> _HandoffContext:
    recommended = list(dict.fromkeys([*affected, *(scope.get("recommended_context") or [])]))
    tests = set(scope.get("tests") or [])
    protected = {item["path"] for item in scope.get("protected_files") or []}
    risks = {scope.get("risk", "low")}
    if impact:
        tests.update(impact.get("tests_relevant") or [])
        protected.update(impact.get("critical_paths_affected") or [])
        risks.add(impact.get("risk", "low"))
    risk = "high" if "high" in risks else "medium" if "medium" in risks else "low"
    return _HandoffContext(recommended, sorted(tests), sorted(protected), risk)


def _response(
    repository: dict[str, Any],
    finding: dict[str, Any],
    finding_id: int,
    goal: str,
    scope: dict[str, Any],
    impact: dict[str, Any] | None,
    context: _HandoffContext,
) -> dict[str, Any]:
    status = str(finding["status"])
    return {
        "repository_id": int(repository["id"]),
        "repository_name": repository["name"],
        "finding": finding,
        "ready_for_agent": status == "planned",
        "workflow_note": _workflow_note(status),
        "goal": goal,
        "risk": context.risk,
        "recommended_context": context.recommended,
        "relevant_tests": context.tests,
        "protected_paths": context.protected,
        "scope": scope,
        "primary_impact": impact,
        "verification": [
            "Run focused tests for the affected behavior and dependency boundary.",
            "Refresh the repository scan after the code change.",
            "Confirm this stable finding is automatically resolved or explain why it remains.",
            "Review any new error-severity findings introduced by the change.",
        ],
        "agent_prompt": _agent_prompt(repository, finding, finding_id),
    }


def _workflow_note(status: str) -> str:
    if status == "planned":
        return "This finding is in the human-approved agent queue."
    return "Plan this finding before treating it as approved engineering work."


def _agent_prompt(repository: dict[str, Any], finding: dict[str, Any], finding_id: int) -> str:
    affected = [str(path) for path in finding.get("affected_artifacts") or []]
    affected_text = ", ".join(affected) if affected else "No file was attached by the detector."
    return "\n".join(
        [
            f"Work on AnaxiGraph finding #{finding_id} in {repository['name']}.",
            f"Goal: {finding['summary']}",
            f"Why it matters: {finding['explanation']}",
            f"Suggested direction: {finding['recommended_action']}",
            f"Affected files: {affected_text}",
            "",
            "Before editing, use the AnaxiMCP tools:",
            f"1. Call ANAXIGRAPH_FINDING_CONTEXT with finding_id={finding_id}.",
            "2. Inspect the recommended files with ANAXIGRAPH_FILE.",
            "3. Call ANAXIGRAPH_IMPACT before changing a shared interface.",
            "4. Make the smallest cohesive change and run the listed relevant tests.",
            "5. Refresh AnaxiGraph and confirm the finding disappears without new errors.",
        ]
    )

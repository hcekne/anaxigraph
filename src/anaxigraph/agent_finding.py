"""Focused assembly for architecture-finding coding handoffs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from anaxigraph.finding_language import finding_caveats, plain_language_contract

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
    """Turn one finding into a size-limited, source-editing handoff."""

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
    return repository, _finding_language(dict(finding))


def _finding_language(finding: dict[str, Any]) -> dict[str, Any]:
    language = finding.get("plain_language")
    if not isinstance(language, dict):
        language = plain_language_contract(
            finding,
            priority_score=int(finding.get("priority_score") or 0),
            priority_label=str(finding.get("priority_label") or "Low"),
            priority_reasons=[str(value) for value in finding.get("priority_reasons") or ()],
            false_positive_conditions=finding_caveats(
                str(finding.get("finding_type") or "observation")
            ),
        )
    finding["plain_language"] = language
    return finding


def _goal(finding_id: int, finding: dict[str, Any], affected: list[str]) -> str:
    result = f"Address architecture finding #{finding_id}: {finding['plain_language']['what']}"
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
            "Run focused tests for the affected behavior and the project rule about which files may use one another.",
            str(finding["plain_language"]["how_to_check"]),
            "Check whether the next scan reports a new finding that the project marks as an error.",
        ],
        "agent_prompt": _agent_prompt(repository, finding, finding_id),
    }


def _workflow_note(status: str) -> str:
    if status == "planned":
        return "This finding has been selected for agent work."
    return "Plan this finding before treating it as approved engineering work."


def _agent_prompt(repository: dict[str, Any], finding: dict[str, Any], finding_id: int) -> str:
    affected = [str(path) for path in finding.get("affected_artifacts") or []]
    affected_text = ", ".join(affected) if affected else "No file was attached by the detector."
    language = finding["plain_language"]
    facts = [f"- {value}" for value in language.get("facts") or ()]
    caveats = [f"- {value}" for value in language.get("when_no_change_may_be_needed") or ()]
    return "\n".join(
        [
            f"Work on AnaxiGraph finding #{finding_id} in {repository['name']}.",
            f"Finding: {language['what']}",
            "What AnaxiGraph saw:",
            *(facts or ["- No measured fact was supplied."]),
            f"Why it matters: {language['why_it_matters']}",
            f"Suggested action: {language['next_step']}",
            "When no code change may be needed:",
            *(caveats or ["- No specific exception was supplied."]),
            f"How to check the result: {language['how_to_check']}",
            f"Affected files: {affected_text}",
            "",
            "Before editing, use the AnaxiMCP tools:",
            f"1. Call ANAXIGRAPH_FINDING_CONTEXT with finding_id={finding_id}.",
            "2. Inspect the recommended files with ANAXIGRAPH_FILE.",
            "3. Call ANAXIGRAPH_IMPACT before changing a shared interface.",
            "4. Make the smallest change that keeps each file focused on one clear job, then run the listed tests.",
            "5. Scan the repository again and confirm the finding disappears without a new error-level finding.",
        ]
    )

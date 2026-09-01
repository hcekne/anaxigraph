"""Wire-budget and file-summary helpers for agent responses."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from anaxigraph.agent_decision_payload import (
    compact_architecture_decision,
)
from anaxigraph.agent_task_path import compact_task_path
from anaxigraph.architecture_guidance import (
    compact_guidance_projection,
    guidance_projection,
)
from anaxigraph.config import AnaxiGraphConfig, path_matches
from anaxigraph.graph_contract import _response_payload_bytes, _with_response_telemetry
from anaxigraph.guidance import FILE_MEASUREMENT_MEANINGS


@dataclass(frozen=True, slots=True)
class _ScopePayloadData:
    goal: str
    intent: str
    focus: str
    charter: dict[str, Any]
    repository_id: int
    snapshot_id: int
    map_status: dict[str, Any]
    files: dict[int, dict[str, Any]]
    outgoing: dict[int, set[int]]
    incoming: dict[int, set[int]]
    primary_ids: list[int]
    related_ids: set[int]
    related_scores: dict[int, float]
    protected_ids: set[int]
    tests: set[str]
    interfaces: list[dict[str, Any]]
    rules: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    decision: dict[str, Any]
    context_limit: int
    payload_limit_bytes: int
    started_at: float


def _scope_payload(data: _ScopePayloadData) -> dict[str, Any]:
    """Assemble and bound the public architecture-guidance response."""

    payload = _scope_payload_body(data)
    payload = {
        **guidance_projection(
            payload,
            intent=data.intent,
            focus=data.focus,
            charter=data.charter,
        ),
        **payload,
    }
    _with_response_telemetry(payload, data.started_at, action="guidance")
    return _bound_scope_payload(payload, data.payload_limit_bytes)


def _scope_payload_body(data: _ScopePayloadData) -> dict[str, Any]:
    primary = [_file_summary(data.files[item]) for item in data.primary_ids]
    related_order = sorted(
        data.related_ids,
        key=lambda item: (
            data.files[item]["artifact_type"] == "test",
            -data.related_scores.get(item, 0),
            data.files[item]["path"],
        ),
    )
    related = [_file_summary(data.files[item]) for item in related_order[: data.context_limit]]
    protected = [_file_summary(data.files[item]) for item in sorted(data.protected_ids)]
    high_degree = any(
        len(data.outgoing[item]) + len(data.incoming[item]) >= 20 for item in data.primary_ids
    )
    risk = _scope_risk(protected, high_degree, data.related_ids)
    risk_reasons = _risk_reasons(protected, high_degree)
    return {
        "goal": data.goal,
        "repository_id": data.repository_id,
        "snapshot_id": data.snapshot_id,
        "map_status": data.map_status,
        "primary_files": primary,
        "related_files": related,
        "protected_files": protected,
        "tests": sorted(data.tests),
        "interfaces": data.interfaces,
        "architecture_rules": data.rules,
        "known_findings": data.findings,
        "architecture_decision": data.decision,
        "risk": risk,
        "risk_reasons": risk_reasons,
        "plain_language": _scope_explanation(
            data.goal,
            len(primary),
            len(data.related_ids),
            risk,
            risk_reasons,
        ),
        "recommended_context": _recommended_context(
            primary, related, data.tests, data.context_limit
        ),
        "stats": _scope_stats(data, primary, protected),
    }


def _scope_explanation(
    goal: str,
    primary_count: int,
    related_count: int,
    risk: str,
    reasons: list[str],
) -> dict[str, Any]:
    return {
        "conclusion": (
            f"For '{goal}', AnaxiGraph selected {primary_count} likely starting "
            f"{'file' if primary_count == 1 else 'files'} and found {related_count} related "
            f"{'file' if related_count == 1 else 'files'} worth reading."
        ),
        "how_to_use_this": (
            "Start with the likely files. Read related files for context; do not edit every listed file."
        ),
        "risk": _risk_explanation(risk, reasons),
        "machine_key_note": (
            "snapshot_id identifies the saved scan used for this answer; it is not a score."
        ),
        "file_measurements": {
            key: FILE_MEASUREMENT_MEANINGS[key] for key in ("lines_of_code", "complexity")
        },
    }


def _risk_explanation(risk: str, reasons: list[str]) -> dict[str, Any]:
    meaning = {
        "high": (
            "Check the listed risks before editing. High means AnaxiGraph found an extra-care "
            "file or many direct code links; it does not mean the code is broken."
        ),
        "medium": (
            "Read the related files before editing because the change may affect nearby code. "
            "This is not a code-quality grade."
        ),
        "low": (
            "AnaxiGraph did not find an extra-care file or unusually connected "
            "starting file. Missing or runtime-only links can still hide effects."
        ),
    }.get(risk, "Read the listed evidence before deciding how carefully to proceed.")
    return {"value": risk, "meaning": meaning, "reasons": reasons}


def _scope_risk(
    protected: list[dict[str, Any]],
    high_degree: bool,
    related_ids: set[int],
) -> str:
    return "high" if protected or high_degree else "medium" if related_ids else "low"


def _risk_reasons(protected: list[dict[str, Any]], high_degree: bool) -> list[str]:
    return [
        reason
        for reason, active in (
            (
                "The task includes a file that project rules mark as needing extra care.",
                bool(protected),
            ),
            (
                "A likely implementation file has at least 20 direct incoming or outgoing code links, so a change may reach many files.",
                high_degree,
            ),
        )
        if active
    ]


def _scope_stats(
    data: _ScopePayloadData,
    primary: list[dict[str, Any]],
    protected: list[dict[str, Any]],
) -> dict[str, int]:
    return {
        "primary_files": len(primary),
        "primary_loc": sum(item["lines_of_code"] for item in primary),
        "related_files": len(data.related_ids),
        "tests": len(data.tests),
        "protected_files": len(protected),
    }


def _recommended_context(
    primary: list[dict[str, Any]],
    related: list[dict[str, Any]],
    tests: set[str],
    context_limit: int,
) -> list[str]:
    result = [item["path"] for item in primary]
    production_limit = max(len(primary), (context_limit * 2) // 3)
    result.extend(
        item["path"]
        for item in related
        if item["path"] not in result
        and item["path"] not in tests
        and len(result) < production_limit
    )
    result.extend(
        path for path in sorted(tests) if path not in result and len(result) < context_limit
    )
    return result


def _bound_scope_payload(payload: dict[str, Any], limit_bytes: int) -> dict[str, Any]:
    """Keep MCP task context within a predictable wire budget without dropping primary files."""

    limit = max(4_000, int(limit_bytes))
    omitted = _scope_omissions()
    payload["payload_budget"] = {
        "limit_bytes": limit,
        "estimated_bytes": 0,
        "truncated": False,
        "omitted": omitted,
    }

    def size() -> int:
        return _response_payload_bytes(payload)

    _trim_scope_collections(payload, size, limit, omitted)
    _compact_optional_scope(payload, size, limit, omitted)
    _compact_scope_file_details(payload, size, limit, omitted)
    _minimize_task_path(payload, size, limit, omitted)
    _compact_rule_identities(payload, size, limit, omitted)
    _minimize_legacy_decision(payload, size, limit, omitted)
    payload["payload_budget"]["truncated"] = any(omitted.values())
    for _attempt in range(4):
        measured = size()
        telemetry = payload.get("telemetry")
        previous = payload["payload_budget"]["estimated_bytes"]
        previous_telemetry = telemetry["payload_bytes"] if telemetry else measured
        payload["payload_budget"]["estimated_bytes"] = measured
        if telemetry:
            telemetry["payload_bytes"] = measured
        if previous == measured and previous_telemetry == measured:
            break
    return payload


def _trim_scope_collections(
    payload: dict[str, Any], size: Callable[[], int], limit: int, omitted: dict[str, int]
) -> None:
    for key in ("related_files", "interfaces"):
        while size() > limit and payload[key]:
            payload[key].pop()
            omitted[key] += 1
    if size() > limit:
        compact_guidance_projection(payload)
        omitted["guidance_details"] = 1
    while size() > limit and payload["known_findings"]:
        payload["known_findings"].pop()
        omitted["known_findings"] += 1
    if size() > limit:
        for rule in payload["architecture_rules"]:
            omitted["rule_details"] += int(rule.pop("description", None) is not None)
            omitted["rule_details"] += int(rule.pop("parameters", None) is not None)
    if size() <= limit:
        return
    for collection in (payload["primary_files"], payload["protected_files"]):
        for item in collection:
            summary = str(item.get("summary") or "")
            if len(summary) > 120:
                item["summary"] = summary[:117].rstrip() + "..."
                omitted["summaries_compacted"] += 1


def _compact_scope_file_details(
    payload: dict[str, Any], size: Callable[[], int], limit: int, omitted: dict[str, int]
) -> None:
    if size() > limit:
        omitted["protected_file_details"] = len(payload["protected_files"])
        payload["protected_files"] = [
            {"path": item["path"], "group": item.get("group")}
            for item in payload["protected_files"]
        ]
    if size() > limit:
        omitted["primary_file_details"] = len(payload["primary_files"])
        payload["primary_files"] = [
            {"path": item["path"], "group": item.get("group")} for item in payload["primary_files"]
        ]
    if size() > limit and payload["risk_reasons"]:
        omitted["risk_reasons"] = len(payload["risk_reasons"])
        payload.pop("risk_reasons")


def _minimize_task_path(
    payload: dict[str, Any], size: Callable[[], int], limit: int, omitted: dict[str, int]
) -> None:
    decision = payload.get("architecture_decision") or {}
    if size() > limit and decision.get("task_path"):
        decision["task_path"] = compact_task_path(decision["task_path"], route_only=True)
        omitted["task_path_details"] = 1


def _compact_rule_identities(
    payload: dict[str, Any], size: Callable[[], int], limit: int, omitted: dict[str, int]
) -> None:
    if size() <= limit:
        return
    rules = payload.get("architecture_rules") or []
    payload["architecture_rules"] = [
        {key: rule[key] for key in ("rule_id", "severity") if key in rule} for rule in rules
    ]
    omitted["rule_details"] += sum(max(0, len(rule) - 2) for rule in rules)


def _minimize_legacy_decision(
    payload: dict[str, Any], size: Callable[[], int], limit: int, omitted: dict[str, int]
) -> None:
    if size() <= limit:
        return
    decision = payload.get("architecture_decision") or {}
    payload["architecture_decision"] = {
        key: decision.get(key)
        for key in ("contract_version", "snapshot_id", "status")
        if decision.get(key) not in (None, "")
    }
    omitted["architecture_decision_details"] = 1


def _maybe_compact_decision(
    payload: dict[str, Any], current_size: int, limit: int, omitted: dict[str, int]
) -> None:
    decision = payload.get("architecture_decision")
    if current_size > limit and isinstance(decision, dict):
        payload["architecture_decision"] = compact_architecture_decision(decision)
        omitted["architecture_decision_details"] = 1


def _compact_optional_scope(
    payload: dict[str, Any], size: Callable[[], int], limit: int, omitted: dict[str, int]
) -> None:
    _compact_map_status(payload, size, limit, omitted)
    if size() > limit:
        compact_guidance_projection(payload)
        omitted["guidance_details"] = 1
    _maybe_compact_decision(payload, size(), limit, omitted)
    while size() > limit and payload["recommended_context"]:
        payload["recommended_context"].pop()
        omitted["recommended_context"] += 1
    if size() > limit:
        language = payload.get("plain_language") or {}
        risk = language.get("risk") or {}
        payload["plain_language"] = {
            "how_to_use_this": language.get("how_to_use_this"),
            "risk": {"value": risk.get("value"), "meaning": risk.get("meaning")},
            "measurement_note": (
                "lines_of_code counts code lines. complexity is a file-wide branch score, not a "
                "code-quality grade. snapshot_id identifies the saved scan; it is not a score."
            ),
        }
        omitted["plain_language_details"] = 1
    if size() > limit and payload.get("stats"):
        omitted["stats"] = len(payload["stats"])
        payload.pop("stats")
    if size() > limit and limit <= 4_000:
        payload.pop("telemetry", None)


def _compact_map_status(
    payload: dict[str, Any], size: Callable[[], int], limit: int, omitted: dict[str, int]
) -> None:
    status = payload.get("map_status") or {}
    if size() <= limit or not status:
        return
    payload["map_status"] = {"state": status.get("state")}
    omitted["plain_language_details"] += 1


def _scope_omissions() -> dict[str, int]:
    return {
        key: 0
        for key in (
            "related_files",
            "known_findings",
            "interfaces",
            "rule_details",
            "summaries_compacted",
            "protected_file_details",
            "primary_file_details",
            "architecture_decision_details",
            "task_path_details",
            "recommended_context",
            "plain_language_details",
            "risk_reasons",
            "stats",
            "guidance_details",
        )
    }


def _is_protected(path: str, config: AnaxiGraphConfig) -> bool:
    patterns = (*config.architecture.protected_paths, *config.agent.protected_paths)
    return any(path_matches(path, pattern) for pattern in patterns)


def _file_summary(item: dict[str, Any]) -> dict[str, Any]:
    result = {
        "path": item["path"],
        "language": item["language"],
        "summary": item["summary"],
        "lines_of_code": item["lines_of_code"],
        "complexity": item["complexity"],
        "group": item["declared_group"] or item["inferred_group"],
    }
    semantic = item.get("semantic") or {}
    if semantic:
        semantic_summary = {
            key: semantic.get(key)
            for key in (
                "status",
                "source",
                "provider",
                "model",
                "confidence",
                "architecture_role",
                "placement_guidance",
                "pattern_opportunities",
                "consolidation_assessment",
                "dead_code_candidates",
                "risks",
            )
            if semantic.get(key) not in (None, "")
        }
        semantic_summary["plain_language"] = semantic.get("plain_language") or {}
        result["semantic"] = semantic_summary
    return result


def _sorted_ids(files: dict[int, dict[str, Any]], ids: set[int]) -> list[int]:
    return sorted(ids, key=lambda item: files[item]["path"])

"""Wire-budget, collision, and file-summary helpers for agent responses."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anaxigraph import git
from anaxigraph.agent_decision_handoff_language import compact_explanation
from anaxigraph.config import AnaxiGraphConfig, path_matches


@dataclass(frozen=True, slots=True)
class _ScopePayloadData:
    goal: str
    branch: str | None
    repository_id: int
    snapshot_id: int
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
    conflicts: list[dict[str, str]]
    context_limit: int
    payload_limit_bytes: int


def _scope_payload(data: _ScopePayloadData) -> dict[str, Any]:
    """Assemble and bound the public task-scope response."""

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
    risk = _scope_risk(protected, data.conflicts, high_degree, data.related_ids)
    payload = {
        "goal": data.goal,
        "branch": data.branch,
        "repository_id": data.repository_id,
        "snapshot_id": data.snapshot_id,
        "primary_files": primary,
        "related_files": related,
        "protected_files": protected,
        "tests": sorted(data.tests),
        "interfaces": data.interfaces,
        "architecture_rules": data.rules,
        "known_findings": data.findings,
        "architecture_decision": data.decision,
        "active_branch_conflicts": data.conflicts,
        "risk": risk,
        "risk_reasons": _risk_reasons(protected, data.conflicts, high_degree),
        "recommended_context": _recommended_context(
            primary, related, data.tests, data.context_limit
        ),
        "stats": _scope_stats(data, primary, protected),
    }
    return _bound_scope_payload(payload, data.payload_limit_bytes)


def _scope_risk(
    protected: list[dict[str, Any]],
    conflicts: list[dict[str, str]],
    high_degree: bool,
    related_ids: set[int],
) -> str:
    return "high" if protected or conflicts or high_degree else "medium" if related_ids else "low"


def _risk_reasons(
    protected: list[dict[str, Any]], conflicts: list[dict[str, str]], high_degree: bool
) -> list[str]:
    return [
        reason
        for reason, active in (
            ("The task context reaches a protected architecture boundary.", bool(protected)),
            ("Another branch changes a file in this task context.", bool(conflicts)),
            ("A primary module is a high-coupling shared dependency.", high_degree),
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
        "conflicting_files": len({item["path"] for item in data.conflicts}),
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
        return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    while size() > limit and payload["related_files"]:
        payload["related_files"].pop()
        omitted["related_files"] += 1
    while size() > limit and payload["known_findings"]:
        payload["known_findings"].pop()
        omitted["known_findings"] += 1
    while size() > limit and payload["interfaces"]:
        payload["interfaces"].pop()
        omitted["interfaces"] += 1
    if size() > limit:
        for rule in payload["architecture_rules"]:
            removed = 0
            removed += int(rule.pop("description", None) is not None)
            removed += int(rule.pop("parameters", None) is not None)
            omitted["rule_details"] += removed
    while size() > limit and payload["active_branch_conflicts"]:
        payload["active_branch_conflicts"].pop()
        omitted["branch_conflicts"] += 1
    if size() > limit:
        for collection in (payload["primary_files"], payload["protected_files"]):
            for item in collection:
                summary = str(item.get("summary") or "")
                if len(summary) > 120:
                    item["summary"] = summary[:117].rstrip() + "..."
                    omitted["summaries_compacted"] += 1
    _compact_optional_scope(payload, size, limit, omitted)
    if size() > limit:
        omitted["protected_file_details"] = len(payload["protected_files"])
        payload["protected_files"] = [
            {"path": item["path"], "group": item.get("group")}
            for item in payload["protected_files"]
        ]
    if size() > limit:
        omitted["primary_file_details"] = len(payload["primary_files"])
        payload["primary_files"] = [
            {
                "path": item["path"],
                "summary": str(item.get("summary") or "")[:80],
                "group": item.get("group"),
            }
            for item in payload["primary_files"]
        ]

    payload["payload_budget"]["truncated"] = any(omitted.values())
    payload["payload_budget"]["estimated_bytes"] = size()
    # Updating the byte count can change its own digit width. A second pass makes the estimate exact.
    payload["payload_budget"]["estimated_bytes"] = size()
    return payload


def _compact_decision(decision: dict[str, Any]) -> dict[str, Any]:
    result = {
        "contract_version": decision.get("contract_version"),
        "snapshot_id": decision.get("snapshot_id"),
        "status": decision.get("status"),
        "plain_language": compact_explanation(decision.get("plain_language"), "conclusion"),
        "placement": _compact_placement(decision.get("placement")),
        "patterns": _compact_pattern_counts(decision.get("patterns")),
        "consolidation_count": len(decision.get("consolidation") or []),
        "change_constraint_count": len(
            (decision.get("change_constraints") or {}).get("items") or []
        ),
        "dead_code_candidate_count": (decision.get("dead_code") or {}).get("candidate_count", 0),
    }
    comparison = (decision.get("verification") or {}).get("post_change_comparison") or {}
    if comparison:
        result["verification"] = {
            "post_change_comparison": {
                key: comparison.get(key)
                for key in (
                    "contract_version",
                    "status",
                    "summary",
                    "baseline_snapshot_id",
                    "current_snapshot_id",
                    "interpretation",
                )
            }
        }
    return result


def _compact_placement(value: Any) -> dict[str, Any]:
    placement = value if isinstance(value, dict) else {}
    return {
        "preferred_path": placement.get("preferred_path"),
        "plain_language": compact_explanation(
            placement.get("plain_language"),
            "conclusion",
        ),
    }


def _compact_pattern_counts(value: Any) -> dict[str, Any]:
    patterns = value if isinstance(value, dict) else {}
    return {"status": patterns.get("status"), "total": patterns.get("total", 0)}


def _maybe_compact_decision(
    payload: dict[str, Any], current_size: int, limit: int, omitted: dict[str, int]
) -> None:
    decision = payload.get("architecture_decision")
    if current_size > limit and isinstance(decision, dict):
        payload["architecture_decision"] = _compact_decision(decision)
        omitted["architecture_decision_details"] = 1


def _compact_optional_scope(
    payload: dict[str, Any], size: Callable[[], int], limit: int, omitted: dict[str, int]
) -> None:
    _maybe_compact_decision(payload, size(), limit, omitted)
    while size() > limit and payload["recommended_context"]:
        payload["recommended_context"].pop()
        omitted["recommended_context"] += 1


def _scope_omissions() -> dict[str, int]:
    return {
        key: 0
        for key in (
            "related_files",
            "known_findings",
            "interfaces",
            "branch_conflicts",
            "rule_details",
            "summaries_compacted",
            "protected_file_details",
            "primary_file_details",
            "architecture_decision_details",
            "recommended_context",
        )
    }


def _branch_conflicts(root: Path, paths: set[str], branch: str | None) -> list[dict[str, str]]:
    if branch and not re.fullmatch(r"[A-Za-z0-9._/-]{1,250}", branch):
        raise ValueError("Branch contains unsupported characters")
    try:
        branches = git.active_branch_changes(root, exclude=branch)
    except (git.GitError, OSError):
        return []
    result = []
    for name, changed in branches.items():
        for path in sorted(paths & changed):
            result.append({"branch": name, "path": path})
    return result


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
        result["semantic"] = {
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
    return result


def _sorted_ids(files: dict[int, dict[str, Any]], ids: set[int]) -> list[int]:
    return sorted(ids, key=lambda item: files[item]["path"])

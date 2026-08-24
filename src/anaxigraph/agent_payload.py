"""Wire-budget, collision, and file-summary helpers for agent responses."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from anaxigraph import git
from anaxigraph.config import AnaxiGraphConfig, path_matches


def _bound_scope_payload(payload: dict[str, Any], limit_bytes: int) -> dict[str, Any]:
    """Keep MCP task context within a predictable wire budget without dropping primary files."""

    limit = max(4_000, int(limit_bytes))
    omitted = {
        "related_files": 0,
        "known_findings": 0,
        "interfaces": 0,
        "branch_conflicts": 0,
        "rule_details": 0,
        "summaries_compacted": 0,
        "protected_file_details": 0,
        "primary_file_details": 0,
    }
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

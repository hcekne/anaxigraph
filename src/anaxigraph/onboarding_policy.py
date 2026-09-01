"""Narrow, comment-preserving updates to an existing repository policy."""

from __future__ import annotations

import re
from typing import Any

import yaml

_TOP_LEVEL_KEY = re.compile(r"^[A-Za-z0-9_-]+\s*:")
_SEMANTIC_KEY = re.compile(r"^(\s+)(enabled|provider)\s*:")


def enable_agent_semantics(content: str) -> str:
    """Enable agent-funded semantics without reserializing unrelated YAML or comments."""

    document = _load_mapping(content)
    semantic = document.get("semantic")
    if semantic is not None and not isinstance(semantic, dict):
        raise ValueError("semantic must be a mapping before --semantic agent can update it")
    if (
        isinstance(semantic, dict)
        and semantic.get("enabled") is True
        and semantic.get("provider") == "agent"
    ):
        return content

    lines = content.splitlines(keepends=True)
    start = _semantic_start(lines)
    if start is None:
        updated = _appended_semantic_block(content)
    else:
        updated = _updated_semantic_block(lines, start)

    verified = _load_mapping(updated).get("semantic") or {}
    if verified.get("enabled") is not True or verified.get("provider") != "agent":
        raise ValueError("Generated repository policy did not enable agent-funded semantics")
    return updated


def _semantic_start(lines: list[str]) -> int | None:
    return next(
        (index for index, line in enumerate(lines) if line.startswith("semantic:")),
        None,
    )


def _appended_semantic_block(content: str) -> str:
    prefix = content.rstrip()
    separator = "\n\n" if prefix else ""
    return (
        f"{prefix}{separator}semantic:\n"
        "  enabled: true\n"
        "  provider: agent\n"
        "  refresh: on_scan\n"
        "  agent_lease_seconds: 1800\n"
    )


def _updated_semantic_block(lines: list[str], start: int) -> str:
    end = next(
        (index for index in range(start + 1, len(lines)) if _TOP_LEVEL_KEY.match(lines[index])),
        len(lines),
    )
    locations: dict[str, int] = {}
    indent = "  "
    for index in range(start + 1, end):
        match = _SEMANTIC_KEY.match(lines[index])
        if match:
            indent = match.group(1)
            locations[match.group(2)] = index
    insert_at = start + 1
    if "enabled" in locations:
        lines[locations["enabled"]] = f"{indent}enabled: true\n"
    else:
        lines.insert(insert_at, f"{indent}enabled: true\n")
        locations = {key: index + 1 for key, index in locations.items()}
        insert_at += 1
    if "provider" in locations:
        lines[locations["provider"]] = f"{indent}provider: agent\n"
    else:
        lines.insert(insert_at, f"{indent}provider: agent\n")
    return "".join(lines)


def _load_mapping(content: str) -> dict[str, Any]:
    document = yaml.safe_load(content) or {}
    if not isinstance(document, dict):
        raise ValueError("Repository policy must contain a YAML mapping")
    return document

"""Deterministic architecture roles used when policy and AI placement are absent."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import PurePosixPath
from typing import Any

_VOCABULARY = json.loads(
    files("anaxigraph").joinpath("catalog/architecture-vocabulary-v3.json").read_text()
)
VOCABULARY_VERSION = str(_VOCABULARY["version"])
INFERRED_GROUPS = tuple(tuple(row) for row in _VOCABULARY["groups"])
_DIRECTORIES = _VOCABULARY["directories"]
_ROOT_FILES = {name: group for group, names in _VOCABULARY["root_files"].items() for name in names}

CURRENT_MAP = "current"
RESPONSIBILITY_MAP = "responsibility"
DECLARED_MAP = "declared"
PATH_MAP = "path"
MAP_LAYERS = (CURRENT_MAP, RESPONSIBILITY_MAP, DECLARED_MAP, PATH_MAP)


def inferred_group(path: str, language: str, artifact_kind: str) -> str:
    """Return a stable subsystem; a root filename is never an architecture area."""

    pure = PurePosixPath(path)
    parts = tuple(part.lower() for part in pure.parts)
    if artifact_kind == "test":
        return "tests"
    if parts and parts[0] in _DIRECTORIES:
        return str(_DIRECTORIES[parts[0]])
    if len(parts) > 1:
        return "application-code"
    name = pure.name.lower()
    if name in _ROOT_FILES:
        return _ROOT_FILES[name]
    if name.startswith(("compose.", "dockerfile.")):
        return "delivery-and-operations"
    if name.startswith(".") or name.endswith((".config.js", ".config.ts")):
        return "quality-tooling"
    if artifact_kind == "documentation":
        return "docs"
    if artifact_kind == "configuration":
        return "build-and-packaging"
    if language in {"python", "javascript", "typescript", "go", "rust", "java"}:
        return "application-code"
    return "repository-governance"


def architecture_placement(
    layer: str,
    declared: str | None,
    path_group: str,
    parents: dict[str, str | None],
    responsibility: dict[str, Any] | None = None,
    *,
    show_missing: bool = False,
) -> dict[str, Any] | None:
    """Resolve one explicit map layer without disguising its source."""

    placement = None
    if layer == CURRENT_MAP:
        if declared:
            return _group_placement(declared, DECLARED_MAP, parents)
        if responsibility:
            return _responsibility_placement(responsibility)
        return _group_placement(path_group, PATH_MAP, parents, fallback=True)
    if layer == RESPONSIBILITY_MAP:
        placement = _responsibility_placement(responsibility) if responsibility else None
    elif layer == DECLARED_MAP:
        placement = _group_placement(declared, DECLARED_MAP, parents) if declared else None
    elif layer == PATH_MAP:
        return _group_placement(path_group, PATH_MAP, parents)
    elif layer not in MAP_LAYERS:
        raise ValueError(f"Unknown responsibility-map layer: {layer}")
    if placement is not None or not show_missing:
        return placement
    reason = f"No {layer} map placement is available for this file."
    return {
        "area": "unconfigured",
        "subsystem": "unconfigured",
        "source": f"missing {layer} map placement",
        "map_layer": layer,
        "why_here": reason,
        "fallback_reason": reason,
    }


def architecture_layers(
    declared: str | None,
    path_group: str,
    parents: dict[str, str | None],
    responsibility: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any] | None]:
    return {
        layer: architecture_placement(layer, declared, path_group, parents, responsibility)
        for layer in MAP_LAYERS
    }


def root_group(group: str, parents: dict[str, str | None]) -> str:
    result = group
    seen: set[str] = set()
    while parents.get(result) and result not in seen:
        seen.add(result)
        result = str(parents[result])
    return result


def _group_placement(
    group: str,
    layer: str,
    parents: dict[str, str | None],
    *,
    fallback: bool = False,
) -> dict[str, Any]:
    reason = (
        "No declared rule or current responsibility assignment places this file."
        if fallback
        else "Repository policy places this file here."
        if layer == DECLARED_MAP
        else "A deterministic path rule places this file here; no AI is used."
    )
    return {
        "area": root_group(group, parents),
        "subsystem": group,
        "source": f"{layer} map",
        "map_layer": layer,
        "why_here": reason,
        "fallback_reason": reason if fallback else None,
    }


def _responsibility_placement(assignment: dict[str, Any]) -> dict[str, Any]:
    return {
        **assignment,
        "source": "inferred responsibility map",
        "map_layer": RESPONSIBILITY_MAP,
        "why_here": (assignment.get("plain_language") or {}).get("why_this_file_is_here")
        or assignment.get("rationale"),
        "fallback_reason": None,
    }

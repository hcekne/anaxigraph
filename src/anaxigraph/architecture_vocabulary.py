"""Deterministic architecture roles used when policy and AI placement are absent."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import PurePosixPath

_VOCABULARY = json.loads(
    files("anaxigraph").joinpath("catalog/architecture-vocabulary-v3.json").read_text()
)
VOCABULARY_VERSION = str(_VOCABULARY["version"])
INFERRED_GROUPS = tuple(tuple(row) for row in _VOCABULARY["groups"])
_DIRECTORIES = _VOCABULARY["directories"]
_ROOT_FILES = {name: group for group, names in _VOCABULARY["root_files"].items() for name in names}


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

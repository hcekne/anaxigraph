"""Resolve the references a fresh-eyes recommendation cites against one reviewed snapshot.

Reference resolution answers exactly one question: can the paths, symbols, findings, commits,
routes, and declared Charter keys a recommendation names still be found? It stays separate from
whether the recommendation's claim is supported or its behavior verified.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from anaxigraph.architecture_charter_corrections import (
    CORRECTABLE_SECTIONS,
)
from anaxigraph.persistence.temporal_reads import snapshot_files, symbols_for_files

_FIELDS = ("current_evidence", "affected_contracts", "expected_deletions", "smallest_change")
_ENDPOINT_HINTS = ("api", "route", "endpoint", "handler", "controller", "server")
_SECTIONS = "|".join(sorted(CORRECTABLE_SECTIONS))
_SUFFIXES = "py|pyi|js|jsx|mjs|cjs|ts|tsx|rs|go|java|rb|kt|css|html|sql|toml|md|json|ya?ml"
_PATTERNS = tuple(
    (kind, re.compile(expression))
    for kind, expression in (
        ("finding", r"(?<![\w:.-])([a-z][\w.-]*:[0-9a-f]{20})(?!\w)"),
        ("declared", rf"(?<![\w.-])((?:{_SECTIONS}):[\w.-]+)(?!\w)"),
        ("path", rf"(?<![\w/.-])((?:[\w.-]+/)*[\w.-]+\.(?:{_SUFFIXES}))(?![\w/-])"),
        ("route", r"(?<!\w)(/(?:api|v[0-9])/[A-Za-z0-9_{}/-]+)"),
        ("commit", r"(?<!\w)([0-9a-f]{7,40})(?!\w)"),
        (
            "symbol",
            r"`([A-Za-z_][\w.]*)(?:\(\))?`"
            r"|(?<![\w.])((?:[A-Za-z_]\w*\.)+[A-Za-z_]\w*)(?![\w.])"
            r"|(?<![\w.])([a-z][a-z0-9]*(?:_[a-z0-9]+)+)(?![\w.])",
        ),
    )
)


@dataclass(frozen=True, slots=True)
class SnapshotIndex:
    """What one reviewed snapshot can resolve, reconstructed once per grounding report."""

    # Files are keyed by full path and by unambiguous basename; symbols by name and suffix.
    files: dict[str, int]
    symbols: frozenset[str]
    endpoints: frozenset[str]
    declared: frozenset[str]


def cited_identifiers(recommendation: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Extract each distinct checkable identifier once, naming the field that cited it."""

    seen: set[tuple[str, str]] = set()
    result: list[tuple[str, str, str]] = []
    for field in _FIELDS:
        value = recommendation.get(field)
        for text in [value] if isinstance(value, str) else list(value or ()):
            for kind, identifier in extract_identifiers(str(text)):
                if (kind, identifier) not in seen:
                    seen.add((kind, identifier))
                    result.append((kind, identifier, field))
    return result


def extract_identifiers(text: str) -> list[tuple[str, str]]:
    """Match the most specific identifier shapes first, removing each match before the next."""

    found: list[tuple[str, str]] = []
    remaining = text
    for kind, pattern in _PATTERNS:
        for match in pattern.finditer(remaining):
            value = next((group for group in match.groups() if group), "")
            if kind == "commit" and not any(character.isdigit() for character in value):
                continue
            if kind == "symbol" and "." in value and value.islower() and "_" not in value:
                continue
            found.append((kind, value))
        remaining = pattern.sub(" ", remaining)
    return found


def resolve_identifier(
    connection: Any, repository_id: int, index: SnapshotIndex, kind: str, value: str, field: str
) -> dict[str, Any]:
    check: dict[str, Any] = {"kind": kind, "value": value, "field": field, "result": "missing"}
    if kind == "path":
        artifact = index.files.get(value) or index.files.get(value.rsplit("/", 1)[-1])
        if artifact is not None:
            check.update({"result": "exists", "artifact_id": artifact})
    elif kind == "symbol":
        check["result"] = resolution_result(value in index.symbols)
    elif kind == "route":
        tail = value.rstrip("/").rsplit("/", 1)[-1]
        check["result"] = resolution_result(value in index.endpoints or tail in index.endpoints)
    elif kind == "declared":
        check["result"] = resolution_result(value in index.declared)
    elif kind == "finding":
        check["result"] = matching_row(
            connection, "findings", "stable_key = ?", repository_id, value
        )
    else:
        check["result"] = matching_row(
            connection, "git_changes", "commit_sha LIKE ?", repository_id, value
        )
    return check


def resolution_result(resolved: bool) -> str:
    return "exists" if resolved else "missing"


def matching_row(connection: Any, table: str, clause: str, repository_id: int, value: str) -> str:
    row = connection.execute(
        f"SELECT 1 FROM {table} WHERE repository_id = ? AND {clause} LIMIT 1",
        (repository_id, f"{value}%" if "LIKE" in clause else value),
    ).fetchone()
    return resolution_result(row is not None)


def snapshot_index(connection: Any, snapshot_id: int, declared_context: Any) -> SnapshotIndex:
    files = snapshot_files(connection, snapshot_id, expand_metadata=False)
    paths = {str(item["path"]): int(item["artifact_id"]) for item in files}
    bases: dict[str, int] = {}
    ambiguous: set[str] = set()
    for path, artifact in paths.items():
        if bases.setdefault(path.rsplit("/", 1)[-1], artifact) != artifact:
            ambiguous.add(path.rsplit("/", 1)[-1])
    resolved = {name: artifact for name, artifact in bases.items() if name not in ambiguous}
    resolved.update(paths)
    names, endpoints = symbol_index(symbols_for_files(connection, files))
    declared = {
        f"{item['section']}:{item['key']}"
        for item in declared_context or ()
        if isinstance(item, dict) and item.get("active", True)
    }
    return SnapshotIndex(resolved, frozenset(names), frozenset(endpoints), frozenset(declared))


def symbol_index(symbols: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    """Index symbols by name and qualified-name suffix, and name the ones a route can reach."""

    names: set[str] = set()
    endpoints: set[str] = set()
    for symbol in symbols:
        name = str(symbol["name"])
        names.add(name)
        parts = str(symbol["qualified_name"]).split(".")
        names.update(".".join(parts[index:]) for index in range(len(parts)))
        if "/" in name:
            endpoints.add(name.rsplit(" ", 1)[-1])
        path = str(symbol.get("path") or "").lower()
        if str(symbol["symbol_type"]) == "api_endpoint" or any(h in path for h in _ENDPOINT_HINTS):
            endpoints.add(name)
    return names, endpoints

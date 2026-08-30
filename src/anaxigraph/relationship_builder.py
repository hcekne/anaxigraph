"""Resolve, reuse, and persist one snapshot's extracted relationships."""

from __future__ import annotations

import json
import posixpath
import sqlite3
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Protocol

from anaxigraph.ir import canonical_python_module, python_module_aliases
from anaxigraph.persistence.temporal_reads import snapshot_relationship_edges
from anaxigraph.persistence.temporal_reconstruction import reconstruct_files
from anaxigraph.persistence.temporal_relationships import record_canonical_relationships
from anaxigraph.relationships import (
    AMBIGUOUS_INTERNAL,
    EXTERNAL,
    RESOLVED_INTERNAL,
    UNRESOLVED_INTERNAL,
)


class ResolverConfig(Protocol):
    aliases: dict[str, str]


@dataclass(frozen=True, slots=True)
class ResolvedDependency:
    target_id: int | None
    target_external: str | None
    resolution_status: str
    candidate_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RelationshipBuildResult:
    total: int
    copied: int
    resolved_sources: int
    reused_sources: int


def build_relationships(
    connection: sqlite3.Connection,
    *,
    snapshot_id: int,
    base_snapshot_id: int | None,
    prepared: list[Any],
    artifacts: dict[str, int],
    config: ResolverConfig,
) -> RelationshipBuildResult:
    to_resolve, copied = _copy_reusable(
        connection,
        snapshot_id=snapshot_id,
        base_snapshot_id=base_snapshot_id,
        prepared=prepared,
        artifacts=artifacts,
    )
    resolver = DependencyResolver(prepared, artifacts, config)
    aggregated = _aggregate(to_resolve, artifacts, resolver)
    record_canonical_relationships(
        connection,
        snapshot_id=snapshot_id,
        base_snapshot_id=base_snapshot_id,
        current_files=reconstruct_files(connection, snapshot_id),
        changed_sources={artifacts[item.discovered.path] for item in to_resolve},
        edges_by_source=_resolved_edges(aggregated),
    )
    return RelationshipBuildResult(
        copied + len(aggregated),
        copied,
        len(to_resolve),
        len(prepared) - len(to_resolve),
    )


def _copy_reusable(
    connection: sqlite3.Connection,
    *,
    snapshot_id: int,
    base_snapshot_id: int | None,
    prepared: list[Any],
    artifacts: dict[str, int],
) -> tuple[list[Any], int]:
    if base_snapshot_id is None:
        return prepared, 0
    previous_by_source: dict[int, list[dict[str, Any]]] = {}
    for edge in snapshot_relationship_edges(connection, base_snapshot_id):
        previous_by_source.setdefault(int(edge["source_artifact_id"]), []).append(edge)
    to_resolve: list[Any] = []
    copied = 0
    for item in prepared:
        if item.discovered.invalidation_reason != "carried_forward":
            to_resolve.append(item)
            continue
        source_id = artifacts[item.discovered.path]
        edges = previous_by_source.get(source_id, [])
        copied += len(edges)
    return to_resolve, copied


def _aggregate(
    prepared: list[Any],
    artifacts: dict[str, int],
    resolver: DependencyResolver,
) -> dict[tuple[int, int | None, str | None, str, str], dict[str, Any]]:
    aggregated: dict[tuple[int, int | None, str | None, str, str], dict[str, Any]] = {}
    for item in prepared:
        source_path = item.discovered.path
        source_id = artifacts[source_path]
        for dependency in item.analysis.dependencies:
            targets = resolver.resolve(source_path, item.discovered.language, dependency)
            for target in targets:
                if target.target_id == source_id and dependency.relationship_type == "imports":
                    continue
                _merge_relationship(aggregated, item, source_id, dependency, target)
    return aggregated


def _merge_relationship(
    aggregated: dict[tuple[int, int | None, str | None, str, str], dict[str, Any]],
    item: Any,
    source_id: int,
    dependency: Any,
    target: ResolvedDependency,
) -> None:
    external = target.target_external if target.target_id is None else None
    key = (
        source_id,
        target.target_id,
        external,
        dependency.relationship_type,
        target.resolution_status,
    )
    confidence = _resolved_confidence(dependency.confidence, target.resolution_status)
    current = aggregated.setdefault(
        key,
        {
            "confidence": confidence,
            "weight": 0,
            "evidence": [],
            "line": dependency.line,
            "source": relationship_source(item.discovered.language, dependency.relationship_type),
            "candidate_paths": set(),
            "original_targets": set(),
        },
    )
    current["weight"] += 1
    current["confidence"] = max(current["confidence"], confidence)
    current["candidate_paths"].update(target.candidate_paths)
    current["original_targets"].add(dependency.target)
    if dependency.evidence and dependency.evidence not in current["evidence"]:
        current["evidence"].append(dependency.evidence)
    current["line"] = min(value for value in (current["line"], dependency.line) if value >= 0)


def _resolved_confidence(confidence: float, status: str) -> float:
    if status == AMBIGUOUS_INTERNAL:
        return min(confidence, 0.5)
    if status == UNRESOLVED_INTERNAL:
        return min(confidence, 0.35)
    return confidence


def _resolved_edges(
    aggregated: dict[tuple[int, int | None, str | None, str, str], dict[str, Any]],
) -> dict[int, list[dict[str, Any]]]:
    result: dict[int, list[dict[str, Any]]] = {}
    for (source_id, target_id, external, relation_type, status), value in aggregated.items():
        metadata = {
            "resolution_status": status,
            "original_targets": sorted(value["original_targets"]),
        }
        if value["candidate_paths"]:
            metadata["candidate_paths"] = sorted(value["candidate_paths"])
        result.setdefault(source_id, []).append(
            {
                "target_artifact_id": target_id,
                "target_external": external,
                "relationship_type": relation_type,
                "source": value["source"],
                "confidence": value["confidence"],
                "evidence": " | ".join(value["evidence"][:5])[:2_000],
                "source_line": value["line"],
                "weight": value["weight"],
                "metadata_json": json.dumps(metadata, sort_keys=True),
            }
        )
    return result


class DependencyResolver:
    def __init__(
        self,
        prepared: list[Any],
        artifacts: dict[str, int],
        config: ResolverConfig,
    ) -> None:
        self.paths = set(artifacts)
        self.artifacts = artifacts
        self.config = config
        self.python_modules: dict[str, set[str]] = {}
        self.symbols: dict[str, set[str]] = {}
        for item in prepared:
            path = item.discovered.path
            if item.discovered.language == "python":
                for alias in python_module_aliases(path):
                    self.python_modules.setdefault(alias, set()).add(path)
            for symbol in item.analysis.symbols:
                self.symbols.setdefault(symbol.name, set()).add(path)
                self.symbols.setdefault(symbol.qualified_name, set()).add(path)
        self.python_roots = {module.split(".", 1)[0] for module in self.python_modules if module}

    def resolve(self, source_path: str, language: str, dependency: Any) -> list[ResolvedDependency]:
        if dependency.target.startswith("symbol:"):
            return self._resolve_symbol(dependency.target)
        if language == "python":
            return self._python_dependencies(source_path, dependency)
        paths = self._resolve_path_import(source_path, dependency.target)
        if paths:
            return [
                ResolvedDependency(self.artifacts[path], None, RESOLVED_INTERNAL) for path in paths
            ]
        status = (
            UNRESOLVED_INTERNAL if self._is_internal_path_target(dependency.target) else EXTERNAL
        )
        return [ResolvedDependency(None, dependency.target, status)]

    def _resolve_symbol(self, target: str) -> list[ResolvedDependency]:
        matches = sorted(self.symbols.get(target.removeprefix("symbol:"), set()))
        if len(matches) == 1:
            return [ResolvedDependency(self.artifacts[matches[0]], None, RESOLVED_INTERNAL)]
        if matches:
            return [ResolvedDependency(None, target, AMBIGUOUS_INTERNAL, tuple(matches))]
        return [ResolvedDependency(None, target, UNRESOLVED_INTERNAL)]

    def _python_dependencies(self, source_path: str, dependency: Any) -> list[ResolvedDependency]:
        paths, ambiguous, normalized = self._resolve_python(source_path, dependency)
        result = [
            ResolvedDependency(self.artifacts[path], None, RESOLVED_INTERNAL) for path in paths
        ]
        if ambiguous:
            result.append(
                ResolvedDependency(None, dependency.target, AMBIGUOUS_INTERNAL, tuple(ambiguous))
            )
        if result:
            return result
        internal = (
            dependency.target.startswith(".") or normalized.split(".", 1)[0] in self.python_roots
        )
        status = UNRESOLVED_INTERNAL if internal else EXTERNAL
        return [ResolvedDependency(None, dependency.target, status)]

    def _resolve_python(
        self, source_path: str, dependency: Any
    ) -> tuple[list[str], list[str], str]:
        target = dependency.target
        if target.startswith("."):
            target = self._absolute_python_target(source_path, target)
        candidates = [target]
        candidates.extend(f"{target}.{name}".strip(".") for name in dependency.names)
        matches: list[str] = []
        ambiguous: set[str] = set()
        for candidate in candidates:
            values = self.python_modules.get(candidate, set())
            if len(values) == 1:
                path = next(iter(values))
                if path not in matches:
                    matches.append(path)
            elif len(values) > 1:
                ambiguous.update(values)
        return matches[:10], sorted(ambiguous), target

    @staticmethod
    def _absolute_python_target(source_path: str, target: str) -> str:
        level = len(target) - len(target.lstrip("."))
        remainder = target[level:]
        base = canonical_python_module(source_path).split(".")[:-1]
        if level > 1:
            base = base[: max(0, len(base) - (level - 1))]
        return ".".join((*base, remainder)).strip(".")

    def _is_internal_path_target(self, target: str) -> bool:
        clean = target.split("?", 1)[0].split("#", 1)[0]
        if clean.startswith((".", "/")):
            return True
        return any(clean.startswith(alias.rstrip("*")) for alias in self.config.aliases)

    def _resolve_path_import(self, source_path: str, target: str) -> list[str]:
        clean = target.split("?", 1)[0].split("#", 1)[0]
        candidate_base = self._candidate_base(source_path, clean)
        if candidate_base is None or candidate_base.startswith("../"):
            return []
        extensions = (
            "",
            ".py",
            ".ts",
            ".tsx",
            ".js",
            ".jsx",
            ".mjs",
            ".cjs",
            ".css",
            ".scss",
            ".json",
            ".md",
            "/__init__.py",
            "/index.ts",
            "/index.tsx",
            "/index.js",
            "/index.jsx",
        )
        return [
            candidate_base + extension
            for extension in extensions
            if candidate_base + extension in self.paths
        ][:1]

    def _candidate_base(self, source_path: str, target: str) -> str | None:
        if target.startswith("."):
            parent = str(PurePosixPath(source_path).parent)
            return posixpath.normpath(posixpath.join(parent, target))
        if target.startswith("/"):
            return target.lstrip("/")
        aliases = sorted(self.config.aliases.items(), key=lambda item: len(item[0]), reverse=True)
        for alias, replacement in aliases:
            prefix = alias.rstrip("*")
            if target.startswith(prefix):
                suffix = target[len(prefix) :].lstrip("/")
                return posixpath.join(replacement.rstrip("*"), suffix)
        return None


def relationship_source(language: str, relationship_type: str) -> str:
    if language == "python":
        return "ast"
    if relationship_type == "references":
        return "configuration"
    return "static"

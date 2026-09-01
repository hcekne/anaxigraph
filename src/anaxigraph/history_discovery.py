"""Delta-aware source discovery for historical repository frames."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

from anaxigraph import git
from anaxigraph.languages import JAVASCRIPT_ANALYZER_LANGUAGES, detect_language


class DiscoveryConfig(Protocol):
    max_file_bytes: int

    def is_ignored(self, path: str, *, is_dir: bool = False) -> bool: ...


@dataclass(frozen=True, slots=True)
class DiscoveredFile:
    path: str
    language: str
    raw_hash: str
    content: bytes
    invalidation_reason: str
    change_kind: str
    source_read: bool


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    files: tuple[DiscoveredFile, ...]
    source_reads: int
    carried_forward: int
    delta: git.RevisionDelta | None


@dataclass(frozen=True, slots=True)
class InvalidationPlan:
    reasons: dict[str, str]
    relationship_sources: frozenset[str]


def discover_files(
    root: Path,
    config: DiscoveryConfig,
    *,
    revision: str | None,
    previous_revision: str | None,
    previous: dict[str, dict[str, Any]],
    analysis_version: int,
    allow_carry: bool,
    progress: Callable[[int, int, str], None] | None = None,
) -> DiscoveryResult:
    """Read a complete working tree or only changed blobs in a historical tree."""

    if revision is None:
        paths = git.listed_files(root) if git.is_repository(root) else _walk_files(root, config)
        return _materialize(
            root,
            config,
            paths=paths,
            revision=None,
            previous=previous,
            analysis_version=analysis_version,
            delta=None,
            allow_carry=False,
            progress=progress,
        )
    paths = git.files_at_revision(root, revision)
    delta = (
        git.revision_delta(root, previous_revision, revision)
        if previous_revision and allow_carry
        else None
    )
    return _materialize(
        root,
        config,
        paths=paths,
        revision=revision,
        previous=previous,
        analysis_version=analysis_version,
        delta=delta,
        allow_carry=allow_carry,
        progress=progress,
    )


def repository_metadata(root: Path, revision: str | None) -> Any:
    return git.metadata(root, revision=revision)


def available_changes(root: Path) -> list[git.GitChange]:
    try:
        return git.recent_changes(root)
    except git.GitError:
        return []


def plan_invalidations(
    files: list[tuple[str, Any, str, bool]],
    previous: dict[str, dict[str, Any]],
) -> InvalidationPlan:
    """Classify direct changes and relationship-context invalidations conservatively."""

    current = {path: analysis for path, analysis, _reason, _read in files}
    affected: set[str] = set()
    reasons: dict[str, str] = {}
    relationship_sources: set[str] = set()
    workspace_context_changed = any(
        _stored_workspace(previous.get(path)) != _analysis_workspace(current.get(path))
        for path in sorted(set(previous) | set(current))
    )
    for path in sorted(set(previous) | set(current)):
        prior_view = _stored_view(previous.get(path))
        current_view = _analysis_view(path, current.get(path))
        if prior_view[:2] != current_view[:2]:
            affected.update(prior_view[0] | prior_view[1] | current_view[0] | current_view[1])

    for path, analysis, initial_reason, source_read in files:
        prior_view = _stored_view(previous.get(path))
        current_view = _analysis_view(path, analysis)
        if source_read:
            reasons[path] = _direct_reason(initial_reason, prior_view, current_view)
            relationship_sources.add(path)
        elif affected and _references_affected(current_view[2], affected):
            reasons[path] = "resolver_context_changed"
            relationship_sources.add(path)
        elif workspace_context_changed and analysis.language in JAVASCRIPT_ANALYZER_LANGUAGES:
            reasons[path] = "resolver_context_changed"
            relationship_sources.add(path)
        else:
            reasons[path] = "carried_forward"
    return InvalidationPlan(reasons, frozenset(relationship_sources))


def apply_invalidation_plan(prepared: list[Any], previous: dict[str, dict[str, Any]]) -> None:
    plan = plan_invalidations(
        [
            (
                item.discovered.path,
                item.analysis,
                item.discovered.invalidation_reason,
                item.discovered.source_read,
            )
            for item in prepared
        ],
        previous,
    )
    for item in prepared:
        item.discovered = replace(
            item.discovered,
            invalidation_reason=plan.reasons[item.discovered.path],
        )


def _direct_reason(
    initial: str,
    prior: tuple[set[str], set[str], set[str]],
    current: tuple[set[str], set[str], set[str]],
) -> str:
    if initial in {"analyzer_upgraded", "policy_changed"}:
        return initial
    if prior[0] != current[0]:
        return "namespace_changed"
    if prior[1] != current[1]:
        return "interface_changed"
    if prior[2] != current[2]:
        return "resolver_context_changed"
    return "content_changed"


def _analysis_view(path: str, analysis: Any | None) -> tuple[set[str], set[str], set[str]]:
    if analysis is None:
        return set(), set(), set()
    identity = analysis.module_identity
    namespace = _path_tokens(path)
    if identity is not None:
        namespace.update(identity.aliases)
        namespace.add(identity.canonical_name)
    interface = set(analysis.exports)
    interface.update(symbol.name for symbol in analysis.symbols)
    references = {
        token
        for item in analysis.dependencies
        for token in _reference_tokens(item.target, item.names)
    }
    return namespace, interface, references


def _stored_view(value: dict[str, Any] | None) -> tuple[set[str], set[str], set[str]]:
    if value is None:
        return set(), set(), set()
    metadata = json.loads(value["metadata_json"] or "{}")
    ir = metadata.get("ir") or {}
    identity = ir.get("module_identity") or {}
    namespace = _path_tokens(str(value["path"]))
    namespace.update(identity.get("aliases") or [])
    if identity.get("canonical_name"):
        namespace.add(identity["canonical_name"])
    interface = set(ir.get("exports") or [])
    interface.update(symbol["name"] for symbol in value.get("symbols") or [])
    references = {
        token
        for item in metadata.get("dependencies") or []
        for token in _reference_tokens(item["target"], item.get("names") or [])
    }
    return namespace, interface, references


def _analysis_workspace(analysis: Any | None) -> dict[str, Any] | None:
    if analysis is None:
        return None
    value = analysis.metadata.get("javascript_workspace")
    return value if isinstance(value, dict) else None


def _stored_workspace(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    metadata = json.loads(value["metadata_json"] or "{}")
    workspace = metadata.get("javascript_workspace")
    return workspace if isinstance(workspace, dict) else None


def _path_tokens(path: str) -> set[str]:
    clean = str(Path(path).with_suffix("")).replace("\\", "/")
    dotted = clean.replace("/", ".")
    parts = dotted.split(".")
    return {clean, dotted, parts[-1], ".".join(parts[1:]) if len(parts) > 1 else dotted}


def _normalized_reference(value: str) -> str:
    clean = value.removeprefix("symbol:").split("?", 1)[0].split("#", 1)[0]
    return clean.removesuffix(".py").replace("/", ".").lstrip(".")


def _reference_tokens(target: str, names: Any) -> set[str]:
    normalized = _normalized_reference(target)
    result = {normalized}
    for name in names:
        result.add(str(name))
        result.add(f"{normalized}.{name}".strip("."))
    return result


def _references_affected(references: set[str], affected: set[str]) -> bool:
    return any(
        reference == token or reference.endswith(f".{token}") or token.endswith(f".{reference}")
        for reference in references
        for token in affected
        if reference and token
    )


def _materialize(
    root: Path,
    config: DiscoveryConfig,
    *,
    paths: list[str],
    revision: str | None,
    previous: dict[str, dict[str, Any]],
    analysis_version: int,
    delta: git.RevisionDelta | None,
    allow_carry: bool,
    progress: Callable[[int, int, str], None] | None,
) -> DiscoveryResult:
    changed = delta.changed_current_paths if delta else frozenset()
    change_kinds = (
        {item.new_path: item.status for item in delta.changes if item.new_path is not None}
        if delta
        else {}
    )
    result = []
    total = len(paths)
    for completed, raw_path in enumerate(paths, start=1):
        item = _materialize_path(
            root,
            config,
            path=_normalized_path(raw_path),
            revision=revision,
            previous=previous,
            analysis_version=analysis_version,
            changed=changed,
            change_kinds=change_kinds,
            can_carry=delta is not None and allow_carry,
        )
        if item is not None:
            result.append(item)
        if progress is not None:
            progress(completed, total, _normalized_path(raw_path))
    files = tuple(sorted(result, key=lambda value: value.path))
    reads = sum(item.source_read for item in files)
    return DiscoveryResult(files, reads, len(files) - reads, delta)


def _materialize_path(
    root: Path,
    config: DiscoveryConfig,
    *,
    path: str,
    revision: str | None,
    previous: dict[str, dict[str, Any]],
    analysis_version: int,
    changed: frozenset[str],
    change_kinds: dict[str, str],
    can_carry: bool,
) -> DiscoveredFile | None:
    if not path or config.is_ignored(path):
        return None
    language = detect_language(path)
    if language is None:
        return None
    prior = previous.get(path)
    if can_carry and path not in changed and _compatible_prior(prior, analysis_version):
        return DiscoveredFile(
            path,
            language,
            str(prior["raw_hash"]),
            b"",
            "carried_forward",
            "unchanged",
            False,
        )
    content = _read_source(root, config, path=path, revision=revision)
    if content is None or b"\0" in content[:8_192]:
        return None
    return DiscoveredFile(
        path,
        language,
        hashlib.sha256(content).hexdigest(),
        content,
        _read_reason(prior, analysis_version, can_carry),
        change_kinds.get(path, "full_scan"),
        True,
    )


def _compatible_prior(prior: dict[str, Any] | None, analysis_version: int) -> bool:
    if prior is None:
        return False
    metadata = json.loads(prior["metadata_json"] or "{}")
    return metadata.get("analysis_version") == analysis_version


def _read_reason(prior: dict[str, Any] | None, analysis_version: int, allow_carry: bool) -> str:
    if prior is None:
        return "content_changed"
    metadata = json.loads(prior["metadata_json"] or "{}")
    if metadata.get("analysis_version") != analysis_version:
        return "analyzer_upgraded"
    if not allow_carry:
        return "policy_changed"
    return "content_changed"


def _read_source(
    root: Path, config: DiscoveryConfig, *, path: str, revision: str | None
) -> bytes | None:
    if revision is not None:
        return git.read_at_revision(root, revision, path, max_bytes=config.max_file_bytes)
    candidate = root / path
    if not candidate.is_file() or candidate.is_symlink():
        return None
    try:
        if candidate.stat().st_size > config.max_file_bytes:
            return None
        return candidate.read_bytes()
    except OSError:
        return None


def _walk_files(root: Path, config: DiscoveryConfig) -> list[str]:
    result: list[str] = []
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        relative_dir = current_path.relative_to(root)
        directories[:] = [
            name
            for name in directories
            if not (current_path / name).is_symlink()
            and not config.is_ignored(str(relative_dir / name), is_dir=True)
        ]
        result.extend(str(relative_dir / name) for name in files)
    return result


def _normalized_path(path: str) -> str:
    value = path.replace("\\", "/")
    return value[2:] if value.startswith("./") else value

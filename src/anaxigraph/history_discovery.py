"""Delta-aware source discovery for historical repository frames."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from anaxigraph import git
from anaxigraph.languages import detect_language


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


def discover_files(
    root: Path,
    config: DiscoveryConfig,
    *,
    revision: str | None,
    previous_revision: str | None,
    previous: dict[str, dict[str, Any]],
    analysis_version: int,
    allow_carry: bool,
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
    )


def repository_metadata(root: Path, revision: str | None) -> Any:
    return git.metadata(root, revision=revision)


def available_changes(root: Path) -> list[git.GitChange]:
    try:
        return git.recent_changes(root)
    except git.GitError:
        return []


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
) -> DiscoveryResult:
    changed = delta.changed_current_paths if delta else frozenset()
    change_kinds = (
        {item.new_path: item.status for item in delta.changes if item.new_path is not None}
        if delta
        else {}
    )
    result = [
        item
        for raw_path in paths
        if (
            item := _materialize_path(
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
        )
        is not None
    ]
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

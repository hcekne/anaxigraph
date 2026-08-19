"""Operator-controlled repository registry for multi-repository services."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class RepositoryTarget:
    """A read-only repository the running service is allowed to analyze."""

    key: str
    path: Path
    config_path: Path | None = None
    history_snapshots: int = 64


def load_repository_registry(path: str | Path) -> tuple[RepositoryTarget, ...]:
    registry_path = Path(path).expanduser().resolve()
    if not registry_path.is_file():
        raise ValueError(f"Repository registry does not exist: {registry_path}")
    raw = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    entries = raw.get("repositories") if isinstance(raw, dict) else None
    if not isinstance(entries, (dict, list)) or not entries:
        raise ValueError("Repository registry must define a non-empty 'repositories' map or list")

    normalized: list[tuple[str, dict[str, Any]]] = []
    if isinstance(entries, dict):
        for key, value in entries.items():
            if not isinstance(value, dict):
                raise ValueError(f"Repository '{key}' must be a mapping")
            normalized.append((str(key), value))
    else:
        for index, value in enumerate(entries, start=1):
            if not isinstance(value, dict):
                raise ValueError(f"Repository entry {index} must be a mapping")
            key = str(value.get("id") or value.get("key") or f"repository-{index}")
            normalized.append((key, value))

    targets: list[RepositoryTarget] = []
    seen_keys: set[str] = set()
    seen_paths: set[Path] = set()
    for key, value in normalized:
        if value.get("enabled", True) is False:
            continue
        if key in seen_keys:
            raise ValueError(f"Duplicate repository registry key: {key}")
        path_value = value.get("path")
        if not isinstance(path_value, str) or not path_value.strip():
            raise ValueError(f"Repository '{key}' requires a path")
        repository = _resolve_path(path_value, registry_path.parent)
        if repository in seen_paths:
            raise ValueError(f"Repository path appears more than once: {repository}")
        config_value = value.get("config")
        if config_value is not None and not isinstance(config_value, str):
            raise ValueError(f"Repository '{key}' config must be a path string")
        history_snapshots = value.get("history_snapshots", 64)
        if not isinstance(history_snapshots, int) or not 0 <= history_snapshots <= 2_000:
            raise ValueError(f"Repository '{key}' history_snapshots must be between 0 and 2000")
        targets.append(
            RepositoryTarget(
                key=key,
                path=repository,
                config_path=(
                    _resolve_path(config_value, registry_path.parent) if config_value else None
                ),
                history_snapshots=history_snapshots,
            )
        )
        seen_keys.add(key)
        seen_paths.add(repository)
    if not targets:
        raise ValueError("Repository registry has no enabled repositories")
    return tuple(targets)


def _resolve_path(value: str, relative_to: Path) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = relative_to / candidate
    return candidate.resolve()

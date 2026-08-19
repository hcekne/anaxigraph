"""Configuration loading with conservative repository defaults."""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

DEFAULT_IGNORE = (
    ".git/**",
    ".hg/**",
    ".svn/**",
    ".codeintel/**",
    ".anaxigraph/**",
    ".venv/**",
    "venv/**",
    "node_modules/**",
    "dist/**",
    "build/**",
    ".next/**",
    ".nuxt/**",
    "coverage/**",
    "**/coverage.xml",
    "**/lcov.info",
    "htmlcov/**",
    "__pycache__/**",
    ".pytest_cache/**",
    ".mypy_cache/**",
    ".ruff_cache/**",
    "*.min.js",
    "*.map",
    "*.lock",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.webp",
    "*.ico",
    "*.pdf",
    "*.zip",
    "*.tar",
    "*.gz",
    "*.woff",
    "*.woff2",
    "*.ttf",
)


@dataclass(frozen=True, slots=True)
class GroupConfig:
    name: str
    paths: tuple[str, ...]
    level: str = "capability"
    parent: str | None = None
    description: str = ""


@dataclass(frozen=True, slots=True)
class RuleConfig:
    rule_id: str
    rule_type: str
    severity: str = "warning"
    description: str = ""
    enabled: bool = True
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ArchitectureConfig:
    policy: str | None = None
    rules: tuple[RuleConfig, ...] = ()
    protected_paths: tuple[str, ...] = ()
    boundaries: dict[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SemanticConfig:
    enabled: bool = False
    command: tuple[str, ...] = ()
    model: str = ""
    prompt_version: str = "v1"
    timeout_seconds: int = 120
    min_changed_lines: int = 1


@dataclass(frozen=True, slots=True)
class AgentConfig:
    context_limit: int = 25
    neighbor_depth: int = 2
    protected_paths: tuple[str, ...] = ()
    test_patterns: tuple[str, ...] = (
        "tests/**",
        "test/**",
        "**/tests/**",
        "**/*.test.*",
        "**/*.spec.*",
        "**/test_*.py",
        "**/*_test.py",
    )


@dataclass(frozen=True, slots=True)
class CodeIntelConfig:
    project_name: str | None = None
    ignore: tuple[str, ...] = DEFAULT_IGNORE
    include: tuple[str, ...] = ()
    groups: tuple[GroupConfig, ...] = ()
    architecture: ArchitectureConfig = field(default_factory=ArchitectureConfig)
    semantic: SemanticConfig = field(default_factory=SemanticConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    aliases: dict[str, str] = field(default_factory=dict)
    coverage_files: tuple[str, ...] = (
        "coverage.xml",
        "coverage/lcov.info",
        "lcov.info",
    )
    max_file_bytes: int = 2_000_000
    config_path: Path | None = None

    def is_ignored(self, path: str, *, is_dir: bool = False) -> bool:
        normalized = path.replace(os.sep, "/")
        if normalized.startswith("./"):
            normalized = normalized[2:]
        candidate = f"{normalized}/" if is_dir else normalized
        if (
            self.include
            and not is_dir
            and not any(path_matches(normalized, pattern) for pattern in self.include)
        ):
            return True
        return any(
            path_matches(normalized, pattern) or (is_dir and path_matches(candidate, pattern))
            for pattern in self.ignore
        )

    def declared_group(self, path: str) -> str | None:
        for group in self.groups:
            if any(path_matches(path, pattern) for pattern in group.paths):
                return group.name
        return None


def path_matches(path: str, pattern: str) -> bool:
    """Match common gitignore-style globs without making config depend on Git."""

    normalized = path.replace("\\", "/")
    clean_pattern = pattern.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    if clean_pattern.startswith("./"):
        clean_pattern = clean_pattern[2:]
    if clean_pattern.endswith("/"):
        clean_pattern += "**"
    if fnmatch.fnmatchcase(normalized, clean_pattern):
        return True
    try:
        if PurePosixPath(normalized).match(clean_pattern):
            return True
    except ValueError:
        pass
    if clean_pattern.startswith("**/"):
        return fnmatch.fnmatchcase(normalized, clean_pattern[3:])
    return False


def _tuple_of_strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, (list, tuple)):
        raise ValueError("Expected a string or list of strings")
    return tuple(str(item) for item in value)


def _groups(value: Any) -> tuple[GroupConfig, ...]:
    if not value:
        return ()
    if not isinstance(value, dict):
        raise ValueError("groups must be a mapping")
    result: list[GroupConfig] = []
    for name, raw in value.items():
        raw = raw or {}
        if isinstance(raw, list):
            raw = {"paths": raw}
        result.append(
            GroupConfig(
                name=str(name),
                paths=_tuple_of_strings(raw.get("paths")),
                level=str(raw.get("level", "capability")),
                parent=str(raw["parent"]) if raw.get("parent") else None,
                description=str(raw.get("description", "")),
            )
        )
    return tuple(result)


def _rules(value: Any) -> tuple[RuleConfig, ...]:
    if not value:
        return ()
    if not isinstance(value, list):
        raise ValueError("architecture.rules must be a list")
    result: list[RuleConfig] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise ValueError(f"architecture.rules[{index}] must be a mapping")
        rule_type = str(raw.get("type") or "").strip()
        if not rule_type:
            raise ValueError(f"architecture.rules[{index}] requires type")
        known = {"id", "type", "severity", "description", "enabled", "params"}
        params = dict(raw.get("params") or {})
        params.update({key: val for key, val in raw.items() if key not in known})
        result.append(
            RuleConfig(
                rule_id=str(raw.get("id") or f"configured-{index + 1}"),
                rule_type=rule_type,
                severity=str(raw.get("severity", "warning")),
                description=str(raw.get("description", "")),
                enabled=bool(raw.get("enabled", True)),
                params=params,
            )
        )
    return tuple(result)


def load_config(repository: Path, config_path: Path | None = None) -> CodeIntelConfig:
    repository = repository.resolve()
    if config_path:
        selected = config_path.resolve()
    else:
        current = repository / ".anaxigraph.yml"
        legacy = repository / ".codeintel.yml"
        selected = current if current.exists() or not legacy.exists() else legacy
    raw: dict[str, Any] = {}
    if selected.exists():
        loaded = yaml.safe_load(selected.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"{selected} must contain a YAML mapping")
        raw = loaded

    project = raw.get("project") or {}
    architecture = raw.get("architecture") or {}
    semantic = raw.get("semantic") or {}
    agent = raw.get("agent") or {}
    boundaries = {
        str(name): _tuple_of_strings(paths)
        for name, paths in (architecture.get("boundaries") or {}).items()
    }
    configured_ignore = _tuple_of_strings(raw.get("ignore"))
    return CodeIntelConfig(
        project_name=str(project.get("name")) if project.get("name") else None,
        ignore=tuple(dict.fromkeys((*DEFAULT_IGNORE, *configured_ignore))),
        include=_tuple_of_strings(raw.get("include")),
        groups=_groups(raw.get("groups")),
        architecture=ArchitectureConfig(
            policy=str(architecture["policy"]) if architecture.get("policy") else None,
            rules=_rules(architecture.get("rules")),
            protected_paths=_tuple_of_strings(architecture.get("protected_paths")),
            boundaries=boundaries,
        ),
        semantic=SemanticConfig(
            enabled=bool(semantic.get("enabled", False)),
            command=_tuple_of_strings(semantic.get("command")),
            model=str(semantic.get("model", "")),
            prompt_version=str(semantic.get("prompt_version", "v1")),
            timeout_seconds=int(semantic.get("timeout_seconds", 120)),
            min_changed_lines=int(semantic.get("min_changed_lines", 1)),
        ),
        agent=AgentConfig(
            context_limit=int(agent.get("context_limit", 25)),
            neighbor_depth=int(agent.get("neighbor_depth", 2)),
            protected_paths=_tuple_of_strings(agent.get("protected_paths")),
            test_patterns=_tuple_of_strings(agent.get("test_patterns"))
            or AgentConfig().test_patterns,
        ),
        aliases={str(key): str(value) for key, value in (raw.get("aliases") or {}).items()},
        coverage_files=_tuple_of_strings(raw.get("coverage", {}).get("files"))
        or CodeIntelConfig().coverage_files,
        max_file_bytes=int(raw.get("max_file_bytes", 2_000_000)),
        config_path=selected if selected.exists() else None,
    )

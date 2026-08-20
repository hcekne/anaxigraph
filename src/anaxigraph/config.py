"""Configuration loading with conservative repository defaults."""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

DEFAULT_IGNORE = (
    ".git/**",
    ".hg/**",
    ".svn/**",
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
    provider: str = "command"
    command: tuple[str, ...] = ()
    model: str = ""
    prompt_version: str = "v1"
    timeout_seconds: int = 120
    refresh: str = "manual"
    reconcile_interval_minutes: int = 1_440
    max_age_days: int = 0
    max_jobs_per_run: int = 100
    max_parallel_jobs: int = 1
    max_attempts: int = 3
    max_source_chars: int = 100_000
    max_context_modules: int = 24
    max_output_tokens: int = 4_000
    agent_lease_seconds: int = 1_800
    daily_budget_usd: float | None = None
    input_cost_per_million: float = 0.0
    output_cost_per_million: float = 0.0
    base_url: str = ""
    api_key_env: str = ""
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = (
        "vendor/**",
        "**/vendor/**",
        "generated/**",
        "**/generated/**",
    )

    def includes_path(self, path: str) -> bool:
        if self.include and not any(path_matches(path, pattern) for pattern in self.include):
            return False
        return not any(path_matches(path, pattern) for pattern in self.exclude)


@dataclass(frozen=True, slots=True)
class AgentConfig:
    context_limit: int = 25
    neighbor_depth: int = 2
    payload_limit_bytes: int = 20_000
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
class AnaxiGraphConfig:
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
    coverage_required: bool = False
    max_file_bytes: int = 2_000_000
    config_path: Path | None = None

    def is_ignored(self, path: str, *, is_dir: bool = False) -> bool:
        normalized = path.replace(os.sep, "/")
        if normalized.startswith("./"):
            normalized = normalized[2:]
        return _is_ignored(self.include, self.ignore, normalized, is_dir)

    def declared_group(self, path: str) -> str | None:
        return _declared_group(self.groups, path)


@lru_cache(maxsize=8_192)
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


@lru_cache(maxsize=50_000)
def _is_ignored(
    include: tuple[str, ...], ignore: tuple[str, ...], normalized: str, is_dir: bool
) -> bool:
    candidate = f"{normalized}/" if is_dir else normalized
    if include and not is_dir and not any(path_matches(normalized, pattern) for pattern in include):
        return True
    return any(
        path_matches(normalized, pattern) or (is_dir and path_matches(candidate, pattern))
        for pattern in ignore
    )


@lru_cache(maxsize=50_000)
def _declared_group(groups: tuple[GroupConfig, ...], path: str) -> str | None:
    for group in groups:
        if any(path_matches(path, pattern) for pattern in group.paths):
            return group.name
    return None


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


def _semantic_config(value: Any) -> SemanticConfig:
    if not value:
        return SemanticConfig()
    if not isinstance(value, dict):
        raise ValueError("semantic must be a mapping")
    provider = str(value.get("provider", "command")).strip().lower()
    if provider not in {"agent", "command", "codex", "claude", "openai", "anthropic"}:
        raise ValueError(
            "semantic.provider must be agent, command, codex, claude, openai, or anthropic"
        )
    refresh = str(value.get("refresh", "manual")).strip().lower().replace("-", "_")
    if refresh not in {"manual", "on_scan", "watch", "periodic"}:
        raise ValueError("semantic.refresh must be manual, on_scan, watch, or periodic")

    def integer(name: str, default: int, minimum: int) -> int:
        result = int(value.get(name, default))
        if result < minimum:
            raise ValueError(f"semantic.{name} must be at least {minimum}")
        return result

    budget_value = value.get("daily_budget_usd")
    budget = float(budget_value) if budget_value is not None else None
    if budget is not None and budget < 0:
        raise ValueError("semantic.daily_budget_usd cannot be negative")
    input_cost = float(value.get("input_cost_per_million", 0.0))
    output_cost = float(value.get("output_cost_per_million", 0.0))
    if input_cost < 0 or output_cost < 0:
        raise ValueError("semantic token costs cannot be negative")

    return SemanticConfig(
        enabled=bool(value.get("enabled", False)),
        provider=provider,
        command=_tuple_of_strings(value.get("command")),
        model=str(value.get("model", "")),
        prompt_version=str(value.get("prompt_version", "v1")),
        timeout_seconds=integer("timeout_seconds", 120, 1),
        refresh=refresh,
        reconcile_interval_minutes=integer("reconcile_interval_minutes", 1_440, 1),
        max_age_days=integer("max_age_days", 0, 0),
        max_jobs_per_run=integer("max_jobs_per_run", 100, 1),
        max_parallel_jobs=integer("max_parallel_jobs", 1, 1),
        max_attempts=integer("max_attempts", 3, 1),
        max_source_chars=integer("max_source_chars", 100_000, 4_000),
        max_context_modules=integer("max_context_modules", 24, 1),
        max_output_tokens=integer("max_output_tokens", 4_000, 256),
        agent_lease_seconds=integer("agent_lease_seconds", 1_800, 60),
        daily_budget_usd=budget,
        input_cost_per_million=input_cost,
        output_cost_per_million=output_cost,
        base_url=str(value.get("base_url", "")),
        api_key_env=str(value.get("api_key_env", "")),
        include=_tuple_of_strings(value.get("include")),
        exclude=_tuple_of_strings(value.get("exclude")) or SemanticConfig().exclude,
    )


def load_config(repository: Path, config_path: Path | None = None) -> AnaxiGraphConfig:
    repository = repository.resolve()
    if config_path:
        selected = config_path.resolve()
    else:
        selected = repository / ".anaxigraph.yml"
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
    return AnaxiGraphConfig(
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
        semantic=_semantic_config(semantic),
        agent=AgentConfig(
            context_limit=int(agent.get("context_limit", 25)),
            neighbor_depth=int(agent.get("neighbor_depth", 2)),
            payload_limit_bytes=max(4_000, int(agent.get("payload_limit_bytes", 20_000))),
            protected_paths=_tuple_of_strings(agent.get("protected_paths")),
            test_patterns=_tuple_of_strings(agent.get("test_patterns"))
            or AgentConfig().test_patterns,
        ),
        aliases={str(key): str(value) for key, value in (raw.get("aliases") or {}).items()},
        coverage_files=_tuple_of_strings(raw.get("coverage", {}).get("files"))
        or AnaxiGraphConfig().coverage_files,
        coverage_required=bool(raw.get("coverage", {}).get("required", False)),
        max_file_bytes=int(raw.get("max_file_bytes", 2_000_000)),
        config_path=selected if selected.exists() else None,
    )

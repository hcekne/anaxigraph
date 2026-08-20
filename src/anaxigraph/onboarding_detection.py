"""Read-only repository discovery used to propose a first-run policy."""

from __future__ import annotations

import json
import os
import re
import tomllib
from pathlib import Path
from typing import Any

import yaml

from anaxigraph import git
from anaxigraph.config import AnaxiGraphConfig, load_config
from anaxigraph.languages import detect_language

_IGNORED_DIRECTORY_NAMES = {
    ".anaxigraph",
    ".git",
    ".hg",
    ".mypy_cache",
    ".next",
    ".nuxt",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "htmlcov",
    "node_modules",
    "target",
    "vendor",
    "venv",
}

_GROUP_DETAILS = {
    "agent-runner": ("agent-runtime", "Agent execution, model-provider, and tool runtime code."),
    "api": ("api", "Public or internal transport and API boundary."),
    "backend": ("backend", "Backend application and service implementation."),
    "client": ("frontend", "User-facing client application."),
    "deploy": ("infrastructure", "Deployment and runtime infrastructure."),
    "docs": ("documentation", "Architecture, operating, and contributor documentation."),
    "documentation": ("documentation", "Architecture, operating, and contributor documentation."),
    "frontend": ("frontend", "User-facing frontend application."),
    "infra": ("infrastructure", "Deployment and runtime infrastructure."),
    "infrastructure": ("infrastructure", "Deployment and runtime infrastructure."),
    "lib": ("library", "Shared library implementation."),
    "migrations": ("database-migrations", "Ordered database schema changes."),
    "packages": ("packages", "Workspace packages and shared libraries."),
    "scripts": ("developer-tooling", "Repository maintenance and developer automation."),
    "server": ("backend", "Backend server implementation."),
    "services": ("services", "Application services and independently deployable components."),
    "src": ("source", "Primary product implementation."),
    "test": ("testing", "Automated verification and test support code."),
    "tests": ("testing", "Automated verification and test support code."),
    "tools": ("developer-tooling", "Repository maintenance and developer automation."),
    "ui": ("frontend", "User-facing interface implementation."),
    "web": ("frontend", "User-facing web application."),
}

_GROUP_PRIORITY = {
    "frontend": 10,
    "backend": 20,
    "source": 30,
    "services": 35,
    "packages": 40,
    "library": 45,
    "testing": 70,
    "documentation": 80,
    "developer-tooling": 90,
    "infrastructure": 100,
    "database-migrations": 110,
}


def detect_project_name(repository: Path) -> str:
    """Prefer existing project metadata, then fall back to the checkout name."""

    config = repository / ".anaxigraph.yml"
    if config.is_file():
        try:
            value = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
            name = (value.get("project") or {}).get("name")
            if name:
                return str(name)
        except (OSError, yaml.YAMLError, AttributeError):
            pass
    package_json = repository / "package.json"
    if package_json.is_file():
        try:
            value = json.loads(package_json.read_text(encoding="utf-8"))
            if value.get("name"):
                return display_name(str(value["name"]))
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
    pyproject = repository / "pyproject.toml"
    if pyproject.is_file():
        try:
            value = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            name = (value.get("project") or {}).get("name")
            if name:
                return display_name(str(name))
        except (OSError, tomllib.TOMLDecodeError, AttributeError):
            pass
    return display_name(repository.name) or "Repository"


def repository_policy_details(repository: Path, config_path: Path | None = None) -> dict[str, Any]:
    config = load_config(repository, config_path)
    return {
        "project_name": config.project_name,
        "semantic": {"enabled": config.semantic.enabled, "provider": config.semantic.provider},
    }


def display_name(value: str) -> str:
    unscoped = value.rsplit("/", 1)[-1]
    words = [word for word in re.split(r"[-_.\s]+", unscoped) if word]
    return " ".join(
        word if any(character.isupper() for character in word) else word.title() for word in words
    )


def project_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (slug or "repository")[:50].rstrip("-")


def detect_repository_groups(repository: Path) -> list[tuple[str, str, str]]:
    """Return (group name, path glob, description) for obvious top-level areas."""

    existing_config = load_config(repository)
    listed_files = git.listed_files(repository)
    analyzable_directories = {
        Path(path).parts[0]
        for path in listed_files
        if len(Path(path).parts) > 1 and detect_language(path)
    }
    candidates: list[tuple[str, str, str]] = []
    used_names: set[str] = set()
    for directory in sorted(repository.iterdir(), key=lambda item: item.name.lower()):
        if not _eligible_directory(
            directory, repository, existing_config, listed_files, analyzable_directories
        ):
            continue
        normalized = project_slug(directory.name)
        configured_name, description = _GROUP_DETAILS.get(
            normalized,
            (normalized, f"Detected top-level {display_name(directory.name)} area."),
        )
        name = _unique_group_name(configured_name, used_names)
        used_names.add(name)
        candidates.append((name, f"{directory.name}/**", description))
    candidates.sort(key=lambda group: (_GROUP_PRIORITY.get(group[0], 60), group[0], group[1]))
    return candidates[:16]


def _eligible_directory(
    directory: Path,
    repository: Path,
    config: AnaxiGraphConfig,
    listed_files: list[str],
    analyzable_directories: set[str],
) -> bool:
    if not directory.is_dir() or directory.name.startswith("."):
        return False
    if directory.name.lower() in _IGNORED_DIRECTORY_NAMES:
        return False
    if config.is_ignored(directory.name, is_dir=True):
        return False
    if listed_files:
        return directory.name in analyzable_directories
    return _contains_analyzable_file(directory, repository)


def _unique_group_name(configured_name: str, used_names: set[str]) -> str:
    name = configured_name
    suffix = 2
    while name in used_names:
        name = f"{configured_name}-{suffix}"
        suffix += 1
    return name


def detect_architecture_policy(repository: Path) -> str | None:
    configured = load_config(repository).architecture.policy
    if configured:
        return configured
    for candidate in (
        "ARCHITECTURE.md",
        "architecture.md",
        "docs/architecture.md",
        "docs/ARCHITECTURE.md",
    ):
        if (repository / candidate).is_file():
            return candidate
    return None


def detect_coverage_files(repository: Path) -> list[str]:
    found: list[str] = []
    for current, directories, files in os.walk(repository):
        relative = Path(current).relative_to(repository)
        directories[:] = [
            name
            for name in directories
            if not name.startswith(".")
            and name.lower() not in (_IGNORED_DIRECTORY_NAMES - {"coverage"})
        ]
        if len(relative.parts) >= 5:
            directories[:] = []
        for name in files:
            if name in {"coverage.xml", "lcov.info"}:
                found.append((relative / name).as_posix().removeprefix("./"))
    return sorted(dict.fromkeys(found)) or ["coverage.xml", "coverage/lcov.info", "lcov.info"]


def _contains_analyzable_file(directory: Path, repository: Path) -> bool:
    examined = 0
    for current, directories, files in os.walk(directory):
        directories[:] = [
            name
            for name in directories
            if not name.startswith(".") and name.lower() not in _IGNORED_DIRECTORY_NAMES
        ]
        for name in files:
            examined += 1
            path = (Path(current) / name).relative_to(repository).as_posix()
            if detect_language(path):
                return True
            if examined >= 3_000:
                return False
    return False

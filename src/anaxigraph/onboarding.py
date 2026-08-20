"""Safe first-run setup for using AnaxiGraph beside an existing repository."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from anaxigraph.onboarding_detection import (
    detect_architecture_policy,
    detect_coverage_files,
    detect_project_name,
    detect_repository_groups,
    project_slug,
)
from anaxigraph.onboarding_policy import enable_agent_semantics
from anaxigraph.onboarding_templates import render_compose, render_repository_config
from anaxigraph.registry import parse_history_snapshots

DEFAULT_CONTAINER_IMAGE = "ghcr.io/hcekne/anaxigraph:latest"
DEFAULT_COMPOSE_FILE = "compose.anaxigraph.yml"
DEFAULT_CONFIG_FILE = ".anaxigraph.yml"


def initialize_repository(
    repository: str | Path,
    *,
    project_name: str | None = None,
    config_name: str = DEFAULT_CONFIG_FILE,
    compose_name: str | None = DEFAULT_COMPOSE_FILE,
    image: str = DEFAULT_CONTAINER_IMAGE,
    port: int = 8765,
    history_snapshots: int | str = "auto",
    semantic_mode: str | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Generate an editable policy and a read-only Docker sidecar definition."""

    root, history_snapshots = _validated_options(
        repository,
        config_name=config_name,
        compose_name=compose_name,
        image=image,
        port=port,
        history_snapshots=history_snapshots,
        semantic_mode=semantic_mode,
    )
    plan = _repository_plan(
        root,
        project_name=project_name,
        config_name=config_name,
        compose_name=compose_name,
        image=image,
        port=port,
        history_snapshots=history_snapshots,
        semantic_mode=semantic_mode,
    )
    return _finish_initialization(
        root,
        plan=plan,
        config_name=config_name,
        compose_name=compose_name,
        port=port,
        semantic_mode=semantic_mode,
        force=force,
        dry_run=dry_run,
    )


def _finish_initialization(
    root: Path,
    *,
    plan: dict[str, Any],
    config_name: str,
    compose_name: str | None,
    port: int,
    semantic_mode: str | None,
    force: bool,
    dry_run: bool,
) -> dict[str, Any]:
    files = _apply_planned_files(
        plan["planned_files"],
        config_name=config_name,
        semantic_mode=semantic_mode,
        force=force,
        dry_run=dry_run,
    )
    return _initialization_result(
        root,
        name=plan["name"],
        groups=plan["groups"],
        policy=plan["policy"],
        coverage_files=plan["coverage_files"],
        files=files,
        compose_name=compose_name,
        port=port,
        semantic_mode=semantic_mode,
        dry_run=dry_run,
    )


def _repository_plan(
    root: Path,
    *,
    project_name: str | None,
    config_name: str,
    compose_name: str | None,
    image: str,
    port: int,
    history_snapshots: int | str,
    semantic_mode: str | None,
) -> dict[str, Any]:
    name = (
        project_name.strip() if project_name and project_name.strip() else detect_project_name(root)
    )
    groups = detect_repository_groups(root)
    policy = detect_architecture_policy(root)
    coverage_files = detect_coverage_files(root)
    return {
        "name": name,
        "groups": groups,
        "policy": policy,
        "coverage_files": coverage_files,
        "planned_files": _planned_files(
            root,
            name=name,
            slug=project_slug(name),
            groups=groups,
            policy=policy,
            coverage_files=coverage_files,
            config_name=config_name,
            compose_name=compose_name,
            image=image,
            port=port,
            history_snapshots=history_snapshots,
            semantic_mode=semantic_mode,
        ),
    }


def _validated_options(
    repository: str | Path,
    *,
    config_name: str,
    compose_name: str | None,
    image: str,
    port: int,
    history_snapshots: int | str,
    semantic_mode: str | None,
) -> tuple[Path, int | str]:
    root = Path(repository).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Repository directory does not exist: {root}")
    if not 1 <= port <= 65_535:
        raise ValueError("Port must be between 1 and 65535")
    history_snapshots = parse_history_snapshots(history_snapshots)
    if not image.strip() or any(character.isspace() for character in image):
        raise ValueError("Container image must be a non-empty reference without whitespace")
    if not config_name or Path(config_name).name != config_name:
        raise ValueError("Config filename must be a filename inside the repository root")
    if compose_name is not None and (not compose_name or Path(compose_name).name != compose_name):
        raise ValueError("Compose filename must be a filename inside the repository root")
    if semantic_mode not in {None, "agent"}:
        raise ValueError("semantic mode must be agent when provided")
    return root, history_snapshots


def _planned_files(
    root: Path,
    *,
    name: str,
    slug: str,
    groups: list[tuple[str, str, str]],
    policy: str | None,
    coverage_files: list[str],
    config_name: str,
    compose_name: str | None,
    image: str,
    port: int,
    history_snapshots: int | str,
    semantic_mode: str | None,
) -> list[tuple[Path, str, str]]:
    config_content = render_repository_config(
        name,
        groups=groups,
        architecture_policy=policy,
        coverage_files=coverage_files,
        semantic_enabled=semantic_mode == "agent",
    )
    planned_files = [(root / config_name, config_content, "repository policy")]
    if compose_name:
        planned_files.append(
            (
                root / compose_name,
                render_compose(
                    project_slug_value=slug,
                    image=image,
                    port=port,
                    history_snapshots=history_snapshots,
                ),
                "Docker sidecar",
            )
        )
    return planned_files


def _apply_planned_files(
    planned_files: list[tuple[Path, str, str]],
    *,
    config_name: str,
    semantic_mode: str | None,
    force: bool,
    dry_run: bool,
) -> list[dict[str, str]]:
    return [
        {
            "path": str(path),
            "purpose": purpose,
            "action": _apply_planned_file(
                path,
                content,
                update_semantics=path.name == config_name and semantic_mode == "agent",
                force=force,
                dry_run=dry_run,
            ),
        }
        for path, content, purpose in planned_files
    ]


def _apply_planned_file(
    path: Path,
    content: str,
    *,
    update_semantics: bool,
    force: bool,
    dry_run: bool,
) -> str:
    existed = path.exists()
    if existed and not force and update_semantics:
        current = path.read_text(encoding="utf-8")
        content = enable_agent_semantics(current)
        if content == current:
            return "unchanged"
        if not dry_run:
            _write_text_atomic(path, content)
        return "would_update" if dry_run else "updated"
    if existed and not force:
        return "skipped"
    if dry_run:
        return "would_overwrite" if existed else "would_create"
    _write_text_atomic(path, content)
    return "overwritten" if existed else "created"


def _initialization_result(
    root: Path,
    *,
    name: str,
    groups: list[tuple[str, str, str]],
    policy: str | None,
    coverage_files: list[str],
    files: list[dict[str, str]],
    compose_name: str | None,
    port: int,
    semantic_mode: str | None,
    dry_run: bool,
) -> dict[str, Any]:
    dashboard_url = f"http://127.0.0.1:{port}"
    mcp_url = f"{dashboard_url}/mcp"
    return {
        "status": "dry_run" if dry_run else "initialized",
        "repository": str(root),
        "project_name": name,
        "project_slug": project_slug(name),
        "detected": {
            "groups": [group[0] for group in groups],
            "architecture_policy": policy,
            "coverage_files": coverage_files,
        },
        "files": files,
        "commands": _initialization_commands(root, compose_name, mcp_url),
        "dashboard_url": dashboard_url,
        "mcp_url": mcp_url,
        "semantic": {
            "requested": semantic_mode,
            "enabled": semantic_mode == "agent",
            "executor": "connected coding agent" if semantic_mode == "agent" else None,
        },
        "network_urls": {
            "container_mcp": "http://anaxigraph:8765/mcp",
            "remote_mcp": f"http://<server-host>:{port}/mcp",
        },
        "codex_config": f'[mcp_servers.anaxigraph]\nurl = "{mcp_url}"\n',
    }


def _initialization_commands(
    root: Path, compose_name: str | None, mcp_url: str
) -> dict[str, str | None]:
    quoted_compose = shlex.quote(compose_name) if compose_name else None
    return {
        "start": f"docker compose -f {quoted_compose} up -d" if quoted_compose else None,
        "start_with_watch": (
            f"docker compose -f {quoted_compose} --profile watch up -d" if quoted_compose else None
        ),
        "logs": (
            f"docker compose -f {quoted_compose} logs -f anaxigraph" if quoted_compose else None
        ),
        "local": f"anaxigraph serve --repository {shlex.quote(str(root))} --scan-on-start --open",
        "connect_codex": f"codex mcp add anaxigraph --url {mcp_url}",
    }


def _write_text_atomic(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.anaxigraph-tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)

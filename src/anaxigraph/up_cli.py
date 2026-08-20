"""CLI contract for the one-command, no-Docker local runtime."""

from __future__ import annotations

import shlex
from argparse import Namespace
from pathlib import Path
from typing import Any

from anaxigraph.local_runtime import (
    LocalRuntime,
    assert_port_available,
    local_database_path,
    print_runtime_banner,
    run_local_service,
)
from anaxigraph.onboarding import DEFAULT_CONFIG_FILE, initialize_repository
from anaxigraph.onboarding_clients import (
    CLIENTS,
    CONNECTION_SCOPES,
    configure_client,
    validate_mcp_url,
)
from anaxigraph.registry import parse_history_snapshots


def configure_up_command(
    commands: Any, *, index_factory: Any, app_factory: Any, config_loader: Any
) -> None:
    up = commands.add_parser(
        "up",
        help="Scan and run a loopback dashboard/MCP service without Docker",
        description=(
            "Create or load a repository policy, keep AnaxiIndex in private user state, scan the "
            "current checkout, and serve the dashboard plus AnaxiMCP on loopback."
        ),
    )
    up.add_argument("repository", nargs="?", type=Path, default=Path.cwd())
    up.add_argument("--port", type=int, default=8765)
    up.add_argument(
        "--history-snapshots",
        type=parse_history_snapshots,
        default="auto",
        help="Background Git history frames: auto or 0 to 2000 (default: auto)",
    )
    up.add_argument(
        "--db", type=Path, help="Explicit AnaxiIndex path (default: per-repo user state)"
    )
    up.add_argument("--open", action="store_true", help="Open the dashboard after it is healthy")
    _add_agent_options(up)
    up.add_argument(
        "--dry-run", action="store_true", help="Preview setup without writing or serving"
    )
    up.add_argument("--json", action="store_true", help="Emit a machine-readable dry-run plan")
    up.set_defaults(
        handler=up_workflow,
        index_factory=index_factory,
        app_factory=app_factory,
        config_loader=config_loader,
    )


def _add_agent_options(up: Any) -> None:
    up.add_argument(
        "--semantic",
        choices=["agent"],
        help="Enable semantic work executed with the connected coding agent's own tokens",
    )
    up.add_argument(
        "--connect",
        action="append",
        choices=CLIENTS,
        help="Connect Codex or Claude; repeat to configure both",
    )
    up.add_argument(
        "--connect-scope",
        choices=CONNECTION_SCOPES,
        default="user",
        help="Private user-wide or trusted project-local MCP configuration (default: user)",
    )
    up.add_argument("--mcp-url", help="Endpoint stored for the coding client")


def up_workflow(args: Namespace) -> dict[str, Any] | None:
    if args.json and not args.dry_run:
        raise ValueError("--json requires --dry-run for the long-running up command")
    runtime, result, restart = _prepare_up(args)
    if args.dry_run:
        return result
    print_runtime_banner(runtime, restart_command=restart)
    run_local_service(
        runtime,
        index_factory=args.index_factory,
        app_factory=args.app_factory,
    )
    print("AnaxiGraph stopped cleanly; durable history will resume next time.")
    return None


def _prepare_up(args: Namespace) -> tuple[LocalRuntime, dict[str, Any], str]:
    repository = args.repository.expanduser().resolve()
    database_path = local_database_path(repository, explicit=args.db)
    runtime = LocalRuntime(
        repository=repository,
        config_path=repository / DEFAULT_CONFIG_FILE,
        database_path=database_path,
        port=args.port,
        history_snapshots=args.history_snapshots,
        open_browser=args.open,
    )
    connection_url = validate_mcp_url(args.mcp_url or runtime.mcp_url)
    if not args.dry_run:
        assert_port_available(args.port)
    initialization = initialize_repository(
        repository,
        config_name=DEFAULT_CONFIG_FILE,
        compose_name=None,
        port=args.port,
        history_snapshots=args.history_snapshots,
        semantic_mode=args.semantic,
        dry_run=args.dry_run,
    )
    connections = _configure_connections(args, repository, connection_url)
    policy = args.config_loader(repository)
    semantic_enabled = args.semantic == "agent" or policy.semantic.enabled
    restart = _restart_command(args, repository)
    result = {
        "status": "dry_run" if args.dry_run else "starting",
        "mode": "local_loopback",
        "repository": str(repository),
        "policy": initialization["files"][0],
        "database": str(database_path),
        "dashboard_url": runtime.dashboard_url,
        "mcp_url": runtime.mcp_url,
        "connection_mcp_url": connection_url,
        "history_snapshots": args.history_snapshots,
        "semantic": {
            "requested": args.semantic,
            "enabled": semantic_enabled,
            "executor": "connected coding agent" if semantic_enabled else None,
        },
        "connections": connections,
        "agent_scan": True,
        "commands": {"stop": "Ctrl-C", "restart": restart},
    }
    return runtime, result, restart


def _configure_connections(
    args: Namespace, repository: Path, connection_url: str
) -> list[dict[str, Any]]:
    return [
        configure_client(
            client,
            scope=args.connect_scope,
            repository=repository,
            mcp_url=connection_url,
            dry_run=args.dry_run,
        )
        for client in dict.fromkeys(args.connect or [])
    ]


def _restart_command(args: Namespace, repository: Path) -> str:
    command = ["uvx", "anaxigraph", "up", str(repository)]
    if args.port != 8765:
        command.extend(("--port", str(args.port)))
    if args.history_snapshots != "auto":
        command.extend(("--history-snapshots", str(args.history_snapshots)))
    if args.db:
        command.extend(("--db", str(args.db.expanduser().resolve())))
    if args.open:
        command.append("--open")
    if args.semantic:
        command.extend(("--semantic", args.semantic))
    for client in dict.fromkeys(args.connect or []):
        command.extend(("--connect", client))
    if args.connect_scope != "user":
        command.extend(("--connect-scope", args.connect_scope))
    if args.mcp_url:
        command.extend(("--mcp-url", args.mcp_url))
    return shlex.join(command)

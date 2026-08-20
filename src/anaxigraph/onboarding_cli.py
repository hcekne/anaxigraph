"""CLI parser and command workflow for explicit first-run setup."""

from __future__ import annotations

import subprocess
from argparse import Namespace
from pathlib import Path
from typing import Any

from anaxigraph.onboarding import initialize_repository
from anaxigraph.onboarding_clients import CLIENTS, CONNECTION_SCOPES, configure_client


def configure_initialize_command(commands: Any) -> None:
    initialize = commands.add_parser(
        "init",
        help="Create policy, sidecar, semantics, and an optional MCP client connection",
        description=(
            "Detect repository areas and generate a reviewable AnaxiGraph policy plus an "
            "optional read-only Docker sidecar. Client configuration changes require an explicit "
            "--connect choice and are previewed by --dry-run."
        ),
    )
    _add_repository_options(initialize)
    _add_agent_options(initialize)
    _add_execution_options(initialize)
    initialize.set_defaults(handler=initialize_workflow)


def _add_repository_options(initialize: Any) -> None:
    initialize.add_argument("repository", nargs="?", type=Path, default=Path.cwd())
    initialize.add_argument("--project-name", help="Human-readable project name")
    initialize.add_argument("--config-name", default=".anaxigraph.yml")
    initialize.add_argument("--compose-name", default="compose.anaxigraph.yml")
    initialize.add_argument(
        "--no-compose",
        action="store_true",
        help="Generate only the repository policy for a local CLI installation",
    )
    initialize.add_argument(
        "--image",
        default="ghcr.io/hcekne/anaxigraph:latest",
        help="Container image written to Compose",
    )
    initialize.add_argument("--port", type=int, default=8765, help="Local dashboard port")
    initialize.add_argument(
        "--history-snapshots",
        default="auto",
        help="Git history frame policy: auto or an integer from 0 to 2000 (default: auto)",
    )


def _add_agent_options(initialize: Any) -> None:
    initialize.add_argument(
        "--semantic",
        choices=["agent"],
        help="Enable semantic work funded and executed by the connected coding agent",
    )
    initialize.add_argument(
        "--connect",
        action="append",
        choices=CLIENTS,
        help="Connect an MCP client; repeat to configure both Codex and Claude",
    )
    initialize.add_argument(
        "--connect-scope",
        choices=CONNECTION_SCOPES,
        default="user",
        help="Write private user-wide or trusted project-local MCP configuration (default: user)",
    )
    initialize.add_argument(
        "--mcp-url",
        help="Agent-reachable MCP URL; defaults to the generated loopback endpoint",
    )


def _add_execution_options(initialize: Any) -> None:
    initialize.add_argument(
        "--force",
        action="store_true",
        help="Replace existing generated filenames after explicit review",
    )
    initialize.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview repository and client changes without writing files",
    )
    initialize.add_argument(
        "--start",
        action="store_true",
        help="Start the generated Docker Compose service after writing it",
    )
    initialize.add_argument("--json", action="store_true", help="Emit machine-readable JSON")


def initialize_workflow(args: Namespace) -> dict[str, Any] | None:
    if args.start and args.dry_run:
        raise ValueError("--start cannot be combined with --dry-run")
    if args.start and args.no_compose:
        raise ValueError("--start requires a generated Compose file")
    result = initialize_repository(
        args.repository,
        project_name=args.project_name,
        config_name=args.config_name,
        compose_name=None if args.no_compose else args.compose_name,
        image=args.image,
        port=args.port,
        history_snapshots=args.history_snapshots,
        semantic_mode=args.semantic,
        force=args.force,
        dry_run=args.dry_run,
    )
    if args.start:
        _start_generated_compose(args, result)
    connection_url = args.mcp_url or result["mcp_url"]
    result["connection_mcp_url"] = connection_url
    result["connections"] = [
        configure_client(
            client,
            scope=args.connect_scope,
            repository=Path(result["repository"]),
            mcp_url=connection_url,
            dry_run=args.dry_run,
        )
        for client in dict.fromkeys(args.connect or [])
    ]
    if args.json:
        return result
    _print_initialization(args, result)
    return None


def _start_generated_compose(args: Namespace, result: dict[str, Any]) -> None:
    started = subprocess.run(
        ["docker", "compose", "-f", args.compose_name, "up", "-d"],
        cwd=result["repository"],
        check=False,
    )
    if started.returncode:
        raise RuntimeError(
            f"Docker Compose exited with status {started.returncode}; generated files were kept"
        )
    result["status"] = "started"


def _print_initialization(args: Namespace, result: dict[str, Any]) -> None:
    verb = "Plan for" if args.dry_run else "AnaxiGraph setup for"
    print(f"{verb} {result['project_name']}")
    print(f"Repository: {result['repository']}\n")
    for item in result["files"]:
        label = item["action"].replace("_", " ")
        print(f"  {label:15} {Path(item['path']).name} · {item['purpose']}")
    for connection in result["connections"]:
        label = connection["action"].replace("_", " ")
        print(f"  {label:15} {connection['client']} MCP · {connection['path']}")
    detected = result["detected"]
    groups = ", ".join(detected["groups"]) or "no obvious top-level areas"
    print(f"\nDetected areas: {groups}")
    if detected["architecture_policy"]:
        print(f"Architecture policy: {detected['architecture_policy']}")
    print("\nEndpoints")
    print(f"  Dashboard:         {result['dashboard_url']}")
    print(f"  MCP on this host:  {result['mcp_url']}")
    print(f"  MCP in Compose:    {result['network_urls']['container_mcp']}")
    print(f"  MCP from remote:   {result['network_urls']['remote_mcp']}")
    print("\nNext steps")
    if result["commands"]["start"] and not args.start:
        print(f"  1. Start:   {result['commands']['start']}")
    elif not result["commands"]["start"]:
        print(f"  1. Start:   {result['commands']['local']}")
    else:
        print(f"  1. Open:    {result['dashboard_url']}")
    if not result["connections"]:
        print(f"  2. Codex:   {result['commands']['connect_codex']}")
    elif any(connection["restart_required"] for connection in result["connections"]):
        print("  2. Restart the configured coding client, then verify its AnaxiGraph MCP tools.")
    if result["semantic"]["enabled"]:
        print("  3. Ask the agent: Bootstrap or resume AnaxiGraph semantic understanding.")
        print(
            "     The connected coding agent supplies the reasoning and tokens; no model key is needed."
        )
    if result["commands"]["start"]:
        print("\nThe repository is mounted read-only; AnaxiIndex persists in a Docker volume.")

"""CLI registration and handlers for local services and operational commands."""

from __future__ import annotations

import argparse
import ipaddress
import os
import sys
import webbrowser
from pathlib import Path
from typing import Any

import uvicorn

import anaxigraph.cli_services as cli_services
import anaxigraph.cli_workflows as cli_workflows
import anaxigraph.registry as repository_registry
from anaxigraph.cli_common import add_repository_arguments, default_db


def configure_server_commands(commands: Any) -> None:
    history = commands.add_parser("history", help="Build saved code maps from earlier Git commits")
    add_repository_arguments(history)
    cli_workflows.configure_operational_commands(
        commands,
        history,
        cli_services.INDEX_FACTORY,
        cli_services.APP_FACTORY,
        cli_services.CONFIG_LOADER,
    )
    for name, help_text in (
        ("serve", "Serve the dashboard, REST API, and MCP endpoint"),
        ("mcp", "Serve Streamable HTTP MCP plus REST/dashboard"),
    ):
        parser = commands.add_parser(name, help=help_text)
        _serve_arguments(parser)
        parser.set_defaults(handler=_serve, command_name=name)


def _serve_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repository", type=Path, default=_repository_from_env())
    parser.add_argument(
        "--registry",
        type=Path,
        default=_registry_from_env(),
        help="YAML registry of repository mounts, policies, and history sampling",
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument("--db", type=Path, default=default_db())
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help=(
            "Address to bind (default: 127.0.0.1, this machine only); any other address makes "
            "the unauthenticated REST API and dashboard reachable from other machines"
        ),
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--scan-on-start", action="store_true")
    parser.add_argument(
        "--watch-interval",
        type=float,
        default=os.environ.get("ANAXIGRAPH_WATCH_INTERVAL", "10"),
        help="Seconds between supervised repository checks (default: 10)",
    )
    parser.add_argument(
        "--no-watch",
        action="store_true",
        help="Serve the last saved map without supervising repository changes",
    )
    parser.add_argument(
        "--history-snapshots",
        type=repository_registry.parse_history_snapshots,
        default="auto",
        help="How many earlier Git versions to map for one repository (default: auto)",
    )
    parser.add_argument("--allow-agent-scan", action="store_true")
    parser.add_argument(
        "--allowed-host",
        action="append",
        dest="allowed_hosts",
        help="Allowed MCP Host header (repeatable, supports :*)",
    )
    parser.add_argument("--open", action="store_true", help="Open the dashboard in a browser")


def _serve(args: argparse.Namespace) -> None:
    repository = args.repository.expanduser().resolve() if args.repository else None
    targets = repository_registry.load_repository_registry(args.registry) if args.registry else ()
    database = cli_services.open_index(args.db)
    app = cli_services.APP_FACTORY(
        database=database,
        repository=repository,
        config_path=args.config.resolve() if args.config else None,
        scan_on_start=args.scan_on_start,
        enable_mcp=True,
        allowed_hosts=args.allowed_hosts,
        allow_scan_tool=args.allow_agent_scan,
        repository_targets=targets,
        repository_history_snapshots=args.history_snapshots,
        watch_interval=None if args.no_watch else args.watch_interval,
    )
    url = f"http://{_display_host(args.host)}:{args.port}"
    print(f"Dashboard: {url}", file=sys.stderr)
    print(f"MCP:       {url}/mcp", file=sys.stderr)
    if targets:
        print(f"Repositories: {len(targets)} configured", file=sys.stderr)
    for line in bind_exposure_notice(
        args.host, args.port, args.allowed_hosts, args.allow_agent_scan
    ):
        print(line, file=sys.stderr)
    if args.open:
        webbrowser.open(url)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


def bind_exposure_notice(
    host: str, port: int, allowed_hosts: list[str] | None, allow_scan: bool
) -> list[str]:
    """Say plainly what a non-loopback bind exposes; a loopback bind exposes nothing new."""

    if _is_loopback(host):
        return []
    bind = f"[{host}]" if ":" in host and not host.startswith("[") else host
    hosts = ", ".join(allowed_hosts) if allowed_hosts else "loopback names and 'anaxigraph:*'"
    notice = [
        f"Exposure notice: AnaxiGraph is listening on {bind}:{port}, so it is reachable from "
        "other machines.",
        "The REST API and dashboard have no login, so keep AnaxiGraph on loopback or behind SSH, "
        f"never on an untrusted or shared network; only MCP checks Host headers ({hosts}).",
    ]
    if allow_scan:
        notice.append(
            "--allow-agent-scan is on, so any agent that reaches this address can start scans."
        )
    return notice


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def _display_host(host: str) -> str:
    """Render a bind address as a URL host, sending unspecified addresses to loopback."""

    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return host
    if address.is_unspecified:
        return "127.0.0.1" if address.version == 4 else "[::1]"
    return f"[{address}]" if address.version == 6 else str(address)


def _repository_from_env() -> Path | None:
    value = os.environ.get("ANAXIGRAPH_REPOSITORY")
    return Path(value).expanduser() if value else None


def _registry_from_env() -> Path | None:
    value = os.environ.get("ANAXIGRAPH_REGISTRY")
    return Path(value).expanduser() if value else None

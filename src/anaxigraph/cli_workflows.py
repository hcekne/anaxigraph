"""Focused CLI workflows extracted from the legacy command module."""

from __future__ import annotations

import os
import sys
from argparse import ArgumentParser, Namespace
from pathlib import Path
from typing import Any

from anaxigraph.environment_doctor import inspect_environment
from anaxigraph.finding_transport import collect_finding_ledger, query_findings
from anaxigraph.history_jobs import open_history_service
from anaxigraph.onboarding_cli import configure_initialize_command
from anaxigraph.registry import RepositoryTarget, parse_history_snapshots
from anaxigraph.up_cli import configure_up_command

__all__ = [
    "collect_finding_ledger",
    "configure_initialize_command",
    "configure_up_command",
    "query_findings",
]


def configure_finding_command(commands: Any, handler: Any, default_db: Path) -> None:
    finding = commands.add_parser(
        "finding", help="Mark a saved finding as reviewed, planned, accepted, or not actionable"
    )
    finding.add_argument("finding_id", type=int)
    finding.add_argument(
        "status",
        choices=[
            "new",
            "acknowledged",
            "accepted",
            "dismissed",
            "planned",
            "resolved",
            "regressed",
        ],
    )
    finding.add_argument("--repository", type=Path, default=Path.cwd())
    finding.add_argument("--db", type=Path, default=default_db)
    finding.add_argument("--json", action="store_true")
    finding.set_defaults(handler=handler)


def configure_operational_commands(
    commands: Any,
    history_parser: ArgumentParser,
    index_factory: Any,
    app_factory: Any,
    config_loader: Any,
) -> None:
    configure_up_command(
        commands,
        index_factory=index_factory,
        app_factory=app_factory,
        config_loader=config_loader,
    )
    configure_history(history_parser)
    doctor_parser = commands.add_parser(
        "doctor",
        help="Verify repository, index, service, MCP, and coding-client readiness",
    )
    doctor_parser.add_argument("repository", nargs="?", type=Path, default=Path.cwd())
    doctor_parser.add_argument("--config", type=Path)
    doctor_parser.add_argument("--db", type=Path, default=_default_db())
    doctor_parser.add_argument("--service-url", help="Dashboard/API root to probe")
    doctor_parser.add_argument("--client", choices=["codex", "claude"])
    doctor_parser.add_argument("--connect-scope", choices=["user", "project"], default="user")
    doctor_parser.add_argument("--mcp-url", help="Expected client and MCP endpoint URL")
    doctor_parser.add_argument("--json", action="store_true")
    doctor_parser.set_defaults(handler=doctor, index_factory=index_factory)


def configure_history(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--limit",
        type=parse_history_snapshots,
        default="auto",
        help="Representative first-parent frames: auto or 1 to 2000 (default: auto)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Analyze every first-parent commit instead of lifetime sampling",
    )
    parser.add_argument("--since", help="Git date expression, for example '3 months ago'")
    control = parser.add_mutually_exclusive_group()
    control.add_argument("--status", action="store_true", help="Show the durable import job")
    control.add_argument("--cancel", action="store_true", help="Cancel after the current frame")
    parser.set_defaults(handler=history)


def history(args: Namespace) -> dict[str, Any]:
    service = open_history_service(args.db)
    repository = service.database.repository(args.repository)
    if args.status:
        return (
            service.status(int(repository["id"]))
            if repository is not None
            else {"status": "not_started"}
        )
    if args.cancel:
        return (
            service.cancel(int(repository["id"]))
            if repository is not None
            else {"cancelled": False, "reason": "repository_not_indexed"}
        )
    if isinstance(args.limit, int) and args.limit < 1:
        raise ValueError("History limit must be at least one")

    def progress(index: int, total: int, commit_sha: str) -> None:
        if not args.json:
            print(f"[{index}/{total}] {commit_sha[:12]}", file=sys.stderr)

    target = RepositoryTarget(
        key="cli",
        path=args.repository.resolve(),
        config_path=args.config.resolve() if args.config else None,
        history_snapshots=args.limit,
    )
    return service.run_inline(target, every_commit=args.all, since=args.since, progress=progress)


def doctor(args: Namespace) -> dict[str, Any]:
    database = args.index_factory(args.db)
    return inspect_environment(
        database.path,
        database.connect,
        repository=args.repository,
        config_path=args.config,
        service_url=args.service_url,
        client=args.client,
        connection_scope=args.connect_scope,
        expected_mcp_url=args.mcp_url,
    )


def _default_db() -> Path:
    configured = os.environ.get("ANAXIGRAPH_DB")
    if configured:
        return Path(configured).expanduser()
    state_root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return state_root / "anaxigraph" / "anaxi-index.db"

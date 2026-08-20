"""Focused CLI workflows extracted from the legacy command module."""

from __future__ import annotations

import subprocess
import sys
from argparse import ArgumentParser, Namespace
from pathlib import Path
from typing import Any

from anaxigraph.history_jobs import open_history_service
from anaxigraph.onboarding import initialize_repository
from anaxigraph.registry import RepositoryTarget, parse_history_snapshots


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


def initialize(args: Namespace) -> dict[str, Any] | None:
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
        force=args.force,
        dry_run=args.dry_run,
    )
    if args.start:
        _start_generated_compose(args, result)
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
    detected = result["detected"]
    groups = ", ".join(detected["groups"]) or "no obvious top-level areas"
    print(f"\nDetected areas: {groups}")
    if detected["architecture_policy"]:
        print(f"Architecture policy: {detected['architecture_policy']}")
    print("\nNext steps")
    if result["commands"]["start"]:
        print(f"  1. Start:   {result['commands']['start']}")
        print(f"  2. Open:    {result['dashboard_url']}")
        print(f"  3. Codex:   {result['commands']['connect_codex']}")
        print("\nThe repository is mounted read-only; AnaxiIndex persists in a Docker volume.")
    else:
        print(f"  1. Start:   {result['commands']['local']}")
        print(f"  2. Codex:   {result['commands']['connect_codex']}")
    if args.start:
        print(f"\nContainer started. Open {result['dashboard_url']}")

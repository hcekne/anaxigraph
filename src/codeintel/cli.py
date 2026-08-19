"""Command-line interface for scans, history, dashboard, and agent context."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any

import uvicorn

from codeintel.agent import agent_scope, branch_collisions, impact_analysis
from codeintel.api import create_app
from codeintel.config import load_config
from codeintel.history import import_git_history
from codeintel.onboarding import initialize_repository
from codeintel.registry import RepositoryTarget, load_repository_registry
from codeintel.scanner import RepositoryScanner
from codeintel.storage import Database


def main(argv: list[str] | None = None) -> None:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        result = args.handler(args)
        if result is not None:
            _print(result, as_json=getattr(args, "json", False))
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        raise SystemExit(130) from None
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"anaxigraph: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="anaxigraph",
        description="AnaxiGraph: temporal architecture intelligence for software repositories.",
    )
    parser.add_argument("--version", action="version", version="AnaxiGraph 0.1.0")
    commands = parser.add_subparsers(dest="command", required=True)

    initialize = commands.add_parser(
        "init",
        help="Create a safe repository policy and Docker sidecar setup",
        description=(
            "Detect obvious repository areas and generate a reviewable AnaxiGraph policy plus "
            "a read-only Docker Compose sidecar. Existing files are never replaced unless "
            "--force is given."
        ),
    )
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
        type=int,
        default=64,
        help="Representative Git history frames to import (default: 64)",
    )
    initialize.add_argument(
        "--force",
        action="store_true",
        help="Replace existing generated filenames after explicit review",
    )
    initialize.add_argument(
        "--dry-run",
        action="store_true",
        help="Show detected setup without writing files",
    )
    initialize.add_argument(
        "--start",
        action="store_true",
        help="Start the generated Docker Compose service after writing it",
    )
    initialize.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    initialize.set_defaults(handler=_initialize)

    scan = commands.add_parser("scan", help="Build a complete current repository map")
    _repository_arguments(scan)
    scan.set_defaults(handler=_scan, run_type="scan")

    update = commands.add_parser("update", help="Incrementally analyze changed artifacts")
    _repository_arguments(update)
    update.set_defaults(handler=_scan, run_type="update")

    review = commands.add_parser("review", help="Refresh and show architecture review findings")
    _repository_arguments(review)
    review.add_argument("--status", default="active", choices=["active", "all", "new", "resolved"])
    review.set_defaults(handler=_review)

    history = commands.add_parser("history", help="Build temporal snapshots from Git commits")
    _repository_arguments(history)
    history.add_argument(
        "--limit",
        type=int,
        default=64,
        help="Evenly sampled first-parent frames from initial commit to HEAD (default: 64)",
    )
    history.add_argument(
        "--all",
        action="store_true",
        help="Analyze every first-parent commit instead of lifetime sampling",
    )
    history.add_argument("--since", help="Git date expression, for example '3 months ago'")
    history.set_defaults(handler=_history)

    watch = commands.add_parser("watch", help="Poll for changes and update incrementally")
    _repository_arguments(watch)
    watch.add_argument("--registry", type=Path, help="Watch every target in a repository registry")
    watch.add_argument("--interval", type=float, default=2.0, help="Polling interval in seconds")
    watch.set_defaults(handler=_watch)

    serve = commands.add_parser("serve", help="Serve the dashboard, REST API, and MCP endpoint")
    _serve_arguments(serve)
    serve.set_defaults(handler=_serve, command_name="serve")

    mcp = commands.add_parser("mcp", help="Serve Streamable HTTP MCP plus REST/dashboard")
    _serve_arguments(mcp)
    mcp.set_defaults(handler=_serve, command_name="mcp")

    scope = commands.add_parser("scope", help="Return bounded task context for a coding goal")
    _repository_arguments(scope)
    scope.add_argument("--goal", required=True, help="The coding goal")
    scope.add_argument("--branch", help="Feature branch used for collision analysis")
    scope.set_defaults(handler=_scope)

    impact = commands.add_parser("impact", help="Analyze reverse-dependency impact")
    _repository_arguments(impact)
    impact.add_argument("--target", required=True, help="Repository path or unique symbol")
    impact.add_argument("--branch", help="Feature branch used for collision analysis")
    impact.set_defaults(handler=_impact)

    collisions = commands.add_parser("collisions", help="Compare active branch change surfaces")
    _repository_arguments(collisions)
    collisions.set_defaults(handler=_collisions)

    export = commands.add_parser(
        "export", help="Export graph, findings, overview, and history as JSON"
    )
    _repository_arguments(export)
    export.add_argument("--output", type=Path, help="Write JSON to this path instead of stdout")
    export.set_defaults(handler=_export)

    finding = commands.add_parser("finding", help="Change a finding lifecycle status")
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
    finding.add_argument("--db", type=Path, default=_default_db())
    finding.add_argument("--json", action="store_true")
    finding.set_defaults(handler=_finding)
    return parser


def _repository_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("repository", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument(
        "--config",
        type=Path,
        help="Configuration file (defaults to .anaxigraph.yml; .codeintel.yml is supported)",
    )
    parser.add_argument("--db", type=Path, default=_default_db(), help="External SQLite database")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")


def _serve_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repository", type=Path, default=_repository_from_env())
    parser.add_argument(
        "--registry",
        type=Path,
        default=_registry_from_env(),
        help="YAML registry of repository mounts, policies, and history sampling",
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument("--db", type=Path, default=_default_db())
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--scan-on-start", action="store_true")
    parser.add_argument(
        "--history-snapshots",
        type=int,
        default=64,
        help="Representative Git frames for a single --repository target (default: 64)",
    )
    parser.add_argument("--allow-agent-scan", action="store_true")
    parser.add_argument(
        "--allowed-host",
        action="append",
        dest="allowed_hosts",
        help="Allowed MCP Host header (repeatable, supports :*)",
    )
    parser.add_argument("--open", action="store_true", help="Open the dashboard in a browser")


def _initialize(args: argparse.Namespace) -> dict[str, Any] | None:
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
    if args.json:
        return result

    verb = "Plan for" if args.dry_run else "AnaxiGraph setup for"
    print(f"{verb} {result['project_name']}")
    print(f"Repository: {result['repository']}")
    print()
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
    return None


def _scan(args: argparse.Namespace) -> dict[str, Any]:
    stats = RepositoryScanner(Database(args.db)).scan(
        args.repository,
        config_path=args.config,
        run_type=args.run_type,
    )
    return {"status": "ok", **stats.as_dict()}


def _review(args: argparse.Namespace) -> dict[str, Any]:
    database = Database(args.db)
    stats = RepositoryScanner(database).scan(
        args.repository,
        config_path=args.config,
        run_type="review",
    )
    statuses = (
        ()
        if args.status == "all"
        else (
            ("new", "acknowledged", "accepted", "planned", "regressed")
            if args.status == "active"
            else (args.status,)
        )
    )
    return {
        "scan": stats.as_dict(),
        "findings": database.findings(stats.repository_id, statuses=statuses),
    }


def _history(args: argparse.Namespace) -> dict[str, Any]:
    if args.limit < 1:
        raise ValueError("History limit must be at least one")

    def progress(index: int, total: int, commit_sha: str) -> None:
        if not args.json:
            print(f"[{index}/{total}] {commit_sha[:12]}", file=sys.stderr)

    result = import_git_history(
        Database(args.db),
        args.repository,
        config_path=args.config,
        max_snapshots=args.limit,
        every_commit=args.all,
        since=args.since,
        progress=progress,
    )
    return result.as_dict()


def _watch(args: argparse.Namespace) -> None:
    if args.interval < 0.2:
        raise ValueError("Watch interval must be at least 0.2 seconds")
    scanner = RepositoryScanner(Database(args.db))
    targets = (
        load_repository_registry(args.registry)
        if args.registry
        else (
            RepositoryTarget(
                key="default",
                path=args.repository.expanduser().resolve(),
                config_path=args.config,
                history_snapshots=0,
            ),
        )
    )
    print(f"Watching {len(targets)} repositories (Ctrl-C to stop)", file=sys.stderr)
    while True:
        for target in targets:
            stats = scanner.scan(
                target.path,
                config_path=target.config_path,
                run_type="watch",
            )
            if stats.analyzed or stats.deleted:
                _print(
                    {"repository": target.key, **stats.as_dict()},
                    as_json=args.json,
                )
        time.sleep(args.interval)


def _serve(args: argparse.Namespace) -> None:
    if not 0 <= args.history_snapshots <= 2_000:
        raise ValueError("History snapshots must be between 0 and 2000")
    repository = args.repository.expanduser().resolve() if args.repository else None
    targets = load_repository_registry(args.registry) if args.registry else ()
    database = Database(args.db)
    app = create_app(
        database=database,
        repository=repository,
        config_path=args.config.resolve() if args.config else None,
        scan_on_start=args.scan_on_start,
        enable_mcp=True,
        allowed_hosts=args.allowed_hosts,
        allow_scan_tool=args.allow_agent_scan,
        repository_targets=targets,
        repository_history_snapshots=args.history_snapshots,
    )
    url = f"http://{'127.0.0.1' if args.host == '0.0.0.0' else args.host}:{args.port}"
    print(f"Dashboard: {url}", file=sys.stderr)
    print(f"MCP:       {url}/mcp", file=sys.stderr)
    if targets:
        print(f"Repositories: {len(targets)} configured", file=sys.stderr)
    if args.open:
        webbrowser.open(url)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


def _scope(args: argparse.Namespace) -> dict[str, Any]:
    database, repository_id, config = _ensure_current(args)
    return agent_scope(
        database,
        repository_id=repository_id,
        goal=args.goal,
        branch=args.branch,
        config=config,
    )


def _impact(args: argparse.Namespace) -> dict[str, Any]:
    database, repository_id, config = _ensure_current(args)
    return impact_analysis(
        database,
        repository_id=repository_id,
        target=args.target,
        branch=args.branch,
        config=config,
    )


def _collisions(args: argparse.Namespace) -> dict[str, Any]:
    database, repository_id, _ = _ensure_current(args)
    return branch_collisions(database, repository_id=repository_id)


def _export(args: argparse.Namespace) -> dict[str, Any] | None:
    database, repository_id, _ = _ensure_current(args)
    value = {
        "overview": database.overview(repository_id),
        "graph": database.graph(repository_id, include_external=True),
        "findings": database.findings(repository_id),
        "snapshots": database.snapshots(repository_id, limit=1_000),
    }
    if args.output:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
        return {"status": "ok", "output": str(output)}
    return value


def _finding(args: argparse.Namespace) -> dict[str, Any]:
    database = Database(args.db)
    row = database.repository(args.repository)
    if row is None:
        raise ValueError("Repository has not been scanned")
    if not database.update_finding_status(int(row["id"]), args.finding_id, args.status):
        raise ValueError("Finding not found")
    return {"id": args.finding_id, "status": args.status}


def _ensure_current(
    args: argparse.Namespace,
) -> tuple[Database, int, Any]:
    database = Database(args.db)
    stats = RepositoryScanner(database).scan(
        args.repository,
        config_path=args.config,
        run_type="agent_context",
    )
    config = load_config(args.repository.resolve(), args.config)
    return database, stats.repository_id, config


def _print(value: Any, *, as_json: bool) -> None:
    if as_json or not isinstance(value, dict):
        print(json.dumps(value, indent=2, sort_keys=True, default=str))
        return
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def _default_db() -> Path:
    configured = os.environ.get("ANAXIGRAPH_DB") or os.environ.get("CODEINTEL_DB")
    if configured:
        return Path(configured).expanduser()
    state_root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    current = state_root / "anaxigraph" / "anaxi-index.db"
    legacy = state_root / "codeintel" / "codeintel.db"
    return legacy if legacy.exists() and not current.exists() else current


def _repository_from_env() -> Path | None:
    value = os.environ.get("ANAXIGRAPH_REPOSITORY") or os.environ.get("CODEINTEL_REPOSITORY")
    return Path(value).expanduser() if value else None


def _registry_from_env() -> Path | None:
    value = os.environ.get("ANAXIGRAPH_REGISTRY") or os.environ.get("CODEINTEL_REGISTRY")
    return Path(value).expanduser() if value else None

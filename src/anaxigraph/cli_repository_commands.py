"""CLI registration and handlers for repository scans and findings."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import anaxigraph.cli_services as cli_services
import anaxigraph.cli_workflows as cli_workflows
import anaxigraph.registry as repository_registry
from anaxigraph.bounded_export import bounded_export
from anaxigraph.cli_common import add_repository_arguments, default_db, emit_json, ensure_current


def configure_repository_commands(commands: Any) -> None:
    _configure_scans(commands)
    _configure_review(commands)
    _configure_watch(commands)
    _configure_export(commands)
    cli_workflows.configure_finding_command(commands, _finding, default_db())


def _configure_scans(commands: Any) -> None:
    scan = commands.add_parser("scan", help="Build a complete current repository map")
    add_repository_arguments(scan)
    scan.set_defaults(handler=_scan, run_type="scan")

    update = commands.add_parser("update", help="Update the saved code map for changed files")
    add_repository_arguments(update)
    update.set_defaults(handler=_scan, run_type="update")


def _configure_review(commands: Any) -> None:
    review = commands.add_parser(
        "review",
        help="Scan the repository and explain code-structure findings in ordinary language",
    )
    add_repository_arguments(review)
    review.add_argument("--status", default="active", choices=["active", "all", "new", "resolved"])
    review.set_defaults(handler=_review)


def _configure_watch(commands: Any) -> None:
    watch = commands.add_parser(
        "watch", help="Check for changed files at intervals and update their saved code map"
    )
    add_repository_arguments(watch)
    watch.add_argument("--registry", type=Path, help="Watch every target in a repository registry")
    watch.add_argument("--interval", type=float, default=2.0, help="Polling interval in seconds")
    watch.set_defaults(handler=_watch)


def _configure_export(commands: Any) -> None:
    export = commands.add_parser(
        "export", help="Export files, direct code links, findings, overview, and history as JSON"
    )
    add_repository_arguments(export)
    export.add_argument("--output", type=Path, help="Write JSON to this path instead of stdout")
    export.set_defaults(handler=_export)


def _scan(args: argparse.Namespace) -> dict[str, Any]:
    database = cli_services.open_index(args.db)
    stats = cli_services.scanner(database).scan(
        args.repository,
        config_path=args.config,
        run_type=args.run_type,
    )
    result: dict[str, Any] = {"status": "ok", **stats.as_dict()}
    config = cli_services.load_repository_config(args.repository.resolve(), args.config)
    if config.semantic.enabled and config.semantic.refresh == "on_scan":
        result["semantic"] = cli_services.semantics(database).bootstrap(
            stats.repository_id, args.repository, config
        )
    elif config.semantic.enabled:
        result["semantic"] = cli_services.semantics(database).status(
            stats.repository_id, config.semantic
        )
    return result


def _review(args: argparse.Namespace) -> dict[str, Any]:
    database = cli_services.open_index(args.db)
    stats = cli_services.scanner(database).scan(
        args.repository,
        config_path=args.config,
        run_type="review",
    )
    config = cli_services.load_repository_config(args.repository, args.config)
    return {
        "scan": stats.as_dict(),
        "finding_page": cli_workflows.query_findings(
            database,
            stats.repository_id,
            config,
            view="diagnostics" if args.status in {"all", "resolved"} else "attention",
            statuses=(args.status,),
        ),
    }


def _watch(args: argparse.Namespace) -> None:
    if args.interval < 0.2:
        raise ValueError("Watch interval must be at least 0.2 seconds")
    scanner = cli_services.scanner(cli_services.open_index(args.db))
    targets = _repository_targets(args)
    print(f"Watching {len(targets)} repositories (Ctrl-C to stop)", file=sys.stderr)
    while True:
        for target in targets:
            stats = scanner.scan(target.path, config_path=target.config_path, run_type="watch")
            if stats.analyzed or stats.deleted:
                emit_json({"repository": target.key, **stats.as_dict()})
            config = cli_services.load_repository_config(target.path, target.config_path)
            if config.semantic.enabled and config.semantic.refresh in {"watch", "on_scan"}:
                cli_services.semantics(scanner.database).bootstrap(
                    stats.repository_id, target.path, config
                )
        time.sleep(args.interval)


def _repository_targets(
    args: argparse.Namespace,
) -> tuple[repository_registry.RepositoryTarget, ...]:
    if args.registry:
        return repository_registry.load_repository_registry(args.registry)
    return (
        repository_registry.RepositoryTarget(
            key="default",
            path=args.repository.expanduser().resolve(),
            config_path=args.config,
            history_snapshots=0,
        ),
    )


def _export(args: argparse.Namespace) -> dict[str, Any] | None:
    database, repository_id, config = ensure_current(args)
    value = bounded_export(database, repository_id, config)
    if not args.output:
        return value
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    return {"status": "ok", "output": str(output)}


def _finding(args: argparse.Namespace) -> dict[str, Any]:
    database = cli_services.open_index(args.db)
    row = database.repository(args.repository)
    if row is None:
        raise ValueError("Repository has not been scanned")
    if not database.update_finding_status(int(row["id"]), args.finding_id, args.status):
        raise ValueError("Finding not found")
    return {"id": args.finding_id, "status": args.status}

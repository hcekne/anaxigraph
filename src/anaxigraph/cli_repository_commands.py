"""CLI registration and handlers for repository scans and findings."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import anaxigraph.cli_services as cli_services
import anaxigraph.cli_workflows as cli_workflows
from anaxigraph.bounded_export import bounded_export
from anaxigraph.cli_common import add_repository_arguments, default_db, ensure_current


def configure_repository_commands(commands: Any) -> None:
    _configure_scans(commands)
    _configure_review(commands)
    _configure_search(commands)
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
    review.set_defaults(handler=_scan, run_type="review")


def _configure_search(commands: Any) -> None:
    search = commands.add_parser("search", help="Find files by name, symbol, or responsibility")
    search.add_argument("query")
    add_repository_arguments(search)
    search.add_argument("--limit", type=int, default=20)
    search.set_defaults(handler=_search)


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
    config = cli_services.load_repository_config(args.repository.resolve(), args.config)
    if args.run_type == "review":
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
    result: dict[str, Any] = {"status": "ok", **stats.as_dict()}
    if config.semantic.enabled and config.semantic.refresh == "on_scan":
        result["semantic"] = cli_services.semantics(database).bootstrap(
            stats.repository_id, args.repository, config
        )
    elif config.semantic.enabled:
        result["semantic"] = cli_services.semantics(database).status(
            stats.repository_id, config.semantic
        )
    return result


def _export(args: argparse.Namespace) -> dict[str, Any] | None:
    database, repository_id, config = ensure_current(args)
    value = bounded_export(database, repository_id, config)
    if not args.output:
        return value
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    return {"status": "ok", "output": str(output)}


def _search(args: argparse.Namespace) -> dict[str, Any]:
    database, repository_id, _config = ensure_current(args)
    limit = max(1, min(int(args.limit), 100))
    return {"query": args.query, "results": database.search(repository_id, args.query, limit=limit)}


def _finding(args: argparse.Namespace) -> dict[str, Any]:
    database = cli_services.open_index(args.db)
    row = database.repository(args.repository)
    if row is None:
        raise ValueError("Repository has not been scanned")
    if not database.update_finding_status(int(row["id"]), args.finding_id, args.status):
        raise ValueError("Finding not found")
    return {"id": args.finding_id, "status": args.status}

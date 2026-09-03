"""CLI registration and handlers for repository scans and findings."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import anaxigraph.cli_services as cli_services
import anaxigraph.cli_workflows as cli_workflows
from anaxigraph.architecture_charter import architecture_charter
from anaxigraph.architecture_charter_corrections import (
    CORRECTABLE_SECTIONS,
    save_charter_correction,
)
from anaxigraph.bounded_export import bounded_export
from anaxigraph.cli_common import add_repository_arguments, default_db, ensure_current
from anaxigraph.semantic_scan_refresh import semantic_refresh_after_scan


def configure_repository_commands(commands: Any) -> None:
    _configure_scans(commands)
    _configure_review(commands)
    _configure_search(commands)
    _configure_charter(commands)
    _configure_export(commands)
    cli_workflows.configure_finding_command(commands, _finding, default_db())


def _configure_scans(commands: Any) -> None:
    scan = commands.add_parser("scan", help="Build a complete current repository map")
    add_repository_arguments(scan)
    _add_semantic_refresh_option(scan)
    scan.set_defaults(handler=_scan, run_type="scan")

    update = commands.add_parser("update", help="Update the saved code map for changed files")
    add_repository_arguments(update)
    _add_semantic_refresh_option(update)
    update.set_defaults(handler=_scan, run_type="update")


def _add_semantic_refresh_option(command: Any) -> None:
    command.add_argument(
        "--prepare-semantics",
        action="store_true",
        default=None,
        help=(
            "Prepare only AI descriptions invalidated by changed code fingerprints; this queues "
            "work but does not itself run a model"
        ),
    )


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


def _configure_charter(commands: Any) -> None:
    charter = commands.add_parser("charter", help="Explain repository purpose and architecture")
    add_repository_arguments(charter)
    charter.add_argument("--correct-section", choices=sorted(CORRECTABLE_SECTIONS))
    charter.add_argument("--key", default="", help="Stable key of a named Charter claim")
    charter.add_argument("--statement", default="", help="Declared replacement or addition")
    charter.add_argument("--author", default="", help="Person or principal making the correction")
    charter.add_argument("--rationale", default="", help="Why the declared context is needed")
    charter.add_argument("--withdraw", action="store_true", help="Withdraw this declared overlay")
    charter.add_argument(
        "--refute",
        action="store_true",
        help="Declare the targeted inferred claim a known non-issue instead of rewording it",
    )
    charter.set_defaults(handler=_charter)


def _configure_export(commands: Any) -> None:
    export = commands.add_parser(
        "export", help="Export files, direct code links, findings, overview, and history as JSON"
    )
    add_repository_arguments(export)
    export.add_argument("--output", type=Path, help="Write JSON to this path instead of stdout")
    export.set_defaults(handler=_export)


def _scan(args: argparse.Namespace) -> dict[str, Any]:
    database = cli_services.open_index(args.db)
    repository = database.repository(args.repository.resolve())
    baseline = database.latest_snapshot(int(repository["id"])) if repository else None
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
    semantic = semantic_refresh_after_scan(
        database,
        repository_id=stats.repository_id,
        repository=args.repository,
        snapshot_id=stats.snapshot_id,
        baseline_snapshot_id=int(baseline["id"]) if baseline else None,
        config=config,
        prepare=getattr(args, "prepare_semantics", None),
    )
    if config.semantic.enabled:
        result["semantic"] = semantic["semantic"]
    result["semantic_refresh"] = semantic["refresh"]
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


def _charter(args: argparse.Namespace) -> dict[str, Any]:
    database, repository_id, config = ensure_current(args)
    repository = database.repository(repository_id)
    assert repository is not None
    correction_values = (
        args.key,
        args.statement,
        args.author,
        args.rationale,
        args.withdraw,
        args.refute,
    )
    if any(correction_values) and not args.correct_section:
        raise ValueError("--correct-section is required when changing declared Charter context")
    if args.correct_section:
        save_charter_correction(
            database,
            repository_id,
            section=args.correct_section,
            key=args.key,
            statement=args.statement,
            author=args.author,
            rationale=args.rationale,
            active=not args.withdraw,
            disposition="refute" if args.refute else "correct",
        )
    overview = database.overview(repository_id)
    semantic = cli_services.semantics(database).status(repository_id, config.semantic)
    return architecture_charter(repository, overview, semantic)


def _finding(args: argparse.Namespace) -> dict[str, Any]:
    database = cli_services.open_index(args.db)
    row = database.repository(args.repository)
    if row is None:
        raise ValueError("Repository has not been scanned")
    if not database.update_finding_status(int(row["id"]), args.finding_id, args.status):
        raise ValueError("Finding not found")
    return {"id": args.finding_id, "status": args.status}

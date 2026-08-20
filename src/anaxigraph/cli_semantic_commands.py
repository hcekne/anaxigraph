"""CLI registration and handlers for semantic analysis work."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

import anaxigraph.cli_services as cli_services
import anaxigraph.registry as repository_registry
from anaxigraph.cli_common import add_repository_arguments, emit_json


def configure_semantic_commands(commands: Any) -> None:
    _configure_understand(commands)
    _configure_status(commands)
    _configure_worker(commands)


def _configure_understand(commands: Any) -> None:
    understand = commands.add_parser(
        "understand",
        help="Build or refresh the repository's versioned semantic dossiers",
    )
    add_repository_arguments(understand)
    understand.add_argument(
        "--limit",
        type=int,
        help="Maximum semantic jobs to execute in this run (defaults to repository policy)",
    )
    understand.add_argument(
        "--force",
        action="store_true",
        help="Reread every eligible module even when its current dossier is reusable",
    )
    understand.add_argument(
        "--retry-failed", action="store_true", help="Retry terminally failed semantic jobs"
    )
    understand.add_argument(
        "--plan-only", action="store_true", help="Queue stale work without invoking a model"
    )
    understand.set_defaults(handler=_understand)


def _configure_status(commands: Any) -> None:
    status = commands.add_parser(
        "semantic-status", help="Show semantic coverage, freshness, failures, and usage"
    )
    add_repository_arguments(status)
    status.set_defaults(handler=_semantic_status)


def _configure_worker(commands: Any) -> None:
    worker = commands.add_parser(
        "semantic-worker",
        help="Continuously scan, reconcile hashes, and process semantic jobs",
    )
    add_repository_arguments(worker)
    worker.add_argument(
        "--registry", type=Path, help="Process every target in a repository registry"
    )
    worker.add_argument(
        "--interval",
        type=float,
        help="Seconds between full-ledger reconciliations (defaults to repository policy)",
    )
    worker.add_argument("--once", action="store_true", help="Run one reconciliation cycle and exit")
    worker.set_defaults(handler=_semantic_worker)


def _understand(args: argparse.Namespace) -> dict[str, Any]:
    if args.limit is not None and args.limit < 1:
        raise ValueError("Semantic job limit must be at least one")
    database = cli_services.open_index(args.db)
    stats = cli_services.scanner(database).scan(
        args.repository,
        config_path=args.config,
        run_type="semantic_bootstrap",
    )
    config = cli_services.load_repository_config(args.repository.resolve(), args.config)
    if not config.semantic.enabled:
        raise ValueError("Semantic analysis is disabled in .anaxigraph.yml")
    result = cli_services.semantics(database).bootstrap(
        stats.repository_id,
        args.repository,
        config,
        limit=args.limit,
        force=args.force,
        retry_failed=args.retry_failed,
        plan_only=args.plan_only,
    )
    return {"scan": stats.as_dict(), **result}


def _semantic_status(args: argparse.Namespace) -> dict[str, Any]:
    database = cli_services.open_index(args.db)
    row = database.repository(args.repository)
    if row is None:
        raise ValueError("Repository has not been scanned")
    config = cli_services.load_repository_config(args.repository.resolve(), args.config)
    return cli_services.semantics(database).status(int(row["id"]), config.semantic)


def _semantic_worker(args: argparse.Namespace) -> dict[str, Any] | None:
    if args.interval is not None and args.interval < 1:
        raise ValueError("Semantic worker interval must be at least one second")
    targets = _semantic_targets(args)
    database = cli_services.open_index(args.db)
    if args.once:
        return _semantic_cycle(args, targets, database, respect_refresh_policy=False)
    print(
        f"Semantic reconciliation for {len(targets)} repositories (Ctrl-C to stop)",
        file=sys.stderr,
    )
    next_due: dict[str, float] = {}
    while True:
        emit_json(
            _semantic_cycle(
                args,
                targets,
                database,
                respect_refresh_policy=True,
                next_due=next_due,
            )
        )
        time.sleep(_wait_seconds(next_due))


def _semantic_targets(
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


def _semantic_cycle(
    args: argparse.Namespace,
    targets: tuple[repository_registry.RepositoryTarget, ...],
    database: Any,
    *,
    respect_refresh_policy: bool,
    next_due: dict[str, float] | None = None,
) -> dict[str, Any]:
    return {
        "repositories": [
            _reconcile_target(
                args,
                target,
                database,
                respect_refresh_policy=respect_refresh_policy,
                next_due=next_due,
            )
            for target in targets
        ]
    }


def _reconcile_target(
    args: argparse.Namespace,
    target: repository_registry.RepositoryTarget,
    database: Any,
    *,
    respect_refresh_policy: bool,
    next_due: dict[str, float] | None,
) -> dict[str, Any]:
    config = cli_services.load_repository_config(target.path, target.config_path)
    if not config.semantic.enabled:
        return {"repository": target.key, "status": "disabled"}
    if respect_refresh_policy and config.semantic.refresh != "periodic":
        return {
            "repository": target.key,
            "status": "skipped",
            "reason": f"semantic.refresh is {config.semantic.refresh}, not periodic",
        }
    due_at = next_due.get(target.key, 0.0) if next_due is not None else 0.0
    if next_due is not None and time.monotonic() < due_at:
        return {
            "repository": target.key,
            "status": "scheduled",
            "next_in_seconds": max(1, round(due_at - time.monotonic())),
        }
    stats = cli_services.scanner(database).scan(
        target.path,
        config_path=target.config_path,
        run_type="semantic_reconcile",
    )
    semantic = cli_services.semantics(database).bootstrap(stats.repository_id, target.path, config)
    if next_due is not None:
        interval = args.interval or config.semantic.reconcile_interval_minutes * 60
        next_due[target.key] = time.monotonic() + interval
    return {"repository": target.key, "scan": stats.as_dict(), "semantic": semantic}


def _wait_seconds(next_due: dict[str, float]) -> int:
    return max(
        1,
        round(min(next_due.values(), default=time.monotonic() + 86_400) - time.monotonic()),
    )

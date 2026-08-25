"""CLI registration and handlers for semantic analysis work."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

import anaxigraph.cli_services as cli_services
import anaxigraph.registry as repository_registry
from anaxigraph.cli_common import add_repository_arguments, emit_json
from anaxigraph.local_runtime import local_database_path
from anaxigraph.semantic_background import (
    launch_understand_background,
    report_background_progress,
    semantic_background_status,
)
from anaxigraph.semantic_execution import add_semantic_execution_arguments
from anaxigraph.semantic_execution import understand_execution as _understand_execution
from anaxigraph.semantic_remote_worker import execute_remote_semantics
from anaxigraph.semantic_service import (
    discover_semantic_service,
    prepare_semantic_service,
    service_semantic_status,
)


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
    budget = understand.add_mutually_exclusive_group()
    budget.add_argument(
        "--limit",
        type=int,
        help="Maximum semantic jobs to execute in this run (defaults to repository policy)",
    )
    budget.add_argument(
        "--until-complete",
        action="store_true",
        help="Continue through module, taxonomy, and synthesis stages until no work remains",
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
    add_semantic_execution_arguments(understand)
    understand.add_argument(
        "--service-url",
        help="Authoritative dashboard/API root (auto-detected on loopback when --db is omitted)",
    )
    understand.set_defaults(handler=_understand, db=None)


def _configure_status(commands: Any) -> None:
    status = commands.add_parser(
        "semantic-status", help="Show semantic coverage, freshness, failures, and usage"
    )
    add_repository_arguments(status)
    status.add_argument(
        "--service-url",
        help="Authoritative dashboard/API root (auto-detected on loopback when --db is omitted)",
    )
    status.set_defaults(handler=_semantic_status, db=None)


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
    if args.db is not None and args.service_url:
        raise ValueError("Choose either --db for a local index or --service-url for a service")
    repository = args.repository.expanduser().resolve()
    service = (
        discover_semantic_service(repository, explicit_url=args.service_url)
        if _service_discovery_enabled(args)
        else None
    )
    if service is not None:
        return _understand_from_service(args, repository, service)
    return _understand_from_local(args, repository)


def _understand_from_service(
    args: argparse.Namespace, repository: Path, service: Any
) -> dict[str, Any]:
    if args.config is not None:
        raise ValueError(
            "--config cannot override the matching service policy "
            f"{service.config_label()}; use --db for an explicitly local index"
        )
    semantic = service.semantic_config()
    if not semantic.enabled:
        raise ValueError(
            "Semantic analysis is disabled by authoritative service policy "
            f"{service.config_label()}"
        )
    execution_semantic, execution_mode = _understand_execution(args, semantic)
    if args.background:
        return launch_understand_background(
            args, repository, execution_semantic, execution_mode, service
        )
    return _understand_service(
        args,
        semantic,
        execution_semantic,
        execution_mode,
        service,
    )


def _understand_from_local(args: argparse.Namespace, repository: Path) -> dict[str, Any]:
    config = cli_services.load_repository_config(repository, args.config)
    if not config.semantic.enabled:
        source = str(config.config_path or repository / ".anaxigraph.yml")
        raise ValueError(f"Semantic analysis is disabled by local policy {source}")
    execution_semantic, execution_mode = _understand_execution(args, config.semantic)
    if args.background:
        return launch_understand_background(
            args, repository, execution_semantic, execution_mode, None
        )
    return _understand_local(
        args,
        repository,
        config,
        execution_semantic,
        execution_mode,
    )


def _understand_local(
    args: argparse.Namespace,
    repository: Path,
    config: Any,
    execution_semantic: Any | None,
    execution_mode: str,
) -> dict[str, Any]:
    database_path = local_database_path(repository, explicit=args.db)
    database = cli_services.open_index(database_path)
    stats = cli_services.scanner(database).scan(
        repository,
        config_path=args.config,
        run_type="semantic_bootstrap",
    )
    result = cli_services.semantics(database).bootstrap(
        stats.repository_id,
        repository,
        config,
        limit=args.limit,
        force=args.force,
        retry_failed=args.retry_failed,
        plan_only=args.plan_only,
        execution_semantic=execution_semantic,
        until_complete=args.until_complete,
    )
    result["execution"] = {
        "mode": execution_mode,
        "model": execution_semantic.model if execution_semantic else None,
        "reasoning_effort": (execution_semantic.reasoning_effort if execution_semantic else None),
        "parallel_jobs": (execution_semantic.max_parallel_jobs if execution_semantic else None),
        "timeout_seconds": (execution_semantic.timeout_seconds if execution_semantic else None),
    }
    result["index"] = {"authority": "local", "database": str(database_path)}
    if config.semantic.provider == "agent" and execution_semantic is None:
        result["status"] = "planned" if args.plan_only else "agent_action_required"
        result["complete"] = False
        if not args.plan_only:
            result["next_action"] = _mcp_continuation(repository)
    else:
        ready = bool(result["semantic"].get("semantically_ready"))
        result["status"] = "complete" if ready else "partial"
        result["complete"] = ready
        _require_requested_completion(args, result)
    return {"scan": stats.as_dict(), **result}


def _understand_service(
    args: argparse.Namespace,
    semantic: Any,
    execution_semantic: Any | None,
    execution_mode: str,
    service: Any,
) -> dict[str, Any]:
    prepared = _prepare_service(args, service)
    if prepared.get("status") == "scan_required":
        return _scan_required_service_result(args, execution_mode, service, prepared)
    if execution_semantic is None:
        result = {key: value for key, value in prepared.items() if key not in {"status", "scan"}}
        result["semantic"] = service_semantic_status(service)
    else:
        result = execute_remote_semantics(
            service,
            semantic,
            execution_semantic,
            limit=args.limit,
            until_complete=args.until_complete,
            retry_failed=args.retry_failed,
        )
    result["execution"] = {
        "mode": execution_mode,
        "model": execution_semantic.model if execution_semantic else None,
        "reasoning_effort": (execution_semantic.reasoning_effort if execution_semantic else None),
        "parallel_jobs": (execution_semantic.max_parallel_jobs if execution_semantic else None),
        "timeout_seconds": (execution_semantic.timeout_seconds if execution_semantic else None),
    }
    result["index"] = service.identity()
    if execution_semantic is None:
        result["status"] = "planned" if args.plan_only else "agent_action_required"
        result["complete"] = False
        if not args.plan_only:
            result["next_action"] = _mcp_continuation(
                args.repository,
                mcp_url=service.mcp_url,
                repository_id=service.repository_id,
            )
    else:
        ready = bool(result["semantic"].get("semantically_ready"))
        result["status"] = "complete" if ready else "partial"
        result["complete"] = ready
        _require_requested_completion(args, result)
    return {"scan": prepared.get("scan") or {}, **result}


def _prepare_service(args: argparse.Namespace, service: Any) -> dict[str, Any]:
    report_background_progress(stage="preparing", completed=0)
    result = prepare_semantic_service(
        service,
        force=args.force,
        retry_failed=args.retry_failed,
    )
    if result.get("status") != "scan_required":
        report_background_progress(stage="executing", completed=0)
    return result


def _scan_required_service_result(
    args: argparse.Namespace,
    execution_mode: str,
    service: Any,
    prepared: dict[str, Any],
) -> dict[str, Any]:
    message = str(
        prepared.get("recommended_action")
        or "Run an explicit repository scan, then retry understand."
    )
    report_background_progress(stage="scan_required", last_error=message)
    if args.until_complete:
        raise RuntimeError(f"Semantic execution requires a current structural snapshot. {message}")
    return {
        "scan": {},
        "status": "scan_required",
        "complete": False,
        "execution": {"mode": execution_mode},
        "index": service.identity(),
        "recommended_action": message,
    }


def _require_requested_completion(args: argparse.Namespace, result: dict[str, Any]) -> None:
    if not args.until_complete or result["complete"]:
        return
    semantic = result.get("semantic") or {}
    jobs = semantic.get("jobs") or {}
    raise RuntimeError(
        "Semantic completion was requested but the queue is not current "
        f"(pending={jobs.get('pending', 0)}, retry={jobs.get('retry', 0)}, "
        f"running={jobs.get('running', 0)}, failed={jobs.get('failed', 0)})."
    )


def _mcp_continuation(
    repository: Path,
    *,
    mcp_url: str | None = None,
    repository_id: int | None = None,
) -> dict[str, Any]:
    result = {
        "kind": "connected_agent_semantic_loop",
        "repository": str(repository.expanduser().resolve()),
        "instruction": (
            "Semantic inference has not run. The connected coding agent must not report this "
            "command as complete; it must execute the MCP work loop until a terminal status."
        ),
        "sequence": [
            "ANAXIGRAPH_SEMANTIC_SCHEMA once",
            "ANAXIGRAPH_SEMANTIC_WORK",
            "ANAXIGRAPH_SEMANTIC_EVIDENCE for every requested page",
            "ANAXIGRAPH_SEMANTIC_SUBMIT",
            "repeat ANAXIGRAPH_SEMANTIC_WORK until complete",
        ],
    }
    if mcp_url:
        result["mcp_url"] = mcp_url
    if repository_id is not None:
        result["repository_id"] = repository_id
    return result


def _semantic_status(args: argparse.Namespace) -> dict[str, Any]:
    if args.db is not None and args.service_url:
        raise ValueError("Choose either --db for a local index or --service-url for a service")
    repository = args.repository.expanduser().resolve()
    service = (
        discover_semantic_service(repository, explicit_url=args.service_url)
        if _service_discovery_enabled(args)
        else None
    )
    if service is not None:
        result = {**service_semantic_status(service), "index": service.identity()}
    else:
        database_path = local_database_path(repository, explicit=args.db)
        database = cli_services.open_index(database_path)
        row = database.repository(args.repository)
        if row is None:
            raise ValueError("Repository has not been scanned")
        config = cli_services.load_repository_config(args.repository.resolve(), args.config)
        result = {
            **cli_services.semantics(database).status(int(row["id"]), config.semantic),
            "index": {"authority": "local", "database": str(database_path)},
        }
    execution_run = semantic_background_status(repository)
    if execution_run:
        result["execution_run"] = execution_run
    return result


def _service_discovery_enabled(args: argparse.Namespace) -> bool:
    return bool(args.service_url) or (args.db is None and not os.environ.get("ANAXIGRAPH_DB"))


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

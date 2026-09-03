"""CLI registration and handlers for the AI-created code map."""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path
from typing import Any

import anaxigraph.cli_services as cli_services
from anaxigraph.cli_common import add_repository_arguments
from anaxigraph.local_runtime import local_database_path
from anaxigraph.operational_health import served_map_status
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


def _configure_understand(commands: Any) -> None:
    understand = commands.add_parser(
        "understand",
        help="Build or refresh AI descriptions of files, code areas, and coding-pattern matches",
    )
    add_repository_arguments(understand)
    budget = understand.add_mutually_exclusive_group()
    budget.add_argument(
        "--limit",
        type=int,
        help="Maximum AI tasks to run now (defaults to the repository setting)",
    )
    budget.add_argument(
        "--until-complete",
        action="store_true",
        help=(
            "Continue until every required file description, code-area grouping, repository "
            "summary, and pattern result is complete"
        ),
    )
    understand.add_argument(
        "--force",
        action="store_true",
        help="Ask the AI to reread every eligible file even when its saved description is current",
    )
    understand.add_argument(
        "--retry-failed", action="store_true", help="Give failed AI tasks another try"
    )
    understand.add_argument(
        "--plan-only", action="store_true", help="Prepare needed AI tasks without starting a model"
    )
    understand.add_argument(
        "--no-scan",
        action="store_true",
        help=(
            "Plan against the saved local map without rescanning; a missing or stale map returns "
            "status=scan_required, exactly as the service path does"
        ),
    )
    add_semantic_execution_arguments(understand)
    understand.add_argument(
        "--service-url",
        help=(
            "Dashboard/API that owns the saved index (found automatically on this machine when "
            "--db is omitted)"
        ),
    )
    understand.set_defaults(handler=_understand, db=None)


def _configure_status(commands: Any) -> None:
    status = commands.add_parser(
        "semantic-status",
        help="Show how much of the AI-created code map is current and what work remains",
    )
    add_repository_arguments(status)
    status.add_argument(
        "--service-url",
        help=(
            "Dashboard/API that owns the saved index (found automatically on this machine when "
            "--db is omitted)"
        ),
    )
    status.set_defaults(handler=_semantic_status, db=None)


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
    started = time.perf_counter()
    database_path = local_database_path(repository, explicit=args.db)
    database = cli_services.open_index(database_path)
    index = {"authority": "local", "database": str(database_path)}
    repository_id, facts = _local_scan_facts(args, repository, database, database_path)
    if repository_id is None:
        return _scan_required_result(args, execution_mode, index, facts)
    result = cli_services.semantics(database).bootstrap(
        repository_id,
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
        "elapsed_ms": round((time.perf_counter() - started) * 1_000, 3),
    }
    result["index"] = index
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
    return {"scan": facts, **result}


def _local_scan_facts(
    args: argparse.Namespace,
    repository: Path,
    database: Any,
    database_path: Path,
) -> tuple[int | None, dict[str, Any]]:
    """Return the scanned repository id with scan facts, or None with scan_required guidance."""

    if not args.no_scan:
        stats = cli_services.scanner(database).scan(
            repository,
            config_path=args.config,
            run_type="semantic_bootstrap",
        )
        return stats.repository_id, stats.as_dict()
    row = database.repository(repository)
    snapshot = database.latest_snapshot(int(row["id"])) if row is not None else None
    status = served_map_status(repository, snapshot) if snapshot is not None else None
    if row is not None and status is not None and status["state"] == "current":
        return int(row["id"]), {}
    return None, {
        "map_status": status,
        "recommended_action": _local_scan_action(repository, database_path, status),
    }


def _local_scan_action(repository: Path, database_path: Path, status: dict[str, Any] | None) -> str:
    guidance = (
        "Refresh the structural scan, then retry understand."
        if status is not None
        else "Run the explicit repository scan, then retry understand."
    )
    return f"{guidance} Run: anaxigraph scan {repository} --db {database_path}"


def _understand_service(
    args: argparse.Namespace,
    semantic: Any,
    execution_semantic: Any | None,
    execution_mode: str,
    service: Any,
) -> dict[str, Any]:
    started = time.perf_counter()
    prepared = _prepare_service(args, service)
    if prepared.get("status") == "scan_required":
        return _scan_required_result(args, execution_mode, service.identity(), prepared)
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
        "elapsed_ms": round((time.perf_counter() - started) * 1_000, 3),
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


def _scan_required_result(
    args: argparse.Namespace,
    execution_mode: str,
    index: dict[str, Any],
    prepared: dict[str, Any],
) -> dict[str, Any]:
    """Report a missing or stale saved map identically for the local and service authorities."""

    message = str(
        prepared.get("recommended_action")
        or "Run an explicit repository scan, then retry understand."
    )
    report_background_progress(stage="scan_required", last_error=message)
    if args.until_complete:
        raise RuntimeError(f"AI mapping requires a current saved repository scan. {message}")
    result = {
        "scan": {},
        "status": "scan_required",
        "complete": False,
        "execution": {"mode": execution_mode},
        "index": index,
        "recommended_action": message,
    }
    if prepared.get("map_status") is not None:
        result["map_status"] = prepared["map_status"]
    return result


def _require_requested_completion(args: argparse.Namespace, result: dict[str, Any]) -> None:
    if not args.until_complete or result["complete"]:
        return
    semantic = result.get("semantic") or {}
    jobs = semantic.get("jobs") or {}
    raise RuntimeError(
        "Complete AI mapping was requested, but work still remains "
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
            "The AI-created code map has not been built. The connected coding agent must keep "
            "requesting, reading, and submitting the saved AI tasks. It must not report this "
            "command as complete until ANAXIGRAPH_SEMANTIC_WORK returns status='complete'."
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

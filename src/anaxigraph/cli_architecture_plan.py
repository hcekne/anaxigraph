"""Headless architecture planning and scheduled workflow refresh using existing workers."""

from __future__ import annotations

from argparse import BooleanOptionalAction
from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any

from anaxigraph.agent_response import small_agent_response
from anaxigraph.architecture_plan_read import architecture_plan_status, steer_plan
from anaxigraph.cli_common import add_repository_arguments, ensure_current
from anaxigraph.cli_planning_service import planning_request, planning_service
from anaxigraph.planning_service import prepare_architecture_plan
from anaxigraph.record_publication import RecordPublisher
from anaxigraph.workflow_execution import WorkflowExecution
from anaxigraph.workflow_settings import FLOW_STEPS, WorkflowSettings


def configure_planning_commands(commands: Any) -> None:
    parser = commands.add_parser(
        "plan", help="Read, request or steer the architecture target; direction is optional"
    )
    add_repository_arguments(parser)
    parser.add_argument(
        "--service-url", help="Service owning this checkout; discovered when --db is omitted"
    )
    parser.add_argument("--start", action="store_true")
    parser.add_argument("--direction", default="")
    parser.add_argument("--select", default="")
    parser.add_argument("--milestone", default="")
    parser.add_argument(
        "--status", choices=("pending", "in_progress", "verified"), default="pending"
    )
    parser.add_argument("--evidence", action="append", default=[])
    parser.add_argument("--actor", choices=("user", "agent"), default="agent")
    parser.add_argument(
        "--details",
        action="store_true",
        help="Include complete options, diagrams and milestone evidence",
    )
    parser.set_defaults(handler=_plan, db=None)
    refresh = commands.add_parser(
        "refresh", help="Run selected workflows and save a Git-ready record for scheduled jobs"
    )
    add_repository_arguments(refresh)
    refresh.add_argument(
        "--workflows",
        default="mapping",
        help="Comma-separated mapping,patterns,fresh-eyes,architecture",
    )
    refresh.add_argument("--executor", choices=("codex", "claude", "saved"), default="saved")
    refresh.add_argument("--model", default="")
    refresh.add_argument("--direction", default=None)
    refresh.add_argument(
        "--save",
        action=BooleanOptionalAction,
        default=True,
        help="Save completed and partial results into anaxigraph/ (default: enabled)",
    )
    refresh.set_defaults(handler=_refresh, db=None)


def _plan(args: Any) -> dict[str, Any]:
    service = planning_service(args)
    if service:
        return planning_request(
            service,
            "architecture-plan",
            {
                "repository_id": service.repository_id,
                "start": args.start,
                "direction": args.direction,
                "option": args.select,
                "milestone": args.milestone,
                "status": args.status,
                "evidence": args.evidence,
                "actor": args.actor,
                "details": args.details,
            }
            if args.start or args.select or args.milestone
            else None,
            details=args.details,
        )
    database, repository_id, config = ensure_current(args)
    if args.start:
        prepare_architecture_plan(database, repository_id, args.repository, config, args.direction)
    if args.select or args.milestone:
        steer_plan(
            database,
            repository_id,
            option=args.select,
            milestone=args.milestone,
            status=args.status,
            evidence=args.evidence,
            actor=args.actor,
        )
    result = architecture_plan_status(database, repository_id, details=args.details)
    return (
        result
        if args.details
        else small_agent_response(result, limit=min(8000, config.agent.payload_limit_bytes))
    )


def _refresh(args: Any) -> dict[str, Any]:
    flows = [name.strip() for name in args.workflows.split(",") if name.strip()]
    if not flows or set(flows) - set(FLOW_STEPS):
        raise ValueError("Choose workflows from mapping,patterns,fresh-eyes,architecture")
    database, repository_id, config = ensure_current(args)
    settings = WorkflowSettings(database.path).read(
        repository_id, config.semantic.max_parallel_jobs, config.semantic.taxonomy.review_passes
    )["steps"]
    settings = _execution_settings(settings, args)
    row = database.repository(repository_id)
    results = {}
    publisher = RecordPublisher(database, repository_id) if args.save else None
    with publisher if publisher else nullcontext():
        for flow in flows:
            request = SimpleNamespace(
                workflow=flow,
                step=None,
                retry_failed=True,
                goal=args.direction,
                restart=False,
                max_jobs=None,
            )
            results[flow] = WorkflowExecution(
                database,
                row,
                config,
                request,
                settings,
                on_progress=publisher.update if publisher else None,
            ).run()
            if results[flow]["status"] != "complete":
                break
    saved = publisher.receipt if publisher else None
    status = (
        "complete"
        if len(results) == len(flows)
        and all(value["status"] == "complete" for value in results.values())
        else "waiting"
    )
    if saved and saved["status"] != "saved":
        status = "record_not_saved"
    return {
        "status": status,
        "workflows": results,
        "record": saved,
        "index": {"authority": "local", "database": str(database.path)},
    }


def _execution_settings(settings: Any, args: Any) -> Any:
    if args.executor == "saved":
        return settings
    if not args.model:
        raise ValueError("Choose --model explicitly when selecting an executor")
    return {
        step: [{**row, "provider": args.executor, "model": args.model} for row in rows]
        for step, rows in settings.items()
    }

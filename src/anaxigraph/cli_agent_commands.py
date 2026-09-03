"""CLI registration and handlers for focused coding-agent context."""

from __future__ import annotations

import argparse
import os
from typing import Any

from anaxigraph.agent import architecture_guidance, impact_analysis
from anaxigraph.architecture_reassessment import architecture_reassessment
from anaxigraph.cli_common import add_repository_arguments, ensure_current
from anaxigraph.semantic_fresh_eyes_executors import parse_proposal_executors
from anaxigraph.semantic_service import (
    FRESH_EYES_START_TIMEOUT_SECONDS,
    discover_semantic_service,
    service_architecture_guidance,
    service_architecture_reassessment,
    service_fresh_eyes_review,
    service_impact,
)
from anaxigraph.understanding import SemanticEngine

_RESTART_FRESH_EYES_HELP = "Rerun every stage after the current review completes"
_TIMEOUT_FRESH_EYES_HELP = (
    "Seconds to wait for the service to accept --start or --restart while it may be planning "
    "(service mode only; the default outlasts the index's 30-second busy window)"
)
_FRESH_EYES_TIMED_OUT = (
    "AnaxiGraph service did not answer the fresh-eyes {action} within {seconds:g} s; it may still "
    "be planning. Read the saved review state with `anaxigraph fresh-eyes {repository}` or rerun "
    "with a longer --timeout-seconds"
)


def configure_agent_commands(commands: Any) -> None:
    guidance = commands.add_parser(
        "guide", help="Ask where to build or how to improve using current architecture evidence"
    )
    add_repository_arguments(guidance)
    guidance.add_argument("--goal", required=True, help="The desired implementation or improvement")
    guidance.add_argument(
        "--intent",
        choices=("build", "improve", "refactor"),
        default="build",
        help="Whether to place new behavior or improve existing structure (refactor is an alias)",
    )
    guidance.add_argument(
        "--focus", default="", help="Optional file, area, or responsibility focus"
    )
    _add_service_url(guidance)
    guidance.set_defaults(handler=_guidance, db=None)

    impact = commands.add_parser(
        "impact", help="Find code and tests that may be affected by changing a file or symbol"
    )
    add_repository_arguments(impact)
    impact.add_argument("--target", required=True, help="Repository path or unique symbol")
    _add_service_url(impact)
    impact.set_defaults(handler=_impact, db=None)

    _configure_fresh_eyes(commands)
    _configure_reassessment(commands)


def _configure_fresh_eyes(commands: Any) -> None:
    fresh_eyes = commands.add_parser(
        "fresh-eyes",
        help="Compare the current system with independent clean-sheet architecture proposals",
    )
    add_repository_arguments(fresh_eyes)
    fresh_eyes.add_argument(
        "--start", action="store_true", help="Request and prepare the fixed review recipe"
    )
    fresh_eyes.add_argument(
        "--proposals",
        type=int,
        choices=(1, 2, 3),
        default=2,
        help="Number of independent clean-sheet proposals (two is recommended)",
    )
    fresh_eyes.add_argument(
        "--proposal-executors",
        default="",
        help=(
            "Pin one executor family per proposal slot, for example codex,claude (use any for an "
            "unpinned slot). Applies to a new review or a restart, never to one already planned."
        ),
    )
    fresh_eyes.add_argument(
        "--retry-failed", action="store_true", help="Retry failed review-stage tasks"
    )
    fresh_eyes.add_argument("--restart", action="store_true", help=_RESTART_FRESH_EYES_HELP)
    fresh_eyes.add_argument(
        "--unpin",
        action="store_true",
        help=(
            "Release every executor assignment of the current review so any executor can finish "
            "it; use this when a pinned executor will not be started"
        ),
    )
    _add_fresh_eyes_reading_arguments(fresh_eyes)
    _add_service_url(fresh_eyes)
    fresh_eyes.set_defaults(handler=_fresh_eyes, db=None)


def _add_fresh_eyes_reading_arguments(fresh_eyes: Any) -> None:
    """Options that choose which recorded review to read, and how long to wait for a start."""

    fresh_eyes.add_argument(
        "--generation",
        type=int,
        default=None,
        help="Read one recorded review generation instead of the current one",
    )
    fresh_eyes.add_argument(
        "--compare-with",
        type=int,
        default=None,
        help="Add a lexical alignment against a second recorded review generation",
    )
    fresh_eyes.add_argument(
        "--timeout-seconds",
        type=float,
        default=FRESH_EYES_START_TIMEOUT_SECONDS,
        help=_TIMEOUT_FRESH_EYES_HELP,
    )


def _configure_reassessment(commands: Any) -> None:
    reassess = commands.add_parser(
        "reassess",
        help="Explain the architecture effect of the latest compatible saved change",
    )
    add_repository_arguments(reassess)
    reassess.add_argument(
        "--from-snapshot",
        type=int,
        help="Optional earlier compatible snapshot (defaults to the previous changed map)",
    )
    reassess.add_argument(
        "--goal",
        default="",
        help="Optional coding goal used to frame the before/after explanation",
    )
    _add_service_url(reassess)
    reassess.set_defaults(handler=_reassess, db=None)


def _add_service_url(parser: Any) -> None:
    parser.add_argument(
        "--service-url",
        help=(
            "Dashboard/API that owns the saved index (found automatically on this machine when "
            "--db is omitted)"
        ),
    )


def _guidance(args: argparse.Namespace) -> dict[str, Any]:
    service = _agent_service(args)
    if service is not None:
        return _service_result(
            service_architecture_guidance(
                service,
                goal=args.goal,
                intent=args.intent,
                focus=args.focus,
            ),
            service,
        )
    database, repository_id, config = ensure_current(args)
    return architecture_guidance(
        database,
        repository_id=repository_id,
        goal=args.goal,
        config=config,
        intent=args.intent,
        focus=args.focus,
    )


def _impact(args: argparse.Namespace) -> dict[str, Any]:
    service = _agent_service(args)
    if service is not None:
        return _service_result(
            service_impact(
                service,
                requested_target=args.target,
            ),
            service,
        )
    database, repository_id, config = ensure_current(args)
    return impact_analysis(
        database,
        repository_id=repository_id,
        target=args.target,
        config=config,
    )


def _fresh_eyes(args: argparse.Namespace) -> dict[str, Any]:
    service = _agent_service(args)
    if service is not None:
        return _service_result(_service_fresh_eyes(service, args), service)
    database, repository_id, config = ensure_current(args)
    engine = SemanticEngine(database)
    if args.unpin:
        return engine.unpin_fresh_eyes_executors(repository_id, config.semantic)
    if args.start or args.restart:
        return engine.start_fresh_eyes_review(
            repository_id,
            args.repository,
            config,
            proposal_count=args.proposals,
            proposal_executors=parse_proposal_executors(args.proposal_executors),
            retry_failed=args.retry_failed,
            restart=args.restart,
        )
    return engine.fresh_eyes_status(
        repository_id,
        config.semantic,
        generation=args.generation,
        compare_with=args.compare_with,
    )


def _service_fresh_eyes(service: Any, args: argparse.Namespace) -> dict[str, Any]:
    starting = bool(args.start or args.restart)
    try:
        return service_fresh_eyes_review(
            service,
            start=starting,
            unpin=args.unpin,
            proposal_count=args.proposals,
            proposal_executors=parse_proposal_executors(args.proposal_executors),
            retry_failed=args.retry_failed,
            restart=args.restart,
            generation=args.generation,
            compare_with=args.compare_with,
            timeout=args.timeout_seconds,
        )
    except OSError as exc:
        if not starting or not _timed_out(exc):
            raise
        message = _FRESH_EYES_TIMED_OUT.format(
            action="restart" if args.restart else "start",
            seconds=args.timeout_seconds,
            repository=args.repository,
        )
        raise OSError(message) from exc


def _timed_out(error: OSError) -> bool:
    return isinstance(error, TimeoutError) or "timed out" in str(error).lower()


def _reassess(args: argparse.Namespace) -> dict[str, Any]:
    service = _agent_service(args)
    if service is not None:
        return _service_result(
            service_architecture_reassessment(
                service,
                from_snapshot_id=args.from_snapshot,
                goal=args.goal,
            ),
            service,
        )
    database, repository_id, config = ensure_current(args)
    return architecture_reassessment(
        database,
        repository_id=repository_id,
        config=config,
        from_snapshot_id=args.from_snapshot,
        goal=args.goal,
    )


def _agent_service(args: argparse.Namespace) -> Any | None:
    if args.db is not None and args.service_url:
        raise ValueError("Choose either --db for a local index or --service-url for a service")
    if args.db is not None or os.environ.get("ANAXIGRAPH_DB"):
        return None
    service = discover_semantic_service(
        args.repository.expanduser().resolve(), explicit_url=args.service_url
    )
    if service is not None and args.config is not None:
        raise ValueError(
            "--config cannot override the matching service policy; use --db for a local index"
        )
    return service


def _service_result(value: dict[str, Any], service: Any) -> dict[str, Any]:
    return {**value, "index": service.identity()}

"""CLI registration and handlers for focused coding-agent context."""

from __future__ import annotations

import argparse
import os
from typing import Any

from anaxigraph.agent import agent_scope, impact_analysis
from anaxigraph.cli_common import add_repository_arguments, ensure_current
from anaxigraph.semantic_service import (
    discover_semantic_service,
    service_agent_scope,
    service_impact,
)


def configure_agent_commands(commands: Any) -> None:
    scope = commands.add_parser(
        "scope", help="Find likely files, relevant tests, risks, and checks for a coding goal"
    )
    add_repository_arguments(scope)
    scope.add_argument("--goal", required=True, help="The coding goal")
    _add_service_url(scope)
    scope.set_defaults(handler=_scope, db=None)

    impact = commands.add_parser(
        "impact", help="Find code and tests that may be affected by changing a file or symbol"
    )
    add_repository_arguments(impact)
    impact.add_argument("--target", required=True, help="Repository path or unique symbol")
    _add_service_url(impact)
    impact.set_defaults(handler=_impact, db=None)


def _add_service_url(parser: Any) -> None:
    parser.add_argument(
        "--service-url",
        help=(
            "Dashboard/API that owns the saved index (found automatically on this machine when "
            "--db is omitted)"
        ),
    )


def _scope(args: argparse.Namespace) -> dict[str, Any]:
    service = _agent_service(args)
    if service is not None:
        return _service_result(
            service_agent_scope(
                service,
                goal=args.goal,
            ),
            service,
        )
    database, repository_id, config = ensure_current(args)
    return agent_scope(
        database,
        repository_id=repository_id,
        goal=args.goal,
        config=config,
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

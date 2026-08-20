"""CLI registration and handlers for bounded coding-agent context."""

from __future__ import annotations

import argparse
from typing import Any

from anaxigraph.agent import agent_scope, branch_collisions, impact_analysis
from anaxigraph.cli_common import add_repository_arguments, ensure_current


def configure_agent_commands(commands: Any) -> None:
    scope = commands.add_parser("scope", help="Return bounded task context for a coding goal")
    add_repository_arguments(scope)
    scope.add_argument("--goal", required=True, help="The coding goal")
    scope.add_argument("--branch", help="Feature branch used for collision analysis")
    scope.set_defaults(handler=_scope)

    impact = commands.add_parser("impact", help="Analyze reverse-dependency impact")
    add_repository_arguments(impact)
    impact.add_argument("--target", required=True, help="Repository path or unique symbol")
    impact.add_argument("--branch", help="Feature branch used for collision analysis")
    impact.set_defaults(handler=_impact)

    collisions = commands.add_parser("collisions", help="Compare active branch change surfaces")
    add_repository_arguments(collisions)
    collisions.set_defaults(handler=_collisions)


def _scope(args: argparse.Namespace) -> dict[str, Any]:
    database, repository_id, config = ensure_current(args)
    return agent_scope(
        database,
        repository_id=repository_id,
        goal=args.goal,
        branch=args.branch,
        config=config,
    )


def _impact(args: argparse.Namespace) -> dict[str, Any]:
    database, repository_id, config = ensure_current(args)
    return impact_analysis(
        database,
        repository_id=repository_id,
        target=args.target,
        branch=args.branch,
        config=config,
    )


def _collisions(args: argparse.Namespace) -> dict[str, Any]:
    database, repository_id, _ = ensure_current(args)
    return branch_collisions(database, repository_id=repository_id)

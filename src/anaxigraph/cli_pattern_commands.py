"""CLI query access to the authoritative pattern-intelligence index."""

from __future__ import annotations

import argparse
from typing import Any

import anaxigraph.cli_services as cli_services
from anaxigraph.cli_common import add_repository_arguments
from anaxigraph.local_runtime import local_database_path
from anaxigraph.pattern_intelligence import PatternIntelligenceService
from anaxigraph.pattern_query import PatternEvaluationQuery
from anaxigraph.semantic_service import (
    discover_semantic_service,
    service_pattern_evaluations,
)


def configure_pattern_commands(commands: Any) -> None:
    parser = commands.add_parser(
        "patterns",
        help="Query finalized coding-pattern evaluations by target or pattern",
    )
    add_repository_arguments(parser)
    parser.add_argument("--snapshot-id", type=int)
    parser.add_argument("--target", default="", help="Exact target key, path, or qualified name")
    parser.add_argument("--pattern", default="", help="Exact pattern catalog key")
    parser.add_argument("--level", default="", help="Target hierarchy level")
    parser.add_argument("--recommendation", default="", help="Final recommendation filter")
    parser.add_argument("--presence", default="", help="Current pattern presence filter")
    parser.add_argument("--sort-by", default="opportunity", help="Score used for descending rank")
    parser.add_argument("--minimum-score", type=int, default=0)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--include-evidence", action="store_true")
    parser.add_argument(
        "--service-url",
        help="Authoritative dashboard/API root (auto-detected when --db is omitted)",
    )
    parser.set_defaults(handler=_patterns, db=None)


def _patterns(args: argparse.Namespace) -> dict[str, Any]:
    if args.snapshot_id is not None and args.snapshot_id < 1:
        raise ValueError("Pattern snapshot id must be positive")
    if args.db is not None and args.service_url:
        raise ValueError("Choose either --db for a local index or --service-url for a service")
    repository = args.repository.expanduser().resolve()
    query = _query(args)
    service = (
        discover_semantic_service(repository, explicit_url=args.service_url)
        if args.db is None
        else None
    )
    if service is not None:
        result = service_pattern_evaluations(service, query, snapshot_id=args.snapshot_id)
        return {**result, "index": service.identity()}
    database_path = local_database_path(repository, explicit=args.db)
    database = cli_services.open_index(database_path)
    row = database.repository(repository)
    if row is None:
        raise ValueError(f"Repository has not been scanned in {database_path}")
    result = PatternIntelligenceService(database).query(
        int(row["id"]), args.snapshot_id, request=query
    )
    return {
        **result,
        "index": {"authority": "local", "database": str(database_path)},
    }


def _query(args: argparse.Namespace) -> PatternEvaluationQuery:
    return PatternEvaluationQuery(
        target=args.target,
        pattern=args.pattern,
        level=args.level,
        recommendation=args.recommendation,
        presence=args.presence,
        sort_by=args.sort_by,
        minimum_score=args.minimum_score,
        limit=args.limit,
        offset=args.offset,
        include_evidence=args.include_evidence,
    )

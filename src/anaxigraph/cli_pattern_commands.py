"""CLI query access to the authoritative pattern-intelligence index."""

from __future__ import annotations

import argparse
from typing import Any

import anaxigraph.cli_services as cli_services
from anaxigraph.cli_common import add_repository_arguments
from anaxigraph.local_runtime import local_database_path
from anaxigraph.pattern_candidate_query import PatternCandidateQuery
from anaxigraph.pattern_intelligence import PatternIntelligenceService
from anaxigraph.pattern_query import PatternEvaluationQuery
from anaxigraph.semantic_service import (
    discover_semantic_service,
    service_pattern_candidates,
    service_pattern_evaluations,
)


def configure_pattern_commands(commands: Any) -> None:
    parser = commands.add_parser(
        "patterns",
        help="Query finalized evaluations or explain sparse pattern candidates",
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
        "--candidates",
        action="store_true",
        help="Explain deterministic sparse-plan selection instead of finalized ratings",
    )
    parser.add_argument(
        "--selection",
        default="skipped",
        help="Candidate explanations to return: skipped, selected, or all",
    )
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
    request = _query(args)
    service = (
        discover_semantic_service(repository, explicit_url=args.service_url)
        if args.db is None
        else None
    )
    if service is not None:
        result = _service_result(service, request, args.snapshot_id)
        return {**result, "index": service.identity()}
    database_path = local_database_path(repository, explicit=args.db)
    database = cli_services.open_index(database_path)
    row = database.repository(repository)
    if row is None:
        raise ValueError(f"Repository has not been scanned in {database_path}")
    result = _local_result(database, int(row["id"]), request, args.snapshot_id)
    return {
        **result,
        "index": {"authority": "local", "database": str(database_path)},
    }


def _query(args: argparse.Namespace) -> PatternEvaluationQuery | PatternCandidateQuery:
    if args.candidates:
        return PatternCandidateQuery(
            pattern=args.pattern,
            target=args.target,
            level=args.level,
            selection=args.selection,
            limit=args.limit,
            offset=args.offset,
            include_evidence=args.include_evidence,
        )
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


def _service_result(
    service: Any,
    request: PatternEvaluationQuery | PatternCandidateQuery,
    snapshot_id: int | None,
) -> dict[str, Any]:
    if isinstance(request, PatternCandidateQuery):
        return service_pattern_candidates(service, request, snapshot_id=snapshot_id)
    return service_pattern_evaluations(service, request, snapshot_id=snapshot_id)


def _local_result(
    database: Any,
    repository_id: int,
    request: PatternEvaluationQuery | PatternCandidateQuery,
    snapshot_id: int | None,
) -> dict[str, Any]:
    service = PatternIntelligenceService(database)
    if isinstance(request, PatternCandidateQuery):
        return service.candidates(repository_id, snapshot_id, request=request)
    return service.query(repository_id, snapshot_id, request=request)

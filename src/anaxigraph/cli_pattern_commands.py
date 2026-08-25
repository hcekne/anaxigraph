"""CLI query access to the authoritative pattern-intelligence index."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import anaxigraph.cli_pattern_calibration as pattern_calibration
import anaxigraph.cli_services as cli_services
from anaxigraph.cli_common import add_repository_arguments
from anaxigraph.local_runtime import local_database_path


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
        "--calibrate",
        type=Path,
        metavar="MANIFEST",
        help="Measure the current pattern map against a versioned calibration manifest",
    )
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
    if args.calibrate is not None and args.candidates:
        raise ValueError("Choose either --calibrate or --candidates")
    repository = args.repository.expanduser().resolve()
    manifest = pattern_calibration.load_manifest(args.calibrate)
    request = None if manifest is not None else pattern_calibration.query(args)
    service = (
        pattern_calibration.discover_service(repository, args.service_url)
        if args.db is None
        else None
    )
    if service is not None:
        return _service_response(service, manifest, request, args.snapshot_id)
    return _local_response(repository, args.db, manifest, request, args.snapshot_id)


def _service_response(
    service: Any,
    manifest: Any,
    request: Any,
    snapshot_id: int | None,
) -> dict[str, Any]:
    result = (
        pattern_calibration.service_result(service, manifest, snapshot_id)
        if manifest is not None
        else pattern_calibration.service_query(service, _required(request), snapshot_id)
    )
    return {**result, "index": service.identity()}


def _local_response(
    repository: Path,
    database_option: Path | None,
    manifest: Any,
    request: Any,
    snapshot_id: int | None,
) -> dict[str, Any]:
    database_path = local_database_path(repository, explicit=database_option)
    database = cli_services.open_index(database_path)
    row = database.repository(repository)
    if row is None:
        raise ValueError(f"Repository has not been scanned in {database_path}")
    result = (
        pattern_calibration.local_result(database, int(row["id"]), manifest, snapshot_id)
        if manifest is not None
        else pattern_calibration.local_query(
            database, int(row["id"]), _required(request), snapshot_id
        )
    )
    return {
        **result,
        "index": {"authority": "local", "database": str(database_path)},
    }


def _required(request: Any) -> Any:
    if request is None:
        raise ValueError("pattern query request is required")
    return request

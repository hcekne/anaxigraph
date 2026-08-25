"""CLI access to saved coding-pattern results and their evidence."""

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
        help="Show completed pattern results or explain why code was selected or skipped",
    )
    add_repository_arguments(parser)
    _add_pattern_filters(parser)
    _add_pattern_modes(parser)
    parser.set_defaults(handler=_patterns, db=None)


def _add_pattern_filters(parser: Any) -> None:
    parser.add_argument("--snapshot-id", type=int, help="Numeric id of a specific saved scan")
    parser.add_argument(
        "--target",
        default="",
        help="Exact machine key, file path, or code name such as Class.method",
    )
    parser.add_argument("--pattern", default="", help="Exact pattern library key")
    parser.add_argument(
        "--level", default="", help="Size of code to check, such as file or function"
    )
    parser.add_argument("--recommendation", default="", help="Suggested-action filter")
    parser.add_argument(
        "--presence", default="", help="Filter by whether the pattern is already present"
    )
    parser.add_argument(
        "--sort-by", default="opportunity", help="Pattern question used to order results"
    )
    parser.add_argument(
        "--minimum-score", type=int, default=0, help="Lowest 0-to-100 answer to include"
    )
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument(
        "--include-evidence",
        action="store_true",
        help="Include the observations, cautions, and changes made by the second AI check",
    )


def _add_pattern_modes(parser: Any) -> None:
    parser.add_argument(
        "--calibrate",
        type=Path,
        metavar="MANIFEST",
        help="Compare current pattern results with expected answers in a saved test-case file",
    )
    parser.add_argument(
        "--candidates",
        action="store_true",
        help="Explain why code was selected or skipped before an AI pattern check",
    )
    parser.add_argument(
        "--selection",
        default="skipped",
        help="Possible matches to return: skipped, selected, or all",
    )
    parser.add_argument(
        "--service-url",
        help="Dashboard/API that owns the saved index (found automatically when --db is omitted)",
    )


def _patterns(args: argparse.Namespace) -> dict[str, Any]:
    if args.snapshot_id is not None and args.snapshot_id < 1:
        raise ValueError("The saved-scan id for pattern results must be positive")
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

"""Explicit save/load commands for a Git-tracked repository architecture record."""

from __future__ import annotations

from typing import Any

from anaxigraph.cli_common import add_repository_arguments, ensure_current
from anaxigraph.cli_planning_service import planning_request, planning_service
from anaxigraph.portable_record import record_status, save_record


def configure_record_commands(commands: Any) -> None:
    parser = commands.add_parser(
        "record", help="Save or load the Git-tracked anaxigraph/ architecture record"
    )
    parser.add_argument("action", choices=("save", "load", "status"))
    add_repository_arguments(parser)
    parser.add_argument(
        "--service-url", help="Service owning this checkout; discovered when --db is omitted"
    )
    parser.set_defaults(handler=_record, db=None)


def _record(args: Any) -> dict[str, Any]:
    service = planning_service(args)
    if service:
        return planning_request(
            service, f"record/{args.action}", None if args.action == "status" else {}
        )
    database, repository_id, _config = ensure_current(args)
    if args.action == "save":
        result = save_record(database, repository_id)
    else:
        result = record_status(database, repository_id)
    return {**result, "index": {"authority": "local", "database": str(database.path)}}

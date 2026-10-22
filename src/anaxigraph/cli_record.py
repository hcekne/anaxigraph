"""Explicit save/load commands for a Git-tracked repository architecture record."""

from __future__ import annotations

from typing import Any

import anaxigraph.cli_services as cli_services
from anaxigraph.cli_common import add_repository_arguments, ensure_current
from anaxigraph.cli_planning_service import planning_request, planning_service
from anaxigraph.portable_record import record_status, save_record


def configure_record_commands(commands: Any) -> None:
    parser = commands.add_parser(
        "record", help="Save or load the Git-tracked anaxigraph/ architecture record"
    )
    parser.add_argument("action", choices=("save", "load", "status", "compact"))
    add_repository_arguments(parser)
    parser.add_argument(
        "--service-url", help="Service owning this checkout; discovered when --db is omitted"
    )
    parser.set_defaults(handler=_record, db=None)


def _record(args: Any) -> dict[str, Any]:
    if args.action == "compact":
        return _compact(args)
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


def _compact(args: Any) -> dict[str, Any]:
    from anaxigraph.config import load_config
    from anaxigraph.local_runtime import local_database_path
    from anaxigraph.persistence.current_retention import retain_current_index
    from anaxigraph.storage_status import storage_status

    if args.service_url:
        raise ValueError("Compaction runs on the server owning the index; use its local --db path")
    root = args.repository.expanduser().resolve()
    database = cli_services.open_index(local_database_path(root, explicit=args.db))
    repository = database.repository(root)
    if repository is None:
        raise ValueError("This checkout is not indexed in the selected local database")
    config = load_config(root, args.config)
    database.storage_policy = config.storage
    with database.scan_lock():
        result = retain_current_index(database, repository["id"], config.storage, migrate=True)
    if result.get("within_budget"):
        scan = cli_services.scanner(database).scan(root, config_path=args.config)
        cli_services.semantics(database).plan(scan.repository_id, root, config)
        result["scan"] = {
            "files": scan.discovered,
            "analyzed": scan.analyzed,
            "reused": scan.reused,
        }
    result["record"] = save_record(database, repository["id"], maintenance=True, config=config)
    result["storage"] = storage_status(database, root, config.storage)
    return result

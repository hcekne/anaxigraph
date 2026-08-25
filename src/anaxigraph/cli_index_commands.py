"""Local-only AnaxiIndex backup and restore commands."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Any

import anaxigraph.cli_services as cli_services
from anaxigraph.cli_common import default_db
from anaxigraph.persistence import (
    SUPPORTED_SCHEMA_VERSIONS,
    create_index_backup,
    inspect_index,
    restore_index_backup,
    validate_index_backup,
)


def configure_index_commands(commands: Any) -> None:
    backup = commands.add_parser("backup", help="Create a validated AnaxiIndex backup")
    backup.add_argument("--db", type=Path, default=default_db())
    backup.add_argument("--output", type=Path, help="New backup path (defaults beside the index)")
    backup.add_argument("--json", action="store_true")
    backup.set_defaults(handler=_backup)

    restore = commands.add_parser("restore", help="Restore AnaxiIndex from a validated backup")
    restore.add_argument("backup", type=Path)
    restore.add_argument("--db", type=Path, default=default_db())
    restore.add_argument("--yes", action="store_true", help="Confirm replacement of the index")
    restore.add_argument("--json", action="store_true")
    restore.set_defaults(handler=_restore)


def _backup(args: argparse.Namespace) -> dict[str, Any]:
    try:
        report = create_index_backup(args.db, args.output)
    except sqlite3.Error as exc:
        raise RuntimeError(f"AnaxiIndex backup failed: {exc}") from exc
    return {
        "contract_version": "anaxigraph-index-backup-v1",
        "status": "complete",
        "backup": report.as_dict(),
    }


def _restore(args: argparse.Namespace) -> dict[str, Any]:
    if not args.yes:
        raise ValueError("Restore replaces the selected index; stop its services and pass --yes")
    try:
        source = validate_index_backup(args.backup)
    except sqlite3.Error as exc:
        raise RuntimeError(f"Invalid SQLite backup: {exc}") from exc
    if source.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        supported = ", ".join(str(value) for value in sorted(SUPPORTED_SCHEMA_VERSIONS))
        raise ValueError(
            f"Backup schema {source.schema_version} is unsupported; supported versions: {supported}"
        )
    try:
        restored = restore_index_backup(args.db, source.path)
        database = cli_services.open_index(args.db)
        health = inspect_index(database.path, database.connect)
    except sqlite3.Error as exc:
        raise RuntimeError(f"AnaxiIndex restore failed: {exc}") from exc
    return {
        "contract_version": "anaxigraph-index-restore-v1",
        "status": "complete",
        "source": source.as_dict(),
        "restored_image": restored.as_dict(),
        "final_schema_version": health["schema_version"],
        "health": health["status"],
    }

"""Shared, side-effect-light helpers for AnaxiGraph command handlers."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import anaxigraph.cli_services as cli_services


def add_repository_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("repository", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument(
        "--config",
        type=Path,
        help="Configuration file (defaults to .anaxigraph.yml)",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=default_db(),
        help="SQLite file where AnaxiGraph saves its index outside the repository",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")


def default_db() -> Path:
    configured = os.environ.get("ANAXIGRAPH_DB")
    if configured:
        return Path(configured).expanduser()
    state_root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return state_root / "anaxigraph" / "anaxi-index.db"


def ensure_current(args: argparse.Namespace) -> tuple[Any, int, Any]:
    database = cli_services.open_index(args.db)
    stats = cli_services.scanner(database).scan(
        args.repository,
        config_path=args.config,
        run_type="agent_context",
    )
    config = cli_services.load_repository_config(args.repository.resolve(), args.config)
    return database, stats.repository_id, config


def emit_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))

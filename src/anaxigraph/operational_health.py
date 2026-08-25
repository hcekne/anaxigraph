"""Compact local index capacity and queue-pressure diagnostics."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

_ACTIVE_RUN_STATES = ("queued", "enumerating", "importing", "finalizing", "running")


def operational_health(database: Any, operation_gate: Any) -> dict[str, Any]:
    with database.connect() as connection:
        database_state = _database_state(connection)
        repositories = int(connection.execute("SELECT COUNT(*) FROM repositories").fetchone()[0])
        runs = _grouped_counts(
            connection,
            "analysis_runs",
            "status",
            where=f"status IN ({','.join('?' for _ in _ACTIVE_RUN_STATES)})",
            parameters=_ACTIVE_RUN_STATES,
        )
        semantic = _grouped_counts(connection, "semantic_jobs", "status")
    files = _index_files(database.path)
    disk = shutil.disk_usage(database.path.parent)
    active_semantic = sum(semantic.get(state, 0) for state in ("pending", "running", "retry"))
    active_runs = sum(runs.values())
    admitted = operation_gate.snapshot()
    return {
        "contract_version": "operational-health-v1",
        "status": "ok",
        "database": {**database_state, **files},
        "disk": {"free_bytes": disk.free, "total_bytes": disk.total},
        "repositories": repositories,
        "pressure": {
            "active_analysis_runs": active_runs,
            "semantic_jobs": semantic,
            "semantic_jobs_actionable": active_semantic,
            "http_operations": admitted,
            "busy": bool(active_runs or active_semantic or admitted["active_count"]),
        },
    }


def _database_state(connection: Any) -> dict[str, Any]:
    values = {
        name: connection.execute(f"PRAGMA {name}").fetchone()[0]
        for name in ("page_count", "page_size", "freelist_count", "journal_mode")
    }
    schema = connection.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()
    return {
        "schema_version": int(schema[0]),
        "journal_mode": str(values["journal_mode"]),
        "allocated_bytes": int(values["page_count"]) * int(values["page_size"]),
        "reclaimable_bytes": int(values["freelist_count"]) * int(values["page_size"]),
    }


def _grouped_counts(
    connection: Any,
    table: str,
    column: str,
    *,
    where: str = "1 = 1",
    parameters: tuple[str, ...] = (),
) -> dict[str, int]:
    rows = connection.execute(
        f"SELECT {column}, COUNT(*) AS count FROM {table} WHERE {where} GROUP BY {column}",
        parameters,
    ).fetchall()
    return {str(row[column]): int(row["count"]) for row in rows}


def _index_files(path: Path) -> dict[str, int]:
    paths = {
        "database_bytes": path,
        "wal_bytes": Path(f"{path}-wal"),
        "shared_memory_bytes": Path(f"{path}-shm"),
    }
    sizes = {name: item.stat().st_size if item.exists() else 0 for name, item in paths.items()}
    sizes["total_index_bytes"] = sum(sizes.values())
    return sizes

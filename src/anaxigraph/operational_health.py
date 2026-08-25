"""Compact local index capacity and queue-pressure diagnostics."""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import anaxigraph.git as git

_ACTIVE_RUN_STATES = ("queued", "enumerating", "importing", "finalizing", "running")


def served_map_status(root: Path, snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Compare a saved map with the checkout that the service can currently read."""

    try:
        checkout = git.metadata(root)
    except (git.GitError, OSError) as exc:
        return _unavailable_map_status(snapshot, exc)
    metadata = _snapshot_metadata(snapshot)
    mapped_commit = str(snapshot.get("commit_sha") or "unknown")
    mapped_dirty = bool(snapshot.get("dirty"))
    state, reason = _map_state(
        mapped_commit,
        mapped_dirty,
        metadata.get("working_tree_fingerprint"),
        checkout.commit_sha,
        checkout.dirty,
        checkout.working_tree_fingerprint,
    )
    return {
        "contract_version": "served-map-status-v1",
        "state": state,
        "safe_to_plan": state == "current",
        "scan_recommended": state != "current",
        "mapped": {
            "snapshot_id": int(snapshot["id"]),
            "commit_sha": mapped_commit,
            "dirty": mapped_dirty,
            "analyzed_at": snapshot.get("analysis_timestamp"),
            "scanner_version": metadata.get("anaxigraph_version"),
            "working_tree_fingerprint": metadata.get("working_tree_fingerprint"),
        },
        "checkout": {
            "commit_sha": checkout.commit_sha,
            "branch": checkout.branch,
            "dirty": checkout.dirty,
            "working_tree_fingerprint": checkout.working_tree_fingerprint,
        },
        "service_version": _service_version(),
        "plain_language": _map_language(state, reason),
    }


def _map_state(
    mapped_commit: str,
    mapped_dirty: bool,
    mapped_worktree: Any,
    checkout_commit: str,
    checkout_dirty: bool,
    checkout_worktree: str | None,
) -> tuple[str, str]:
    if "unversioned" in {mapped_commit, checkout_commit}:
        return "uncertain", "Git could not identify both saved and current commits."
    if mapped_commit != checkout_commit:
        return "stale", f"The saved map uses {mapped_commit[:12]}, not {checkout_commit[:12]}."
    if mapped_worktree and checkout_worktree:
        if str(mapped_worktree) == checkout_worktree:
            return "current", "The saved map matches the current commit and working files."
        return "stale", "The working files have changed since this map was saved."
    if mapped_dirty != checkout_dirty:
        return "stale", "The saved map and checkout disagree about uncommitted changes."
    if mapped_dirty:
        return "uncertain", "Both use the same commit, but uncommitted content may have changed."
    return "current", f"The saved map and clean checkout both use {checkout_commit[:12]}."


def _map_language(state: str, reason: str) -> dict[str, str]:
    action = (
        "Use this map for planning."
        if state == "current"
        else "Refresh the structural scan before relying on this map for a code change."
    )
    return {"summary": reason, "action": action}


def _snapshot_metadata(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    try:
        metadata = json.loads(str(snapshot.get("metadata_json") or "{}"))
    except (TypeError, ValueError):
        return {}
    return metadata if isinstance(metadata, dict) else {}


def _service_version() -> str:
    try:
        return version("anaxigraph")
    except PackageNotFoundError:
        return "unknown"


def _unavailable_map_status(snapshot: Mapping[str, Any], error: Exception) -> dict[str, Any]:
    return {
        "contract_version": "served-map-status-v1",
        "state": "unavailable",
        "safe_to_plan": False,
        "scan_recommended": True,
        "mapped": {"snapshot_id": int(snapshot["id"])},
        "checkout": None,
        "service_version": _service_version(),
        "plain_language": {
            "summary": f"The service could not inspect the checkout: {error}",
            "action": "Restore read access to the registered checkout, then refresh the scan.",
        },
    }


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

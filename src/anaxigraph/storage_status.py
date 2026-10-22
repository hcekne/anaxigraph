"""Report local mapping, portable publication and Git delivery independently."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from anaxigraph.portable_paths import record_directory


def storage_status(database: Any, root: Path, policy: Any) -> dict[str, Any]:
    directory = record_directory(root)
    paths = [path for path in directory.rglob("*") if path.is_file()] if directory.is_dir() else []
    record_bytes = sum(path.stat().st_size for path in paths)
    index_bytes = database.path.stat().st_size
    wal = database.path.with_name(database.path.name + "-wal")
    wal_bytes = wal.stat().st_size if wal.exists() else 0
    return {
        "index_bytes": index_bytes,
        "wal_bytes": wal_bytes,
        "record_bytes": record_bytes,
        "record_files": len(paths),
        "active_bytes": record_bytes + index_bytes + wal_bytes,
        "budget_bytes": policy.budget_bytes,
        "hard_ceiling_bytes": 200_000_000,
        "within_budget": record_bytes + index_bytes + wal_bytes <= policy.budget_bytes
        and index_bytes <= policy.index_bytes
        and record_bytes <= policy.record_bytes
        and len(paths) <= policy.record_files,
    }

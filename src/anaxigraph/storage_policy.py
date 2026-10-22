"""Small, explicit budgets for portable understanding and disposable local caches."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

HARD_STORAGE_BYTES = 200_000_000


@dataclass(frozen=True, slots=True)
class StoragePolicy:
    budget_bytes: int = 100_000_000
    record_bytes: int = 25_000_000
    index_bytes: int = 64_000_000
    record_files: int = 32
    comparison_checkpoints: int = 2
    detailed_history: bool = False


def storage_policy(raw: Any = None) -> StoragePolicy:
    raw = raw or {}
    if not isinstance(raw, dict):
        raise ValueError("storage must be a mapping")
    defaults = StoragePolicy()
    values = {}
    for name in (
        "budget_bytes",
        "record_bytes",
        "index_bytes",
        "record_files",
        "comparison_checkpoints",
    ):
        value = raw.get(name, getattr(defaults, name))
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < (0 if name == "comparison_checkpoints" else 1)
        ):
            raise ValueError(
                f"storage.{name} must be a nonnegative integer"
                if name == "comparison_checkpoints"
                else f"storage.{name} must be a positive integer"
            )
        values[name] = value
    if not isinstance(raw.get("detailed_history", False), bool):
        raise ValueError("storage.detailed_history must be true or false")
    if values["budget_bytes"] > HARD_STORAGE_BYTES:
        raise ValueError("AnaxiGraph storage cannot exceed the 200 MB hard ceiling")
    if values["record_bytes"] + values["index_bytes"] > values["budget_bytes"]:
        raise ValueError("storage.record_bytes + storage.index_bytes must fit storage.budget_bytes")
    if values["record_files"] > 64 or values["comparison_checkpoints"] > 20:
        raise ValueError("Storage allows at most 64 record files and 20 comparison checkpoints")
    return StoragePolicy(**values, detailed_history=raw.get("detailed_history", False))


def admit_index_write(connection: Any, path: Path, policy: StoragePolicy) -> None:
    wal = path.with_name(path.name + "-wal")
    active = path.stat().st_size + (wal.stat().st_size if wal.exists() else 0)
    if active > policy.budget_bytes - policy.record_bytes:
        raise ValueError(
            "AnaxiGraph local cache and write-ahead log exceed the storage budget. Compact the index or restart the owning service to release old readers before adding analysis."
        )
    used_pages = (
        connection.execute("PRAGMA page_count").fetchone()[0]
        - connection.execute("PRAGMA freelist_count").fetchone()[0]
    )
    if used_pages * connection.execute("PRAGMA page_size").fetchone()[0] > policy.index_bytes:
        raise ValueError(
            "AnaxiGraph index exceeds its storage budget. Run 'anaxigraph record compact' on the server owning this database before adding more analysis."
        )

"""Small, explicit budgets for portable understanding and disposable local caches."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from anaxigraph.storage_usage import index_file_usage, registered_record_usage

HARD_STORAGE_BYTES = 200_000_000


def repository_storage_policy(root: Path, config_path: Path | None = None):
    selected = config_path if config_path and config_path.is_file() else root / ".anaxigraph.yml"
    raw = yaml.safe_load(selected.read_text()) if selected.is_file() else {}
    if raw is not None and not isinstance(raw, dict):
        raise ValueError("Repository storage configuration must be a mapping")
    return storage_policy((raw or {}).get("storage"))


@dataclass(frozen=True, slots=True)
class StoragePolicy:
    budget_bytes: int = 100_000_000
    record_bytes: int = 25_000_000
    index_bytes: int = 95_000_000
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
    if max(values["record_bytes"], values["index_bytes"]) > values["budget_bytes"]:
        raise ValueError("Each storage component ceiling must fit storage.budget_bytes")
    if values["record_files"] > 64 or values["comparison_checkpoints"] > 20:
        raise ValueError("Storage allows at most 64 record files and 20 comparison checkpoints")
    return StoragePolicy(**values, detailed_history=raw.get("detailed_history", False))


def admit_index_write(connection: Any, path: Path, policy: StoragePolicy) -> None:
    _admit_pool(connection, path, policy, registered_record_usage(connection)["bytes"])


def admit_record_write(connection, path, root, proposed_bytes, policy):
    if proposed_bytes > policy.record_bytes:
        raise ValueError("Portable record exceeds its storage budget; previous record retained")
    records = registered_record_usage(
        connection, replacing_root=root, replacement_bytes=proposed_bytes
    )
    _admit_pool(connection, path, policy, records["bytes"])


def admit_publication_peak(connection, path, added_bytes):
    active = sum(index_file_usage(path).values()) + registered_record_usage(connection)["bytes"]
    if active + added_bytes > HARD_STORAGE_BYTES:
        raise ValueError(
            "Portable publication would exceed the 200 MB hard storage ceiling; previous record retained"
        )


def _admit_pool(connection, path, policy, record_bytes):
    usage = index_file_usage(path)
    projected = (
        connection.execute("PRAGMA page_count").fetchone()[0]
        * connection.execute("PRAGMA page_size").fetchone()[0]
    )
    if max(usage["index_bytes"], projected) > policy.index_bytes:
        raise ValueError(
            "AnaxiGraph index exceeds its storage budget. Run 'anaxigraph record compact' on the server owning this database before adding more analysis."
        )
    steady = max(usage["index_bytes"], projected) + usage["shm_bytes"] + record_bytes
    if steady > policy.budget_bytes:
        raise ValueError(
            "AnaxiGraph retained index, SHM and managed records exceed the shared storage budget. Compact the index before adding analysis; previous record retained."
        )
    if sum(usage.values()) + record_bytes > HARD_STORAGE_BYTES:
        raise ValueError(
            "AnaxiGraph physical index, WAL/SHM and records exceed the 200 MB hard storage ceiling; release old readers and checkpoint before adding analysis"
        )


@contextmanager
def maintenance_headroom(connection, path):
    """Allow disposable rewrites to compact before final steady-budget admission."""
    records = registered_record_usage(connection)["bytes"]
    usage = index_file_usage(path)
    reserve = 16_064_000  # One bounded decoded metadata row plus four SQLite pages.
    available = HARD_STORAGE_BYTES - records - sum(usage.values()) - reserve
    page_size = connection.execute("PRAGMA page_size").fetchone()[0]
    original = connection.execute("PRAGMA max_page_count").fetchone()[0]
    if available < connection.execute("PRAGMA page_count").fetchone()[0] * page_size:
        raise ValueError("Insufficient physical headroom for bounded cache maintenance")
    connection.execute(f"PRAGMA max_page_count={available // page_size}")
    exhausted = False

    def guard_bytes():
        nonlocal exhausted
        exhausted = sum(index_file_usage(path).values()) + records > HARD_STORAGE_BYTES - reserve
        return int(exhausted)

    connection.set_progress_handler(guard_bytes, 1000)
    try:
        yield
        if guard_bytes():
            raise ValueError("Cache maintenance exceeds the physical storage ceiling")
    except sqlite3.OperationalError as error:
        if exhausted:
            raise ValueError("Cache maintenance exceeds the physical storage ceiling") from error
        raise
    finally:
        connection.set_progress_handler(None, 0)
        connection.execute(f"PRAGMA max_page_count={original}")

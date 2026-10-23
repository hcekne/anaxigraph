"""Bounded, validated page reclamation while the index owner is initializing."""

from __future__ import annotations

import os
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from anaxigraph.ir_codec import decode_metadata, storage_metadata
from anaxigraph.persistence.index_backup import _validate_database
from anaxigraph.persistence.index_lifetime import index_file_lock
from anaxigraph.persistence.semantic_payloads import register_semantic_payloads
from anaxigraph.storage_policy import HARD_STORAGE_BYTES
from anaxigraph.storage_usage import registered_record_usage

PAGE_BYTES = 16_384


class CompactionHeadroomError(ValueError):
    """Canonical data fits, but source plus compact copy cannot coexist safely."""


def compact_identity_caches(connection):
    changes = []
    for key, value in connection.execute(
        "SELECT key,value FROM schema_meta WHERE key LIKE 'portable-identities:%'"
    ):
        packed = storage_metadata(decode_metadata(value))
        if packed != value:
            changes.append((packed, key))
    connection.executemany(
        "UPDATE schema_meta SET value='{}' WHERE key=?", [(key,) for _value, key in changes]
    )
    connection.executemany("UPDATE schema_meta SET value=? WHERE key=?", changes)
    if changes:
        connection.execute(
            "INSERT OR REPLACE INTO schema_meta VALUES ('index-compaction-pending','true')"
        )
    return len(changes)


def compact_closed_index(path: Path, *, schema_version: int, record_bytes: int) -> None:
    """Replace a closed owner index; never compact an active service connection."""
    staged = path.with_name(f".{path.name}.compact.tmp")
    with index_file_lock(path, exclusive=True):
        _remove_staged(staged)
        try:
            with closing(sqlite3.connect(path)) as source:
                register_semantic_payloads(source)
                source.execute("PRAGMA temp_store=MEMORY")
                source.execute("PRAGMA busy_timeout=30000")
                busy, _, _ = source.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                if busy:
                    raise RuntimeError("Stop other index readers before reclaiming cache pages")
                source.execute("PRAGMA journal_mode=DELETE")
                limit, guard = _preflight(source, path, staged, record_bytes)
                source.execute(f"PRAGMA page_size={PAGE_BYTES}")
                _vacuum_staged(source, staged, limit, guard)
            _validate_staged(staged, schema_version, limit)
            staged.chmod(path.stat().st_mode & 0o777)
            with staged.open("rb") as handle:
                os.fsync(handle.fileno())
            _publish_staged(staged, path)
        finally:
            _remove_staged(staged)


def rebuild_compact_cache(path, *, schema_version, build, admit):
    """Build disposable pages in bounded RAM while preserving the durable canonical base."""
    staged = path.with_name(f".{path.name}.compact.tmp")
    with index_file_lock(path, exclusive=True):
        _remove_staged(staged)
        try:
            with closing(sqlite3.connect(":memory:")) as memory:
                memory.row_factory = sqlite3.Row
                register_semantic_payloads(memory)
                memory.execute("PRAGMA temp_store=MEMORY")
                with closing(sqlite3.connect(path)) as source:
                    register_semantic_payloads(source)
                    source.execute("PRAGMA busy_timeout=30000")
                    if source.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]:
                        raise RuntimeError("Close index readers before rebuilding its cache")
                    source.execute("PRAGMA journal_mode=DELETE")
                    source.backup(memory)
                memory.execute("PRAGMA foreign_keys=ON")
                page_bytes = memory.execute("PRAGMA page_size").fetchone()[0]
                memory.execute(f"PRAGMA max_page_count={HARD_STORAGE_BYTES // page_bytes}")
                build(memory)
                memory.commit()
                records = registered_record_usage(memory)["bytes"]
                limit, guard = _preflight(memory, path, staged, records)
                memory.execute(f"PRAGMA page_size={PAGE_BYTES}")
                _vacuum_staged(memory, staged, limit, guard)
            _validate_staged(staged, schema_version, limit)
            with closing(sqlite3.connect(staged)) as target:
                target.row_factory = sqlite3.Row
                register_semantic_payloads(target)
                admit(target, staged)
            staged.chmod(path.stat().st_mode & 0o777)
            with staged.open("rb") as handle:
                os.fsync(handle.fileno())
            _publish_staged(staged, path)
        finally:
            _remove_staged(staged)


def _vacuum_staged(source, staged, limit, guard):
    budget_exhausted = False

    def guard_size():
        nonlocal budget_exhausted
        budget_exhausted = bool(_stage_over_budget(staged, limit, guard))
        return int(budget_exhausted)

    source.set_progress_handler(guard_size, 1)
    try:
        source.execute("VACUUM INTO ?", (str(staged),))
    except sqlite3.OperationalError as error:
        if budget_exhausted:
            raise CompactionHeadroomError(
                "Staged index cannot fit safely within 200 MB; current index preserved"
            ) from error
        raise
    finally:
        source.set_progress_handler(None, 0)


def _publish_staged(staged, path):
    os.replace(staged, path)
    if os.name != "nt":
        descriptor = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _preflight(connection, path, staged, record_bytes):
    record_bytes = max(record_bytes, registered_record_usage(connection)["bytes"])
    source_bytes = path.stat().st_size
    page_size = connection.execute("PRAGMA page_size").fetchone()[0]
    used = connection.execute("PRAGMA page_count").fetchone()[0]
    free = connection.execute("PRAGMA freelist_count").fetchone()[0]
    objects = connection.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type IN ('table','index')"
    ).fetchone()[0]
    try:
        payload, cells, largest = connection.execute(
            "SELECT SUM(payload),SUM(ncell),MAX(mx_payload) FROM dbstat"
        ).fetchone()
        estimate = (payload or 0) + (cells or 0) * 4 + objects * PAGE_BYTES
    except sqlite3.OperationalError:
        largest = 2_000_000
        estimate = (used - free) * page_size + objects * PAGE_BYTES
    limit = min(
        HARD_STORAGE_BYTES - record_bytes - source_bytes, shutil.disk_usage(path.parent).free
    )
    if estimate > limit:
        raise CompactionHeadroomError(
            "Index compaction cannot fit its source, staged copy and portable record within 200 MB; the current index and recovery backup are preserved"
        )
    return limit, max(64_000, (largest or 0) + PAGE_BYTES * 4)


def _stage_over_budget(staged, limit, guard):
    # Keep measured row/page headroom between bounded progress callbacks.
    try:
        return int(os.stat(staged).st_size > limit - guard)
    except FileNotFoundError:
        return 0


def _validate_staged(path, schema_version, limit):
    if path.stat().st_size > limit:
        raise CompactionHeadroomError("Staged index compaction exceeds its storage budget")
    _validate_database(path, expected_version=schema_version, immutable=True)
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro&immutable=1", uri=True)) as connection:
        if connection.execute("PRAGMA foreign_key_check").fetchone():
            raise RuntimeError("Staged index compaction failed its foreign-key check")


def _remove_staged(path):
    for suffix in ("", "-journal", "-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)

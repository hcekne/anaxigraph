"""Report local mapping, portable publication and Git delivery independently."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Any

from anaxigraph.storage_usage import index_file_usage, managed_record_usage, registered_record_usage


def storage_status(database: Any, root: Path, policy: Any) -> dict[str, Any]:
    with closing(database.connect()) as connection:
        archive = connection.execute(
            "SELECT COALESCE(SUM(length(data)),0) FROM semantic_payloads"
        ).fetchone()[0]
        records = registered_record_usage(connection)
        projected = (
            connection.execute("PRAGMA page_count").fetchone()[0]
            * connection.execute("PRAGMA page_size").fetchone()[0]
        )
    selected = managed_record_usage(root)
    usage = index_file_usage(database.path)
    backups = list(database.path.parent.glob(database.path.name + "*.backup"))
    backup_bytes = sum(path.stat().st_size for path in backups if path.is_file())
    active = records["bytes"] + sum(usage.values())
    steady = max(usage["index_bytes"], projected) + usage["shm_bytes"] + records["bytes"]
    return {
        **usage,
        "legacy_archive_bytes": archive,
        "archive_included_in_index": True,
        "recovery_backup_bytes": backup_bytes,
        "known_peak_bytes": active + backup_bytes,
        "record_bytes": selected["bytes"],
        "record_files": selected["files"],
        "all_record_bytes": records["bytes"],
        "managed_records": records["records"],
        "budget_scope": "shared_index_and_registered_checkout_records",
        "active_bytes": active,
        "steady_bytes": steady,
        "transient_bytes": max(0, active - steady),
        "checkpoint_or_truncate_pending": usage["wal_bytes"] > 0,
        "record_limit_bytes": policy.record_bytes,
        "record_file_limit": policy.record_files,
        "index_limit_bytes": policy.index_bytes,
        "budget_bytes": policy.budget_bytes,
        "hard_ceiling_bytes": 200_000_000,
        "within_budget": steady <= policy.budget_bytes
        and active <= 200_000_000
        and usage["index_bytes"] <= policy.index_bytes
        and selected["bytes"] <= policy.record_bytes
        and selected["files"] <= policy.record_files,
    }

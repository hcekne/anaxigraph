"""Compatible snapshot lineage selection for architecture reassessment."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Mapping
from typing import Any

from anaxigraph.persistence.snapshot_catalog import resolve_snapshot
from anaxigraph.persistence.temporal_hashing import analysis_signature

_MAX_LINEAGE_DEPTH = 2_500
_MAX_NOOP_BASELINES = 8


def requested_baseline(
    connection: sqlite3.Connection,
    repository_id: int,
    target: Mapping[str, Any],
    requested: int,
) -> sqlite3.Row:
    row = resolve_snapshot(connection, repository_id, requested)
    if row is None:
        raise ValueError("comparison snapshot does not belong to the selected repository")
    _require_compatible(row, target)
    return row


def compatible_baselines(
    connection: sqlite3.Connection,
    repository_id: int,
    target: Mapping[str, Any],
) -> Iterator[sqlite3.Row]:
    """Yield a bounded set of earlier compatible, non-identical snapshot candidates."""

    signature = analysis_signature(str(target["metadata_json"] or "{}"))
    fingerprint = str(target["content_fingerprint"])
    current_id = target["base_snapshot_id"]
    yielded = 0
    depth = 0
    while current_id is not None and depth < _MAX_LINEAGE_DEPTH:
        row = connection.execute(
            "SELECT * FROM snapshots WHERE id = ? AND repository_id = ?",
            (int(current_id), repository_id),
        ).fetchone()
        if row is None:
            break
        if (
            analysis_signature(str(row["metadata_json"] or "{}")) == signature
            and str(row["content_fingerprint"]) != fingerprint
        ):
            yield row
            yielded += 1
            if yielded >= _MAX_NOOP_BASELINES:
                break
        current_id = row["base_snapshot_id"]
        depth += 1


def _require_compatible(baseline: Mapping[str, Any], target: Mapping[str, Any]) -> None:
    before = analysis_signature(str(baseline["metadata_json"] or "{}"))
    after = analysis_signature(str(target["metadata_json"] or "{}"))
    if before != after:
        raise ValueError(
            "comparison snapshots use different analysis contracts; choose a compatible snapshot"
        )

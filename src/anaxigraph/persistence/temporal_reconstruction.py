"""Bounded snapshot reconstruction with disposable reference checkpoints."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from anaxigraph.persistence.temporal_hashing import digest

CHECKPOINT_INTERVAL = 16
CHECKPOINT_POLICY_VERSION = "bounded-delta-v1"


@dataclass(frozen=True, slots=True)
class ReconstructionDiagnostics:
    snapshot_id: int | None
    traversed_deltas: int
    checkpoint_snapshot_id: int | None
    duration_ms: float
    returned_rows: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def reconstruct_files(
    connection: sqlite3.Connection,
    snapshot_id: int | None,
) -> dict[int, dict[str, Any]]:
    state, _diagnostics = reconstruct_files_with_diagnostics(connection, snapshot_id)
    return state


def reconstruct_files_with_diagnostics(
    connection: sqlite3.Connection,
    snapshot_id: int | None,
) -> tuple[dict[int, dict[str, Any]], ReconstructionDiagnostics]:
    started = time.perf_counter()
    checkpoint_id, frames = _reconstruction_path(connection, snapshot_id)
    state = _checkpoint_files(connection, checkpoint_id)
    for frame in reversed(frames):
        _apply_file_changes(connection, state, frame)
    return state, _diagnostics(started, snapshot_id, frames, checkpoint_id, len(state))


def reconstruct_relationships(
    connection: sqlite3.Connection,
    snapshot_id: int | None,
) -> dict[int, int]:
    state, _diagnostics = reconstruct_relationships_with_diagnostics(connection, snapshot_id)
    return state


def reconstruct_relationships_with_diagnostics(
    connection: sqlite3.Connection,
    snapshot_id: int | None,
) -> tuple[dict[int, int], ReconstructionDiagnostics]:
    started = time.perf_counter()
    checkpoint_id, frames = _reconstruction_path(connection, snapshot_id)
    state = _checkpoint_relationships(connection, checkpoint_id)
    for frame in reversed(frames):
        _apply_relationship_changes(connection, state, frame)
    return state, _diagnostics(started, snapshot_id, frames, checkpoint_id, len(state))


def snapshot_lineage(
    connection: sqlite3.Connection,
    snapshot_id: int | None,
) -> list[int]:
    _checkpoint_id, frames = _reconstruction_path(
        connection,
        snapshot_id,
        stop_at_checkpoint=False,
    )
    return frames


def refresh_checkpoint_if_due(connection: sqlite3.Connection, snapshot_id: int) -> bool:
    invalidate_checkpoints(connection, snapshot_id)
    snapshot = connection.execute(
        "SELECT repository_id, sequence FROM snapshots WHERE id = ?",
        (snapshot_id,),
    ).fetchone()
    if snapshot is None:
        raise RuntimeError(f"Cannot checkpoint missing snapshot {snapshot_id}")
    if int(snapshot["sequence"]) % CHECKPOINT_INTERVAL:
        return False
    files, file_diagnostics = reconstruct_files_with_diagnostics(connection, snapshot_id)
    relationships, _relationship_diagnostics = reconstruct_relationships_with_diagnostics(
        connection,
        snapshot_id,
    )
    _insert_checkpoint(
        connection,
        snapshot_id,
        int(snapshot["repository_id"]),
        int(snapshot["sequence"]),
        file_diagnostics.traversed_deltas,
        files,
        relationships,
    )
    return True


def rebuild_checkpoints(
    connection: sqlite3.Connection,
    repository_id: int | None = None,
) -> dict[str, int]:
    if repository_id is None:
        connection.execute("DELETE FROM snapshot_checkpoints")
        rows = connection.execute(
            "SELECT id FROM snapshots ORDER BY repository_id, sequence, id"
        ).fetchall()
    else:
        connection.execute(
            "DELETE FROM snapshot_checkpoints WHERE repository_id = ?",
            (repository_id,),
        )
        rows = connection.execute(
            """
            SELECT id FROM snapshots WHERE repository_id = ?
            ORDER BY sequence, id
            """,
            (repository_id,),
        ).fetchall()
    created = sum(refresh_checkpoint_if_due(connection, int(row["id"])) for row in rows)
    return {"snapshots": len(rows), "checkpoints": created}


def ensure_checkpoint_policy(connection: sqlite3.Connection) -> dict[str, int] | None:
    """Materialize checkpoints once when an index adopts the current cache policy."""

    row = connection.execute(
        "SELECT value FROM schema_meta WHERE key = 'checkpoint_policy_version'"
    ).fetchone()
    if row is not None and row[0] == CHECKPOINT_POLICY_VERSION:
        return None
    report = rebuild_checkpoints(connection)
    connection.execute(
        """
        INSERT OR REPLACE INTO schema_meta(key, value)
        VALUES ('checkpoint_policy_version', ?)
        """,
        (CHECKPOINT_POLICY_VERSION,),
    )
    return report


def canonical_state_hashes(
    files: dict[int, dict[str, Any]],
    relationships: dict[int, int],
) -> tuple[str, str]:
    return _file_state_hash(files), digest(sorted(relationships.items()))


def invalidate_checkpoints(connection: sqlite3.Connection, snapshot_id: int) -> None:
    connection.execute(
        """
        WITH RECURSIVE descendants(id) AS (
            SELECT ?
            UNION
            SELECT snapshots.id FROM snapshots
            JOIN descendants ON snapshots.base_snapshot_id = descendants.id
        )
        DELETE FROM snapshot_checkpoints
        WHERE snapshot_id IN (SELECT id FROM descendants)
        """,
        (snapshot_id,),
    )


def _reconstruction_path(
    connection: sqlite3.Connection,
    snapshot_id: int | None,
    *,
    stop_at_checkpoint: bool = True,
) -> tuple[int | None, list[int]]:
    frames: list[int] = []
    seen: set[int] = set()
    current = snapshot_id
    while current is not None:
        if current in seen:
            raise RuntimeError(f"Snapshot base cycle detected at {current}")
        seen.add(current)
        if stop_at_checkpoint and _has_checkpoint(connection, current):
            return current, frames
        frames.append(current)
        row = connection.execute(
            "SELECT base_snapshot_id FROM snapshots WHERE id = ?",
            (current,),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"Snapshot lineage references missing snapshot {current}")
        current = int(row[0]) if row[0] is not None else None
    return None, frames


def _has_checkpoint(connection: sqlite3.Connection, snapshot_id: int) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM snapshot_checkpoints WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        is not None
    )


def _checkpoint_files(
    connection: sqlite3.Connection,
    checkpoint_id: int | None,
) -> dict[int, dict[str, Any]]:
    if checkpoint_id is None:
        return {}
    rows = connection.execute(
        "SELECT * FROM checkpoint_files WHERE checkpoint_snapshot_id = ?",
        (checkpoint_id,),
    ).fetchall()
    return {int(row["artifact_id"]): dict(row) for row in rows}


def _checkpoint_relationships(
    connection: sqlite3.Connection,
    checkpoint_id: int | None,
) -> dict[int, int]:
    if checkpoint_id is None:
        return {}
    rows = connection.execute(
        """
        SELECT source_artifact_id, relationship_set_id
        FROM checkpoint_relationships WHERE checkpoint_snapshot_id = ?
        """,
        (checkpoint_id,),
    ).fetchall()
    return {int(row["source_artifact_id"]): int(row["relationship_set_id"]) for row in rows}


def _apply_file_changes(
    connection: sqlite3.Connection,
    state: dict[int, dict[str, Any]],
    snapshot_id: int,
) -> None:
    rows = connection.execute(
        "SELECT * FROM snapshot_file_changes WHERE snapshot_id = ?",
        (snapshot_id,),
    ).fetchall()
    for row in rows:
        artifact_id = int(row["artifact_id"])
        if row["change_kind"] == "delete":
            state.pop(artifact_id, None)
        else:
            state[artifact_id] = dict(row)


def _apply_relationship_changes(
    connection: sqlite3.Connection,
    state: dict[int, int],
    snapshot_id: int,
) -> None:
    rows = connection.execute(
        "SELECT * FROM snapshot_relationship_changes WHERE snapshot_id = ?",
        (snapshot_id,),
    ).fetchall()
    for row in rows:
        source_id = int(row["source_artifact_id"])
        if row["change_kind"] == "retract":
            state.pop(source_id, None)
        else:
            state[source_id] = int(row["relationship_set_id"])


def _insert_checkpoint(
    connection: sqlite3.Connection,
    snapshot_id: int,
    repository_id: int,
    sequence: int,
    source_depth: int,
    files: dict[int, dict[str, Any]],
    relationships: dict[int, int],
) -> None:
    _insert_checkpoint_header(
        connection,
        snapshot_id,
        repository_id,
        sequence,
        source_depth,
        files,
        relationships,
    )
    connection.executemany(
        """
        INSERT INTO checkpoint_files(
            checkpoint_snapshot_id, artifact_id, file_fact_id, path, declared_group,
            inferred_group, analysis_status, first_seen_at, last_changed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [_checkpoint_file_values(snapshot_id, value) for value in files.values()],
    )
    connection.executemany(
        """
        INSERT INTO checkpoint_relationships(
            checkpoint_snapshot_id, source_artifact_id, relationship_set_id
        ) VALUES (?, ?, ?)
        """,
        [(snapshot_id, source_id, set_id) for source_id, set_id in relationships.items()],
    )


def _insert_checkpoint_header(
    connection: sqlite3.Connection,
    snapshot_id: int,
    repository_id: int,
    sequence: int,
    source_depth: int,
    files: dict[int, dict[str, Any]],
    relationships: dict[int, int],
) -> None:
    file_hash, relationship_hash = canonical_state_hashes(files, relationships)
    connection.execute(
        """
        INSERT INTO snapshot_checkpoints(
            snapshot_id, repository_id, sequence, source_delta_depth, file_count,
            relationship_source_count, file_state_hash, relationship_state_hash, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot_id,
            repository_id,
            sequence,
            source_depth,
            len(files),
            len(relationships),
            file_hash,
            relationship_hash,
            datetime.now(UTC).isoformat(),
        ),
    )


def _checkpoint_file_values(snapshot_id: int, value: dict[str, Any]) -> tuple[Any, ...]:
    return (
        snapshot_id,
        value["artifact_id"],
        value["file_fact_id"],
        value["path"],
        value["declared_group"],
        value["inferred_group"],
        value["analysis_status"],
        value["first_seen_at"],
        value["last_changed_at"],
    )


def _file_state_hash(files: dict[int, dict[str, Any]]) -> str:
    fields = (
        "artifact_id",
        "file_fact_id",
        "path",
        "declared_group",
        "inferred_group",
        "analysis_status",
        "first_seen_at",
        "last_changed_at",
    )
    values = sorted(tuple(file.get(field) for field in fields) for file in files.values())
    return digest(values)


def _diagnostics(
    started: float,
    snapshot_id: int | None,
    frames: list[int],
    checkpoint_id: int | None,
    returned_rows: int,
) -> ReconstructionDiagnostics:
    return ReconstructionDiagnostics(
        snapshot_id=snapshot_id,
        traversed_deltas=len(frames),
        checkpoint_snapshot_id=checkpoint_id,
        duration_ms=round((time.perf_counter() - started) * 1_000, 3),
        returned_rows=returned_rows,
    )

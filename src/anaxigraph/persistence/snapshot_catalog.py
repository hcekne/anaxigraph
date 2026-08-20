"""Snapshot catalog and timeline read models over canonical temporal facts."""

from __future__ import annotations

import sqlite3
from typing import Any

from anaxigraph.persistence.temporal_reads import (
    snapshot_files_with_diagnostics,
    snapshot_relationship_edges_with_diagnostics,
)


def read_snapshots(
    connection: sqlite3.Connection,
    repository_id: int,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT s.* FROM snapshots s
        WHERE s.repository_id = ?
        ORDER BY COALESCE(datetime(s.commit_timestamp), s.analysis_timestamp) DESC, s.id DESC
        LIMIT ?
        """,
        (repository_id, limit),
    ).fetchall()
    return [_with_statistics(connection, dict(row)) for row in rows]


def read_timeline(
    connection: sqlite3.Connection,
    repository_id: int,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT s.* FROM snapshots s
        JOIN repositories r ON r.id = s.repository_id
        WHERE s.repository_id = ?
          AND (s.snapshot_kind = 'commit' OR s.id = r.current_snapshot_id)
        ORDER BY COALESCE(datetime(s.commit_timestamp), s.analysis_timestamp), s.id
        """,
        (repository_id,),
    ).fetchall()
    current_row = connection.execute(
        "SELECT current_snapshot_id FROM repositories WHERE id = ?",
        (repository_id,),
    ).fetchone()
    current_id = int(current_row[0]) if current_row and current_row[0] is not None else None
    commit_frames = _merge_current_frame([dict(row) for row in rows], current_id)
    selected = _sample(commit_frames, limit)
    return [_with_statistics(connection, item) for item in selected]


def _with_statistics(
    connection: sqlite3.Connection,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    snapshot_id = int(snapshot["id"])
    files, file_diagnostics = snapshot_files_with_diagnostics(connection, snapshot_id)
    edges, relationship_diagnostics = snapshot_relationship_edges_with_diagnostics(
        connection, snapshot_id
    )
    snapshot.update(
        file_count=len(files),
        lines_of_code=sum(int(file["lines_of_code"] or 0) for file in files),
        relationship_count=len(edges),
        reconstruction={
            "files": file_diagnostics.as_dict(),
            "relationships": relationship_diagnostics.as_dict(),
        },
    )
    return snapshot


def _merge_current_frame(
    rows: list[dict[str, Any]],
    current_id: int | None,
) -> list[dict[str, Any]]:
    commits: list[dict[str, Any]] = []
    indexes: dict[str, int] = {}
    current: dict[str, Any] | None = None
    for item in rows:
        if current_id is not None and int(item["id"]) == current_id:
            current = item
        if item["snapshot_kind"] != "commit":
            continue
        commit_sha = str(item["commit_sha"])
        if commit_sha in indexes:
            commits[indexes[commit_sha]] = item
        else:
            indexes[commit_sha] = len(commits)
            commits.append(item)
    if current is not None:
        _place_current(commits, indexes, current)
    return commits


def _place_current(
    commits: list[dict[str, Any]],
    indexes: dict[str, int],
    current: dict[str, Any],
) -> None:
    same_fingerprint = next(
        (
            index
            for index, frame in enumerate(commits)
            if frame["content_fingerprint"] == current["content_fingerprint"]
        ),
        None,
    )
    same_commit = indexes.get(str(current["commit_sha"]))
    if same_fingerprint is not None:
        commits[same_fingerprint] = current
    elif current.get("dirty") or same_commit is None:
        commits.append(current)
    else:
        commits[same_commit] = current


def _sample(frames: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    bounded = max(1, limit)
    if len(frames) <= bounded:
        return frames
    if bounded == 1:
        return [frames[-1]]
    indexes = {round(index * (len(frames) - 1) / (bounded - 1)) for index in range(bounded)}
    return [frames[index] for index in sorted(indexes)]

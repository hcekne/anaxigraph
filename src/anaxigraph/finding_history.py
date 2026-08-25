"""Bounded introduction, resolution, and recurrence evidence for one finding."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from anaxigraph.architecture_persistence import FINDING_OBSERVATION_VERSION

FINDING_HISTORY_VERSION = "finding-history-v1"

_LINEAGE_SQL = """
WITH RECURSIVE lineage(
    id, base_snapshot_id, sequence, commit_sha, commit_timestamp,
    analysis_timestamp, snapshot_kind, dirty, metadata_json, depth
) AS (
    SELECT snapshot.id, snapshot.base_snapshot_id, snapshot.sequence,
           snapshot.commit_sha, snapshot.commit_timestamp, snapshot.analysis_timestamp,
           snapshot.snapshot_kind, snapshot.dirty, snapshot.metadata_json, 0
    FROM repositories repository
    JOIN snapshots snapshot ON snapshot.id = repository.current_snapshot_id
    WHERE repository.id = ?
    UNION ALL
    SELECT parent.id, parent.base_snapshot_id, parent.sequence, parent.commit_sha,
           parent.commit_timestamp, parent.analysis_timestamp, parent.snapshot_kind,
           parent.dirty, parent.metadata_json, lineage.depth + 1
    FROM snapshots parent JOIN lineage ON parent.id = lineage.base_snapshot_id
    WHERE parent.repository_id = ? AND lineage.depth < 2500
)
SELECT lineage.*,
       EXISTS(SELECT 1 FROM finding_occurrences occurrence
              WHERE occurrence.finding_id = ? AND occurrence.snapshot_id = lineage.id) AS observed,
       (SELECT changes.subject FROM git_changes changes
        WHERE changes.repository_id = ? AND changes.commit_sha = lineage.commit_sha
          AND changes.subject IS NOT NULL LIMIT 1) AS subject
FROM lineage ORDER BY lineage.sequence, lineage.id
"""


def finding_history(
    database: Any,
    repository_id: int,
    finding_id: int,
) -> dict[str, Any]:
    """Explain one finding's lifetime along the current retained snapshot lineage."""

    with database.connect() as connection:
        finding = connection.execute(
            "SELECT id FROM findings WHERE id = ? AND repository_id = ?",
            (finding_id, repository_id),
        ).fetchone()
        if finding is None:
            raise ValueError(f"Finding not found: {finding_id}")
        frames = _finding_lineage(connection, repository_id, finding_id)
    return _history_packet(frames)


def _finding_lineage(
    connection: sqlite3.Connection, repository_id: int, finding_id: int
) -> list[dict[str, Any]]:
    rows = connection.execute(
        _LINEAGE_SQL,
        (repository_id, repository_id, finding_id, repository_id),
    ).fetchall()
    frames = []
    for position, row in enumerate(rows):
        metadata = json.loads(row["metadata_json"] or "{}")
        sha = str(row["commit_sha"] or "unknown")
        subject = str(row["subject"] or "").strip()
        label = f"{subject} ({sha[:8]})" if subject else f"commit {sha[:8]}"
        if row["snapshot_kind"] == "working_tree" and row["dirty"]:
            label = f"current working tree ({sha[:8]})"
        frames.append(
            {
                "snapshot_id": int(row["id"]),
                "commit_sha": sha,
                "label": label,
                "timestamp": row["commit_timestamp"] or row["analysis_timestamp"],
                "snapshot_kind": str(row["snapshot_kind"]),
                "observed": bool(row["observed"]),
                "indexed": metadata.get("finding_observation_version")
                == FINDING_OBSERVATION_VERSION,
                "_position": position,
            }
        )
    return frames


def _history_packet(frames: list[dict[str, Any]]) -> dict[str, Any]:
    indexed = [frame for frame in frames if frame["indexed"]]
    transitions = _transitions(indexed)
    observed = [frame for frame in indexed if frame["observed"]]
    introduction = next(
        (item for item in transitions if item["kind"] in {"introduced", "already_present"}),
        None,
    )
    resolutions = [item for item in transitions if item["kind"] == "resolved"]
    recurrences = [item for item in transitions if item["kind"] == "regressed"]
    state = _state(frames, indexed, observed, introduction, recurrences, resolutions)
    missing = len(frames) - len(indexed)
    status = (
        "not_indexed"
        if not indexed
        else "current_frame_only"
        if len(indexed) == 1
        else "partial_history"
        if missing
        else "available"
    )
    returned = _bounded(transitions)
    return {
        "contract_version": FINDING_HISTORY_VERSION,
        "status": status,
        "state": state,
        "introduction": introduction,
        "resolution": resolutions[-1] if resolutions else None,
        "recurrence": recurrences[-1] if recurrences else None,
        "transitions": returned,
        "work": {
            "retained_frames": len(frames),
            "indexed_frames": len(indexed),
            "observed_frames": len(observed),
            "transition_count": len(transitions),
            "returned_transitions": len(returned),
            "unindexed_frames": missing,
        },
        "plain_language": _language(state, introduction, resolutions, recurrences, missing),
    }


def _transitions(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    previous = None
    seen = False
    for frame in frames:
        if previous is None:
            if frame["observed"]:
                result.append(_transition("already_present", frame, None))
                seen = True
        elif frame["observed"] != previous["observed"]:
            kind = "resolved" if not frame["observed"] else "regressed" if seen else "introduced"
            result.append(_transition(kind, frame, previous))
        seen = seen or frame["observed"]
        previous = frame
    return result


def _transition(
    kind: str, frame: dict[str, Any], previous: dict[str, Any] | None
) -> dict[str, Any]:
    public = {key: value for key, value in frame.items() if not key.startswith("_")}
    prior = (
        {key: value for key, value in previous.items() if not key.startswith("_")}
        if previous
        else None
    )
    adjacent = previous is not None and frame["_position"] - previous["_position"] == 1
    return {
        "kind": kind,
        "frame": public,
        "previous_indexed_frame": prior,
        "precision": "adjacent_retained_frames" if adjacent else "retained_frames_only",
    }


def _state(
    frames: list[dict[str, Any]],
    indexed: list[dict[str, Any]],
    observed: list[dict[str, Any]],
    introduction: dict[str, Any] | None,
    recurrences: list[dict[str, Any]],
    resolutions: list[dict[str, Any]],
) -> str:
    if not frames or not indexed or not frames[-1]["indexed"]:
        return "unknown"
    if not observed:
        return "not_observed"
    if len(indexed) == 1:
        return "history_unavailable"
    if frames[-1]["observed"]:
        if recurrences:
            return "regressed"
        current = {key: value for key, value in frames[-1].items() if not key.startswith("_")}
        if (
            introduction
            and introduction["kind"] == "introduced"
            and introduction["frame"] == current
        ):
            return "new"
        return "persistent"
    return "resolved" if resolutions else "unknown"


def _language(
    state: str,
    introduction: dict[str, Any] | None,
    resolutions: list[dict[str, Any]],
    recurrences: list[dict[str, Any]],
    missing: int,
) -> dict[str, str]:
    first = introduction["frame"]["label"] if introduction else "an indexed frame"
    if state == "resolved":
        conclusion = f"This problem first appears in {first} and is gone by {resolutions[-1]['frame']['label']}."
    elif state == "regressed":
        conclusion = f"This problem disappeared by {resolutions[-1]['frame']['label']} but returned by {recurrences[-1]['frame']['label']}."
    elif state == "new":
        conclusion = f"This problem first appears in the current retained frame, {first}."
    elif state == "persistent":
        conclusion = f"This problem is still present and was already visible in {first}."
    elif state == "not_observed":
        conclusion = (
            "This finding was not seen in any indexed frame on the current retained timeline."
        )
    else:
        conclusion = (
            "There are not enough indexed frames to say when this problem appeared or disappeared."
        )
    limits = "This compares retained code maps, not every Git commit. A change happened after the previous indexed frame and by the named frame."
    if missing:
        limits += f" {missing} retained frame{'s were' if missing != 1 else ' was'} created before finding history was recorded."
    return {"conclusion": conclusion, "limits": limits}


def _bounded(transitions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return transitions if len(transitions) <= 12 else [*transitions[:6], *transitions[-6:]]

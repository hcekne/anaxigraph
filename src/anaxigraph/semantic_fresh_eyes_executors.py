"""Executor pins on a live fresh-eyes review: who a stage waits for, and how to release it."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from anaxigraph.semantic_fresh_eyes_contract import (
    fresh_eyes_plan_executors,
    fresh_eyes_plan_options,
    fresh_eyes_plan_token,
)
from anaxigraph.semantic_fresh_eyes_plan import FRESH_EYES_PLAN_KEY, FRESH_EYES_SCOPE
from anaxigraph.semantic_index_port import SemanticIndex

_PLAN_SQL = (
    "SELECT * FROM semantic_scope_states WHERE snapshot_id = ? AND scope_type = ? AND scope_key = ?"
)
_PINNED_JOBS_SQL = (
    "SELECT id, scope_key, metadata_json FROM semantic_jobs WHERE snapshot_id = ? "
    "AND job_kind = 'fresh_proposal' AND status IN ('pending', 'retry') ORDER BY scope_key"
)
_DONE_STAGE_STATES = frozenset({"current", "superseded"})


def unpin_review_executors(database: SemanticIndex, repository_id: int) -> list[dict[str, str]]:
    """Drop every executor pin of the current review so any executor can finish it.

    ``fresh-eyes --restart`` refuses while a plan is not current, so this is the way out of a
    review whose pinned executor never arrived: every recorded stage is kept and only the
    assignment is removed, from the plan token and from each queued proposal job.
    """

    snapshot = database.latest_snapshot(repository_id)
    if snapshot is None:
        return []
    with database.transaction() as connection:
        return _unpin_plan(connection, int(snapshot["id"]))


def _unpin_plan(connection: sqlite3.Connection, snapshot_id: int) -> list[dict[str, str]]:
    row = connection.execute(_PLAN_SQL, (snapshot_id, FRESH_EYES_SCOPE, FRESH_EYES_PLAN_KEY))
    plan = row.fetchone()
    if plan is None:
        return []
    released = _clear_job_pins(connection, snapshot_id)
    if not fresh_eyes_plan_executors(dict(plan)) and not released:
        return []
    proposal_count, generation = fresh_eyes_plan_options(dict(plan))
    connection.execute(
        "UPDATE semantic_scope_states SET interface_hash = ? "
        "WHERE snapshot_id = ? AND scope_type = ? AND scope_key = ?",
        (
            fresh_eyes_plan_token(proposal_count, generation),
            snapshot_id,
            FRESH_EYES_SCOPE,
            FRESH_EYES_PLAN_KEY,
        ),
    )
    return released


def waiting_executor_action(stages: list[dict[str, Any]]) -> str | None:
    """Name the executor an unfinished pinned stage waits for, and the command that starts it."""

    for stage in stages:
        pinned = str(stage.get("required_executor") or "")
        state = str(stage.get("state") or "waiting")
        if pinned and state not in _DONE_STAGE_STATES:
            return (
                f"Start the pinned {pinned} executor for {str(stage['label']).lower()}: "
                f"anaxigraph understand . --executor {pinned} --until-complete"
            )
    return None


def _clear_job_pins(connection: sqlite3.Connection, snapshot_id: int) -> list[dict[str, str]]:
    released: list[dict[str, str]] = []
    for row in connection.execute(_PINNED_JOBS_SQL, (snapshot_id,)).fetchall():
        metadata = _metadata(row["metadata_json"])
        pinned = str(metadata.get("required_executor") or "")
        if not pinned:
            continue
        metadata["required_executor"] = None
        connection.execute(
            "UPDATE semantic_jobs SET metadata_json = ? WHERE id = ?",
            (json.dumps(metadata, default=str), int(row["id"])),
        )
        released.append({"scope_key": str(row["scope_key"]), "required_executor": pinned})
    return released


def _metadata(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}

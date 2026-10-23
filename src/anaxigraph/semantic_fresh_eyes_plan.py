"""Plan the fixed fresh-eyes recipe on the existing durable semantic queue."""

from __future__ import annotations

import sqlite3
from typing import Any

from anaxigraph.semantic_config_port import SemanticConfig
from anaxigraph.semantic_fresh_eyes_contract import (
    FRESH_EYES_PLAN_KEY,
    FRESH_EYES_SCOPE,
    fresh_eyes_plan_executors,
    fresh_eyes_plan_goal,
    fresh_eyes_plan_options,
    fresh_eyes_plan_token,
)
from anaxigraph.semantic_fresh_eyes_jobs import upsert_state


class FreshEyesPlanner:
    """Advance one explicitly requested review; never start model work on its own."""

    def request(
        self,
        connection: sqlite3.Connection,
        *,
        repository_id: int,
        snapshot_id: int,
        proposal_count: int,
        generation: int = 1,
        proposal_executors: tuple[str, ...] = (),
        goal: str = "",
    ) -> bool:
        from anaxigraph.semantic_fresh_eyes_functional import (
            SemanticAnalysisError,
            assert_functional,
            is_functional_plan,
        )

        try:
            assert_functional({"functional_direction": goal})
        except SemanticAnalysisError as error:
            raise ValueError(
                "Fresh Eyes direction must describe required behavior without source paths; "
                "use Architecture Planning for implementation-specific direction"
            ) from error
        if proposal_count not in {1, 2, 3, 5}:
            raise ValueError("Fresh Eyes retains three alternatives or explores five sketches")
        if proposal_count < 3 and len(proposal_executors) == proposal_count:
            proposal_executors = (*proposal_executors, *("any",) * (3 - proposal_count))
        proposal_count = max(3, proposal_count)
        existing = _plan_state(connection, snapshot_id)
        if existing is not None and is_functional_plan(existing):
            if goal != fresh_eyes_plan_goal(existing):
                _update_goal(connection, snapshot_id, existing, goal)
            return False
        if existing is not None:
            generation = max(generation, fresh_eyes_plan_options(existing)[1] + 1)
            _retire_legacy_work(connection, snapshot_id)
        token = fresh_eyes_plan_token(proposal_count, generation, proposal_executors, goal=goal)
        upsert_state(
            connection,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            scope_type=FRESH_EYES_SCOPE,
            scope_key=FRESH_EYES_PLAN_KEY,
            status="requested",
            reason="Fresh-eyes review requested; waiting for current repository understanding",
            interface_hash=token,
        )
        return True

    def plan_active(
        self,
        connection: sqlite3.Connection,
        *,
        repository_id: int,
        snapshot_id: int,
        semantic: SemanticConfig,
        retry_failed: bool,
    ) -> tuple[int, str | None]:
        plan = _plan_state(connection, snapshot_id)
        if plan is None:
            return 0, None
        from anaxigraph.semantic_fresh_eyes_functional import is_functional_plan
        from anaxigraph.semantic_fresh_eyes_functional_plan import plan_functional

        if is_functional_plan(plan):
            count, generation = fresh_eyes_plan_options(plan)
            return plan_functional(
                connection,
                {
                    "repository_id": repository_id,
                    "snapshot_id": snapshot_id,
                    "proposal_count": count,
                    "generation": generation,
                    "proposal_executors": fresh_eyes_plan_executors(plan),
                    "goal": fresh_eyes_plan_goal(plan),
                    "semantic": semantic,
                    "retry_failed": retry_failed,
                },
            )
        if plan["status"] != "current":
            self.request(
                connection,
                repository_id=repository_id,
                snapshot_id=snapshot_id,
                proposal_count=3,
                generation=fresh_eyes_plan_options(plan)[1] + 1,
                goal="",
            )
            return self.plan_active(
                connection,
                repository_id=repository_id,
                snapshot_id=snapshot_id,
                semantic=semantic,
                retry_failed=retry_failed,
            )
        return 0, "fresh_eyes_complete"


def _update_goal(connection, snapshot_id, plan, goal):
    count, generation = fresh_eyes_plan_options(plan)
    token = fresh_eyes_plan_token(count, generation + 1, fresh_eyes_plan_executors(plan), goal=goal)
    connection.execute(
        "UPDATE semantic_jobs SET status='superseded',error='Functional direction changed' "
        "WHERE snapshot_id=? AND scope_type='fresh_eyes' AND status IN ('pending','retry','running')",
        (snapshot_id,),
    )
    connection.execute(
        "DELETE FROM semantic_scope_states WHERE snapshot_id=? AND scope_type='fresh_eyes' "
        "AND scope_key!='plan'",
        (snapshot_id,),
    )
    connection.execute(
        "UPDATE semantic_scope_states SET interface_hash = ?, status = 'requested', "
        "context_document_id = NULL, reason = 'New functional brief revision requested' "
        "WHERE snapshot_id = ? AND scope_type = ? AND scope_key = ?",
        (token, snapshot_id, FRESH_EYES_SCOPE, FRESH_EYES_PLAN_KEY),
    )


def _retire_legacy_work(connection: Any, snapshot_id: int) -> None:
    connection.execute(
        "UPDATE semantic_jobs SET status='superseded',error='Replaced by functional Fresh Eyes v2' "
        "WHERE snapshot_id=? AND scope_type='fresh_eyes' AND scope_key NOT LIKE 'functional:%' "
        "AND status IN ('pending','retry','running')",
        (snapshot_id,),
    )


def _plan_state(connection: sqlite3.Connection, snapshot_id: int) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT * FROM semantic_scope_states WHERE snapshot_id = ? AND scope_type = ? "
        "AND scope_key = ?",
        (snapshot_id, FRESH_EYES_SCOPE, FRESH_EYES_PLAN_KEY),
    ).fetchone()
    return dict(row) if row else None

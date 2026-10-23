"""High-level status and explicit start operation for the fixed architecture review."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import partial
from pathlib import Path
from typing import Any

from anaxigraph.semantic_fresh_eyes_consensus import compare_generations
from anaxigraph.semantic_fresh_eyes_contract import (
    fresh_eyes_plan_goal,
    fresh_eyes_plan_options,
)
from anaxigraph.semantic_fresh_eyes_executors import (
    unpin_review_executors,
    waiting_executor_action,
)
from anaxigraph.semantic_fresh_eyes_generations import (
    generation_payload,
    list_generations,
    select_generation,
)
from anaxigraph.semantic_fresh_eyes_grounding import with_grounding
from anaxigraph.semantic_fresh_eyes_payload import (
    missing_review,
    not_started_payload,
)
from anaxigraph.semantic_fresh_eyes_plan import (
    FRESH_EYES_PLAN_KEY,
    FRESH_EYES_SCOPE,
    FreshEyesPlanner,
)
from anaxigraph.semantic_index_port import SemanticIndex
from anaxigraph.semantic_ports import (
    AnaxiGraphConfig,
    SemanticConfig,
    SemanticPlanningPort,
    SemanticReportingPort,
)
from anaxigraph.snapshot_provenance import dirty_snapshot_caveat, snapshot_provenance

_PLAN_ROW_SQL = (
    "SELECT * FROM semantic_scope_states WHERE snapshot_id = ? AND scope_type = ? AND scope_key = ?"
)


class FreshEyesReviewService:
    def __init__(
        self,
        database: SemanticIndex,
        planner: FreshEyesPlanner,
        planning: SemanticPlanningPort,
        reporting: SemanticReportingPort,
    ) -> None:
        self._database = database
        self._planner = planner
        self._planning = planning
        self._reporting = reporting

    def start(
        self,
        repository_id: int,
        repository: str | Path,
        config: AnaxiGraphConfig,
        *,
        proposal_count: int = 3,
        proposal_executors: Sequence[str] = (),
        retry_failed: bool = False,
        restart: bool = False,
        plan: bool = True,
        goal: str | None = None,
    ) -> dict[str, Any]:
        """Start or resume functional review. Executor pins apply to new generations;
        changing requirements refreshes affected functional scopes.
        """

        semantic = _review_semantic(config)
        snapshot = self._database.latest_snapshot(repository_id)
        if snapshot is None:
            raise ValueError("Repository has not been scanned")
        snapshot_id = int(snapshot["id"])
        with self._database.transaction() as connection:
            goal = _requested_goal(connection, repository_id, snapshot_id, goal)
            generation = _requested_generation(
                connection, repository_id, snapshot_id, restart=restart
            )
            created = self._planner.request(
                connection,
                repository_id=repository_id,
                snapshot_id=snapshot_id,
                proposal_count=proposal_count,
                generation=generation,
                proposal_executors=tuple(proposal_executors),
                goal=goal,
            )
        stage, enqueued = self._plan_outcome(
            repository_id, repository, config, plan=plan, retry_failed=retry_failed
        )
        return {
            "status": "restarted"
            if restart and created
            else "started"
            if created
            else "already_started",
            "plan_stage": stage,
            "enqueued": enqueued,
            "review": self.status(repository_id, semantic),
        }

    def _plan_outcome(
        self,
        repository_id: int,
        repository: str | Path,
        config: AnaxiGraphConfig,
        *,
        plan: bool,
        retry_failed: bool,
    ) -> tuple[str, int]:
        """Plan the queue now, or report a deferred stage for the next claim to consume.

        A deferred request is picked up by ``plan_active`` during the next
        ``claim_agent_work`` call that finds the queue otherwise empty, so a busy
        queue keeps the request ``requested`` until it drains.
        """

        if not plan:
            return "deferred", 0
        planned = self._planning.plan(
            repository_id,
            repository,
            config,
            retry_failed=retry_failed,
        )
        return planned.stage, planned.enqueued

    def unpin(self, repository_id: int, semantic: SemanticConfig | None = None) -> dict[str, Any]:
        """Let any executor finish a review whose pinned executor never arrived."""

        released = unpin_review_executors(self._database, repository_id)
        return {
            "status": "unpinned" if released else "not_pinned",
            "unpinned": released,
            "review": self.status(repository_id, semantic),
        }

    def status(
        self,
        repository_id: int,
        semantic: SemanticConfig | None = None,
        *,
        generation: int | None = None,
        compare_with: int | None = None,
        scope_id: str = "",
        details: bool = True,
    ) -> dict[str, Any]:
        """Read the current review, one recorded generation, or two generations side by side."""

        snapshot = self._database.latest_snapshot(repository_id)
        if snapshot is None:
            return missing_review(repository_id)
        snapshot_id = int(snapshot["id"])
        semantic_status = self._reporting.status(repository_id, semantic)
        with self._database.connect() as connection:
            generations = list_generations(connection, repository_id, snapshot_id)
            row = connection.execute(
                _PLAN_ROW_SQL, (snapshot_id, FRESH_EYES_SCOPE, FRESH_EYES_PLAN_KEY)
            ).fetchone()
            read = partial(
                _generation_view,
                connection,
                repository_id,
                snapshot_id,
                dict(row) if row is not None else None,
                semantic_status,
                generations,
                snapshot,
                scope_id=scope_id,
                details=details,
            )
            payload = read(generation)
            if compare_with is None:
                return payload
            return {**payload, "alignment": compare_generations(payload, read(compare_with))}


def _generation_view(
    connection: Any,
    repository_id: int,
    snapshot_id: int,
    plan: dict[str, Any] | None,
    semantic_status: dict[str, Any],
    generations: list[dict[str, Any]],
    snapshot: Mapping[str, Any],
    generation: int | None,
    *,
    scope_id: str = "",
    details: bool = True,
) -> dict[str, Any]:
    """Build the payload of the requested recorded generation, or of the current review.

    Only payloads read from the current snapshot carry its provenance; a recorded generation
    may come from an earlier snapshot and must not be labelled with today's checkout.
    """

    if generation is not None and not _selects_current(plan, generation):
        recorded = generation_payload(
            connection,
            repository_id,
            select_generation(generations, generation),
            generations,
            semantic_status,
            scope_id=scope_id,
            details=details,
        )
        return with_grounding(connection, recorded, review_id=_review_document(recorded))
    if plan is None:
        return _with_snapshot_provenance(
            not_started_payload(repository_id, snapshot_id, semantic_status, generations),
            snapshot,
        )
    return _with_snapshot_provenance(
        _current_review(
            connection,
            repository_id,
            snapshot_id,
            plan,
            semantic_status,
            generations,
            scope_id=scope_id,
            details=details,
        ),
        snapshot,
    )


def _review_semantic(config: AnaxiGraphConfig) -> SemanticConfig:
    """Refuse a review the connected coding agent cannot fund."""

    semantic = config.semantic
    if not semantic.enabled:
        raise ValueError("Build AI understanding before starting a fresh-eyes review")
    if semantic.provider != "agent":
        raise ValueError(
            "Fresh-eyes review uses the connected coding agent's tokens; set semantic.provider: agent"
        )
    return semantic


def _with_snapshot_provenance(
    payload: dict[str, Any], snapshot: Mapping[str, Any]
) -> dict[str, Any]:
    """Name the checkout this review was read from, and warn when it was not committed."""

    provenance_block = snapshot_provenance(snapshot)
    payload["snapshot"] = provenance_block
    caveat = dirty_snapshot_caveat(provenance_block)
    if caveat:
        payload["caveats"] = [caveat, *payload.get("caveats", [])]
    return payload


def _review_document(payload: dict[str, Any]) -> Any:
    stage = next((item for item in payload["stages"] if item["key"] == "review"), None)
    return (stage or {}).get("document_id")


def _selects_current(plan: dict[str, Any] | None, generation: int) -> bool:
    return plan is not None and fresh_eyes_plan_options(plan)[1] == int(generation)


def _current_review(
    connection: Any,
    repository_id: int,
    snapshot_id: int,
    plan: dict[str, Any],
    semantic_status: dict[str, Any],
    generations: list[dict[str, Any]],
    *,
    scope_id: str = "",
    details: bool = True,
) -> dict[str, Any]:
    result = _functional_view(
        connection, repository_id, snapshot_id, plan, generations, scope_id, details
    )
    if result is not None:
        return result
    if not any(item["generation"] == fresh_eyes_plan_options(plan)[1] for item in generations):
        return not_started_payload(repository_id, snapshot_id, semantic_status, generations)
    return with_grounding(
        connection,
        generation_payload(
            connection,
            repository_id,
            select_generation(generations, fresh_eyes_plan_options(plan)[1]),
            generations,
            semantic_status,
            details=details,
        ),
        review_id=plan.get("context_document_id"),
    )


def _functional_view(connection, repository_id, snapshot_id, plan, generations, scope_id, details):
    from anaxigraph.semantic_fresh_eyes_functional_read import (
        apply_bundle_status,
        requested_functional_status,
    )

    result = requested_functional_status(
        connection, repository_id, snapshot_id, plan, scope_id=scope_id, details=details
    )
    if result is not None:
        result["generations"] = generations
        result["review_goal"] = fresh_eyes_plan_goal(plan)
        current = next(
            (
                item
                for item in generations
                if item["snapshot_id"] == snapshot_id
                and item["generation"] == result["review_generation"]
            ),
            None,
        )
        apply_bundle_status(result, current)
        result["next_action"] = waiting_executor_action(result["stages"]) or result["next_action"]
        return result
    return None


def _requested_goal(connection, repository_id, snapshot_id, goal):
    if goal is not None:
        if len(goal) > 4_000:
            raise ValueError("Review goal must be at most 4,000 characters")
        return goal.strip()
    prior = connection.execute(
        "SELECT interface_hash FROM semantic_scope_states WHERE repository_id = ? "
        "AND snapshot_id <= ? AND scope_type = ? AND scope_key = ? ORDER BY snapshot_id DESC LIMIT 1",
        (repository_id, snapshot_id, FRESH_EYES_SCOPE, FRESH_EYES_PLAN_KEY),
    ).fetchone()
    return (
        fresh_eyes_plan_goal(dict(prior))
        if prior and str(prior["interface_hash"] or "").startswith("functional-v2|")
        else ""
    )


def _requested_generation(
    connection: Any, repository_id: int, snapshot_id: int, *, restart: bool
) -> int:
    plan = connection.execute(
        _PLAN_ROW_SQL, (snapshot_id, FRESH_EYES_SCOPE, FRESH_EYES_PLAN_KEY)
    ).fetchone()
    if (
        plan is not None
        and restart
        and str(plan["status"]) != "current"
        and str(plan["interface_hash"] or "").startswith("functional-v2|")
    ):
        raise ValueError("Finish or retry the current fresh-eyes review before requesting a rerun")
    prior = (
        plan
        or connection.execute(
            "SELECT * FROM semantic_scope_states WHERE repository_id = ? AND snapshot_id != ? "
            "AND scope_type = ? AND scope_key = ? AND status = 'current' "
            "ORDER BY snapshot_id DESC LIMIT 1",
            (repository_id, snapshot_id, FRESH_EYES_SCOPE, FRESH_EYES_PLAN_KEY),
        ).fetchone()
    )
    if prior is None:
        if restart:
            raise ValueError("Start the first fresh-eyes review before requesting a rerun")
        return 1
    _proposal_count, generation = fresh_eyes_plan_options(dict(prior))
    if restart and plan is not None:
        connection.execute(
            "DELETE FROM semantic_scope_states WHERE snapshot_id = ? AND scope_type = ?",
            (snapshot_id, FRESH_EYES_SCOPE),
        )
    legacy = not str(prior["interface_hash"] or "").startswith("functional-v2|")
    return generation + 1 if restart or legacy else generation

"""Atomic persistence operations for selected history frames."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from anaxigraph.persistence.temporal_facts import rebase_snapshot_facts
from anaxigraph.scan_commit import refresh_historical_snapshot_intelligence


def rebase_existing_snapshot(
    database: Any,
    *,
    snapshot_id: int,
    base_snapshot_id: int | None,
) -> None:
    """Attach a reused frame to the selected first-parent lineage atomically."""

    with database.transaction() as connection:
        rebase_snapshot_facts(
            connection,
            snapshot_id=snapshot_id,
            base_snapshot_id=base_snapshot_id,
        )


def materialize_revision(context: Any, state: Any, commit_sha: str) -> bool:
    """Reuse/rebase a compatible frame or scan the selected revision."""

    existing = context.database.commit_snapshot(
        context.plan.repository_id,
        commit_sha,
        context.plan.signature,
    )
    if existing is not None:
        rebase_existing_snapshot(
            context.database,
            snapshot_id=int(existing["id"]),
            base_snapshot_id=state.baseline_snapshot_id,
        )
        refresh_historical_snapshot_intelligence(
            context.database,
            repository_id=context.plan.repository_id,
            snapshot_id=int(existing["id"]),
            config=context.plan.config,
        )
        state.baseline_snapshot_id = int(existing["id"])
        return True
    stats = context.scanner.scan(
        context.root,
        config_path=context.config_path,
        revision=commit_sha,
        run_type="history",
        baseline_snapshot_id=state.baseline_snapshot_id,
        previous_revision=state.baseline_revision,
    )
    state.baseline_snapshot_id = stats.snapshot_id
    add_frame_work(state.work, context.database, stats)
    return False


def add_frame_work(work: dict[str, Any], database: Any, stats: Any) -> None:
    """Accumulate auditable discovery and invalidation counters for one frame."""

    with database.connect() as connection:
        run = connection.execute(
            "SELECT metadata_json FROM analysis_runs WHERE id = ?",
            (stats.analysis_run_id,),
        ).fetchone()
    metadata = json.loads(run["metadata_json"] or "{}") if run else {}
    for key in (
        "source_reads",
        "carried_forward",
        "relationship_sources_resolved",
        "relationship_sources_reused",
        "relationships_copied",
    ):
        work[key] += int(metadata.get(key) or 0)
    work["analyzed_files"] += stats.analyzed
    work["reused_analysis"] += stats.reused
    reasons = Counter(metadata.get("invalidation_reasons") or {})
    total_reasons = Counter(work["invalidation_reasons"])
    total_reasons.update(reasons)
    work["invalidation_reasons"] = dict(sorted(total_reasons.items()))

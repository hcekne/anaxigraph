"""Recovery state for a nonterminal remote semantic queue with no claimable work."""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from anaxigraph.semantic_service import SemanticServiceTarget, prepare_semantic_service


class IdleRecovery:
    """Prepare once when an until-complete queue is nonterminal but unclaimable."""

    def __init__(self, target: SemanticServiceTarget, retry_failed: bool) -> None:
        self.target = target
        self.retry_failed = retry_failed
        self.snapshot_id: int | None = None
        self.polls = 0
        self.refreshed: set[int] = set()

    def reset(self) -> None:
        self.snapshot_id = None
        self.polls = 0

    async def recover(self, state: str, semantic: dict[str, Any]) -> dict[str, Any] | None:
        if not _stranded_queue(state, semantic):
            self.reset()
            return None
        snapshot_id = int(semantic.get("snapshot_id") or 0)
        if self.snapshot_id != snapshot_id:
            self.snapshot_id = snapshot_id
            self.polls = 0
        self.polls += 1
        if self.polls < 3:
            return None
        if snapshot_id in self.refreshed:
            jobs = semantic.get("jobs") or {}
            raise RuntimeError(
                "Semantic queue remained nonterminal with no claimable work after a synchronous "
                f"prepare (snapshot={snapshot_id}, pending={semantic.get('pending', 0)}, "
                f"retry={jobs.get('retry', 0)}, running={jobs.get('running', 0)})."
            )
        try:
            prepared = await asyncio.to_thread(
                prepare_semantic_service,
                self.target,
                force=False,
                retry_failed=self.retry_failed,
            )
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"Could not recover the stranded semantic queue: {exc}") from exc
        self.refreshed.add(snapshot_id)
        self.reset()
        print(
            f"Semantic queue was stranded at snapshot {snapshot_id}; prepared the next stage.",
            file=sys.stderr,
            flush=True,
        )
        return prepared


def _stranded_queue(state: str, semantic: dict[str, Any]) -> bool:
    jobs = semantic.get("jobs") or {}
    active = sum(int(jobs.get(key, 0)) for key in ("pending", "retry", "running"))
    return bool(
        state == "waiting"
        and not semantic.get("semantically_ready")
        and not (semantic.get("budget") or {}).get("paused")
        and active == 0
    )

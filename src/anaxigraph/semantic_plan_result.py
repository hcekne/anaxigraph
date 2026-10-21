"""The stable result of planning one semantic queue pass."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from anaxigraph.semantic_status_language import semantic_work_plan


@dataclass(frozen=True, slots=True)
class SemanticPlan:
    repository_id: int
    snapshot_id: int
    enqueued: int
    active_jobs: int
    stage: str
    status: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "repository_id": self.repository_id,
            "snapshot_id": self.snapshot_id,
            "enqueued": self.enqueued,
            "active_jobs": self.active_jobs,
            "stage": self.stage,
            "work_plan": self.work_plan(),
            "semantic": self.status,
        }

    def work_plan(self) -> dict[str, Any]:
        return semantic_work_plan(
            self.status,
            stage=self.stage,
            new_jobs=self.enqueued,
            active_jobs=self.active_jobs,
        )

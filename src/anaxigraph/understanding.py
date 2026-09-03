"""Stable semantic facade over explicit, independently testable services."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from anaxigraph.config import AnaxiGraphConfig, SemanticConfig
from anaxigraph.semantic_index_port import SemanticIndex
from anaxigraph.semantic_scope_plan import SemanticPlan
from anaxigraph.semantic_services import SemanticServices, build_semantic_services

__all__ = ["SemanticEngine", "SemanticPlan"]


class SemanticEngine:
    """Compatibility facade preserving the CLI, REST, and MCP semantic protocol."""

    def __init__(self, database: SemanticIndex) -> None:
        self._services: SemanticServices = build_semantic_services(database)

    def plan(
        self,
        repository_id: int,
        repository: str | Path,
        config: AnaxiGraphConfig,
        *,
        force: bool = False,
        retry_failed: bool = False,
    ) -> SemanticPlan:
        return self._services.planning.plan(
            repository_id,
            repository,
            config,
            force=force,
            retry_failed=retry_failed,
        )

    def run_jobs(
        self,
        repository_id: int,
        repository: str | Path,
        config: AnaxiGraphConfig,
        *,
        limit: int | None = None,
        execution_semantic: SemanticConfig | None = None,
    ) -> dict[str, Any]:
        return self._services.runner.run_jobs(
            repository_id,
            repository,
            config,
            limit=limit,
            execution_semantic=execution_semantic,
        )

    def bootstrap(
        self,
        repository_id: int,
        repository: str | Path,
        config: AnaxiGraphConfig,
        *,
        limit: int | None = None,
        force: bool = False,
        retry_failed: bool = False,
        plan_only: bool = False,
        execution_semantic: SemanticConfig | None = None,
        until_complete: bool = False,
    ) -> dict[str, Any]:
        return self._services.runner.bootstrap(
            repository_id,
            repository,
            config,
            limit=limit,
            force=force,
            retry_failed=retry_failed,
            plan_only=plan_only,
            execution_semantic=execution_semantic,
            until_complete=until_complete,
            run_jobs=self.run_jobs,
        )

    def status(
        self,
        repository_id: int,
        semantic: SemanticConfig | None = None,
    ) -> dict[str, Any]:
        return self._services.reporting.status(repository_id, semantic)

    def dossier(
        self,
        repository_id: int,
        path: str,
        snapshot_id: int | None = None,
    ) -> dict[str, Any] | None:
        return self._services.reporting.dossier(repository_id, path, snapshot_id)

    def fresh_eyes_status(
        self,
        repository_id: int,
        semantic: SemanticConfig | None = None,
        *,
        generation: int | None = None,
        compare_with: int | None = None,
    ) -> dict[str, Any]:
        return self._services.fresh_eyes.status(
            repository_id, semantic, generation=generation, compare_with=compare_with
        )

    def start_fresh_eyes_review(
        self,
        repository_id: int,
        repository: str | Path,
        config: AnaxiGraphConfig,
        *,
        proposal_count: int = 2,
        retry_failed: bool = False,
        restart: bool = False,
        plan: bool = True,
    ) -> dict[str, Any]:
        return self._services.fresh_eyes.start(
            repository_id,
            repository,
            config,
            proposal_count=proposal_count,
            retry_failed=retry_failed,
            restart=restart,
            plan=plan,
        )

    def claim_agent_work(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self._services.agent.claim_agent_work(*args, **kwargs)

    def agent_evidence_page(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self._services.agent.agent_evidence_page(*args, **kwargs)

    def submit_agent_work(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self._services.agent.submit_agent_work(*args, **kwargs)

    def release_agent_work(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self._services.agent.release_agent_work(*args, **kwargs)

    def fail_agent_work(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self._services.agent.fail_agent_work(*args, **kwargs)

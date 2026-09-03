"""Narrow structural interfaces shared by composed semantic services."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Protocol

from anaxigraph.semantic import SemanticResult
from anaxigraph.semantic_config_port import AnaxiGraphConfig as AnaxiGraphConfig
from anaxigraph.semantic_config_port import SemanticConfig as SemanticConfig
from anaxigraph.semantic_index_port import SemanticIndex as SemanticIndex


class SemanticReportingPort(Protocol):
    def status(
        self, repository_id: int, semantic: SemanticConfig | None = None
    ) -> dict[str, Any]: ...


class SemanticPlanningPort(Protocol):
    def plan(
        self,
        repository_id: int,
        repository: str | Path,
        config: AnaxiGraphConfig,
        *,
        force: bool = False,
        retry_failed: bool = False,
    ) -> Any: ...


class SemanticPatternPlanningPort(Protocol):
    def plan_patterns(
        self,
        connection: sqlite3.Connection,
        *,
        repository_id: int,
        snapshot_id: int,
        semantic: SemanticConfig,
        retry_failed: bool,
    ) -> tuple[int, bool]: ...


class SemanticFreshEyesPlanningPort(Protocol):
    def plan_active(
        self,
        connection: sqlite3.Connection,
        *,
        repository_id: int,
        snapshot_id: int,
        semantic: SemanticConfig,
        retry_failed: bool,
    ) -> tuple[int, str | None]: ...


class SemanticEvidencePort(Protocol):
    def job_request(
        self, job: dict[str, Any], root: Path, semantic: SemanticConfig
    ) -> dict[str, Any]: ...


class SemanticPersistencePort(Protocol):
    def complete_job(
        self,
        job: dict[str, Any],
        result: SemanticResult,
        provider: str,
        semantic: SemanticConfig,
    ) -> None: ...

    def fail_job(
        self,
        job: dict[str, Any],
        exc: Exception,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> bool: ...

    def mark_superseded(self, job_id: int, reason: str) -> None: ...

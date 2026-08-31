"""Shared dependencies and repository selection for REST route modules."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException

import anaxigraph.api_support as api_support
from anaxigraph.api_operation_gate import RepositoryOperationGate
from anaxigraph.api_semantic import SemanticRefreshCoordinator
from anaxigraph.index_authority import IndexWriteAuthority
from anaxigraph.repository_watch import RepositoryWatchService


@dataclass(frozen=True, slots=True)
class ApiContext:
    database: Any
    targets: tuple[Any, ...]
    default_repository: Path | None
    history_service: Any
    semantic_refresh: Any
    scan_coordinator: Any
    config_loader: Any
    operation_gate: Any
    write_authority: Any
    watch_service: Any | None

    def target_for_path(self, path: Path) -> Any | None:
        resolved = path.resolve()
        return next(
            (target for target in self.targets if target.path.resolve() == resolved),
            None,
        )

    def visible_repositories(self) -> list[dict[str, Any]]:
        rows = self.database.repositories()
        if self.targets:
            rows = [row for row in rows if self.target_for_path(Path(row["path"])) is not None]
        return rows

    def selected_repository(self, repository_id: int | None = None) -> dict[str, Any]:
        row = self._selected_row(repository_id)
        if row is None:
            raise HTTPException(status_code=404, detail="No analyzed repository found")
        if self.targets and self.target_for_path(Path(row["path"])) is None:
            raise HTTPException(status_code=404, detail="Repository is not in the active registry")
        return row

    def selected_config(self, row: dict[str, Any]):
        row_path = Path(row["path"]).resolve()
        target = self.target_for_path(row_path)
        return (
            self.config_loader(target.path, target.config_path)
            if target
            else self.config_loader(row_path)
        )

    def admit_operation(
        self,
        repository_id: int,
        operation: str,
        *,
        hold: bool,
        cooldown_seconds: float = 5,
    ) -> None:
        admission = self.operation_gate.acquire(
            repository_id,
            operation,
            cooldown_seconds=cooldown_seconds,
            hold=hold,
        )
        if admission.allowed:
            return
        retry_after = max(1, int(admission.retry_after_seconds) + 1)
        raise HTTPException(
            status_code=409 if admission.reason == "already_running" else 429,
            detail=f"{operation} is {admission.reason.replace('_', ' ')}",
            headers={"Retry-After": str(retry_after)},
        )

    def finish_operation(self, repository_id: int, operation: str) -> None:
        self.operation_gate.release(repository_id, operation)

    def _selected_row(self, repository_id: int | None) -> dict[str, Any] | None:
        if repository_id:
            return self.database.repository(repository_id)
        if self.default_repository:
            return self.database.repository(self.default_repository)
        return self.database.repository()


def build_api_context(
    database: Any,
    targets: tuple[Any, ...],
    default_repository: Path | None,
    watch_interval: float | None,
) -> ApiContext:
    """Compose one shared runtime context for every server adapter."""

    history_service = api_support.HistoryJobService(database)
    semantic_refresh = SemanticRefreshCoordinator(database)
    return ApiContext(
        database=database,
        targets=targets,
        default_repository=default_repository,
        history_service=history_service,
        semantic_refresh=semantic_refresh,
        scan_coordinator=api_support.ScanCoordinator(database),
        config_loader=api_support.load_config,
        operation_gate=RepositoryOperationGate(),
        write_authority=IndexWriteAuthority(database.path),
        watch_service=(
            RepositoryWatchService(
                database,
                targets,
                interval_seconds=watch_interval,
                scanner_factory=api_support.RepositoryScanner,
                config_loader=api_support.load_config,
                semantic_factory=api_support.SemanticEngine,
                history_service=history_service,
            )
            if watch_interval is not None
            else None
        ),
    )

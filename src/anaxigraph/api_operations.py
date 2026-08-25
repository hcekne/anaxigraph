"""Local server health, scan admission, and bounded export routes."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

import anaxigraph.api_support as api_support
from anaxigraph.bounded_export import bounded_export
from anaxigraph.operational_health import operational_health


def operations_router(context: Any) -> APIRouter:
    return OperationsRoutes(context).router


class OperationsRoutes:
    def __init__(self, context: Any) -> None:
        self.context = context
        self.router = APIRouter()
        self.router.add_api_route("/healthz", self.healthz, methods=["GET"])
        self.router.add_api_route("/api/health", self.health, methods=["GET"])
        self.router.add_api_route("/api/scan", self.scan, methods=["POST"])
        self.router.add_api_route("/api/export", self.export, methods=["GET"])

    def healthz(self) -> dict[str, str]:
        try:
            with self.context.database.connect() as connection:
                connection.execute("SELECT 1").fetchone()
        except sqlite3.Error as exc:
            raise HTTPException(status_code=503, detail="AnaxiIndex unavailable") from exc
        return {"status": "ok"}

    def health(self) -> dict[str, Any]:
        try:
            return operational_health(self.context.database, self.context.operation_gate)
        except sqlite3.Error as exc:
            raise HTTPException(status_code=503, detail="AnaxiIndex unavailable") from exc

    async def scan(self, repository_id: int | None = None) -> dict[str, Any]:
        row = self.context.selected_repository(repository_id)
        target = self.context.target_for_path(Path(row["path"]))
        if target is None:
            raise HTTPException(
                status_code=403,
                detail="This indexed repository is read-only in the current server process",
            )
        repository_id = int(row["id"])
        self.context.admit_operation(repository_id, "scan", hold=True)
        try:
            stats = await asyncio.to_thread(
                api_support.RepositoryScanner(self.context.database).scan,
                target.path,
                config_path=target.config_path,
            )
        finally:
            self.context.finish_operation(repository_id, "scan")
        config = self.context.selected_config(row)
        if config.semantic.enabled and config.semantic.refresh == "on_scan":
            self.context.semantic_refresh.start(target)
        return stats.as_dict()

    def export(self, repository_id: int | None = None) -> dict[str, Any]:
        row = self.context.selected_repository(repository_id)
        repository_id = int(row["id"])
        return bounded_export(
            self.context.database,
            repository_id,
            self.context.selected_config(row),
        )

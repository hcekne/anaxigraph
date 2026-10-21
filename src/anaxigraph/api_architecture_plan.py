"""Saved architecture targets, optional steering and explicit repository record publication."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from anaxigraph.architecture_plan_read import architecture_plan_status, steer_plan
from anaxigraph.planning_service import prepare_architecture_plan
from anaxigraph.portable_record import load_record, record_status, save_record


class PlanningRequest(BaseModel):
    repository_id: int | None = None
    start: bool = False
    direction: str = Field(default="", max_length=4000)
    option: str = Field(default="", max_length=200)
    milestone: str = Field(default="", max_length=200)
    status: Literal["", "pending", "in_progress", "verified"] = ""
    evidence: list[str] = Field(default_factory=list, max_length=30)
    actor: Literal["user", "agent"] = "user"


def architecture_plan_router(context: Any) -> APIRouter:
    routes = ArchitecturePlanRoutes(context)
    router = APIRouter()
    router.add_api_route("/api/architecture-plan", routes.status, methods=["GET"])
    router.add_api_route("/api/architecture-plan", routes.update, methods=["POST"])
    router.add_api_route("/api/record/save", routes.save, methods=["POST"])
    router.add_api_route("/api/record/status", routes.record_status, methods=["GET"])
    router.add_api_route("/api/record/load", routes.load, methods=["POST"])
    return router


class ArchitecturePlanRoutes:
    def __init__(self, context: Any) -> None:
        self.context = context

    def status(self, repository_id: int | None = None, details: bool = True) -> dict[str, Any]:
        row = self.context.selected_repository(repository_id)
        return architecture_plan_status(self.context.database, int(row["id"]), details=details)

    def update(self, request: PlanningRequest) -> dict[str, Any]:
        row = self.context.selected_repository(request.repository_id)
        self._mounted(row)
        repository_id = int(row["id"])
        try:
            if request.start:
                config = self.context.selected_config(row)
                prepare_architecture_plan(
                    self.context.database, repository_id, row["path"], config, request.direction
                )
            if request.option or request.milestone:
                return steer_plan(
                    self.context.database,
                    repository_id,
                    option=request.option,
                    milestone=request.milestone,
                    status=request.status,
                    evidence=request.evidence,
                    actor=request.actor,
                )
            return architecture_plan_status(self.context.database, repository_id)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    def save(self, repository_id: int | None = None) -> dict[str, Any]:
        row = self.context.selected_repository(repository_id)
        self._mounted(row)
        try:
            return save_record(self.context.database, int(row["id"]))
        except (ValueError, OSError) as error:
            raise HTTPException(400, str(error)) from error

    def record_status(self, repository_id: int | None = None) -> dict[str, Any]:
        row = self.context.selected_repository(repository_id)
        return record_status(self.context.database, int(row["id"]))

    def load(self, repository_id: int | None = None) -> dict[str, Any]:
        row = self.context.selected_repository(repository_id)
        self._mounted(row)
        try:
            result = load_record(
                self.context.database,
                int(row["id"]),
                Path(row["path"]),
                config=self.context.selected_config(row),
            )
            target = self.context.target_for_path(Path(row["path"]))
            return {**result, "scan": self.context.scan_coordinator.start(target, int(row["id"]))}
        except (ValueError, OSError) as error:
            raise HTTPException(400, str(error)) from error

    def _mounted(self, row: Any) -> None:
        if self.context.target_for_path(Path(row["path"])) is None:
            raise HTTPException(403, "This repository is available for reading only")

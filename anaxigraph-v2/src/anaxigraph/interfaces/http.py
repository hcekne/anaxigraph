"""HTTP and packaged dashboard access to the shared application."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskInput(Input):
    task: str = Field(min_length=1, max_length=8000)
    limit: int = Field(default=12, ge=1, le=50)


class PlanInput(Input):
    task: str = Field(min_length=1, max_length=8000)
    files: list[str] = Field(max_length=100)


class ValidationInput(Input):
    receipts: list[dict[str, Any]] | None = Field(default=None, max_length=100)


class AnalysisInput(Input):
    kind: str = Field(pattern="^(annotate|patterns|fresh-eyes)$")
    scope: list[str] | None = Field(default=None, max_length=100)


class SubmissionInput(Input):
    request_id: str = Field(min_length=1, max_length=200)
    result: dict[str, Any]


def create_app(application: Any) -> FastAPI:
    server = FastAPI(
        title="AnaxiGraph V2", description="One shared map for humans and coding agents"
    )
    assets = Path(__file__).parent / "assets"
    server.mount("/assets", StaticFiles(directory=assets), name="assets")

    @server.exception_handler(ValueError)
    async def invalid_request(_request: Request, error: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(error)})

    @server.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        return FileResponse(assets / "index.html")

    @server.get("/api/status")
    def status() -> dict:
        return application.status()

    @server.get("/api/modules")
    def modules(
        sort: str = "path",
        descending: bool = False,
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> dict:
        return application.modules(sort, descending, limit, offset)

    @server.get("/api/entity")
    def entity(entity_id: str, limit: int = Query(default=30, ge=1, le=100)) -> dict:
        return application.inspect(entity_id, limit)

    @server.get("/api/reviews")
    def reviews(kind: str | None = None) -> dict:
        return application.reviews(kind)

    @server.post("/api/scan")
    def scan() -> dict:
        return application.scan()

    @server.post("/api/prepare")
    def prepare(body: TaskInput) -> dict:
        return application.prepare_change(body.task, body.limit)

    @server.post("/api/assess")
    def assess(body: PlanInput) -> dict:
        return application.assess_plan(body.task, body.files)

    @server.post("/api/validate")
    def validate(body: ValidationInput) -> dict:
        return application.validate_change(body.receipts)

    @server.post("/api/analysis/request")
    def analysis_request(body: AnalysisInput) -> dict:
        return application.analysis_request(body.kind, body.scope)

    @server.post("/api/analysis/submit")
    def submit(body: SubmissionInput) -> dict:
        return application.submit_analysis(body.request_id, body.result)

    return server

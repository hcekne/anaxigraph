"""Validated request bodies for AnaxiGraph's HTTP transport."""

from typing import Literal

from pydantic import BaseModel, Field


class GuidanceRequest(BaseModel):
    goal: str = Field(min_length=2, max_length=2_000)
    intent: Literal["build", "improve", "refactor"] = "build"
    focus: str = Field(default="", max_length=1_000)
    repository_id: int | None = None


class FreshEyesRequest(BaseModel):
    proposal_count: int = Field(default=2, ge=1, le=3)
    retry_failed: bool = False
    restart: bool = False
    wait: bool = True
    repository_id: int | None = None


class ImpactRequest(BaseModel):
    target: str = Field(min_length=1, max_length=1_000)
    repository_id: int | None = None


class FindingStatusRequest(BaseModel):
    status: str


class CharterCorrectionRequest(BaseModel):
    section: str = Field(min_length=1, max_length=100)
    key: str = Field(default="", max_length=200)
    statement: str = Field(default="", max_length=4_000)
    author: str = Field(min_length=1, max_length=200)
    rationale: str = Field(min_length=1, max_length=2_000)
    active: bool = True
    disposition: str = "correct"
    repository_id: int | None = None

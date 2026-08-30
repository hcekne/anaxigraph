"""Validated request bodies for AnaxiGraph's HTTP transport."""

from pydantic import BaseModel, Field


class ScopeRequest(BaseModel):
    goal: str = Field(min_length=2, max_length=2_000)
    repository_id: int | None = None


class ImpactRequest(BaseModel):
    target: str = Field(min_length=1, max_length=1_000)
    repository_id: int | None = None


class FindingStatusRequest(BaseModel):
    status: str

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from scripts.smoke_container_sidecar import _wait_for_mcp_repository


class _RepositorySession:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = iter(responses)
        self.calls = 0

    async def call_tool(self, name: str, *, arguments: dict[str, object]):
        self.calls += 1
        assert name == "ANAXIGRAPH_REPOSITORIES"
        assert arguments == {}
        repositories = next(self.responses)
        if not isinstance(repositories, list):
            return repositories
        return SimpleNamespace(
            isError=False,
            structuredContent={"repositories": repositories},
        )


def test_container_smoke_waits_for_startup_scan_repository() -> None:
    session = _RepositorySession([[], [], [{"id": 7}]])

    repositories = asyncio.run(_wait_for_mcp_repository(session, timeout_seconds=1, poll_seconds=0))

    assert repositories == [{"id": 7}]
    assert session.calls == 3


def test_container_smoke_explains_repository_readiness_timeout() -> None:
    session = _RepositorySession([[]])

    with pytest.raises(RuntimeError, match="startup scan did not expose a repository"):
        asyncio.run(_wait_for_mcp_repository(session, timeout_seconds=0, poll_seconds=0))


def test_container_smoke_retries_temporary_mcp_readiness_errors() -> None:
    temporary_error = SimpleNamespace(
        isError=True,
        content=[SimpleNamespace(text="The startup scan is still running")],
        structuredContent=None,
    )
    session = _RepositorySession([temporary_error, [{"id": 9}]])

    repositories = asyncio.run(_wait_for_mcp_repository(session, timeout_seconds=1, poll_seconds=0))

    assert repositories == [{"id": 9}]
    assert session.calls == 2

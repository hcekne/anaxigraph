from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from scripts.smoke_container_sidecar import _wait_for_mcp_repository


class _RepositorySession:
    def __init__(self, responses: list[list[dict[str, object]]]) -> None:
        self.responses = iter(responses)
        self.calls = 0

    async def call_tool(self, name: str, *, arguments: dict[str, object]):
        self.calls += 1
        assert name == "ANAXIGRAPH_REPOSITORIES"
        assert arguments == {}
        repositories = next(self.responses)
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

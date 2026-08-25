"""Repository-sized semantic lifecycle through the real Streamable HTTP MCP transport."""

from __future__ import annotations

import httpx
import pytest
from semantic_support import (
    _DeterministicLifecycleProvider,
    _enable_agent_semantics,
    _service_target,
)

import anaxigraph.semantic_remote_worker as remote_worker
from anaxigraph.config import SemanticConfig, load_config
from anaxigraph.mcp_server import create_anaxi_mcp_server
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.storage import AnaxiIndex
from benchmarks.repository_factory import create_history_repository


@pytest.mark.anyio
async def test_two_hundred_module_mcp_lifecycle_resumes_and_finishes(tmp_path, monkeypatch):
    repository = tmp_path / "large-semantic-repository"
    create_history_repository(repository, file_count=200, commits=1)
    _enable_agent_semantics(repository)
    source_before = _source_bytes(repository)
    database = AnaxiIndex(tmp_path / "large-semantic-index.db")
    stats = RepositoryScanner(database).scan(repository)
    config = load_config(repository)
    target = _service_target("http://testserver", stats.repository_id, repository)
    monkeypatch.setattr(
        remote_worker,
        "create_semantic_provider",
        lambda _config: _DeterministicLifecycleProvider(),
    )
    execution = SemanticConfig(provider="codex", max_parallel_jobs=16, timeout_seconds=30)

    first_server = _server(database, repository)
    first_app = first_server.streamable_http_app()
    async with first_server.session_manager.run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=first_app),
            base_url="http://testserver",
            timeout=30,
        ) as client:
            partial = await remote_worker._execute(
                target,
                config.semantic,
                execution,
                limit=100,
                until_complete=False,
                retry_failed=False,
                http_client=client,
            )
            assert partial["completed"] == 100

    _abandon_one_pending_lease(database, stats.repository_id, stats.snapshot_id)
    restarted_server = _server(database, repository)
    restarted_app = restarted_server.streamable_http_app()
    async with restarted_server.session_manager.run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=restarted_app),
            base_url="http://testserver",
            timeout=30,
        ) as client:
            resumed = await remote_worker._execute(
                target,
                config.semantic,
                execution,
                limit=None,
                until_complete=True,
                retry_failed=False,
                http_client=client,
            )

    status = resumed["semantic"]
    assert status["coverage"] == 1.0
    assert status["baseline_complete"] is True
    assert status["semantically_ready"] is True
    assert status["taxonomy"]["ready"] is True
    assert status["taxonomy"]["current"]["review_passes"] == 2
    assert status["patterns"]["ready"] is True
    assert status["patterns"]["selected"] == status["patterns"]["finalized"] > 0
    assert _source_bytes(repository) == source_before
    _assert_clean_durable_queue(database, stats.repository_id, stats.snapshot_id)


def _server(database, repository):
    return create_anaxi_mcp_server(
        database=database,
        repository=repository,
        config_path=None,
        allowed_hosts=["testserver"],
    )


def _source_bytes(repository) -> dict[str, bytes]:
    return {
        path.relative_to(repository).as_posix(): path.read_bytes()
        for path in repository.rglob("*")
        if path.is_file() and ".git" not in path.parts
    }


def _abandon_one_pending_lease(database, repository_id: int, snapshot_id: int) -> None:
    with database.transaction() as connection:
        job = connection.execute(
            "SELECT id FROM semantic_jobs WHERE repository_id = ? AND snapshot_id = ? "
            "AND status = 'pending' ORDER BY priority DESC, id LIMIT 1",
            (repository_id, snapshot_id),
        ).fetchone()
        assert job is not None
        connection.execute(
            """
            UPDATE semantic_jobs SET status = 'running', attempts = 1,
                worker_id = 'abandoned-scale-worker',
                started_at = '2000-01-01T00:00:00+00:00',
                lease_expires_at = '2000-01-01T00:01:00+00:00'
            WHERE id = ?
            """,
            (int(job["id"]),),
        )


def _assert_clean_durable_queue(database, repository_id: int, snapshot_id: int) -> None:
    with database.connect() as connection:
        running = connection.execute(
            "SELECT COUNT(*) FROM semantic_jobs WHERE repository_id = ? AND snapshot_id = ? "
            "AND status = 'running'",
            (repository_id, snapshot_id),
        ).fetchone()[0]
        duplicates = connection.execute(
            """
            SELECT scope_type, scope_key, COUNT(*) FROM semantic_scope_states
            WHERE snapshot_id = ? GROUP BY scope_type, scope_key HAVING COUNT(*) > 1
            """,
            (snapshot_id,),
        ).fetchall()
        unfinished = connection.execute(
            "SELECT COUNT(*) FROM semantic_jobs WHERE repository_id = ? AND snapshot_id = ? "
            "AND status IN ('pending', 'retry', 'running')",
            (repository_id, snapshot_id),
        ).fetchone()[0]
    assert running == 0
    assert unfinished == 0
    assert duplicates == []

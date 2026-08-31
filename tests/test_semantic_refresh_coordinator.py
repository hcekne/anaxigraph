"""Semantic refresh admission around durable expired leases."""

from __future__ import annotations

from dataclasses import replace

import anaxigraph.api_semantic as api_semantic
from anaxigraph.config import load_config
from anaxigraph.registry import RepositoryTarget
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.understanding import SemanticEngine


def test_refresh_coordinator_does_not_treat_an_expired_lease_as_live(
    repository, database, monkeypatch
):
    base = load_config(repository)
    config = replace(
        base,
        semantic=replace(base.semantic, enabled=True, provider="agent", max_parallel_jobs=4),
    )
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    engine.plan(stats.repository_id, repository, config)
    with database.transaction() as connection:
        job = connection.execute(
            "SELECT id FROM semantic_jobs ORDER BY priority DESC, id LIMIT 1"
        ).fetchone()
        connection.execute(
            """
            UPDATE semantic_jobs SET status = 'running', attempts = 1,
                worker_id = 'abandoned-worker', started_at = '2000-01-01T00:00:00+00:00',
                lease_expires_at = '2000-01-01T00:01:00+00:00'
            WHERE id = ?
            """,
            (job["id"],),
        )
    launched = []

    class Thread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            launched.append(True)

    monkeypatch.setattr(api_semantic, "load_config", lambda *_args: config)
    monkeypatch.setattr(api_semantic.threading, "Thread", Thread)
    coordinator = api_semantic.SemanticRefreshCoordinator(database)

    assert coordinator.start(RepositoryTarget("sample", repository)) is True
    assert launched == [True]


def test_refresh_coordinator_joins_owned_threads_before_shutdown(database):
    joined = []

    class Thread:
        alive = True

        def join(self, *, timeout):
            joined.append(timeout)
            self.alive = False

        def is_alive(self):
            return self.alive

    coordinator = api_semantic.SemanticRefreshCoordinator(database)
    coordinator.threads["sample"] = Thread()

    assert coordinator.close(timeout_seconds=1) is True
    assert len(joined) == 1
    assert 0 <= joined[0] <= 1

"""Stage-boundary planning and linear semantic queue control."""

from __future__ import annotations

from dataclasses import replace

from semantic_support import _agent_dossier

from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_agent_protocol import agent_no_work_message, agent_no_work_status
from anaxigraph.storage import AnaxiIndex
from anaxigraph.understanding import SemanticEngine
from benchmarks.repository_factory import create_history_repository


def _prepared_queue(repository, database):
    base = load_config(repository)
    config = replace(
        base,
        semantic=replace(
            base.semantic,
            enabled=True,
            provider="agent",
            max_parallel_jobs=4,
            agent_lease_seconds=120,
        ),
    )
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    plan = engine.plan(stats.repository_id, repository, config)
    assert plan.active_jobs > 1
    return config, stats, engine


def _reject_planning(*_args, **_kwargs):
    raise AssertionError("queue control must not plan while current-stage work exists")


def test_module_plan_uses_inventory_fact_ids_without_per_module_reconstruction(
    repository, database, monkeypatch
):
    base = load_config(repository)
    config = replace(
        base,
        semantic=replace(base.semantic, enabled=True, provider="agent"),
    )
    stats = RepositoryScanner(database).scan(repository)
    monkeypatch.setattr(
        "anaxigraph.persistence.semantic_fact_references.reconstruct_files",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("semantic planning reconstructed the complete snapshot per module")
        ),
    )

    engine = SemanticEngine(database)
    plan = engine.plan(stats.repository_id, repository, config)

    assert plan.active_jobs == stats.discovered
    with database.connect() as connection:
        missing = connection.execute(
            "SELECT COUNT(*) FROM semantic_jobs WHERE artifact_id IS NOT NULL "
            "AND file_fact_id IS NULL"
        ).fetchone()[0]
    assert missing == 0


def test_two_thousand_module_plan_has_constant_fact_reconstruction_count(tmp_path, monkeypatch):
    repository = tmp_path / "large-repository"
    create_history_repository(repository, file_count=2_000, commits=1)
    database = AnaxiIndex(tmp_path / "large-index.db")
    stats = RepositoryScanner(database).scan(repository)
    base = load_config(repository)
    config = replace(
        base,
        semantic=replace(base.semantic, enabled=True, provider="agent"),
    )
    calls = 0

    def counted(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("live semantic planning must use inventory fact references")

    monkeypatch.setattr(
        "anaxigraph.persistence.semantic_fact_references.reconstruct_files",
        counted,
    )

    engine = SemanticEngine(database)
    plan = engine.plan(stats.repository_id, repository, config)

    assert stats.discovered == plan.active_jobs == 2_000
    assert calls == 0
    action = engine.status(stats.repository_id, config.semantic)["recommended_action"]
    assert action["kind"] == "durable_host_executor"
    assert "--background" in action["command"]
    assert "--model" not in action["command"]
    language = engine.status(stats.repository_id, config.semantic)["plain_language"]
    assert "no worker is running right now" in language["conclusion"]
    assert any("does not hardcode" in item for item in language["how_to_read_progress"])


def test_agent_claim_uses_an_existing_queue_without_planning(repository, database, monkeypatch):
    config, stats, engine = _prepared_queue(repository, database)
    monkeypatch.setattr(engine._services.planning, "plan", _reject_planning)

    packet = engine.claim_agent_work(
        stats.repository_id,
        repository,
        config,
        agent_id="queue-first-test",
    )

    assert packet["status"] == "work"


def test_agent_submit_commits_without_replanning(repository, database, monkeypatch):
    config, stats, engine = _prepared_queue(repository, database)
    packet = engine.claim_agent_work(
        stats.repository_id,
        repository,
        config,
        agent_id="submit-boundary-test",
    )
    monkeypatch.setattr(engine._services.planning, "plan", _reject_planning)

    result = engine.submit_agent_work(
        stats.repository_id,
        repository,
        config,
        job_id=packet["job"]["id"],
        lease_token=packet["lease"]["token"],
        dossier=_agent_dossier(packet["analysis_request"]),
    )

    assert result["status"] == "completed"
    assert result["next_plan_stage"] == "claim_next"


def test_agent_claim_atomically_recovers_an_expired_lease_without_planning(
    repository, database, monkeypatch
):
    config, stats, engine = _prepared_queue(repository, database)
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
    monkeypatch.setattr(engine._services.planning, "plan", _reject_planning)

    packet = engine.claim_agent_work(
        stats.repository_id,
        repository,
        config,
        agent_id="expired-lease-test",
    )

    assert packet["status"] == "work"
    assert packet["job"]["id"] == job["id"]
    assert packet["job"]["attempt"] == 2


def test_status_distinguishes_expired_work(repository, database):
    config, stats, engine = _prepared_queue(repository, database)
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

    jobs = engine.status(stats.repository_id, config.semantic)["jobs"]
    assert jobs["running"] == jobs["running_expired"] == jobs["reclaimable"] == 1
    assert jobs["running_live"] == 0


def test_no_work_status_reports_live_and_queued_jobs_before_a_ready_baseline():
    ready = {"semantically_ready": True, "baseline_complete": True, "jobs": {}}

    peer_holds_review_stage = {**ready, "jobs": {"running": 1}}
    assert agent_no_work_status(peer_holds_review_stage) == "busy"
    assert agent_no_work_message(peer_holds_review_stage).startswith("Another coding agent")

    assert agent_no_work_status({**ready, "jobs": {"pending": 1}}) == "waiting"
    assert agent_no_work_status({**ready, "jobs": {"retry": 1}}) == "waiting"
    assert agent_no_work_status(ready) == "complete"

    paused = {"semantically_ready": False, "budget": {"paused": True}, "jobs": {"pending": 3}}
    assert agent_no_work_status(paused) == "paused"
    assert agent_no_work_status({**paused, "jobs": {"running": 1}}) == "busy"
    failed = {"baseline_complete": True, "failed": 2, "jobs": {}}
    assert agent_no_work_status(failed) == "complete_with_failures"

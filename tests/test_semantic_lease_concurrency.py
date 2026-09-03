"""Two-connection lease tests: claims stay distinct and stale writes are refused."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from semantic_support import _agent_dossier, _fake_provider, _semantic_config

from anaxigraph import semantic_lease_claim
from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic import SemanticResult
from anaxigraph.semantic_job_state import SemanticLeaseLost
from anaxigraph.semantic_leases import SemanticLeaseService
from anaxigraph.storage import AnaxiIndex
from anaxigraph.understanding import SemanticEngine

_RESULT = SemanticResult({"summary": "Guarded lease test"}, 0.8, ("pkg/core.py",))
_EXPIRED = "2000-01-01T00:01:00+00:00"


def _agent_queue(repository: Path, database: AnaxiIndex):
    base = load_config(repository)
    config = replace(
        base,
        semantic=replace(
            base.semantic,
            enabled=True,
            provider="agent",
            max_parallel_jobs=2,
            agent_lease_seconds=120,
        ),
    )
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    assert engine.plan(stats.repository_id, repository, config).active_jobs >= 2
    return config, stats.repository_id, engine


def _expire_running_leases(database: AnaxiIndex) -> None:
    with database.transaction() as connection:
        connection.execute(
            "UPDATE semantic_jobs SET lease_expires_at = ? WHERE status = 'running'", (_EXPIRED,)
        )


def _job_row(database: AnaxiIndex, job_id: int) -> dict[str, Any]:
    with database.connect() as connection:
        return dict(
            connection.execute("SELECT * FROM semantic_jobs WHERE id = ?", (job_id,)).fetchone()
        )


def _scope_of(job: dict[str, Any]) -> tuple[Any, Any, Any]:
    return (job["snapshot_id"], job["scope_type"], job["scope_key"])


def _document_executors(database: AnaxiIndex, job: dict[str, Any]) -> list[str | None]:
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT executor_id FROM semantic_documents
            WHERE snapshot_id = ? AND scope_type = ? AND scope_key = ? AND document_kind = ?
            """,
            (*_scope_of(job), job["job_kind"]),
        ).fetchall()
    return [row["executor_id"] for row in rows]


def _scope_state(database: AnaxiIndex, job: dict[str, Any]) -> tuple[str, str]:
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT status, reason FROM semantic_scope_states
            WHERE snapshot_id = ? AND scope_type = ? AND scope_key = ?
            """,
            _scope_of(job),
        ).fetchone()
    return tuple(row)


def _reclaimed_pair(engine, repository_id, config, database):
    leases = engine._services.leases
    first = leases.claim_job(
        repository_id, config.semantic, worker_id="runner-a", executor_id="cli:a"
    )
    assert first is not None
    _expire_running_leases(database)
    second = leases.claim_job(
        repository_id, config.semantic, worker_id="runner-b", executor_id="cli:b"
    )
    assert second is not None
    assert (second["id"], second["attempts"]) == (first["id"], 2)
    return first, second


def test_two_index_handles_never_claim_the_same_job(repository, database):
    config, repository_id, engine = _agent_queue(repository, database)
    services = [
        SemanticLeaseService(AnaxiIndex(database.path), engine._services.persistence)
        for _ in range(2)
    ]
    barrier = threading.Barrier(2)

    def claim(index: int):
        barrier.wait(timeout=10)
        return services[index].claim_job(
            repository_id, config.semantic, worker_id=f"handle-{index}"
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        for _ in range(20):
            jobs = list(executor.map(claim, range(2)))
            assert all(job is not None for job in jobs)
            assert len({int(job["id"]) for job in jobs}) == 2
            with database.connect() as connection:
                running = connection.execute(
                    "SELECT COUNT(*) FROM semantic_jobs WHERE status = 'running'"
                ).fetchone()[0]
            assert running == 2
            with database.transaction() as connection:
                connection.execute(
                    """
                    UPDATE semantic_jobs SET status = 'pending', attempts = 0, worker_id = NULL,
                        lease_expires_at = NULL, lease_token_hash = NULL
                    WHERE status = 'running'
                    """
                )


def test_stale_worker_complete_after_reclaim_is_rejected(repository, database):
    config, repository_id, engine = _agent_queue(repository, database)
    persistence = engine._services.persistence
    first, second = _reclaimed_pair(engine, repository_id, config, database)

    with pytest.raises(SemanticLeaseLost, match="lease was reclaimed"):
        persistence.complete_job(first, _RESULT, "agent", config.semantic)

    row = _job_row(database, first["id"])
    assert (row["status"], row["worker_id"], row["executor_id"]) == ("running", "runner-b", "cli:b")
    assert _document_executors(database, first) == []

    persistence.complete_job(second, _RESULT, "agent", config.semantic)
    row = _job_row(database, first["id"])
    assert (row["status"], row["executor_id"], row["worker_id"]) == ("completed", "cli:b", None)
    assert _document_executors(database, first) == ["cli:b"]


def test_fail_job_with_stale_worker_does_not_requeue(repository, database):
    config, repository_id, engine = _agent_queue(repository, database)
    first, _second = _reclaimed_pair(engine, repository_id, config, database)
    before = _scope_state(database, first)

    with pytest.raises(SemanticLeaseLost):
        engine._services.persistence.fail_job(first, RuntimeError("stale worker gave up"))

    row = _job_row(database, first["id"])
    assert (row["status"], row["worker_id"], row["attempts"]) == ("running", "runner-b", 2)
    assert _scope_state(database, first) == before


def test_complete_after_release_is_rejected(repository, database):
    config, repository_id, engine = _agent_queue(repository, database)
    leases = engine._services.leases
    job = leases.claim_job(repository_id, config.semantic, worker_id="runner-a")
    leases.release_agent_job(job, "handing the job back")

    with pytest.raises(SemanticLeaseLost):
        engine._services.persistence.complete_job(job, _RESULT, "agent", config.semantic)

    row = _job_row(database, job["id"])
    assert (row["status"], row["worker_id"]) == ("retry", None)
    assert _document_executors(database, job) == []


def test_claim_returns_none_when_the_selected_row_changed_underneath(
    repository, database, monkeypatch
):
    config, repository_id, engine = _agent_queue(repository, database)
    with database.connect() as connection:
        stale = connection.execute(
            "SELECT * FROM semantic_jobs WHERE status = 'pending' ORDER BY priority DESC, id LIMIT 1"
        ).fetchone()
    with database.transaction() as connection:
        connection.execute(
            "UPDATE semantic_jobs SET status = 'completed', completed_at = ? WHERE id = ?",
            (_EXPIRED, stale["id"]),
        )
    monkeypatch.setattr(semantic_lease_claim, "_next_job", lambda *_args, **_kwargs: stale)

    claimed = engine._services.leases.claim_job(
        repository_id, config.semantic, worker_id="late-worker"
    )

    assert claimed is None
    row = _job_row(database, stale["id"])
    assert (row["status"], row["attempts"], row["worker_id"]) == ("completed", 0, None)


def test_agent_submit_loses_to_a_reclaim_inside_the_validation_window(
    repository, database, monkeypatch
):
    config, repository_id, engine = _agent_queue(repository, database)
    packet_a = engine.claim_agent_work(repository_id, repository, config, agent_id="agent-a")
    assert packet_a["status"] == "work"
    job_id = packet_a["job"]["id"]
    evidence = engine._services.evidence
    original_request = evidence.job_request
    reclaim: dict[str, Any] = {}

    def reclaim_then_request(job, root, semantic):
        if not reclaim:
            reclaim["started"] = True
            _expire_running_leases(database)
            reclaim["packet"] = engine.claim_agent_work(
                repository_id, repository, config, agent_id="agent-b"
            )
        return original_request(job, root, semantic)

    monkeypatch.setattr(evidence, "job_request", reclaim_then_request)
    with pytest.raises(ValueError, match="lease was reclaimed"):
        engine.submit_agent_work(
            repository_id,
            repository,
            config,
            job_id=job_id,
            lease_token=packet_a["lease"]["token"],
            dossier=_agent_dossier(packet_a["analysis_request"]),
        )

    packet_b = reclaim["packet"]
    assert (packet_b["status"], packet_b["job"]["id"], packet_b["job"]["attempt"]) == (
        "work",
        job_id,
        2,
    )
    row = _job_row(database, job_id)
    assert (row["status"], row["executor_id"]) == ("running", "agent-b")
    assert str(row["worker_id"]).startswith("mcp:agent-b:")
    assert _document_executors(database, row) == []

    submit_b = dict(
        job_id=job_id,
        lease_token=packet_b["lease"]["token"],
        dossier=_agent_dossier(packet_b["analysis_request"]),
    )
    completed = engine.submit_agent_work(repository_id, repository, config, **submit_b)
    assert completed["status"] == "completed"
    assert _document_executors(database, row) == ["agent-b"]
    repeated = engine.submit_agent_work(repository_id, repository, config, **submit_b)
    assert repeated["status"] == "already_completed"


def test_submit_after_source_change_marks_the_job_superseded(repository, database):
    config, repository_id, engine = _agent_queue(repository, database)
    packet = engine.claim_agent_work(repository_id, repository, config, agent_id="agent-a")
    assert (packet["status"], packet["job"]["kind"]) == ("work", "intrinsic")
    target = repository / packet["job"]["scope_key"]
    target.write_text(
        target.read_text(encoding="utf-8") + "\n# edited after planning\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="changed after this semantic job was planned"):
        engine.submit_agent_work(
            repository_id,
            repository,
            config,
            job_id=packet["job"]["id"],
            lease_token=packet["lease"]["token"],
            dossier=_agent_dossier(packet["analysis_request"]),
        )

    assert _job_row(database, packet["job"]["id"])["status"] == "superseded"


@pytest.mark.parametrize("analysis", ["result", "error"])
def test_runner_records_a_lost_lease_instead_of_overwriting_the_new_claimant(
    repository, database, tmp_path, monkeypatch, analysis
):
    _semantic_config(repository, _fake_provider(tmp_path), tmp_path / "semantic.log")
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    assert engine.plan(stats.repository_id, repository, config).active_jobs >= 2
    reclaimed: dict[str, Any] = {}

    def steal_lease(_provider, _request, _semantic):
        _expire_running_leases(database)
        reclaimed["job"] = engine._services.leases.claim_job(
            stats.repository_id, config.semantic, worker_id="runner-b"
        )
        if analysis == "error":
            raise RuntimeError("the slow worker failed after losing its lease")
        return _RESULT

    monkeypatch.setattr(engine._services.runner, "analyze_request", steal_lease)
    run = engine.run_jobs(stats.repository_id, repository, config, limit=1)

    assert {
        key: run[key] for key in ("processed", "lease_lost", "completed", "failed", "retry")
    } == {
        "processed": 1,
        "lease_lost": 1,
        "completed": 0,
        "failed": 0,
        "retry": 0,
    }
    job = reclaimed["job"]
    row = _job_row(database, job["id"])
    assert (row["status"], row["worker_id"], row["attempts"]) == ("running", "runner-b", 2)
    assert _document_executors(database, job) == []

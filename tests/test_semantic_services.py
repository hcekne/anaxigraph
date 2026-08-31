from __future__ import annotations

import yaml

from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic import SemanticResult
from anaxigraph.semantic_agent import SemanticAgentService
from anaxigraph.semantic_leases import SemanticLeaseService
from anaxigraph.semantic_reporting import SemanticReportingService
from anaxigraph.semantic_requests import SemanticEvidenceService
from anaxigraph.semantic_results import SemanticPersistenceService
from anaxigraph.semantic_runner import SemanticRunnerService
from anaxigraph.semantic_scope_plan import SemanticPlanningService
from anaxigraph.understanding import SemanticEngine


def test_semantic_engine_is_a_composed_compatibility_facade(database) -> None:
    engine = SemanticEngine(database)

    assert SemanticEngine.__bases__ == (object,)
    assert not hasattr(engine, "database")
    services = engine._services
    assert isinstance(services.planning, SemanticPlanningService)
    assert isinstance(services.leases, SemanticLeaseService)
    assert isinstance(services.evidence, SemanticEvidenceService)
    assert isinstance(services.persistence, SemanticPersistenceService)
    assert isinstance(services.runner, SemanticRunnerService)
    assert isinstance(services.reporting, SemanticReportingService)
    assert isinstance(services.agent, SemanticAgentService)
    composed = (
        services.planning,
        services.leases,
        services.evidence,
        services.persistence,
        services.runner,
        services.reporting,
        services.agent,
    )
    assert all(type(service).__bases__ == (object,) for service in composed)


def test_lease_service_persists_declared_claim_and_release_transitions(
    repository, database
) -> None:
    policy = yaml.safe_load((repository / ".anaxigraph.yml").read_text(encoding="utf-8"))
    policy["semantic"] = {
        "enabled": True,
        "provider": "agent",
        "max_parallel_jobs": 1,
    }
    (repository / ".anaxigraph.yml").write_text(
        yaml.safe_dump(policy, sort_keys=False), encoding="utf-8"
    )
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    engine.plan(stats.repository_id, repository, config)

    job = engine._services.leases.claim_job(
        stats.repository_id, config.semantic, worker_id="service-test"
    )
    assert job is not None
    assert job["status"] == "running"
    engine._services.leases.release_agent_job(job, "test handoff")

    with database.connect() as connection:
        stored = connection.execute(
            "SELECT status, attempts, worker_id, lease_expires_at FROM semantic_jobs WHERE id = ?",
            (job["id"],),
        ).fetchone()
    assert tuple(stored) == ("retry", 0, None, None)

    resumed = engine._services.leases.claim_job(
        stats.repository_id, config.semantic, worker_id="service-test-2"
    )
    assert resumed is not None
    assert resumed["id"] == job["id"]
    assert resumed["status"] == "running"

    engine._services.persistence.complete_job(
        resumed,
        SemanticResult({"summary": "Test module responsibility"}, 0.8, ("pkg/core.py",)),
        "agent",
        config.semantic,
    )
    with database.connect() as connection:
        completed = connection.execute(
            "SELECT status, metadata_json FROM semantic_jobs WHERE id = ?",
            (resumed["id"],),
        ).fetchone()
    assert tuple(completed) == ("completed", "{}")

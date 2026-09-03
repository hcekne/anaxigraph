from __future__ import annotations

import pytest
import yaml

from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic import SemanticResult
from anaxigraph.semantic_agent import SemanticAgentService
from anaxigraph.semantic_contract import SemanticAnalysisError
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


def _planned_agent_engine(repository, database):
    """Scan and plan one agent-funded repository so a job can be claimed and completed."""

    policy = yaml.safe_load((repository / ".anaxigraph.yml").read_text(encoding="utf-8"))
    policy["semantic"] = {"enabled": True, "provider": "agent", "max_parallel_jobs": 4}
    (repository / ".anaxigraph.yml").write_text(
        yaml.safe_dump(policy, sort_keys=False), encoding="utf-8"
    )
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    engine.plan(stats.repository_id, repository, config)
    return engine, config, stats


def _job_row(database, job_id: int) -> dict:
    with database.connect() as connection:
        return dict(
            connection.execute("SELECT * FROM semantic_jobs WHERE id = ?", (job_id,)).fetchone()
        )


def _document_rows(database) -> list[dict]:
    with database.connect() as connection:
        return [
            dict(row) for row in connection.execute("SELECT * FROM semantic_documents ORDER BY id")
        ]


@pytest.mark.parametrize(
    ("provider", "usage_reported", "expected_source", "expects_cost"),
    [
        ("agent", False, "unknown", False),
        ("command", False, "estimated", False),
        ("codex", True, "reported", True),
    ],
)
def test_completion_records_where_its_token_counts_came_from(
    repository, database, provider, usage_reported, expected_source, expects_cost
) -> None:
    engine, config, stats = _planned_agent_engine(repository, database)
    job = engine._services.leases.claim_job(
        stats.repository_id, config.semantic, worker_id="usage-source"
    )
    assert job is not None

    engine._services.persistence.complete_job(
        job,
        SemanticResult(
            {"summary": "Reported usage"},
            0.8,
            ("pkg/core.py",),
            usage_reported=usage_reported,
        ),
        provider,
        config.semantic,
    )

    stored = _job_row(database, int(job["id"]))
    assert stored["usage_source"] == expected_source
    assert (stored["actual_cost_usd"] is not None) is expects_cost
    if expected_source == "estimated":
        assert stored["input_tokens"] > 0
    else:
        assert stored["input_tokens"] == 0
    document = next(item for item in _document_rows(database) if item["scope_key"])
    assert document["usage_source"] == expected_source


def test_completion_and_failure_keep_the_cached_prompt_split(repository, database) -> None:
    engine, config, stats = _planned_agent_engine(repository, database)
    persistence = engine._services.persistence
    job = engine._services.leases.claim_job(
        stats.repository_id, config.semantic, worker_id="cache-split"
    )
    assert job is not None

    persistence.complete_job(
        job,
        SemanticResult(
            {"summary": "Cached prompt"},
            0.8,
            ("pkg/core.py",),
            input_tokens=39_002,
            output_tokens=800,
            cache_read_input_tokens=30_000,
            cache_creation_input_tokens=9_000,
            usage_reported=True,
        ),
        "claude",
        config.semantic,
    )

    stored = _job_row(database, int(job["id"]))
    assert stored["input_tokens"] == 39_002
    assert stored["cache_read_input_tokens"] == 30_000
    assert stored["cache_creation_input_tokens"] == 9_000
    document = next(item for item in _document_rows(database) if item["scope_key"])
    assert document["cache_read_input_tokens"] == 30_000
    assert document["cache_creation_input_tokens"] == 9_000

    failing = engine._services.leases.claim_job(
        stats.repository_id, config.semantic, worker_id="cache-split-failure"
    )
    assert failing is not None
    persistence.fail_job(
        failing,
        SemanticAnalysisError("model stopped"),
        input_tokens=120,
        output_tokens=30,
        cache_read_input_tokens=100,
        cache_creation_input_tokens=5,
        usage_reported=True,
    )

    failed = _job_row(database, int(failing["id"]))
    assert failed["usage_source"] == "reported"
    assert failed["cache_read_input_tokens"] == 100
    assert failed["cache_creation_input_tokens"] == 5


def test_unreported_failure_stays_unknown(repository, database) -> None:
    engine, config, stats = _planned_agent_engine(repository, database)
    job = engine._services.leases.claim_job(
        stats.repository_id, config.semantic, worker_id="silent-failure"
    )
    assert job is not None

    engine._services.persistence.fail_job(job, SemanticAnalysisError("killed before usage"))

    stored = _job_row(database, int(job["id"]))
    assert stored["usage_source"] == "unknown"
    assert (stored["input_tokens"], stored["output_tokens"]) == (0, 0)


def test_claimed_effort_reaches_the_job_and_its_document(repository, database) -> None:
    engine, config, stats = _planned_agent_engine(repository, database)
    job = engine._services.leases.claim_job(
        stats.repository_id,
        config.semantic,
        worker_id="effort",
        executor_id="cli:claude",
        executor_model="claude-test",
        executor_effort="medium",
    )
    assert job is not None
    assert job["executor_effort"] == "medium"

    engine._services.persistence.complete_job(
        job,
        SemanticResult({"summary": "Effort recorded"}, 0.8, ("pkg/core.py",)),
        "agent",
        config.semantic,
    )

    assert _job_row(database, int(job["id"]))["executor_effort"] == "medium"
    document = next(item for item in _document_rows(database) if item["scope_key"])
    assert document["executor_effort"] == "medium"


def test_an_unrequested_effort_is_recorded_as_the_executor_default(repository, database) -> None:
    engine, config, stats = _planned_agent_engine(repository, database)
    job = engine._services.leases.claim_job(
        stats.repository_id, config.semantic, worker_id="default-effort"
    )
    assert job is not None

    assert job["executor_effort"] is None
    assert _job_row(database, int(job["id"]))["executor_effort"] is None


def test_a_reported_attempt_is_not_relabelled_by_a_later_silent_one(repository, database) -> None:
    engine, config, stats = _planned_agent_engine(repository, database)
    persistence = engine._services.persistence
    first = engine._services.leases.claim_job(
        stats.repository_id, config.semantic, worker_id="reported-attempt"
    )
    assert first is not None
    persistence.fail_job(
        first,
        SemanticAnalysisError("model stopped"),
        input_tokens=120,
        output_tokens=30,
        usage_reported=True,
    )

    with database.transaction() as connection:
        connection.execute(
            "UPDATE semantic_jobs SET available_at = '2020-01-01T00:00:00+00:00' WHERE id = ?",
            (first["id"],),
        )
    retried = engine._services.leases.claim_job(
        stats.repository_id, config.semantic, worker_id="silent-attempt"
    )
    assert retried is not None
    assert retried["id"] == first["id"]
    persistence.fail_job(retried, SemanticAnalysisError("killed before usage"))

    stored = _job_row(database, int(first["id"]))
    assert stored["usage_source"] == "reported"
    assert (stored["input_tokens"], stored["output_tokens"]) == (120, 30)

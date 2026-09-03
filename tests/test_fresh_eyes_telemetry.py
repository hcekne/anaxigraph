from __future__ import annotations

import yaml
from fresh_eyes_support import TwoExecutorReview
from semantic_support import _agent_dossier, _enable_agent_semantics

from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_fresh_eyes_telemetry import ATTEMPTS_CAVEAT
from anaxigraph.understanding import SemanticEngine


def _drain(
    engine,
    repository_id,
    repository,
    config,
    prefix,
    *,
    agent_model="fixture-model",
    input_tokens=0,
    output_tokens=0,
):
    for index in range(500):
        packet = engine.claim_agent_work(
            repository_id,
            repository,
            config,
            agent_id=f"{prefix}-{index}",
            agent_model=agent_model,
        )
        if packet["status"] == "complete":
            return
        engine.submit_agent_work(
            repository_id,
            repository,
            config,
            job_id=packet["job"]["id"],
            lease_token=packet["lease"]["token"],
            dossier=_agent_dossier(packet["analysis_request"]),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
    raise AssertionError("Semantic work did not converge")


def _completed_review(repository, database, *, input_tokens=0, output_tokens=0):
    """Finish the baseline and one fresh-eyes review, reporting the given usage per stage."""

    _enable_agent_semantics(repository)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    _drain(engine, stats.repository_id, repository, config, "baseline")
    engine.start_fresh_eyes_review(stats.repository_id, repository, config)
    _drain(
        engine,
        stats.repository_id,
        repository,
        config,
        "review",
        agent_model="telemetry-model",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    return engine, stats.repository_id, config


def _single_attempt(repository):
    """Let one refusal exhaust a job so the failed branch needs no retry backoff wait."""

    path = repository / ".anaxigraph.yml"
    policy = yaml.safe_load(path.read_text(encoding="utf-8"))
    policy["semantic"]["max_attempts"] = 1
    path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")


def _document_sizes(database):
    with database.connect() as connection:
        return {
            int(row["id"]): int(row["size"])
            for row in connection.execute(
                "SELECT id, LENGTH(value_json) AS size FROM semantic_documents"
            ).fetchall()
        }


def test_stage_runs_report_duration_tokens_bytes_and_executor(repository, database):
    engine, repository_id, config = _completed_review(
        repository, database, input_tokens=40_000, output_tokens=900
    )

    review = engine.fresh_eyes_status(repository_id, config.semantic)

    sizes = _document_sizes(database)
    stages = review["stages"]
    assert [item["key"] for item in stages] == [
        "proposal:a",
        "proposal:b",
        "adjudication",
        "comparison",
        "review",
    ]
    for stage in stages:
        telemetry = stage["telemetry"]
        assert telemetry["duration_ms"] >= 0
        assert telemetry["attempts_observed"] >= 1
        assert telemetry["output_bytes"] == sizes[stage["document_id"]]
        assert telemetry["executor_model"] == "telemetry-model"
        assert telemetry["job_status"] == "completed"
        assert telemetry["token_counts_reported"] is True
        assert telemetry["input_tokens_plausible"] is True
    totals = review["telemetry"]
    assert totals["stage_count"] == 5
    assert totals["output_bytes"] == sum(item["telemetry"]["output_bytes"] for item in stages)
    assert totals["input_tokens"] == 5 * 40_000
    assert totals["attempts_observed"] == 5
    assert totals["wall_clock_ms"] >= max(item["telemetry"]["duration_ms"] for item in stages)
    assert ATTEMPTS_CAVEAT in totals["caveats"]


def test_implausible_token_counts_are_flagged_not_summed(repository, database):
    engine, repository_id, config = _completed_review(
        repository, database, input_tokens=2, output_tokens=40_178
    )

    review = engine.fresh_eyes_status(repository_id, config.semantic)

    totals = review["telemetry"]
    assert all(item["telemetry"]["token_counts_reported"] is True for item in review["stages"])
    assert all(item["telemetry"]["input_tokens"] == 2 for item in review["stages"])
    assert all(item["telemetry"]["input_tokens_plausible"] is False for item in review["stages"])
    assert totals["input_tokens"] == 0
    assert totals["output_tokens"] == 5 * 40_178
    assert totals["stages_with_implausible_input_tokens"] == 5
    assert any("input tokens against an estimated" in item for item in totals["caveats"])


def test_unreported_token_counts_are_named_and_excluded(repository, database):
    engine, repository_id, config = _completed_review(repository, database)

    totals = engine.fresh_eyes_status(repository_id, config.semantic)["telemetry"]

    assert totals["input_tokens"] == 0
    assert totals["output_tokens"] == 0
    assert totals["stages_reporting_usage"] == 0
    assert any("reported no token counts" in item for item in totals["caveats"])


def test_a_failed_and_retried_stage_reports_its_attempts_and_error(repository, database):
    _enable_agent_semantics(repository)
    _single_attempt(repository)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    review = TwoExecutorReview(engine, stats.repository_id, repository, config)
    review.run_until_complete()
    engine.start_fresh_eyes_review(stats.repository_id, repository, config)
    packet = review.claim(review.executors[0])
    assert packet["job"]["kind"] == "fresh_proposal"
    engine.fail_agent_work(
        stats.repository_id,
        config,
        job_id=packet["job"]["id"],
        lease_token=packet["lease"]["token"],
        reason="fixture executor refused the packet",
    )

    failed = engine.fresh_eyes_status(stats.repository_id, config.semantic)

    stage = next(item for item in failed["stages"] if item["telemetry"]["job_status"] == "failed")
    assert failed["state"] == "failed"
    assert stage["telemetry"]["attempts_observed"] >= 1
    assert "fixture executor refused" in stage["telemetry"]["error"]
    assert stage["telemetry"]["output_bytes"] == 0
    assert stage["telemetry"]["document_id"] is None

    engine.start_fresh_eyes_review(stats.repository_id, repository, config, retry_failed=True)
    review.run_until_complete()
    retried = engine.fresh_eyes_status(stats.repository_id, config.semantic)
    assert retried["state"] == "current"
    assert all(item["telemetry"]["job_status"] == "completed" for item in retried["stages"])
    assert all(item["telemetry"]["attempts_observed"] >= 1 for item in retried["stages"])
    assert ATTEMPTS_CAVEAT in retried["telemetry"]["caveats"]


def test_generation_bundles_carry_the_same_stage_telemetry(repository, database):
    engine, repository_id, config = _completed_review(
        repository, database, input_tokens=40_000, output_tokens=900
    )

    review = engine.fresh_eyes_status(repository_id, config.semantic)

    bundle = review["generations"][-1]
    assert bundle["document_ids"] == [item["document_id"] for item in review["stages"]]
    assert [item["key"] for item in bundle["telemetry"]["stages"]] == [
        item["key"] for item in review["stages"]
    ]
    assert bundle["telemetry"]["output_bytes"] == review["telemetry"]["output_bytes"]
    assert bundle["telemetry"]["input_tokens"] == review["telemetry"]["input_tokens"]

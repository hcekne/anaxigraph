from __future__ import annotations

import json

import pytest
from semantic_support import _agent_dossier, _enable_agent_semantics

from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_fresh_eyes_contract import fresh_eyes_plan_options
from anaxigraph.understanding import SemanticEngine


def _finish_work(
    engine,
    repository_id,
    repository,
    config,
    *,
    prefix="baseline",
    requests=None,
    agent_model="fixture-model",
):
    kinds = []
    for index in range(500):
        packet = engine.claim_agent_work(
            repository_id,
            repository,
            config,
            agent_id=f"{prefix}-{index}",
            agent_model=agent_model,
        )
        if packet["status"] == "complete":
            return kinds
        assert packet["status"] == "work"
        kinds.append(packet["job"]["kind"])
        if requests is not None:
            requests.append(packet["analysis_request"])
        engine.submit_agent_work(
            repository_id,
            repository,
            config,
            job_id=packet["job"]["id"],
            lease_token=packet["lease"]["token"],
            dossier=_agent_dossier(packet["analysis_request"]),
        )
    raise AssertionError("Semantic work did not converge")


def test_fixed_fresh_eyes_recipe_is_resumable_blind_and_agent_funded(repository, database):
    _enable_agent_semantics(repository)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    baseline_kinds = _finish_work(
        engine, stats.repository_id, repository, config, prefix="baseline"
    )
    assert "synthesis" in baseline_kinds
    assert engine.status(stats.repository_id, config.semantic)["semantically_ready"] is True

    started = engine.start_fresh_eyes_review(
        stats.repository_id,
        repository,
        config,
        proposal_count=2,
    )
    assert started["status"] == "started"
    assert started["review"]["state"] == "in_progress"

    first = engine.claim_agent_work(
        stats.repository_id,
        repository,
        config,
        agent_id="proposal-a",
        agent_model="fixture-model",
    )
    assert first["job"]["kind"] == "fresh_proposal"
    proposal_packet = first["analysis_request"]
    assert set(proposal_packet) >= {
        "capability_brief",
        "external_constraints",
        "information_boundary",
    }
    assert "current_system" not in proposal_packet
    assert "responsibility_map" not in proposal_packet
    assert "recent_history" not in proposal_packet
    assert "pkg/core.py" not in str(proposal_packet["capability_brief"])
    engine.submit_agent_work(
        stats.repository_id,
        repository,
        config,
        job_id=first["job"]["id"],
        lease_token=first["lease"]["token"],
        dossier=_agent_dossier(proposal_packet),
    )

    restarted = SemanticEngine(database)
    review_requests = []
    review_kinds = _finish_work(
        restarted,
        stats.repository_id,
        repository,
        config,
        prefix="review",
        requests=review_requests,
    )
    assert review_kinds == [
        "fresh_proposal",
        "fresh_adjudication",
        "fresh_comparison",
        "fresh_review",
    ]
    comparison_request = next(
        item for item in review_requests if item["analysis_kind"] == "fresh_comparison"
    )
    assert comparison_request["current_system"]["dependency_evidence"]
    history_kinds = {
        item["evidence_kind"] for item in comparison_request["current_system"]["recent_history"]
    }
    assert history_kinds == {"recent_commit", "high_churn_module"}
    result = restarted.fresh_eyes_status(stats.repository_id, config.semantic)
    assert result["state"] == "current"
    assert result["ready"] is True
    assert len(result["proposals"]) == 2
    assert result["diversity"]["cross_provider"] is False
    assert result["recommendations"][0]["action"] == "consolidate"
    assert result["strategy"]["contract_version"] == "fresh-eyes-review-v1"
    assert set(result["fingerprints"]) == {"capability", "reference", "comparison"}
    assert all(result["fingerprints"].values())
    assert len(result["input_manifests"]) == 5
    proposal_manifests = [
        item for item in result["input_manifests"] if item["job_kind"] == "fresh_proposal"
    ]
    assert len(proposal_manifests) == 2
    assert all("repository_paths" in item["manifest"]["withheld"] for item in proposal_manifests)
    assert restarted.status(stats.repository_id, config.semantic)["semantically_ready"] is True


def test_completed_review_can_be_rerun_with_new_model_without_rereading_modules(
    repository, database
):
    _enable_agent_semantics(repository)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    _finish_work(engine, stats.repository_id, repository, config)
    engine.start_fresh_eyes_review(stats.repository_id, repository, config)
    _finish_work(engine, stats.repository_id, repository, config, prefix="first-review")
    first = engine.fresh_eyes_status(stats.repository_id, config.semantic)
    first_ids = {stage["document_id"] for stage in first["stages"]}
    util = repository / "pkg" / "util.py"
    util.write_text(
        util.read_text(encoding="utf-8").replace("value * 2", "value * 3"), encoding="utf-8"
    )
    stats = RepositoryScanner(database).scan(repository)
    _finish_work(engine, stats.repository_id, repository, config, prefix="changed-baseline")
    with database.connect() as connection:
        module_jobs = connection.execute(
            "SELECT COUNT(*) FROM semantic_jobs WHERE scope_type = 'module'"
        ).fetchone()[0]

    restarted = engine.start_fresh_eyes_review(
        stats.repository_id,
        repository,
        config,
        restart=True,
    )
    assert restarted["status"] == "restarted"
    assert restarted["review"]["review_generation"] == 2
    kinds = _finish_work(
        engine,
        stats.repository_id,
        repository,
        config,
        prefix="strong-review",
        agent_model="stronger-model",
    )

    assert kinds == [
        "fresh_proposal",
        "fresh_proposal",
        "fresh_adjudication",
        "fresh_comparison",
        "fresh_review",
    ]
    second = engine.fresh_eyes_status(stats.repository_id, config.semantic)
    assert second["review_generation"] == 2
    assert first_ids.isdisjoint({stage["document_id"] for stage in second["stages"]})
    assert all(
        stage["provenance"]["executor_model"] == "stronger-model" for stage in second["stages"]
    )
    with database.connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM semantic_jobs WHERE scope_type = 'module'"
            ).fetchone()[0]
            == module_jobs
        )
    third = engine.start_fresh_eyes_review(stats.repository_id, repository, config, restart=True)
    assert third["review"]["review_generation"] == 3
    with pytest.raises(ValueError, match="Finish or retry"):
        engine.start_fresh_eyes_review(stats.repository_id, repository, config, restart=True)


def test_restart_requires_an_earlier_review_and_legacy_plan_values_are_bounded(
    repository, database
):
    _enable_agent_semantics(repository)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)

    with pytest.raises(ValueError, match="Start the first"):
        SemanticEngine(database).start_fresh_eyes_review(
            stats.repository_id, repository, config, restart=True
        )
    assert fresh_eyes_plan_options({"interface_hash": "invalid"}) == (2, 1)


def test_implementation_changes_reuse_reference_but_capability_changes_invalidate_it(
    repository, database
):
    _enable_agent_semantics(repository)
    config = load_config(repository)
    first = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    _finish_work(engine, first.repository_id, repository, config)
    engine.start_fresh_eyes_review(first.repository_id, repository, config)
    _finish_work(engine, first.repository_id, repository, config, prefix="first-review")
    first_review = engine.fresh_eyes_status(first.repository_id, config.semantic)
    first_proposal_ids = [item["document_id"] for item in first_review["stages"][:2]]

    util = repository / "pkg" / "util.py"
    util.write_text(
        util.read_text(encoding="utf-8").replace("value * 2", "value * 3"), encoding="utf-8"
    )
    second = RepositoryScanner(database).scan(repository)
    _finish_work(engine, second.repository_id, repository, config, prefix="implementation")
    reused = engine.start_fresh_eyes_review(second.repository_id, repository, config)
    assert reused["plan_stage"] == "fresh_eyes_comparison"
    with database.connect() as connection:
        kinds = [
            row[0]
            for row in connection.execute(
                "SELECT job_kind FROM semantic_jobs WHERE snapshot_id = ? AND scope_type = 'fresh_eyes'",
                (second.snapshot_id,),
            ).fetchall()
        ]
    assert kinds == ["fresh_comparison"]
    second_status = engine.fresh_eyes_status(second.repository_id, config.semantic)
    assert [item["document_id"] for item in second_status["stages"][:2]] == first_proposal_ids
    _finish_work(engine, second.repository_id, repository, config, prefix="second-review")
    reused_manifests = engine.fresh_eyes_status(second.repository_id, config.semantic)[
        "input_manifests"
    ]
    assert len(reused_manifests) == 5
    assert sum(item["job_kind"] == "fresh_proposal" for item in reused_manifests) == 2

    util.write_text(
        util.read_text(encoding="utf-8").replace("value * 3", "value * 4"), encoding="utf-8"
    )
    third = RepositoryScanner(database).scan(repository)
    _finish_work(engine, third.repository_id, repository, config, prefix="capability-baseline")
    with database.transaction() as connection:
        row = connection.execute(
            """
            SELECT sd.id, sd.value_json FROM semantic_scope_states ss
            JOIN semantic_documents sd ON sd.id = ss.context_document_id
            WHERE ss.snapshot_id = ? AND ss.scope_type = 'repository'
            """,
            (third.snapshot_id,),
        ).fetchone()
        charter = json.loads(row["value_json"])
        charter["capability_brief"]["observable_capabilities"].append(
            "Expose a newly required public export."
        )
        connection.execute(
            "UPDATE semantic_documents SET value_json = ? WHERE id = ?",
            (json.dumps(charter, sort_keys=True), int(row["id"])),
        )
    invalidated = engine.start_fresh_eyes_review(third.repository_id, repository, config)
    assert invalidated["plan_stage"] == "fresh_eyes_proposals"
    assert invalidated["review"]["invalidation_reason"].startswith("Capability fingerprint changed")
    with database.connect() as connection:
        proposal_jobs = connection.execute(
            """
            SELECT COUNT(*) FROM semantic_jobs WHERE snapshot_id = ?
              AND scope_type = 'fresh_eyes' AND job_kind = 'fresh_proposal'
            """,
            (third.snapshot_id,),
        ).fetchone()[0]
    assert proposal_jobs == 2

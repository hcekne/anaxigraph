from __future__ import annotations

import json
import re
import subprocess

import pytest
from fresh_eyes_support import (
    CODEX_EXECUTOR,
    TWO_EXECUTORS,
    TwoExecutorReview,
)
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
    agent_effort="",
):
    kinds = []
    for index in range(500):
        packet = engine.claim_agent_work(
            repository_id,
            repository,
            config,
            agent_id=f"{prefix}-{index}",
            agent_model=agent_model,
            agent_effort=agent_effort,
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


def _two_executor_review(repository, database, *, proposal_count=2) -> TwoExecutorReview:
    """Finish the baseline with both executors, then start one review for them to share."""
    _enable_agent_semantics(repository)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    review = TwoExecutorReview(
        SemanticEngine(database),
        stats.repository_id,
        repository,
        config,
        dossier_factory=_agent_dossier,
    )
    baseline = review.run_until_complete()
    assert {executor for executor, _ in baseline} == set(TWO_EXECUTORS)
    started = review.engine.start_fresh_eyes_review(
        stats.repository_id, repository, config, proposal_count=proposal_count
    )
    assert started["status"] == "started"
    return review


def test_two_host_executors_share_one_fresh_eyes_review(repository, database):
    review = _two_executor_review(repository, database)

    stages = review.run_until_complete()

    kinds = [kind for _, kind in stages]
    assert kinds[0] == "fresh_adjudication"
    assert kinds.count("fresh_proposal") == 9
    assert kinds.count("fresh_comparison") == 3
    assert kinds[-1] == "fresh_review"
    assert {executor for executor, _ in stages} == set(TWO_EXECUTORS)
    result = review.engine.fresh_eyes_status(review.repository_id, review.config.semantic)
    assert result["state"] == "current"
    assert {
        item["provenance"]["executor_id"]
        for scope in result["scope_reviews"]
        for item in scope["alternatives"]
    } == set(TWO_EXECUTORS)
    assert [claim["status"] for claim in review.claims[-2:]] == ["complete", "complete"]
    assert result["isolation"]["status"] == "unverified"
    for claim in review.claims:
        if str(claim.get("kind", "")).startswith("fresh_"):
            assert claim["request"]["information_boundary"]["mode"] == "implementation_blind"
            assert "current_system" not in claim["request"]


def test_second_executor_is_told_busy_while_a_peer_holds_a_fresh_eyes_stage(repository, database):
    review = _two_executor_review(repository, database)
    hierarchy = review.claim(CODEX_EXECUTOR)
    review.submit(hierarchy)
    held = review.hold_one_each("fresh_proposal")
    third = review.claim(CODEX_EXECUTOR)

    blocked = review.claim(CODEX_EXECUTOR)

    assert blocked["status"] == "busy"
    assert blocked["semantic"]["semantically_ready"] is True
    assert blocked["semantic"]["jobs"]["running"] == 3
    review.submit_all(held)
    review.submit(third)
    remaining = [kind for _, kind in review.run_until_complete()]
    assert remaining.count("fresh_proposal") == 6
    assert remaining.count("fresh_comparison") == 3
    assert remaining[-1] == "fresh_review"


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
    assert first["job"]["kind"] == "fresh_adjudication"
    proposal_packet = first["analysis_request"]
    assert set(proposal_packet) >= {
        "capability_projection",
        "information_boundary",
    }
    assert "current_system" not in proposal_packet
    assert "responsibility_map" not in proposal_packet
    assert "recent_history" not in proposal_packet
    assert "pkg/core.py" not in str(proposal_packet["capability_projection"])
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
    assert review_kinds.count("fresh_proposal") == 9
    assert review_kinds.count("fresh_comparison") == 3
    assert review_kinds[-1] == "fresh_review"
    comparison_request = next(
        item for item in review_requests if item["analysis_kind"] == "fresh_comparison"
    )
    assert "current_system" not in comparison_request
    assert len(comparison_request["alternatives"]) == 3
    assert all("current_system" not in item for item in review_requests)
    result = restarted.fresh_eyes_status(stats.repository_id, config.semantic)
    assert result["state"] == "current"
    assert result["ready"] is True
    assert result["counts"]["retained_alternatives"] == 9
    assert result["recommendations"] == []
    assert result["strategy"]["contract_version"] == "functional-review-v2"
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
        agent_effort="high",
    )

    assert kinds[0] == "fresh_adjudication"
    assert kinds.count("fresh_proposal") == 9
    assert kinds.count("fresh_comparison") == 3
    assert kinds[-1] == "fresh_review"
    second = engine.fresh_eyes_status(stats.repository_id, config.semantic)
    assert second["review_generation"] == 2
    assert first_ids.isdisjoint({stage["document_id"] for stage in second["stages"]})
    assert all(
        stage["provenance"]["executor_model"] == "stronger-model" for stage in second["stages"]
    )
    assert all(stage["provenance"]["executor_effort"] == "high" for stage in second["stages"])
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
    assert reused["plan_stage"] == "fresh_eyes_complete"
    with database.connect() as connection:
        kinds = [
            row[0]
            for row in connection.execute(
                "SELECT job_kind FROM semantic_jobs WHERE snapshot_id = ? AND scope_type = 'fresh_eyes'",
                (second.snapshot_id,),
            ).fetchall()
        ]
    assert kinds == []
    second_status = engine.fresh_eyes_status(second.repository_id, config.semantic)
    assert [item["document_id"] for item in second_status["stages"][:2]] == first_proposal_ids
    _finish_work(engine, second.repository_id, repository, config, prefix="second-review")
    assert (
        engine.fresh_eyes_status(second.repository_id, config.semantic)["counts"]
        == first_review["counts"]
    )

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
    assert invalidated["plan_stage"] == "fresh_eyes_functional_brief"
    assert invalidated["review"]["functional_brief"] is None
    with database.connect() as connection:
        proposal_jobs = connection.execute(
            """
            SELECT COUNT(*) FROM semantic_jobs WHERE snapshot_id = ?
              AND scope_type = 'fresh_eyes' AND job_kind = 'fresh_proposal'
            """,
            (third.snapshot_id,),
        ).fetchone()[0]
    assert proposal_jobs == 0


def _generations(engine, repository_id, config):
    return engine.fresh_eyes_status(repository_id, config.semantic)["generations"]


def test_generation_index_lists_every_rerun_with_provenance(repository, database):
    _enable_agent_semantics(repository)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    _finish_work(engine, stats.repository_id, repository, config)
    engine.start_fresh_eyes_review(stats.repository_id, repository, config)
    _finish_work(engine, stats.repository_id, repository, config, prefix="one", agent_model="m1")
    engine.start_fresh_eyes_review(stats.repository_id, repository, config, restart=True)
    _finish_work(engine, stats.repository_id, repository, config, prefix="two", agent_model="m2")
    engine.start_fresh_eyes_review(stats.repository_id, repository, config, restart=True)
    _finish_work(engine, stats.repository_id, repository, config, prefix="three", agent_model="m3")

    bundles = _generations(engine, stats.repository_id, config)

    assert [item["generation"] for item in bundles] == [1, 2, 3]
    assert [item["executor_models"] for item in bundles] == [["m1"], ["m2"], ["m3"]]
    assert [item["state"] for item in bundles] == ["superseded", "superseded", "current"]
    assert [item["ready"] for item in bundles] == [False, False, True]
    assert [len(item["stages"]) for item in bundles] == [14, 14, 14]
    documents = [set(item["document_ids"]) for item in bundles]
    assert all(len(item) == 14 for item in documents)
    assert len(set().union(*documents)) == 42
    for bundle in bundles:
        assert bundle["recommendation_count"] == 0
        assert bundle["rejected_idea_count"] == 0
        assert bundle["review_document_id"] in bundle["document_ids"]
        assert bundle["telemetry"]["stage_count"] == 14
        assert all(item["duration_ms"] >= 0 for item in bundle["telemetry"]["stages"])
        assert all(item["attempts_observed"] >= 1 for item in bundle["telemetry"]["stages"])
    review = engine.fresh_eyes_status(stats.repository_id, config.semantic)
    assert review["generations"][-2]["generation"] == 2
    assert review["generations"][-2]["review_document_id"] == bundles[1]["review_document_id"]


def test_generation_index_attributes_legacy_jobs_without_manifest_generation(repository, database):
    _enable_agent_semantics(repository)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    _finish_work(engine, stats.repository_id, repository, config)
    engine.start_fresh_eyes_review(stats.repository_id, repository, config)
    _finish_work(engine, stats.repository_id, repository, config, prefix="legacy")
    with database.transaction() as connection:
        connection.execute(
            "UPDATE semantic_jobs SET metadata_json = '{}' WHERE scope_type = 'fresh_eyes'"
        )

    bundles = _generations(engine, stats.repository_id, config)

    assert [item["generation"] for item in bundles] == [1]
    assert bundles[0]["state"] == "current"
    assert len(bundles[0]["document_ids"]) == 14
    assert engine.fresh_eyes_status(stats.repository_id, config.semantic)["ready"] is True


def test_generation_spanning_snapshots_groups_reused_proposals(repository, database):
    _enable_agent_semantics(repository)
    config = load_config(repository)
    first = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    _finish_work(engine, first.repository_id, repository, config)
    engine.start_fresh_eyes_review(first.repository_id, repository, config)
    _finish_work(engine, first.repository_id, repository, config, prefix="first-review")
    util = repository / "pkg" / "util.py"
    util.write_text(
        util.read_text(encoding="utf-8").replace("value * 2", "value * 3"), encoding="utf-8"
    )
    second = RepositoryScanner(database).scan(repository)
    _finish_work(engine, second.repository_id, repository, config, prefix="implementation")
    engine.start_fresh_eyes_review(second.repository_id, repository, config)
    _finish_work(engine, second.repository_id, repository, config, prefix="second-review")

    bundles = _generations(engine, second.repository_id, config)

    assert [item["generation"] for item in bundles] == [1, 1]
    assert bundles[0]["snapshot_id"] != bundles[1]["snapshot_id"]
    assert [item["state"] for item in bundles] == ["superseded", "current"]
    reused = [item["document_id"] for item in bundles[1]["stages"] if ":proposal:" in item["key"]]
    assert reused == [
        item["document_id"] for item in bundles[0]["stages"] if ":proposal:" in item["key"]
    ]
    assert [item["job_status"] for item in bundles[1]["stages"][:2]] == ["reused", "reused"]
    assert bundles[0]["review_document_id"] == bundles[1]["review_document_id"]


def _snapshot_metadata(database, snapshot_id: int) -> dict:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT metadata_json FROM snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()
    return json.loads(row["metadata_json"])


def test_fresh_eyes_review_warns_when_produced_from_a_dirty_checkout(repository, database):
    _enable_agent_semantics(repository)
    config = load_config(repository)
    engine = SemanticEngine(database)
    stats = RepositoryScanner(database).scan(repository)

    dirty = engine.fresh_eyes_status(stats.repository_id, config.semantic)

    provenance = dirty["snapshot"]
    assert provenance["snapshot_id"] == stats.snapshot_id
    assert provenance["dirty"] is True
    assert re.fullmatch("[0-9a-f]{64}", provenance["working_tree_fingerprint"])
    metadata = _snapshot_metadata(database, stats.snapshot_id)
    assert provenance["working_tree_fingerprint"] == metadata["working_tree_fingerprint"]
    assert re.fullmatch("[0-9a-f]{40}", provenance["commit_sha"])
    assert "dirty checkout" in dirty["caveats"][0]
    assert provenance["commit_sha"][:12] in dirty["caveats"][0]

    subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-qm", "Enable agent"], check=True)
    committed = RepositoryScanner(database).scan(repository)
    clean = engine.fresh_eyes_status(committed.repository_id, config.semantic)

    assert clean["snapshot"]["dirty"] is False
    assert clean["snapshot"]["commit_sha"] != provenance["commit_sha"]
    assert not any("dirty checkout" in caveat for caveat in clean["caveats"])

from __future__ import annotations

import pytest
from semantic_support import _agent_dossier, _enable_agent_semantics

from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.understanding import SemanticEngine


def _finish_work(engine, repository_id, repository, config, *, prefix, agent_model="fixture-model"):
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
        )
    raise AssertionError("Semantic work did not converge")


def test_status_can_select_a_superseded_generation(repository, database):
    _enable_agent_semantics(repository)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    _finish_work(engine, stats.repository_id, repository, config, prefix="baseline")
    engine.start_fresh_eyes_review(stats.repository_id, repository, config)
    _finish_work(engine, stats.repository_id, repository, config, prefix="one", agent_model="m1")
    first = engine.fresh_eyes_status(stats.repository_id, config.semantic)
    engine.start_fresh_eyes_review(stats.repository_id, repository, config, restart=True)
    _finish_work(engine, stats.repository_id, repository, config, prefix="two", agent_model="m2")

    selected = engine.fresh_eyes_status(stats.repository_id, config.semantic, generation=1)

    assert selected["review_generation"] == 1
    assert selected["state"] == "superseded"
    assert selected["ready"] is False
    assert selected["identity"].endswith(":generation-1")
    assert selected["recommendations"] == first["recommendations"]
    assert selected["strategy"] == first["strategy"]
    assert [item["document_id"] for item in selected["stages"]] == [
        item["document_id"] for item in first["stages"]
    ]
    assert all(item["provenance"]["executor_model"] == "m1" for item in selected["stages"])
    assert len(selected["input_manifests"]) == 5
    assert all(selected["fingerprints"].values())
    assert selected["previous_review"] is None
    assert any("cannot be restarted or retried" in item for item in selected["caveats"])
    assert "start" not in selected["next_action"].lower()
    current = engine.fresh_eyes_status(stats.repository_id, config.semantic, generation=2)
    assert current["review_generation"] == 2
    assert current["state"] == "current"
    assert current["ready"] is True


def test_unknown_generation_is_rejected_with_available_list(repository, database):
    _enable_agent_semantics(repository)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    _finish_work(engine, stats.repository_id, repository, config, prefix="baseline")
    engine.start_fresh_eyes_review(stats.repository_id, repository, config)
    _finish_work(engine, stats.repository_id, repository, config, prefix="one")

    with pytest.raises(ValueError, match="available generations: 1"):
        engine.fresh_eyes_status(stats.repository_id, config.semantic, generation=99)


def test_a_rescanned_snapshot_reports_stale_with_the_recorded_generations(repository, database):
    _enable_agent_semantics(repository)
    config = load_config(repository)
    first = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    _finish_work(engine, first.repository_id, repository, config, prefix="baseline")
    engine.start_fresh_eyes_review(first.repository_id, repository, config)
    _finish_work(engine, first.repository_id, repository, config, prefix="one")
    reviewed = engine.fresh_eyes_status(first.repository_id, config.semantic)
    charter = repository / "pkg" / "extra.py"
    charter.write_text("def added(value: int) -> int:\n    return value + 1\n", encoding="utf-8")
    second = RepositoryScanner(database).scan(repository)

    stale = engine.fresh_eyes_status(second.repository_id, config.semantic)

    assert stale["state"] == "stale"
    assert stale["ready"] is False
    assert stale["snapshot_id"] == second.snapshot_id
    assert stale["previous_review"]["generation"] == 1
    assert stale["previous_review"]["snapshot_id"] == first.snapshot_id
    assert [item["generation"] for item in stale["generations"]] == [1]
    assert stale["generations"][0]["state"] == "superseded"
    assert stale["telemetry"]["stage_count"] == 0
    recorded = engine.fresh_eyes_status(second.repository_id, config.semantic, generation=1)
    assert recorded["recommendations"] == reviewed["recommendations"]


def test_compare_payload_reports_alignment_between_two_generations(repository, database):
    _enable_agent_semantics(repository)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    _finish_work(engine, stats.repository_id, repository, config, prefix="baseline")
    engine.start_fresh_eyes_review(stats.repository_id, repository, config)
    _finish_work(engine, stats.repository_id, repository, config, prefix="one", agent_model="m1")
    engine.start_fresh_eyes_review(stats.repository_id, repository, config, restart=True)
    _finish_work(engine, stats.repository_id, repository, config, prefix="two", agent_model="m2")

    compared = engine.fresh_eyes_status(
        stats.repository_id, config.semantic, generation=1, compare_with=2
    )

    assert compared["review_generation"] == 1
    alignment = compared["alignment"]
    assert alignment["method"] == "lexical"
    assert alignment["contract_version"] == "fresh-eyes-alignment-v1"
    assert alignment["left"]["review_generation"] == 1
    assert alignment["right"]["review_generation"] == 2
    assert alignment["left"]["state"] == "superseded"
    assert alignment["right"]["state"] == "current"
    assert [item["left"]["title"] for item in alignment["aligned"]] == [
        "Consolidate duplicate orchestration"
    ]
    conflicts = [item["kind"] for item in alignment["conflicting"]]
    assert conflicts == ["rejected_vs_recommended"]
    assert alignment["conflicting"][0]["right"]["title"] == "Add a general workflow engine"
    assert alignment["unmatched_left"] == []
    assert [item["title"] for item in alignment["unmatched_right"]] == [
        "Bound the working tree drift window"
    ]
    assert any("lexical" in caveat for caveat in alignment["caveats"])
    assert alignment["facts"]["left"]["recommendations"] == 1
    assert alignment["facts"]["right"]["recommendations"] == 3
    assert len(alignment["fingerprint"]) == 64
    plain = engine.fresh_eyes_status(stats.repository_id, config.semantic, generation=1)
    assert "alignment" not in plain
    assert {key: compared[key] for key in plain} == plain


def test_comparing_a_generation_with_itself_is_labelled_as_such(repository, database):
    _enable_agent_semantics(repository)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    _finish_work(engine, stats.repository_id, repository, config, prefix="baseline")
    engine.start_fresh_eyes_review(stats.repository_id, repository, config)
    _finish_work(engine, stats.repository_id, repository, config, prefix="one")

    compared = engine.fresh_eyes_status(stats.repository_id, config.semantic, compare_with=1)

    assert compared["alignment"]["left"] == compared["alignment"]["right"]
    assert compared["alignment"]["caveats"][-1].startswith("Both sides name the same")
    assert len(compared["alignment"]["aligned"]) == 1
    with pytest.raises(ValueError, match="generation 9 was never recorded"):
        engine.fresh_eyes_status(stats.repository_id, config.semantic, compare_with=9)

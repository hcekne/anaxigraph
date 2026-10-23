"""Saved functional alternatives survive interruption, reruns and implementation-only changes."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from fresh_eyes_support import baseline_review, prepared_review
from saved_fresh_eyes_support import seed_legacy_review

from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.understanding import SemanticEngine


def test_resume_reuses_each_completed_alternative(repository, database):
    review = prepared_review(repository, database)
    saved = []
    while len(saved) < 3:
        packet = review.claim(review.executors[0])
        assert packet["status"] == "work"
        review.submit(packet)
        if packet["job"]["kind"] == "fresh_proposal":
            saved.append(packet["job"]["id"])
    review.engine = SemanticEngine(database)
    review.run_until_complete()
    status = review.engine.fresh_eyes_status(review.repository_id, review.config.semantic)
    assert status["ready"] and status["counts"]["retained_alternatives"] == 9
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT id,status FROM semantic_jobs WHERE id IN (?,?,?)", saved
        ).fetchall()
        assert {row["status"] for row in rows} == {"completed"}
        total = connection.execute(
            "SELECT COUNT(*) FROM semantic_jobs WHERE job_kind='fresh_proposal'"
        ).fetchone()[0]
        assert total == 9


def test_rerun_keeps_prior_functional_alternatives_readable(repository, database):
    review = prepared_review(repository, database)
    review.run_until_complete()
    first = review.engine.fresh_eyes_status(review.repository_id, review.config.semantic)
    identities = {item["id"] for scope in first["scope_reviews"] for item in scope["alternatives"]}
    started = review.engine.start_fresh_eyes_review(
        review.repository_id, repository, review.config, restart=True
    )
    assert started["review"]["review_generation"] == 2
    review.run_until_complete()
    historical = review.engine.fresh_eyes_status(
        review.repository_id, review.config.semantic, generation=1
    )
    assert historical["state"] == "superseded" and not historical["ready"]
    assert identities == {
        item["id"] for scope in historical["scope_reviews"] for item in scope["alternatives"]
    }


def test_implementation_edit_reuses_compatible_functional_review(repository, database):
    review = prepared_review(repository, database)
    review.run_until_complete()
    first = review.engine.fresh_eyes_status(review.repository_id, review.config.semantic)
    path = repository / "pkg" / "util.py"
    path.write_text(path.read_text().replace("value * 2", "value + value"))
    RepositoryScanner(database).scan(repository)
    review.config = load_config(repository)
    review.run_until_complete()
    review.engine.start_fresh_eyes_review(review.repository_id, repository, review.config)
    jobs = review.run_until_complete()
    assert not [kind for _executor, kind in jobs if kind.startswith("fresh_")]
    second = review.engine.fresh_eyes_status(review.repository_id, review.config.semantic)
    assert second["ready"]
    assert first["functional_brief"]["revision"] == second["functional_brief"]["revision"]
    assert first["counts"] == second["counts"]


def test_fresh_eyes_is_queued_while_independent_pattern_reviews_are_unfinished(
    repository, database
):
    review = baseline_review(repository, database)
    full = replace(review.config, semantic=replace(review.config.semantic, detailed_reviews=True))
    review.engine.plan(review.repository_id, repository, full)
    review.config = full
    assessment = review.claim(review.executors[0])
    assert assessment["job"]["kind"] == "pattern_assessment"
    review.submit(assessment)
    review.engine.plan(review.repository_id, repository, full)
    started = review.engine.start_fresh_eyes_review(review.repository_id, repository, full)
    assert started["plan_stage"] == "fresh_eyes_functional_brief"
    with database.connect() as connection:
        counts = dict(
            connection.execute(
                "SELECT job_kind,COUNT(*) FROM semantic_jobs WHERE status='pending' GROUP BY job_kind"
            )
        )
    assert counts["pattern_review"] > 0
    assert counts["fresh_adjudication"] == 1


def test_oversized_blind_claim_fails_durably_without_evidence_pages(
    repository, database, monkeypatch
):
    review = baseline_review(repository, database)
    config = replace(
        review.config,
        semantic=replace(review.config.semantic, max_source_chars=512, max_attempts=1),
    )
    review.engine.start_fresh_eyes_review(review.repository_id, repository, config)

    def refuse_packet(*_args, **_kwargs):
        raise AssertionError("Oversized blind evidence must never become a work packet")

    monkeypatch.setattr(
        "anaxigraph.semantic_agent_contracts.SemanticAgentContractService.work_response",
        refuse_packet,
    )
    with pytest.raises(ValueError, match="all functional evidence inline"):
        review.engine.claim_agent_work(
            review.repository_id, repository, config, agent_id="bounded-blind-worker"
        )
    with database.connect() as connection:
        jobs = connection.execute(
            "SELECT status,error,metadata_json FROM semantic_jobs WHERE scope_type='fresh_eyes'"
        ).fetchall()
    assert len(jobs) == 1 and jobs[0]["status"] == "failed"
    assert "functional packet exceeds" in jobs[0]["error"]
    assert "evidence_manifest" not in jobs[0]["metadata_json"]
    assert list(repository.rglob("semantic-evidence-*")) == []


def test_interrupted_legacy_review_auto_resumes_blindly_without_losing_originals(
    repository, database
):
    review = baseline_review(repository, database)
    snapshot = database.latest_snapshot(review.repository_id)["id"]
    originals = seed_legacy_review(database, review.repository_id, snapshot)
    with database.transaction() as connection:
        before = [
            tuple(row)
            for row in connection.execute(
                "SELECT id,value_json,provider,model FROM semantic_document_values WHERE scope_type='fresh_eyes' ORDER BY id"
            )
        ]
        connection.execute(
            "UPDATE semantic_scope_states SET status='requested',interface_hash=? "
            "WHERE scope_type='fresh_eyes' AND scope_key='plan'",
            ('2:1::"Improve pkg/core.py"',),
        )
        connection.execute(
            "INSERT INTO semantic_jobs(repository_id,snapshot_id,scope_type,scope_key,job_kind,reason,status,"
            "input_hash,provider,model,prompt_version,schema_version,metadata_json,available_at) "
            "VALUES(?,?,'fresh_eyes','proposal:b','fresh_proposal','interrupted-v1','pending',"
            "'legacy-pending','agent','','old-v1','fresh-eyes-proposal-v1','{}','2000-01-01')",
            (review.repository_id, snapshot),
        )
    review.engine.plan(review.repository_id, repository, review.config)
    status = review.engine.fresh_eyes_status(review.repository_id, review.config.semantic)
    assert status["review_generation"] == 2 and status["review_goal"] == ""
    assert not status["ready"]
    with database.connect() as connection:
        assert before == [
            tuple(row)
            for row in connection.execute(
                "SELECT id,value_json,provider,model FROM semantic_document_values WHERE scope_type='fresh_eyes' ORDER BY id"
            )
        ]
        assert (
            connection.execute(
                "SELECT status FROM semantic_jobs WHERE input_hash='legacy-pending'"
            ).fetchone()[0]
            == "superseded"
        )
        job = connection.execute(
            "SELECT metadata_json FROM semantic_jobs WHERE scope_key='functional:brief'"
        ).fetchone()
        assert "pkg/core.py" not in job["metadata_json"]
        assert json.loads(job["metadata_json"])["input_manifest"]["review_generation"] == 2
    archive = review.engine.fresh_eyes_status(
        review.repository_id, review.config.semantic, generation=1
    )
    assert set(archive["archive"]["document_ids"]) == set(originals.values())

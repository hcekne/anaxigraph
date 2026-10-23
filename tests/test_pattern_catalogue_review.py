"""Catalogue coverage is work identity, independent of ranking and display limits."""

from __future__ import annotations

import copy
import json
from dataclasses import replace

import httpx
import pytest
from semantic_support import _pattern_evaluation
from test_pattern_candidates import _projection, _six_level_evidence
from test_scan_recovery_contracts import _strict_violations

from anaxigraph.api import create_app
from anaxigraph.config import load_config
from anaxigraph.pattern_catalog import bundled_pattern_catalog
from anaxigraph.pattern_catalog_models import PatternCatalog
from anaxigraph.pattern_catalogue_contract import resolved_evaluation
from anaxigraph.pattern_catalogue_plan import build_catalogue_assessment_plan
from anaxigraph.pattern_catalogue_query import PatternCatalogueQuery
from anaxigraph.pattern_evaluation_contract import (
    pattern_response_schema,
    validated_pattern_response,
)
from anaxigraph.pattern_intelligence import PatternIntelligenceService
from anaxigraph.persistence.pattern_review_references import expanded_pattern_review
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic import _codex_schema
from anaxigraph.semantic_contract import SemanticAnalysisError
from anaxigraph.semantic_freshness import semantic_digest
from anaxigraph.semantic_lease_claim import claim_next_job
from anaxigraph.semantic_pattern_plan import SemanticPatternPlanner
from anaxigraph.semantic_pattern_requests import pattern_request
from anaxigraph.semantic_results import SemanticPersistenceService
from anaxigraph.understanding import SemanticEngine


def test_every_card_is_considered_without_positive_evidence_or_target_scope_filter():
    catalog = bundled_pattern_catalog()
    projection = _projection()
    plan = build_catalogue_assessment_plan(catalog, projection)

    assert {item.pattern_key for item in plan.candidates} == {
        card.stable_key for card in catalog.cards
    }
    assert len(plan.candidates) == len(catalog.cards)
    assert {item.target.key for item in plan.candidates} == {"repository:root"}
    assert all("catalogue_coverage" in item.selection_reasons for item in plan.candidates)
    assert not plan.skipped_by_reason and not plan.omitted_candidates
    assert plan.as_dict()["expected_pattern_ids"] == [card.stable_key for card in catalog.cards]


def test_custom_catalogue_above_old_total_limit_is_not_truncated():
    bundled = bundled_pattern_catalog()
    extras = [
        replace(bundled.cards[0], stable_key=f"custom-pattern-{i}", name=f"Custom {i}")
        for i in range(201)
    ]
    catalog = PatternCatalog(
        "custom", tuple(sorted((*bundled.cards, *extras), key=lambda c: c.stable_key)), 1
    )

    plan = build_catalogue_assessment_plan(catalog, _projection(*_six_level_evidence()))

    assert len(plan.candidates) == len(bundled.cards) + 201 > 200
    assert plan.catalog_fingerprint == catalog.fingerprint
    assert len(set(plan.expected_pattern_ids)) == len(plan.candidates)


def _request(kind="pattern_assessment", pattern="pipeline"):
    catalog = bundled_pattern_catalog()
    candidate = next(
        item
        for item in build_catalogue_assessment_plan(
            catalog, _projection(*_six_level_evidence())
        ).candidates
        if item.pattern_key == pattern
    )
    return {
        "analysis_kind": kind,
        "candidate": candidate.as_dict(),
        "pattern": catalog.card(pattern).as_dict(),
        "score_contract_version": "pattern-scores-v3",
    }


@pytest.mark.parametrize(
    "pattern", ["adapter", "pipeline", "immutable-data", "bulkhead", "cache-aside"]
)
def test_absent_patterns_from_different_families_can_be_useful_without_a_bug(pattern):
    request = _request(pattern=pattern)
    value = _pattern_evaluation(request)
    value["scores"]["conformance"]["value"] = 90
    value["scores"]["opportunity"]["value"] = 90
    value["presence"] = "partial"
    value["rationale"] = "Current conformance elsewhere does not decide this placement's benefit."

    result = validated_pattern_response(value, request)

    assert result.value["recommendation"] == "introduce"
    assert result.value["pros"] and result.value["cons"] and result.value["placements"]


@pytest.mark.parametrize("field", ["pros", "cons", "placements"])
def test_catalogue_assessment_requires_explicit_contextual_tradeoffs(field):
    request = _request()
    value = _pattern_evaluation(request)
    value.pop(field)
    with pytest.raises(SemanticAnalysisError, match="missing required fields"):
        validated_pattern_response(value, request)


def _review_request():
    request = _request("pattern_review")
    request["assessment"] = _pattern_evaluation(request)
    request["assessment_fingerprint"] = semantic_digest(request["assessment"])
    request["assessment_input_hash"] = "e" * 64
    value = {
        "review_contract_version": "pattern-review-v2",
        "candidate_fingerprint": request["candidate"]["input_fingerprint"],
        "assessment_fingerprint": request["assessment_fingerprint"],
        "assessment_input_hash": request["assessment_input_hash"],
        "verdict": "approve",
        "summary": "The evidence supports the stated tradeoffs.",
        "issues": [],
        "evaluation": None,
        "competing_interpretations": [],
        "confidence": 80,
        "evidence": ["repository:root"],
    }
    return request, value


def test_approved_review_references_canonical_assessment_instead_of_copying_it():
    request, value = _review_request()
    result = validated_pattern_response(value, request)
    assert result.value["evaluation"] is None
    assert resolved_evaluation(result.value, request["assessment"]) == request["assessment"]
    expanded = {**value, "evaluation": copy.deepcopy(request["assessment"])}
    assert validated_pattern_response(expanded, request).value["evaluation"] is None


def test_review_cannot_substitute_a_different_assessment_or_omit_a_revision():
    request, value = _review_request()
    wrong = {**value, "assessment_fingerprint": "f" * 64}
    with pytest.raises(ValueError, match="assessment_fingerprint"):
        validated_pattern_response(wrong, request)
    wrong = {**value, "assessment_input_hash": "f" * 64}
    with pytest.raises(ValueError, match="assessment_input_hash"):
        validated_pattern_response(wrong, request)
    with pytest.raises(ValueError, match="must supply"):
        validated_pattern_response({**value, "verdict": "revise"}, request)


def test_catalogue_nullable_review_and_full_assessment_have_strict_wire_schemas():
    for request in (_request(), _review_request()[0]):
        assert _strict_violations(_codex_schema(pattern_response_schema(request))) == []


def _prepare(repository, database):
    stats = RepositoryScanner(database).scan(repository)
    semantic = replace(
        load_config(repository).semantic, enabled=True, provider="agent", detailed_reviews=True
    )
    with database.transaction() as connection:
        queued, complete = SemanticPatternPlanner().plan_patterns(
            connection,
            repository_id=stats.repository_id,
            snapshot_id=stats.snapshot_id,
            semantic=semantic,
            retry_failed=False,
        )
    assert queued == len(bundled_pattern_catalog().cards) and not complete
    return stats, semantic


@pytest.mark.anyio
async def test_catalogue_table_pages_missing_work_without_turning_it_into_poor_fit(
    repository, database
):
    stats = RepositoryScanner(database).scan(repository)
    app = create_app(database=database, repository=repository, enable_mcp=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/patterns/catalogue", params={"limit": 3, "offset": 3})
        manifest = await client.get(
            "/api/patterns/catalogue", params={"include_manifest": True, "limit": 1}
        )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["snapshot_id"] == stats.snapshot_id
    assert (
        result["catalogue"]["expected"]
        == result["catalogue"]["missing"]
        == len(bundled_pattern_catalog().cards)
    )
    assert result["returned"] == 3 and result["next_offset"] == 6
    assert all(
        item["scores"] is None and item["recommendation"] is None for item in result["items"]
    )
    assert not result["catalogue"]["complete"]
    assert "expected_ids" not in result["catalogue"]
    assert set(manifest.json()["catalogue"]["expected_ids"]) == {
        card.stable_key for card in bundled_pattern_catalog().cards
    }


def _claim(database, stats, semantic, job_id):
    return claim_next_job(
        database,
        stats.repository_id,
        semantic,
        worker_id="catalogue-test",
        lease_seconds=3600,
        lease_token_hash=None,
        executor_id="fixture",
        executor_model="fixture",
        job_ids=(job_id,),
    )


def test_manifest_durable_review_and_unchanged_resume_do_not_repeat_saved_work(
    repository, database
):
    stats, semantic = _prepare(repository, database)
    service = PatternIntelligenceService(database)
    first = service.catalogue(stats.repository_id)
    assert first["catalogue"]["manifest_saved"] and first["catalogue"]["considered"] == len(
        bundled_pattern_catalog().cards
    )
    with database.connect() as connection:
        job_id = connection.execute(
            "SELECT id FROM semantic_jobs WHERE job_kind = 'pattern_assessment' ORDER BY id LIMIT 1"
        ).fetchone()[0]
    job = _claim(database, stats, semantic, job_id)
    request = pattern_request(database, job, repository, semantic)
    value = _pattern_evaluation(request)
    value["placements"][0]["target_key"] = "function:pkg/core.py#Calculator.calculate"
    persistence = SemanticPersistenceService(database)
    persistence.complete_job(job, validated_pattern_response(value, request), "agent", semantic)
    with database.connect() as connection:
        review_id = connection.execute(
            "SELECT id FROM semantic_jobs WHERE job_kind = 'pattern_review'"
        ).fetchone()[0]
    review = _claim(database, stats, semantic, review_id)
    review_request = pattern_request(database, review, repository, semantic)
    _, review_value = _review_request()
    review_value.update(
        candidate_fingerprint=job["metadata"]["candidate"]["input_fingerprint"],
        assessment_fingerprint=review_request["assessment_fingerprint"],
        assessment_input_hash=review_request["assessment_input_hash"],
    )
    persistence.complete_job(
        review, validated_pattern_response(review_value, review_request), "agent", semantic
    )
    after = service.catalogue(stats.repository_id)
    assert after["catalogue"]["rated"] == after["catalogue"]["reviewed"] == 1
    assert (
        after["catalogue"]["missing"] == len(bundled_pattern_catalog().cards) - 1
        and not after["catalogue"]["complete"]
    )
    with database.transaction() as connection:
        assert SemanticPatternPlanner().plan_patterns(
            connection,
            repository_id=stats.repository_id,
            snapshot_id=stats.snapshot_id,
            semantic=semantic,
            retry_failed=False,
        ) == (0, False)
        row = dict(
            connection.execute(
                "SELECT * FROM semantic_documents WHERE document_kind = 'pattern_review'"
            ).fetchone()
        )
        assert json.loads(row["value_json"])["evaluation"] is None
        assert expanded_pattern_review(connection, row)["evaluation"] == value
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM semantic_documents WHERE document_kind = 'pattern_manifest'"
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT attempts FROM semantic_jobs WHERE id = ?", (job_id,)
            ).fetchone()[0]
            == 1
        )
    page = service.catalogue(stats.repository_id, request=PatternCatalogueQuery(state="reviewed"))
    assert page["total"] == 1 and page["items"][0]["pros"] and page["items"][0]["cons"]
    local = service.query_targets(stats.repository_id, stats.snapshot_id, ["module:pkg/core.py"])
    assert len(local) == 1 and local[0]["placements"][0]["target_key"].startswith("function:")
    with database.transaction() as connection:
        invalid = json.loads(row["value_json"])
        invalid["assessment_fingerprint"] = "invalid"
        connection.execute(
            "UPDATE semantic_documents SET value_json = ? WHERE id = ?",
            (json.dumps(invalid), row["id"]),
        )
    # Scope-state labels cannot substitute for immutable expected-ID review coverage.
    with database.transaction() as connection:
        connection.execute(
            "UPDATE semantic_scope_states SET status='current' WHERE scope_type='pattern'"
        )
    status = SemanticEngine(database).status(stats.repository_id, semantic)["patterns"]
    assert not status["ready"] and status["catalogue"]["reviewed"] == 0
    assert status["catalogue"]["expected"] == len(bundled_pattern_catalog().cards)
    corrupted = service.catalogue(stats.repository_id)["catalogue"]
    assert corrupted["rated"] == 1 and corrupted["reviewed"] == 0 and not corrupted["complete"]

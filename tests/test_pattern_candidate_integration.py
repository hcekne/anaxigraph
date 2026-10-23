from __future__ import annotations

from semantic_support import _fake_provider, _semantic_config

from anaxigraph.config import load_config
from anaxigraph.pattern_candidate_query import PatternCandidateQuery
from anaxigraph.pattern_intelligence import PatternIntelligenceService
from anaxigraph.pattern_query import PatternEvaluationQuery
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.understanding import SemanticEngine


def test_catalogue_coverage_and_local_diagnostics_have_distinct_scopes(
    repository, database, tmp_path
):
    log = tmp_path / "candidate-query-semantic.log"
    provider = _fake_provider(tmp_path)
    _semantic_config(repository, provider, log, detailed_reviews=True)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    SemanticEngine(database).bootstrap(stats.repository_id, repository, config, until_complete=True)
    service = PatternIntelligenceService(database)
    evaluations = service.query(stats.repository_id, request=PatternEvaluationQuery(limit=100))
    coverage = service.catalogue(stats.repository_id)["catalogue"]
    assert coverage["complete"] and coverage["reviewed"] == coverage["expected"]
    assert {item["target"]["level"] for item in evaluations["items"]} == {"repository"}

    candidates = service.candidates(
        stats.repository_id,
        request=PatternCandidateQuery(
            pattern="strategy",
            level="module",
            selection="all",
            limit=100,
        ),
    )
    assert candidates["plan_ready"] is True
    assert candidates["selected_count"] == 0  # Placements are separate from catalogue assessment.
    assert candidates["total"] == candidates["targets_considered"]

    skipped = service.candidates(
        stats.repository_id,
        request=PatternCandidateQuery(
            pattern="circular-dependency",
            level="module",
            selection="skipped",
            limit=100,
        ),
    )
    assert skipped["skipped_count"] > 0
    assert skipped["total"] == skipped["skipped_count"]
    assert set(skipped["counts_by_reason"]) <= {
        "below_priority",
        "counter_evidence",
        "no_positive_evidence",
        "sparse_plan_bound",
    }

    selected = service.candidates(
        stats.repository_id,
        request=PatternCandidateQuery(
            pattern="modular-monolith",
            target="repository:root",
            selection="selected",
            include_evidence=True,
        ),
    )
    assert selected["total"] == 1
    assert selected["items"][0]["reason"] == "selected"
    signal = selected["items"][0]["details"]["signals"][0]
    assert signal["plain_language"]["what_was_checked"].startswith("AnaxiGraph checked")
    assert "not code quality" in signal["plain_language"]["evidence_strength"]["meaning"]

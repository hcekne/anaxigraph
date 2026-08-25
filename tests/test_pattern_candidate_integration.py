from __future__ import annotations

from semantic_support import _fake_provider, _semantic_config

from anaxigraph.config import load_config
from anaxigraph.pattern_candidate_query import PatternCandidateQuery
from anaxigraph.pattern_intelligence import PatternIntelligenceService
from anaxigraph.pattern_query import PatternEvaluationQuery
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.understanding import SemanticEngine


def test_current_sparse_plan_explains_selected_and_skipped_targets(repository, database, tmp_path):
    log = tmp_path / "candidate-query-semantic.log"
    provider = _fake_provider(tmp_path)
    _semantic_config(repository, provider, log)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    SemanticEngine(database).bootstrap(stats.repository_id, repository, config)
    service = PatternIntelligenceService(database)
    evaluations = service.query(stats.repository_id, request=PatternEvaluationQuery(limit=100))
    module_evaluation = next(
        item for item in evaluations["items"] if item["target"]["level"] == "module"
    )

    candidates = service.candidates(
        stats.repository_id,
        request=PatternCandidateQuery(
            pattern=module_evaluation["pattern"]["key"],
            level="module",
            selection="all",
            limit=100,
        ),
    )
    assert candidates["plan_ready"] is True
    assert candidates["selected_count"] > 0
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
            pattern=module_evaluation["pattern"]["key"],
            target=module_evaluation["target"]["key"],
            selection="selected",
            include_evidence=True,
        ),
    )
    assert selected["total"] == 1
    assert selected["items"][0]["reason"] == "selected"
    assert selected["items"][0]["details"]["signals"]

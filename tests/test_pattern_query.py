from __future__ import annotations

import urllib.parse

import pytest
from semantic_support import _fake_provider, _semantic_config

from anaxigraph.config import load_config
from anaxigraph.pattern_intelligence import PatternIntelligenceService
from anaxigraph.pattern_query import (
    PATTERN_QUERY_LIMIT,
    PATTERN_QUERY_MAX_LIMIT,
    PatternEvaluationQuery,
)
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_service import SemanticServiceTarget, service_pattern_evaluations
from anaxigraph.understanding import SemanticEngine


def test_pattern_query_defaults_are_bounded_and_explicit():
    query = PatternEvaluationQuery()

    assert query.limit == PATTERN_QUERY_LIMIT
    assert query.sort_by == "opportunity"
    assert query.filters() == {
        "target": "",
        "pattern": "",
        "level": "",
        "recommendation": "",
        "presence": "",
        "sort_by": "opportunity",
        "minimum_score": 0,
        "include_evidence": False,
    }


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("level", "package", "target level"),
        ("recommendation", "rewrite_everything", "recommendation"),
        ("presence", "maybe", "presence"),
        ("sort_by", "magic", "score sort"),
        ("minimum_score", -1, "minimum_score"),
        ("minimum_score", 101, "minimum_score"),
        ("limit", 0, "query limit"),
        ("limit", PATTERN_QUERY_MAX_LIMIT + 1, "query limit"),
        ("offset", -1, "offset"),
        ("target", "x" * 2_001, "target is too long"),
        ("pattern", "x" * 2_001, "pattern is too long"),
    ],
)
def test_pattern_query_rejects_unbounded_or_unknown_filters(field, value, message):
    with pytest.raises(ValueError, match=message):
        PatternEvaluationQuery(**{field: value})


def test_pattern_query_accepts_every_supported_dimension_and_direction():
    query = PatternEvaluationQuery(
        target="module:src/service.py",
        pattern="strategy",
        level="module",
        recommendation="introduce",
        presence="absent",
        sort_by="execution_safety",
        minimum_score=65,
        limit=1,
        offset=2,
        include_evidence=True,
    )

    assert query.filters()["target"] == "module:src/service.py"
    assert query.filters()["pattern"] == "strategy"
    assert query.filters()["include_evidence"] is True


def test_current_projection_supports_target_and_pattern_directions(repository, database, tmp_path):
    log = tmp_path / "pattern-query-semantic.log"
    provider = _fake_provider(tmp_path)
    _semantic_config(repository, provider, log)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    status = SemanticEngine(database).bootstrap(stats.repository_id, repository, config)["semantic"]

    service = PatternIntelligenceService(database)
    results = service.query(stats.repository_id, request=PatternEvaluationQuery(limit=100))

    assert results["total"] == status["patterns"]["finalized"]
    assert results["returned"] == results["total"]
    assert all(item["review"]["verdict"] == "approve" for item in results["items"])
    first = results["items"][0]
    language = first["plain_language"]
    assert language["version"] == "pattern-explanation-v2"
    assert language["conclusion"]
    assert language["what_anaxigraph_saw"]
    assert language["why_it_may_matter"]
    assert language["what_to_do"]
    assert language["reasons_not_to_change_the_code"]
    assert language["how_to_check"]
    assert len(language["score_meanings"]) == 5
    assert language["independent_review"].startswith("A separate AI pass")

    target_results = service.query(
        stats.repository_id,
        request=PatternEvaluationQuery(
            target=first["target"]["key"],
            limit=1,
            include_evidence=True,
        ),
    )
    assert target_results["total"] > 0
    assert target_results["items"][0]["target"]["key"] == first["target"]["key"]
    assert target_results["items"][0]["details"]["evidence"]

    pattern_results = service.query(
        stats.repository_id,
        request=PatternEvaluationQuery(pattern=first["pattern"]["key"], limit=100),
    )
    assert pattern_results["total"] > 0
    assert {item["pattern"]["key"] for item in pattern_results["items"]} == {
        first["pattern"]["key"]
    }


def test_service_pattern_query_preserves_bounds_and_filters(monkeypatch):
    captured = {}

    def request_json(url, *, timeout):
        captured.update(url=url, timeout=timeout)
        return {"contract_version": "pattern-query-v1", "total": 0, "items": []}

    monkeypatch.setattr("anaxigraph.semantic_service._request_json", request_json)
    target = SemanticServiceTarget("http://127.0.0.1:8765", 17, "Fixture", "/repo")
    query = PatternEvaluationQuery(
        target="module:src/service.py",
        pattern="strategy",
        sort_by="suitability",
        minimum_score=60,
        limit=7,
        offset=14,
        include_evidence=True,
    )

    result = service_pattern_evaluations(target, query, snapshot_id=9, timeout=3)
    parameters = urllib.parse.parse_qs(urllib.parse.urlsplit(captured["url"]).query)

    assert result["contract_version"] == "pattern-query-v1"
    assert captured["timeout"] == 3
    assert parameters == {
        "repository_id": ["17"],
        "snapshot_id": ["9"],
        "target": ["module:src/service.py"],
        "pattern": ["strategy"],
        "sort_by": ["suitability"],
        "minimum_score": ["60"],
        "include_evidence": ["True"],
        "limit": ["7"],
        "offset": ["14"],
    }


def test_service_pattern_query_rejects_an_invalid_projection(monkeypatch):
    monkeypatch.setattr("anaxigraph.semantic_service._request_json", lambda *_a, **_k: [])
    target = SemanticServiceTarget("http://127.0.0.1:8765", 17, "Fixture", "/repo")

    with pytest.raises(ValueError, match="invalid pattern projection"):
        service_pattern_evaluations(target, PatternEvaluationQuery())

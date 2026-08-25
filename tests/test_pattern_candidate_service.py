from __future__ import annotations

from anaxigraph.pattern_candidate_query import PatternCandidateQuery
from anaxigraph.semantic_service import SemanticServiceTarget, service_pattern_candidates


def test_service_candidate_query_preserves_selection_filters(monkeypatch):
    captured = {}

    def request_json(url, *, timeout):
        captured.update(url=url, timeout=timeout)
        return {"contract_version": "pattern-candidate-query-v1", "items": []}

    monkeypatch.setattr("anaxigraph.semantic_service._request_json", request_json)
    target = SemanticServiceTarget("http://127.0.0.1:8765", 17, "Fixture", "/repo")
    request = PatternCandidateQuery(
        pattern="strategy", level="module", selection="all", limit=7, offset=14
    )

    result = service_pattern_candidates(target, request, snapshot_id=9, timeout=3)

    assert result["contract_version"] == "pattern-candidate-query-v1"
    assert captured["timeout"] == 3
    assert "/api/patterns/candidates?" in captured["url"]
    assert "pattern=strategy" in captured["url"]
    assert "selection=all" in captured["url"]
    assert "snapshot_id=9" in captured["url"]

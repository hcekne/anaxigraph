from __future__ import annotations

import pytest

from anaxigraph.pattern_candidate_query import (
    PatternCandidateQuery,
    empty_pattern_candidates,
    query_pattern_candidates,
)
from anaxigraph.pattern_catalog import bundled_pattern_catalog
from anaxigraph.pattern_evidence import (
    EvidenceReference,
    PatternEvidenceProjection,
    PatternFeature,
    TargetEvidence,
)
from anaxigraph.pattern_targets import module_target, symbol_target


def test_pattern_candidate_query_defaults_to_skipped_targets():
    query = PatternCandidateQuery(pattern="strategy")

    assert query.selection == "skipped"
    assert query.limit == 20
    assert query.filters() == {
        "pattern": "strategy",
        "target": "",
        "level": "",
        "selection": "skipped",
        "include_evidence": False,
    }
    assert empty_pattern_candidates(3, query)["snapshot_id"] is None


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"pattern": ""}, "requires a pattern key"),
        ({"pattern": "strategy", "level": "package"}, "target level"),
        ({"pattern": "strategy", "selection": "maybe"}, "selection"),
        ({"pattern": "strategy", "limit": 0}, "query limit"),
        ({"pattern": "strategy", "limit": 101}, "query limit"),
        ({"pattern": "strategy", "offset": -1}, "offset"),
        ({"pattern": "x" * 2_001}, "identity is too long"),
        ({"pattern": "strategy", "target": "x" * 2_001}, "identity is too long"),
    ],
)
def test_pattern_candidate_query_rejects_invalid_or_unbounded_values(values, message):
    with pytest.raises(ValueError, match=message):
        PatternCandidateQuery(**values)


def test_candidate_query_distinguishes_selected_work_from_sparse_bound_omissions():
    module = module_target("src/service.py", subsystem_key="subsystem:runtime")
    first = symbol_target(
        module.path,
        "src.service.first",
        "function",
        parent_key=module.key,
        label="first",
    )
    second = symbol_target(
        module.path,
        "src.service.second",
        "function",
        parent_key=module.key,
        label="second",
    )
    evidence = EvidenceReference("fixture", "src/service.py:1")

    def target_evidence(target, fingerprint):
        return TargetEvidence(
            target,
            7,
            fingerprint,
            (
                PatternFeature("code.complexity", 14, 1.0, (evidence,)),
                PatternFeature("code.logical_lines", 60, 1.0, (evidence,)),
            ),
        )

    projection = PatternEvidenceProjection(
        3,
        7,
        "c" * 64,
        {},
        (target_evidence(first, "a" * 64), target_evidence(second, "b" * 64)),
    )
    result = query_pattern_candidates(
        bundled_pattern_catalog(),
        projection,
        PatternCandidateQuery(pattern="long-function", selection="all", include_evidence=True),
        selected_target_keys={first.key},
        plan_ready=True,
    )

    assert result["selected_count"] == 1
    assert result["skipped_count"] == 1
    assert [item["reason"] for item in result["items"]] == [
        "selected",
        "sparse_plan_bound",
    ]
    selected = result["items"][0]["plain_language"]
    assert selected["version"] == "pattern-candidate-explanation-v1"
    assert "full agent evaluation" in selected["conclusion"]
    assert selected["why_this_pair_was_considered"]
    assert selected["why_it_was_selected_or_skipped"]
    assert selected["what_anaxigraph_found"]
    assert selected["what_anaxigraph_could_not_check"]
    assert selected["what_happens_next"]
    assert selected["queue_rank"]["value"] > 0
    signal = next(
        item
        for item in result["items"][0]["details"]["signals"]
        if item["feature"] == "code.logical_lines"
    )
    assert signal["actual"] == 60
    assert signal["expected"] is not None
    assert signal["plain_language"]["what_was_checked"].startswith("AnaxiGraph checked whether")
    assert "not code quality" in signal["plain_language"]["evidence_strength"]["meaning"]
    with pytest.raises(ValueError, match="unknown pattern key"):
        query_pattern_candidates(
            bundled_pattern_catalog(),
            projection,
            PatternCandidateQuery(pattern="not-a-catalog-card"),
            selected_target_keys=set(),
            plan_ready=True,
        )

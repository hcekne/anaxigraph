from __future__ import annotations

import hashlib

import pytest

from anaxigraph.analyzer_capabilities import CAPABILITY_FACTS, declare_capabilities
from anaxigraph.pattern_candidates import (
    PatternCandidatePolicy,
    build_pattern_candidate_plan,
    explain_pattern_candidate,
)
from anaxigraph.pattern_catalog import bundled_pattern_catalog
from anaxigraph.pattern_catalog_models import EvidenceSignal
from anaxigraph.pattern_evidence import (
    EvidenceReference,
    PatternEvidenceProjection,
    PatternFeature,
    TargetEvidence,
)
from anaxigraph.pattern_signals import capability_coverage, observe_signal
from anaxigraph.pattern_targets import (
    area_target,
    module_target,
    repository_target,
    subsystem_target,
    symbol_target,
)


def _capabilities():
    return declare_capabilities(
        "candidate-fixture",
        "1",
        "deep",
        deep=tuple(sorted(CAPABILITY_FACTS)),
    )


def _feature(name, value, confidence=1.0, availability="available"):
    return PatternFeature(
        name,
        value,
        confidence,
        (EvidenceReference("fixture", "fixture:target"),),
        availability,
    )


def _evidence(target, *features, fingerprint="a" * 64):
    capabilities = _capabilities()
    return TargetEvidence(
        target,
        7,
        fingerprint,
        tuple(sorted(features, key=lambda item: item.name)),
        (capabilities.fingerprint,),
    )


def _projection(*items):
    capabilities = _capabilities()
    return PatternEvidenceProjection(
        3,
        7,
        "b" * 64,
        {capabilities.fingerprint: capabilities.as_dict()},
        tuple(items),
    )


def _six_level_evidence():
    repository = repository_target("Fixture")
    area = area_target("core", "Core", source="semantic")
    subsystem = subsystem_target("runtime", "Runtime", area_key=area.key, source="semantic")
    module = module_target("src/service.py", subsystem_key=subsystem.key)
    type_target = symbol_target(
        module.path,
        "src.service.Provider",
        "class",
        parent_key=module.key,
        label="Provider",
    )
    function = symbol_target(
        module.path,
        "src.service.Provider.run",
        "method",
        parent_key=type_target.key,
        label="run",
    )
    return (
        _evidence(
            function,
            _feature("code.complexity", 14),
            _feature("code.logical_lines", 64),
            _feature("syntax.control_flow", {"count": 5, "values": ["if"]}),
        ),
        _evidence(
            type_target,
            _feature("code.complexity", 8),
            _feature("code.logical_lines", 30),
            _feature("interface.signatures", ["Provider()"]),
            _feature("syntax.constructors", {"count": 2, "values": ["__init__"]}),
        ),
        _evidence(
            module,
            _feature("graph.fan_in", 4),
            _feature("graph.fan_out", 7),
            _feature("history.change_count", 5),
            _feature("semantic.dossier", True, 0.9),
            _feature("semantic.responsibilities", ["Coordinate provider execution"], 0.9),
            _feature("types.count", 3),
        ),
        _evidence(
            subsystem,
            _feature("graph.fan_out", 12),
            _feature("modules.count", 8),
            _feature("semantic.coverage", 1.0),
        ),
        _evidence(
            area,
            _feature("graph.fan_out", 18),
            _feature("modules.count", 12),
            _feature("semantic.coverage", 1.0),
        ),
        _evidence(
            repository,
            _feature("graph.fan_out", 24),
            _feature("modules.count", 20),
            _feature("semantic.coverage", 1.0),
        ),
    )


def test_sparse_plan_produces_stable_candidates_at_all_six_levels():
    projection = _projection(*_six_level_evidence())
    policy = PatternCandidatePolicy(per_target_limit=5)

    first = build_pattern_candidate_plan(bundled_pattern_catalog(), projection, policy=policy)
    second = build_pattern_candidate_plan(bundled_pattern_catalog(), projection, policy=policy)
    value = first.as_dict()

    assert first.fingerprint == second.fingerprint
    assert value["selection_version"] == "pattern-candidate-selection-v2"
    assert [item.input_fingerprint for item in first.candidates] == [
        item.input_fingerprint for item in second.candidates
    ]
    assert all(0 < count <= 5 for count in value["counts_by_level"].values())
    assert value["selected"] == sum(value["counts_by_level"].values())
    assert value["selected"] <= value["targets_considered"] * policy.per_target_limit
    assert value["selected"] < value["eligible_pairs"]
    assert value["skipped_by_reason"]["per_target_limit"] > 0


def test_long_function_candidate_keeps_direct_evidence_and_separate_counter_evidence():
    function = _six_level_evidence()[0]
    plan = build_pattern_candidate_plan(
        bundled_pattern_catalog(),
        _projection(function),
        policy=PatternCandidatePolicy(per_target_limit=20),
    )
    candidate = next(item for item in plan.candidates if item.pattern_key == "long-function")

    assert candidate.selection_reasons == ("problem_signal", "supporting_evidence")
    assert {item.feature for item in candidate.matched_signals} == {
        "code.complexity",
        "code.logical_lines",
    }
    assert candidate.counter_signals == ()
    assert candidate.priority > 50
    assert candidate.as_dict()["pattern_key"] == "long-function"


def test_semantic_unknowns_select_bounded_architecture_questions():
    repository = _six_level_evidence()[-1]
    plan = build_pattern_candidate_plan(
        bundled_pattern_catalog(),
        _projection(repository),
        policy=PatternCandidatePolicy(per_target_limit=4),
    )

    assert len(plan.candidates) == 4
    assert {item.target.level for item in plan.candidates} == {"repository"}
    assert any("semantic_question" in item.selection_reasons for item in plan.candidates)
    assert all(item.semantic_questions for item in plan.candidates)
    assert plan.omitted_candidates > 0


def test_global_bound_reserves_candidate_work_for_every_available_level():
    plan = build_pattern_candidate_plan(
        bundled_pattern_catalog(),
        _projection(*_six_level_evidence()),
        policy=PatternCandidatePolicy(
            per_target_limit=5,
            total_limit=6,
            minimum_priority=0,
            per_level_reserve=1,
        ),
    )

    assert len(plan.candidates) == 6
    assert {item.target.level for item in plan.candidates} == {
        "symbol",
        "type",
        "module",
        "subsystem",
        "area",
        "repository",
    }
    assert dict(plan.skipped_by_reason)["total_limit"] > 0


def test_global_bound_reserves_distinct_patterns_before_repeating_generic_ones():
    first = _six_level_evidence()[2]
    second = _evidence(
        module_target("src/other.py", subsystem_key="subsystem:runtime"),
        *first.features,
        fingerprint="d" * 64,
    )

    plan = build_pattern_candidate_plan(
        bundled_pattern_catalog(),
        _projection(first, second),
        policy=PatternCandidatePolicy(
            per_target_limit=4,
            total_limit=8,
            per_level_reserve=0,
            per_pattern_reserve=1,
        ),
    )

    assert len(plan.candidates) == 8
    assert len({item.pattern_key for item in plan.candidates}) == 8
    assert all(
        sum(item.target.key == target.target.key for item in plan.candidates) == 4
        for target in (first, second)
    )


def test_semantic_responsibility_breaks_generic_signal_ties_for_provider_work():
    module = _evidence(
        module_target("src/providers.py", subsystem_key="subsystem:runtime"),
        _feature("syntax.constructors", {"count": 5, "values": ["__init__"]}),
        _feature("types.count", 5),
        _feature("semantic.responsibilities", ["Choose interchangeable provider implementations"]),
    )

    plan = build_pattern_candidate_plan(
        bundled_pattern_catalog(),
        _projection(module),
        policy=PatternCandidatePolicy(
            per_target_limit=4,
            total_limit=4,
            per_level_reserve=0,
            per_pattern_reserve=2,
        ),
    )

    provider = next(item for item in plan.candidates if item.pattern_key == "provider-abstraction")
    assert provider.priority == 49
    assert "identity-map" not in {item.pattern_key for item in plan.candidates}


def test_skipped_pair_explains_missing_evidence_without_persisting_dense_records():
    module = _six_level_evidence()[2]
    projection = _projection(module)

    explanation = explain_pattern_candidate(
        bundled_pattern_catalog(),
        projection,
        target_key=module.target.key,
        pattern_key="circular-dependency",
    )

    assert not explanation["selected"]
    assert explanation["reason"] == "no_positive_evidence"
    assert explanation["missing_evidence"] == [
        "graph.cycle_count",
        "graph.cycle_membership",
        "semantic.risks",
    ]
    assert explanation["candidate"] is None


def test_pair_explanation_reports_ineligible_scope_and_unknown_identities():
    function = _six_level_evidence()[0]
    projection = _projection(function)
    wrong_scope = explain_pattern_candidate(
        bundled_pattern_catalog(),
        projection,
        target_key=function.target.key,
        pattern_key="modular-monolith",
    )

    assert wrong_scope["reason"] == "wrong_scope"
    assert not wrong_scope["eligible_scope"]
    with pytest.raises(ValueError, match="unknown pattern key"):
        explain_pattern_candidate(
            bundled_pattern_catalog(),
            projection,
            target_key=function.target.key,
            pattern_key="missing",
        )


@pytest.mark.parametrize(
    ("operator", "value", "expected", "outcome"),
    [
        ("exists", ["value"], None, "matched"),
        ("contains", ["Provider abstraction"], "provider", "matched"),
        ("count_gte", {"count": 3}, 3, "matched"),
        ("count_lte", ["one"], 0, "not_matched"),
        ("gte", 7, 5, "matched"),
        ("lte", 7, 5, "not_matched"),
    ],
)
def test_signal_operators_are_deterministic(operator, value, expected, outcome):
    target = _six_level_evidence()[0].target
    evidence = _evidence(target, _feature("fixture.value", value))
    signal = EvidenceSignal("fixture.value", operator, expected)

    observation = observe_signal("problem", signal, evidence)

    assert observation.outcome == outcome


def test_aliases_remain_visible_in_candidate_evidence():
    target = _six_level_evidence()[0].target
    evidence = _evidence(
        target,
        _feature("syntax.async_behavior", {"count": 3, "values": ["await"]}),
    )
    signal = EvidenceSignal("syntax.async_calls", "count_gte", 2)

    observation = observe_signal("supporting", signal, evidence)

    assert observation.outcome == "matched"
    assert observation.feature == "syntax.async_calls"
    assert observation.resolved_feature == "syntax.async_behavior"


def test_capability_coverage_reports_partial_parent_support():
    target = _six_level_evidence()[3].target
    evidence = TargetEvidence(
        target,
        7,
        "a" * 64,
        (
            _feature(
                "analyzer.capability_coverage",
                {
                    "calls": {
                        "available": 2,
                        "total": 4,
                        "levels": {"structural": 2, "unavailable": 2},
                    }
                },
            ),
        ),
    )
    requirement = bundled_pattern_catalog().card("adapter").required_capabilities[0]

    coverage = capability_coverage(evidence, {}, requirement)

    assert coverage.ratio == 0.5
    assert not coverage.complete
    assert "2/4" in coverage.gap


def test_only_changed_target_changes_candidate_input_fingerprints():
    items = _six_level_evidence()
    before = build_pattern_candidate_plan(bundled_pattern_catalog(), _projection(*items))
    changed = _evidence(
        items[0].target,
        *items[0].features,
        fingerprint=hashlib.sha256(b"changed target").hexdigest(),
    )
    after = build_pattern_candidate_plan(
        bundled_pattern_catalog(),
        _projection(changed, *items[1:]),
    )
    before_by_pair = {
        (item.target.key, item.pattern_key): item.input_fingerprint for item in before.candidates
    }
    after_by_pair = {
        (item.target.key, item.pattern_key): item.input_fingerprint for item in after.candidates
    }

    unchanged_pairs = set(before_by_pair) & set(after_by_pair)
    assert all(
        before_by_pair[pair] != after_by_pair[pair]
        for pair in unchanged_pairs
        if pair[0] == changed.target.key
    )
    assert all(
        before_by_pair[pair] == after_by_pair[pair]
        for pair in unchanged_pairs
        if pair[0] != changed.target.key
    )


@pytest.mark.parametrize(
    "values",
    [
        {"per_target_limit": 0},
        {"total_limit": 0},
        {"minimum_priority": 101},
        {"per_level_reserve": -1},
        {"per_pattern_reserve": -1},
    ],
)
def test_candidate_policy_rejects_unbounded_or_invalid_values(values):
    with pytest.raises(ValueError):
        PatternCandidatePolicy(**values)

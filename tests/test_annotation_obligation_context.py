"""Late qualified contracts survive compact group inputs and selected Pattern witnesses."""

from copy import deepcopy

from annotation_contract_support import annotation_case
from fresh_eyes_support import TwoExecutorReview
from semantic_support import _agent_dossier, _enable_agent_semantics

from anaxigraph.config import SemanticConfig, load_config
from anaxigraph.pattern_evidence_source import read_pattern_evidence
from anaxigraph.persistence.pattern_evidence_features import _semantic_features
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_agent_protocol import packetize_agent_request, rehydrate_agent_request
from anaxigraph.semantic_request_support import compact_dossier
from anaxigraph.understanding import SemanticEngine


def _qualified_annotation(request):
    value = _agent_dossier(request)
    template = annotation_case()[1]["contracts"][0]
    template["functions"] = [item["qualified_name"] for item in request["functions"]]
    value["contracts"] = [
        {**deepcopy(template), "name": f"session-contract-{index}"} for index in range(13)
    ]
    late = "; ".join(
        f"Before effect {index}, verify the active lease and retain ordered evidence for retry"
        for index in range(13)
    )
    value["contracts"][-1]["invariants"] = [f"Ordering rule {i}" for i in range(12)] + [late]
    value["contracts"][-1]["inputs"] = ["Caller owns the session until all effects are committed"]
    value["contracts"][-1]["errors"] = ["Reject an expired lease without any external effect"]
    value["capabilities"] = [
        {
            "name": "ordered-calculation",
            "purpose": "Calculate quantities while preserving ordered session ownership.",
            "inputs": ["A caller-owned session"],
            "outputs": ["The calculated quantity"],
            "constraints": [f"Capability rule {i}" for i in range(12)] + [late],
        }
    ]
    return value


def _review_with_qualified_annotation(repository, database):
    _enable_agent_semantics(repository)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    annotations = {}

    def result(request):
        if request["analysis_kind"] == "annotation" and request["path"] == "pkg/core.py":
            annotations["core"] = _qualified_annotation(request)
            return annotations["core"]
        return _agent_dossier(request)

    review = TwoExecutorReview(
        SemanticEngine(database), stats.repository_id, repository, config, dossier_factory=result
    )
    review.run_until_complete()
    return review, stats, annotations["core"]


def _assert_paged_roundtrip(request):
    bounded, manifest, pages = packetize_agent_request(
        request, SemanticConfig(max_source_chars=4_000)
    )
    assert manifest and pages
    assert rehydrate_agent_request(bounded, pages) == request


def test_thirteenth_contract_and_late_qualifications_reach_group_and_pattern_inputs(
    repository, database
):
    review, stats, annotation = _review_with_qualified_annotation(repository, database)
    groups = [
        claim["request"]
        for claim in review.claims
        if claim["kind"] == "synthesis" and claim["request"]["scope_type"] == "group"
    ]
    group, child = next(
        (request, child)
        for request in groups
        for child in request["child_dossiers"]
        if child["scope"] == "pkg/core.py"
    )
    for key in ("contracts", "capabilities"):
        assert child["value"][key] == annotation[key]
    _assert_paged_roundtrip(group)
    with database.connect() as connection:
        projection = read_pattern_evidence(connection, stats.repository_id, stats.snapshot_id)
    module = next(
        item
        for item in projection.items
        if item.target.level == "module" and item.target.path == "pkg/core.py"
    )
    for key in ("contracts", "capabilities"):
        assert module.feature(f"semantic.{key}").value == annotation[key]
    witnessed_levels = set()
    for parent in projection.items:
        feature = parent.feature("architecture.witnesses")
        witnesses = feature.value["items"] if feature else []
        for witness in witnesses:
            if witness["path"] != "pkg/core.py":
                continue
            witnessed_levels.add(parent.target.level)
            assert len(witnesses) <= 8
            for key in ("contracts", "capabilities"):
                assert witness[key] == annotation[key]
            _assert_paged_roundtrip(
                {"analysis_kind": "pattern_assessment", "target_evidence": parent.as_dict()}
            )
    assert witnessed_levels == {"subsystem", "area", "repository"}


def test_legacy_compaction_and_pattern_features_do_not_gain_new_annotation_fields():
    legacy = {
        "summary": "A saved legacy summary.",
        "responsibilities": ["Calculate quantities"],
        "public_contracts": ["Call configure first"],
        "evidence": ["pkg/core.py"],
        "confidence": 0.8,
    }
    for detailed in (True, False):
        assert compact_dossier(legacy, detailed=detailed) == legacy
    names = {item.name for item in _semantic_features(legacy, "module:pkg/core.py")}
    assert "semantic.contracts" not in names and "semantic.capabilities" not in names

"""Branch contracts for bounded coding-agent semantic evidence packets."""

from __future__ import annotations

import pytest

from anaxigraph.config import SemanticConfig
from anaxigraph.semantic_agent_protocol import (
    packetize_agent_request,
    rehydrate_agent_request,
)


def test_agent_packetization_leaves_small_and_unpageable_requests_unchanged():
    small = {"analysis_kind": "annotation", "functions": []}
    oversized_unknown = {"analysis_kind": "unknown", "payload": "x" * 5_000}
    semantic = SemanticConfig(max_source_chars=4_000)

    assert packetize_agent_request(small, semantic) == (small, None, [])
    assert packetize_agent_request(oversized_unknown, semantic) == (
        oversized_unknown,
        None,
        [],
    )


def test_agent_packetization_pages_compact_group_evidence():
    request = {"analysis_kind": "synthesis", "child_dossiers": _large_evidence("child")}
    bounded, manifest, pages = packetize_agent_request(
        request, SemanticConfig(max_source_chars=4_000)
    )
    assert manifest["contains"] == ["child_dossiers"]
    assert rehydrate_agent_request(bounded, pages) == request


def test_agent_packetization_preserves_annotation_source_functions_and_relationships():
    request = {
        "analysis_kind": "annotation",
        "path": "large.py",
        "source": "value = 1\n" * 1_000,
        "functions": _large_evidence("function"),
        "relationships": _large_evidence("relationship"),
    }
    bounded, manifest, pages = packetize_agent_request(
        request, SemanticConfig(max_source_chars=4_000)
    )
    assert set(manifest["contains"]) == {"source_chunks", "functions", "relationships"}
    assert "source" not in bounded
    assert rehydrate_agent_request(bounded, pages) == request


def test_agent_packetization_stops_taxonomy_inventory_paging_when_bounded():
    request = {
        "analysis_kind": "taxonomy_proposal",
        "modules": _large_evidence("module"),
        "relationships": [{"kind": "small"}],
    }

    bounded, manifest, pages = packetize_agent_request(
        request, SemanticConfig(max_source_chars=4_000)
    )

    assert manifest is not None
    assert manifest["contains"] == ["modules"]
    assert bounded["relationships"] == request["relationships"]
    assert rehydrate_agent_request(bounded, pages) == request


def test_agent_packetization_pages_previous_taxonomy_and_validation():
    request = {
        "analysis_kind": "taxonomy_review",
        "modules": [],
        "relationships": [],
        "candidate_taxonomy": None,
        "previous_taxonomy": {
            "memberships": _large_evidence("membership"),
            "nodes": _large_evidence("node"),
        },
        "deterministic_validation": {"issues": _large_evidence("issue")},
    }

    bounded, manifest, pages = packetize_agent_request(
        request, SemanticConfig(max_source_chars=4_000)
    )

    assert manifest is not None
    assert set(manifest["contains"]) == {
        "previous_taxonomy.memberships",
        "previous_taxonomy.nodes",
        "deterministic_validation.issues",
    }
    assert rehydrate_agent_request(bounded, pages) == request


def test_agent_packetization_pages_pattern_source_and_features():
    request = {
        "analysis_kind": "pattern_assessment",
        "path": "large.py",
        "source": "value = 1\n" * 1_000,
        "target_evidence": {"features": _large_evidence("feature")},
    }

    bounded, manifest, pages = packetize_agent_request(
        request, SemanticConfig(max_source_chars=4_000)
    )

    assert manifest is not None
    assert set(manifest["contains"]) == {"source_chunks", "target_evidence.features"}
    assert rehydrate_agent_request(bounded, pages) == request


@pytest.mark.parametrize(
    "kind", ["fresh_adjudication", "fresh_proposal", "fresh_comparison", "fresh_review"]
)
def test_functional_passes_stay_inline_and_reject_oversize_without_pages(kind):
    request = {
        "analysis_kind": kind,
        "protocol_version": "fresh-eyes-recipe-v2",
        "scope": {"purpose": "Deliver useful understanding"},
    }
    config = SemanticConfig(max_source_chars=4_000)
    assert packetize_agent_request(request, config) == (request, None, [])
    oversized = {**request, "required_capabilities": _large_evidence("functional capability")}
    with pytest.raises(ValueError, match="reduce the functional scope.*context budget"):
        packetize_agent_request(oversized, config)
    assert "evidence_manifest" not in oversized
    assert oversized["required_capabilities"] == _large_evidence("functional capability")


def _large_evidence(label: str) -> list[dict[str, str]]:
    return [{"kind": label, "detail": f"{label}-{index}-" + "x" * 2_000} for index in range(4)]


def test_architecture_plan_pages_keep_all_contract_qualifications_and_alternatives():
    request = {
        "analysis_kind": "architecture_plan",
        "current_system": {
            "semantic_graph": {
                "nodes": _large_evidence("contract"),
                "edges": _large_evidence("edge"),
                "totals_by_kind": {"contract": 20},
            },
            "pattern_reviews": _large_evidence("pattern"),
        },
        "fresh_eyes": _large_evidence("alternative"),
        "direction": "",
    }
    bounded, manifest, pages = packetize_agent_request(
        request, SemanticConfig(max_source_chars=4000)
    )
    assert manifest["page_count"] == len(pages)
    assert {
        "fresh_eyes",
        "current_system.pattern_reviews",
        "current_system.semantic_graph.nodes",
        "current_system.semantic_graph.edges",
    } <= set(manifest["contains"])
    assert rehydrate_agent_request(bounded, pages) == request

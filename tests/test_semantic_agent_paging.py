"""Branch contracts for bounded coding-agent semantic evidence packets."""

from __future__ import annotations

import pytest

from anaxigraph.config import SemanticConfig
from anaxigraph.semantic_agent_protocol import (
    packetize_agent_request,
    rehydrate_agent_request,
)


def test_agent_packetization_leaves_small_and_unpageable_requests_unchanged():
    small = {"analysis_kind": "context", "neighbor_dossiers": []}
    oversized_unknown = {"analysis_kind": "unknown", "payload": "x" * 5_000}
    semantic = SemanticConfig(max_source_chars=4_000)

    assert packetize_agent_request(small, semantic) == (small, None, [])
    assert packetize_agent_request(oversized_unknown, semantic) == (
        oversized_unknown,
        None,
        [],
    )


@pytest.mark.parametrize(
    ("kind", "field"),
    [("context", "neighbor_dossiers"), ("synthesis", "child_dossiers")],
)
def test_agent_packetization_pages_primary_list_evidence(kind, field):
    request = {"analysis_kind": kind, field: _large_evidence("primary")}
    if kind == "context":
        request["relationships"] = _large_evidence("relationship")

    bounded, manifest, pages = packetize_agent_request(
        request, SemanticConfig(max_source_chars=4_000)
    )

    assert manifest is not None
    assert field in manifest["contains"]
    assert ("relationships" in manifest["contains"]) is (kind == "context")
    assert rehydrate_agent_request(bounded, pages) == request


def test_agent_packetization_pages_intrinsic_facts_after_source():
    request = {
        "analysis_kind": "intrinsic",
        "path": "large.py",
        "source": "value = 1\n" * 1_000,
        "deterministic_facts": {
            "symbols": [],
            "relationships": _large_evidence("relationship"),
            "recent_changes": _large_evidence("change"),
        },
    }

    bounded, manifest, pages = packetize_agent_request(
        request, SemanticConfig(max_source_chars=4_000)
    )

    assert manifest is not None
    assert set(manifest["contains"]) == {
        "source_chunks",
        "deterministic_facts.relationships",
        "deterministic_facts.recent_changes",
    }
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


def test_agent_packetization_pages_fresh_eyes_declared_context_last():
    request = {
        "analysis_kind": "fresh_comparison",
        "current_system": {
            "module_dossiers": _large_evidence("dossier"),
            "declared_context": _large_evidence("declared"),
        },
    }

    bounded, manifest, pages = packetize_agent_request(
        request, SemanticConfig(max_source_chars=4_000)
    )

    assert manifest is not None
    assert manifest["contains"] == [
        "current_system.module_dossiers",
        "current_system.declared_context",
    ]
    assert rehydrate_agent_request(bounded, pages) == request


def test_agent_packetization_pages_mission_filter_declared_context_after_the_comparison():
    request = {
        "analysis_kind": "fresh_review",
        "comparison": {"candidate_changes": _large_evidence("change")},
        "declared_context": _large_evidence("declared"),
    }

    bounded, manifest, pages = packetize_agent_request(
        request, SemanticConfig(max_source_chars=4_000)
    )

    assert manifest is not None
    assert manifest["contains"] == ["comparison.candidate_changes", "declared_context"]
    assert rehydrate_agent_request(bounded, pages) == request


def _large_evidence(label: str) -> list[dict[str, str]]:
    return [{"kind": label, "detail": f"{label}-{index}-" + "x" * 2_000} for index in range(4)]

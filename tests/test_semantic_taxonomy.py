from __future__ import annotations

import json
import threading
import time

import pytest

from anaxigraph.config import SemanticConfig
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_agent_protocol import packetize_agent_request
from anaxigraph.semantic_contract import SemanticAnalysisError, SemanticResult
from anaxigraph.semantic_freshness import legacy_input_matches
from anaxigraph.semantic_taxonomy_contract import (
    taxonomy_analysis_kind,
    validated_agent_semantic_response,
)
from anaxigraph.semantic_taxonomy_partition import filter_previous
from anaxigraph.semantic_taxonomy_runner import (
    analyze_taxonomy_proposal,
    analyze_taxonomy_review,
)
from anaxigraph.semantic_taxonomy_validation import normalize_taxonomy


def _node(key: str, members: list[dict], *, level: str = "subsystem") -> dict:
    value = {
        "key": key,
        "name": key.replace("-", " ").title(),
        "description": f"Description for {key}",
        "responsibility": f"Own {key}",
        "confidence": 0.8,
        "rationale": f"Evidence supports {key}",
        "evidence": [key],
        "counter_evidence": [],
    }
    if level == "area":
        value["subsystems"] = members
    else:
        value["members"] = members
    return value


def _member(path: str, confidence: float) -> dict:
    return {
        "path": path,
        "confidence": confidence,
        "rationale": "Responsibility match",
        "evidence": [path],
        "alternatives": [],
    }


def test_taxonomy_validator_repairs_membership_and_bounds_shape(repository, database):
    stats = RepositoryScanner(database).scan(repository)
    paths = sorted(item["path"] for item in database.modules(stats.repository_id))
    candidate = {
        "summary": "A deliberately imperfect candidate.",
        "areas": [
            _node(
                "delivery",
                [_node("runtime", [_member(paths[0], 0.2), _member(paths[1], 0.8)])],
                level="area",
            ),
            _node(
                "platform",
                [
                    _node(
                        "foundation",
                        [
                            _member(paths[0], 0.9),
                            _member(paths[2], 0.8),
                            _member("not/in/the/repository.py", 1.0),
                        ],
                    )
                ],
                level="area",
            ),
            _node(
                "operations",
                [_node("tooling", [_member(paths[3], 0.7)])],
                level="area",
            ),
        ],
        "facets": [
            {
                "name": "testing",
                "description": "Cross-cutting verification",
                "members": [paths[1], "unknown"],
                "evidence": [paths[1]],
            }
        ],
        "confidence": 0.8,
        "evidence": paths[:3],
    }
    candidate["areas"][0]["rationale"] = "Cluster-5 contains the delivery files."
    with database.transaction() as connection:
        normalized = normalize_taxonomy(
            connection,
            repository_id=stats.repository_id,
            snapshot_id=stats.snapshot_id,
            value=candidate,
            eligible_paths=paths,
            settings={"max_areas": 2, "max_subsystems": 4, "stability_bias": 0.8},
            locked_memberships={paths[4]: "Pinned boundary"},
        )

    memberships = normalized["memberships"]
    assert [item["path"] for item in memberships] == paths
    assert len({item["artifact_id"] for item in memberships}) == len(paths)
    assert next(item for item in memberships if item["path"] == paths[0])["confidence"] == 0.9
    assert next(item for item in memberships if item["path"] == paths[4])["locked"] is True
    assert sum(item["level"] == "area" for item in normalized["nodes"]) <= 2
    assert sum(item["level"] == "subsystem" for item in normalized["nodes"]) <= 4
    subsystem_keys = {
        item["node_key"] for item in normalized["nodes"] if item["level"] == "subsystem"
    }
    assert {item["node_key"] for item in memberships} <= subsystem_keys
    assert normalized["facets"][0]["members"] == [paths[1]]
    issue_kinds = {item["kind"] for item in normalized["validation"]["issues"]}
    assert {
        "ignored_unknown_module",
        "repaired_duplicate_membership",
        "repaired_missing_membership",
        "repaired_area_limit",
        "repaired_subsystem_limit",
        "applied_locked_membership",
        "unexplained_internal_group_reference",
    } <= issue_kinds
    assert normalized["validation"]["status"] == "adjusted"


def test_taxonomy_agent_contract_rejects_incomplete_proposals_and_reviews():
    proposal = {"analysis_kind": "taxonomy_proposal"}
    with pytest.raises(SemanticAnalysisError, match="missing required fields"):
        validated_agent_semantic_response({"summary": "incomplete"}, proposal)

    review = {"analysis_kind": "taxonomy_review"}
    with pytest.raises(SemanticAnalysisError, match="missing required fields"):
        validated_agent_semantic_response(
            {"verdict": "approve", "summary": "still incomplete"}, review
        )


def test_taxonomy_routing_and_legacy_reuse_fail_closed():
    assert taxonomy_analysis_kind({"analysis_kind": "taxonomy_proposal"}) is True
    assert taxonomy_analysis_kind({"analysis_kind": "intrinsic"}) is False
    assert (
        legacy_input_matches(
            {"prompt_version": "old", "schema_version": "module-dossier-v4"},
            {},
            prompt_version="current",
        )
        is False
    )
    assert (
        legacy_input_matches(
            {"prompt_version": "current", "schema_version": "unknown-contract"},
            {},
            prompt_version="current",
        )
        is False
    )
    assert filter_previous(
        {
            "summary": "Previous map",
            "memberships": [{"path": "keep.py"}, {"path": "drop.py"}],
        },
        {"keep.py"},
    ) == {"summary": "Previous map", "memberships": [{"path": "keep.py"}]}


def test_locked_subsystem_overflow_is_bounded_and_prunes_empty_areas(repository, database):
    stats = RepositoryScanner(database).scan(repository)
    paths = sorted(item["path"] for item in database.modules(stats.repository_id))
    candidate = {
        "summary": "Locks consume the configured subsystem capacity.",
        "areas": [
            _node(
                "primary",
                [
                    _node("locked-a", [_member(paths[0], 0.9)]),
                    _node("locked-b", [_member(paths[1], 0.9)]),
                ],
                level="area",
            ),
            _node(
                "secondary",
                [_node("unlocked", [_member(path, 0.7) for path in paths[2:]])],
                level="area",
            ),
        ],
        "facets": [],
        "confidence": 0.8,
        "evidence": [],
    }
    with database.transaction() as connection:
        normalized = normalize_taxonomy(
            connection,
            repository_id=stats.repository_id,
            snapshot_id=stats.snapshot_id,
            value=candidate,
            eligible_paths=paths,
            settings={"max_areas": 4, "max_subsystems": 2, "stability_bias": 0.8},
            locked_memberships={paths[0]: "locked-a", paths[1]: "locked-b"},
        )

    subsystems = [item for item in normalized["nodes"] if item["level"] == "subsystem"]
    areas = [item for item in normalized["nodes"] if item["level"] == "area"]
    assert len(subsystems) == 3  # Two explicit locks plus one bounded overflow.
    assert {item["parent_key"] for item in subsystems} == {item["node_key"] for item in areas}
    assert normalized["validation"]["status"] == "adjusted"
    assert "repaired_subsystem_limit_with_locked_overflow" in {
        item["kind"] for item in normalized["validation"]["issues"]
    }


def test_large_hosted_taxonomy_proposal_and_review_reconcile_clusters():
    modules = [
        {
            "path": f"src/module_{index}.py",
            "artifact_type": "source",
            "language": "python",
            "lines_of_code": 20,
            "dossier": {"summary": f"Module {index}", "architecture_role": "runtime"},
        }
        for index in range(36)
    ]
    calls = []
    lock = threading.Lock()
    active = 0
    peak = 0

    class Provider:
        def analyze(self, request):
            nonlocal active, peak
            chunk = str(request.get("analysis_kind")).endswith("_chunk")
            with lock:
                calls.append(request)
                active += int(chunk)
                peak = max(peak, active)
            if chunk:
                time.sleep(0.01)
            taxonomy = _taxonomy_for_modules(request.get("modules") or [])
            value = (
                {
                    "verdict": "approve",
                    "summary": "The supplied partition is coherent.",
                    "issues": [],
                    "taxonomy": taxonomy,
                    "confidence": 0.9,
                    "evidence": ["partition review"],
                }
                if str(request.get("analysis_kind")).startswith("taxonomy_review")
                else taxonomy
            )
            with lock:
                active -= int(chunk)
            return SemanticResult(value, 0.9, (), input_tokens=10, output_tokens=5)

    semantic = SemanticConfig(max_source_chars=5_000, max_output_tokens=900, max_parallel_jobs=4)
    proposal_request = {
        "contract": "Build the complete responsibility map.",
        "schema_version": "repository-understanding-v5",
        "analysis_kind": "taxonomy_proposal",
        "scope_type": "repository",
        "scope_key": "1",
        "constraints": {"max_areas": 4, "max_subsystems": 12},
        "hints": [],
        "locked_memberships": {},
        "modules": modules,
        "relationships": [],
        "previous_taxonomy": None,
    }
    proposal = analyze_taxonomy_proposal(Provider(), proposal_request, semantic)
    proposal_paths = _taxonomy_paths(proposal.value)

    assert proposal_paths == {item["path"] for item in modules}
    assert "taxonomy_inventory_chunk" in {item["analysis_kind"] for item in calls}
    assert calls[-1]["analysis_kind"] == "taxonomy_proposal"
    assert peak == 4
    assert all(not path.startswith("@anaxigraph/") for path in proposal_paths)
    validated_agent_semantic_response(proposal.value, proposal_request)

    calls.clear()
    peak = 0
    review_request = {
        **proposal_request,
        "analysis_kind": "taxonomy_review",
        "candidate_taxonomy": proposal.value,
        "review_pass": 1,
        "deterministic_validation": {},
    }
    review = analyze_taxonomy_review(Provider(), review_request, semantic)
    review_paths = _taxonomy_paths(review.value["taxonomy"])

    assert review_paths == {item["path"] for item in modules}
    assert "taxonomy_review_chunk" in {item["analysis_kind"] for item in calls}
    assert calls[-1]["analysis_kind"] == "taxonomy_review"
    assert peak == 4
    assert review.input_tokens == len(calls) * 10
    assert review.output_tokens == len(calls) * 5
    validated_agent_semantic_response(review.value, review_request)


def test_large_agent_taxonomy_review_pages_candidate_memberships():
    modules = [
        {
            "path": f"src/module_{index}.py",
            "dossier": {"summary": "x" * 200},
        }
        for index in range(60)
    ]
    request = {
        "contract": "Review the complete candidate.",
        "analysis_kind": "taxonomy_review",
        "modules": modules,
        "relationships": [],
        "candidate_taxonomy": _taxonomy_for_modules(modules),
        "previous_taxonomy": None,
        "deterministic_validation": {},
    }

    bounded, manifest, pages = packetize_agent_request(
        request, SemanticConfig(max_source_chars=4_000)
    )

    assert manifest is not None
    assert len(json.dumps(bounded, ensure_ascii=False)) <= 4_000
    assert "candidate_taxonomy" in manifest["contains"]
    assert sum(len(page.get("candidate_taxonomy", {}).get("members", [])) for page in pages) == len(
        modules
    )


def _taxonomy_for_modules(modules: list[dict]) -> dict:
    members = [_member(str(item["path"]), 0.85) for item in modules]
    return {
        "summary": "A bounded responsibility map.",
        "areas": [_node("delivery", [_node("runtime", members)], level="area")] if members else [],
        "facets": [],
        "confidence": 0.9,
        "evidence": [str(item["path"]) for item in modules[:5]],
    }


def _taxonomy_paths(value: dict) -> set[str]:
    return {
        str(member["path"])
        for area in value.get("areas") or []
        for subsystem in area.get("subsystems") or []
        for member in subsystem.get("members") or []
    }

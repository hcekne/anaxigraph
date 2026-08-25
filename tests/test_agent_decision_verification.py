from __future__ import annotations

from anaxigraph.agent_decision_verification import (
    compare_verification_baselines,
    verification_baseline,
)


def _baseline(*, repository="repository-a", goal="Change service", snapshot=10):
    return verification_baseline(
        repository_identity=repository,
        goal=goal,
        snapshot_id=snapshot,
        modules=[
            {
                "path": "src/service.py",
                "structural_hash": "hash-1",
                "fan_in": 2,
                "fan_out": 3,
                "declared_group": "services",
            }
        ],
        findings=[{"stable_key": "finding-1"}],
        patterns=[
            {
                "target": "src/service.py",
                "key": "cohesive-module",
                "scores": {
                    "suitability": 90,
                    "conformance": 80,
                    "opportunity": 20,
                    "confidence": 85,
                },
            }
        ],
    )


def test_comparison_reports_unchanged_facts_after_a_new_snapshot():
    previous = _baseline(snapshot=10)
    current = _baseline(snapshot=11)

    result = compare_verification_baselines(previous, current)

    assert result["status"] == "unchanged"
    assert "tracked architecture facts did not change" in result["summary"]
    assert result["changes"]["modules"] == {
        "newly_tracked": [],
        "no_longer_tracked": [],
        "changed": [],
    }


def test_comparison_refuses_a_baseline_from_another_repository():
    result = compare_verification_baselines(
        _baseline(repository="repository-a", snapshot=10),
        _baseline(repository="repository-b", snapshot=11),
    )

    assert result["status"] == "incomparable"
    assert "different repository" in result["summary"]
    assert result["changes"] == {"modules": {}, "findings": {}, "patterns": {}}


def test_comparison_reads_a_legacy_baseline_with_an_identity_caveat():
    legacy = _baseline(snapshot=10)
    legacy.pop("contract_version")
    legacy.pop("repository_fingerprint")
    legacy.pop("goal_fingerprint")

    result = compare_verification_baselines(
        {"architecture_decision": {"verification": {"post_change_baseline": legacy}}},
        _baseline(snapshot=11),
    )

    assert result["status"] == "unchanged"
    assert result["caveats"]
    assert "identity could not be checked" in result["caveats"][0]

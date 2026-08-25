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
    assert result["changes"]["modules"] == {}
    assert result["changes"]["findings"] == {}
    assert result["changes"]["patterns"] == {}
    assert result["changes"]["structural_effects"]["introduced"] == []


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


def test_version_one_baseline_does_not_invent_missing_measurement_changes():
    previous = _baseline(snapshot=10)
    previous["contract_version"] = "architecture-verification-baseline-v1"
    previous.pop("findings")
    previous["modules"][0].pop("lines_of_code")
    previous["modules"][0].pop("complexity")
    current = _baseline(snapshot=11)
    current["modules"][0].update(
        {"lines_of_code": 400, "complexity": 18, "fan_in": 9, "fan_out": 10}
    )

    result = compare_verification_baselines(previous, current)

    effects = result["changes"]["structural_effects"]
    assert effects["introduced"] == []
    assert effects["worsened"] == []
    assert "version-1 baseline lacks" in result["caveats"][0]


def test_comparison_classifies_a_finding_that_became_more_severe():
    previous = _baseline(snapshot=10)
    current = _baseline(snapshot=11)
    previous["findings"][0]["severity"] = "warning"
    current["findings"][0]["severity"] = "error"

    result = compare_verification_baselines(previous, current)

    worsened = result["changes"]["structural_effects"]["worsened"]
    assert len(worsened) == 1
    assert worsened[0]["finding_key"] == "finding-1"
    assert worsened[0]["previous_severity"] == "warning"
    assert worsened[0]["severity"] == "error"


def test_comparison_does_not_call_a_small_line_edit_structural_worsening():
    previous = _baseline(snapshot=10)
    current = _baseline(snapshot=11)
    previous["modules"][0]["lines_of_code"] = 120
    current["modules"][0]["lines_of_code"] = 125

    result = compare_verification_baselines(previous, current)

    worsened = result["changes"]["structural_effects"]["worsened"]
    assert all(item["category"] != "file_size" for item in worsened)

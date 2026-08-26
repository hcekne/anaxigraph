from __future__ import annotations

import json

from anaxigraph.agent_decision_payload import compact_architecture_decision
from anaxigraph.agent_verification_contract import validated_baseline


def test_compact_decision_keeps_actionable_change_coupling_fields():
    result = compact_architecture_decision(
        {
            "contract_version": "architecture-decision-v1",
            "snapshot_id": 12,
            "status": "semantic_and_reviewed",
            "history_evidence": {
                "change_coupling": {
                    "status": "available",
                    "window_commits": 100,
                    "items": [
                        {
                            "selected_path": "src/service.py",
                            "partner_path": "tests/test_service.py",
                            "shared_commits": 5,
                            "relationship_kind": "co_change_only",
                            "plain_language": {"observation": "Large text omitted when compact."},
                        }
                    ],
                }
            },
        }
    )

    coupling = result["history_evidence"]["change_coupling"]
    assert coupling["status"] == "available"
    assert coupling["items"] == [
        {
            "selected_path": "src/service.py",
            "partner_path": "tests/test_service.py",
            "shared_commits": 5,
            "relationship_kind": "co_change_only",
        }
    ]


def test_compact_decision_keeps_the_before_change_record():
    baseline = {
        "contract_version": "architecture-verification-baseline-v2",
        "snapshot_id": 12,
        "modules": [{"path": "src/service.py", "structural_hash": "before"}],
    }

    result = compact_architecture_decision(
        {
            "contract_version": "architecture-decision-v1",
            "verification": {"post_change_baseline": baseline},
        }
    )

    assert result["verification"]["post_change_baseline"] == baseline


def test_compact_decision_keeps_finding_facts_without_repeated_long_prose():
    long_text = "A concrete explanation of the same saved finding. " * 20
    baseline = {
        "contract_version": "architecture-verification-baseline-v2",
        "repository_fingerprint": "r" * 64,
        "goal_fingerprint": "g" * 64,
        "snapshot_id": 12,
        "modules": [],
        "finding_keys": [f"finding-{index}" for index in range(12)],
        "findings": [
            {
                "key": f"finding-{index}",
                "type": "dependency_cycle",
                "severity": "warning",
                "paths": [f"src/module_{index}.py"],
                "observation": f"Module {index} participates in a dependency cycle.",
                "why_it_matters": long_text,
                "next_step": long_text,
                "when_no_change_may_be_needed": [long_text, long_text],
                "how_to_check": long_text,
            }
            for index in range(12)
        ],
        "patterns": [],
    }

    result = compact_architecture_decision(
        {
            "contract_version": "architecture-decision-v1",
            "verification": {"post_change_baseline": baseline},
        }
    )
    compact = result["verification"]["post_change_baseline"]

    assert len(json.dumps(compact).encode()) < 8_000
    assert compact["findings"][0]["observation"].startswith("Module 0")
    assert "why_it_matters" not in compact["findings"][0]
    restored = validated_baseline(compact, label="previous")
    assert len(restored["findings"]) == 12
    assert restored["findings"][0]["why_it_matters"]
    assert restored["findings"][0]["next_step"]
    assert restored["findings"][0]["how_to_check"]

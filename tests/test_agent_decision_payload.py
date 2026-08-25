from __future__ import annotations

from anaxigraph.agent_decision_payload import compact_architecture_decision


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

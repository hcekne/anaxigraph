"""Packet selection checks coverage, determinism, and actual serialized size."""

import pytest

from anaxigraph.semantic_evidence_selection import (
    bounded_evidence,
    evidence_bytes,
    module_role,
    representative_items,
    responsibility_memberships,
    safe_review_evidence,
    select_modules,
)


def test_documentation_cannot_crowd_out_changed_production_contracts():
    rows = [{"scope_key": f"docs/a{index}.md"} for index in range(200)]
    rows += [{"scope_key": f"tests/test_{index}.py"} for index in range(40)]
    rows += [{"scope_key": f"src/module_{index}.py", "reread": index == 99} for index in range(100)]
    memberships = {
        item["scope_key"]: f"area/subsystem-{index % 8}" for index, item in enumerate(rows)
    }
    inventory = {"src/module_98.py": {"public_interfaces": ["public_api"]}}
    selected = select_modules(rows, inventory, {}, memberships)
    assert selected == select_modules(list(reversed(rows)), inventory, {}, memberships)
    assert len(selected) == 80
    assert sum(module_role(item["scope_key"]) == "production" for item in selected) == 56
    assert {"src/module_98.py", "src/module_99.py"} <= {item["scope_key"] for item in selected}
    assert len({memberships[item["scope_key"]] for item in selected}) == 8
    assert select_modules([], {}, {}, {}) == []


def test_sampling_is_round_robin_and_zero_limit_is_empty():
    rows = [{"id": index, "group": index % 3} for index in range(30)]
    arguments = {"group": lambda item: str(item["group"]), "rank": lambda item: item["id"]}
    assert representative_items(rows, limit=0, **arguments) == []
    assert [item["id"] for item in representative_items(rows, limit=5, **arguments)] == list(
        range(5)
    )
    taxonomy = {
        "areas": [
            {"key": "core", "subsystems": [{"key": "queue", "members": [{"path": "src/jobs.py"}]}]}
        ]
    }
    assert responsibility_memberships(taxonomy) == {"src/jobs.py": "core/queue"}


def test_packet_budget_retains_selected_modules_and_discloses_compaction():
    value = {
        "input_manifest": {"identities": ["source-hash"]},
        "information_boundary": {"mode": "repository_aware"},
        "review_goal": "Preserve user contracts",
        "current_system": {
            "module_dossiers": [
                {
                    "scope": f"src/{index}.py",
                    "value": {"summary": "界" * 12_000, "contracts": ["x" * 4_000] * 20},
                }
                for index in range(80)
            ]
        },
    }
    assert evidence_bytes(value) > 1_048_576
    selected = bounded_evidence(value)
    assert evidence_bytes(selected) <= 800_000
    assert len(selected["current_system"]["module_dossiers"]) == 80
    assert selected["input_manifest"] == value["input_manifest"]
    assert selected["review_goal"] == value["review_goal"]
    assert selected["evidence_limits"]["omitted_list_entries"] > 0
    assert selected["evidence_limits"]["shortened_strings"] > 0
    assert selected == bounded_evidence(value)
    assert bounded_evidence({"small": "packet"}) == {"small": "packet"}
    with pytest.raises(ValueError, match="identity metadata"):
        bounded_evidence({"input_manifest": {"identity": "x" * 10_000}}, limit=500)


def test_legacy_pattern_advice_cannot_be_reintroduced_by_review_sampling():
    current = {
        "evaluation": {"score_contract_version": "pattern-scores-v2", "recommendation": "retain"}
    }
    assert safe_review_evidence(current) == current
    old = {
        "evaluation": {
            "score_contract_version": "pattern-scores-v1",
            "pattern_key": "god-object",
            "recommendation": "retain",
        }
    }
    result = safe_review_evidence(old)
    assert result["legacy_advice_withheld"]
    assert result["evaluation"]["recommendation"] == "insufficient_evidence"
    assert old["evaluation"]["recommendation"] == "retain"

"""Packet selection checks coverage, determinism, and actual serialized size."""

import pytest
from fresh_eyes_support import baseline_review

from anaxigraph.semantic_evidence_selection import (
    bounded_evidence,
    evidence_bytes,
    module_role,
    representative_items,
    responsibility_memberships,
    safe_review_evidence,
    select_modules,
)
from anaxigraph.semantic_fresh_eyes_evidence import current_charter, current_system_evidence


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


@pytest.mark.parametrize(
    "field",
    [
        "capability_brief",
        "external_constraints",
        "declared_context",
        "public_contracts",
        "invariants",
        "protected_behavior",
        "counter_evidence",
    ],
)
def test_compaction_preserves_late_constraints_and_counterevidence(field):
    constraints = [f"Required behavior {index}" for index in range(12)]
    constraints.append("Caller obligation. " * 80 + "Never charge before reserving inventory.")
    value = {
        "current_system": {field: constraints},
        "supporting_description": "Background explanation. " * 2_000,
    }
    selected = bounded_evidence(value, limit=6_000)
    assert selected["current_system"][field] == constraints
    assert evidence_bytes(selected) <= 6_000
    assert selected["evidence_limits"]["shortened_strings"] == 1
    assert value["current_system"][field] == constraints


def test_oversized_essential_context_is_rejected_instead_of_misrepresented():
    with pytest.raises(ValueError, match="essential constraints"):
        bounded_evidence({"public_contracts": ["critical " * 1_000]}, limit=1_000)


def test_reviewed_taxonomy_preserves_responsibility_memberships(repository, database, monkeypatch):
    review = baseline_review(repository, database)
    snapshot_id = database.latest_snapshot(review.repository_id)["id"]
    with database.connect() as connection:
        current, manifest = current_system_evidence(
            connection, review.repository_id, snapshot_id, current_charter(connection, snapshot_id)
        )
    taxonomy = current["responsibility_map"]
    assert taxonomy["areas"] and "taxonomy" not in taxonomy
    memberships = responsibility_memberships(taxonomy)
    assert memberships
    for document in current["module_dossiers"]:
        assert document["responsibility_owner"] == memberships[document["scope"]]
    assert manifest["coverage"]["responsibilities_total"] == len(set(memberships.values()))
    assert manifest["coverage"]["unmapped_modules"] == 0
    monkeypatch.setattr(
        "anaxigraph.semantic_fresh_eyes_evidence._current_taxonomy", lambda *_: None
    )
    with database.connect() as connection:
        _, missing = current_system_evidence(
            connection, review.repository_id, snapshot_id, current_charter(connection, snapshot_id)
        )
    assert missing["coverage"]["responsibilities_total"] == 0
    assert missing["coverage"]["unmapped_modules"] == missing["coverage"]["current_modules"]


def test_compaction_preserves_paths_owners_and_every_responsibility():
    path = "src/" + "nested/" * 30 + "public_contract.py"
    owner = "area/" + "responsibility-" * 30
    value = {
        "module_dossiers": [
            {"scope": path, "responsibility_owner": owner, "summary": "x" * 20_000}
        ],
        "responsibility_map": {
            "areas": [
                {
                    "key": f"area-{area}",
                    "subsystems": [
                        {"key": f"subsystem-{group}", "members": [{"path": path}] * 30}
                        for group in range(10)
                    ],
                }
                for area in range(6)
            ]
        },
    }
    selected = bounded_evidence(value, limit=40_000)
    assert selected["module_dossiers"][0]["scope"] == path
    assert selected["module_dossiers"][0]["responsibility_owner"] == owner
    areas = selected["responsibility_map"]["areas"]
    assert len(areas) == 6 and all(len(area["subsystems"]) == 10 for area in areas)
    assert areas[0]["subsystems"][0]["members"][0]["path"] == path
    assert evidence_bytes(selected) <= 40_000

"""Cross-generation views preserve records without inventing agreement verdicts."""

from copy import deepcopy

from anaxigraph.semantic_fresh_eyes_consensus import compare_generations


def _functional(generation):
    scopes = [
        {
            "scope_id": scope,
            "scope": {"purpose": f"Deliver {scope}"},
            "alternatives": [
                {
                    "id": f"alternative:{generation}:{scope}:{slot}",
                    "design": {"summary": f"Choice {slot}", "components": [{"key": "owner"}]},
                    "provenance": {"executor_model": f"model-{generation}"},
                }
                for slot in "abc"
            ],
            "comparison": {
                "summary": f"Original {scope} comparison",
                "retained_alternative_ids": [
                    f"alternative:{generation}:{scope}:{slot}" for slot in "abc"
                ],
            },
        }
        for scope in ("product", "capability", "subsystem")
    ]
    return {
        "protocol_version": "fresh-eyes-recipe-v2",
        "review_generation": generation,
        "snapshot_id": 7,
        "state": "current" if generation == 2 else "superseded",
        "counts": {"retained_alternatives": 9},
        "scope_reviews": scopes,
        "functional_brief": {"revision": f"revision-{generation}", "purpose": "Deliver work"},
        "stages": [{"document_id": generation * 100 + i} for i in range(14)],
    }


def test_functional_comparison_keeps_all_original_alternatives_and_provenance():
    left, right = _functional(1), _functional(2)
    before = deepcopy((left, right))
    result = compare_generations(left, right)
    assert result["method"] == "recorded_side_by_side"
    assert result["contract_version"] == "fresh-eyes-generation-records-v2"
    assert result["subject"] == "retained_functional_alternatives"
    for side, original in (("left", left), ("right", right)):
        assert result["records"][side]["scope_reviews"] == original["scope_reviews"]
        assert result["records"][side]["functional_brief"] == original["functional_brief"]
        assert result[side]["alternative_count"] == 9
        assert len(result[side]["document_ids"]) == 14
    assert (left, right) == before
    assert not {"aligned", "conflicting", "score", "pairs", "fingerprint"} & result.keys()


def test_legacy_comparison_preserves_exact_original_document_values():
    document = {
        "id": 1,
        "value": {
            "contract_version": "fresh-eyes-review-v1",
            "recommendations": [{"title": "Original paid conclusion", "confidence": 0.37}],
        },
        "source": "agent",
        "executor_model": "historical-model",
        "created_at": "2026-01-01",
    }
    left = {
        "review_generation": 1,
        "snapshot_id": 4,
        "state": "legacy_archive",
        "stages": [{"document_id": 1}],
        "archive": {
            "documents": [document],
            "document_ids": [1],
            "read_only": True,
            "details_available": True,
        },
    }
    right = deepcopy(left)
    right["review_generation"] = 2
    original = deepcopy((left, right))
    result = compare_generations(left, right)
    assert result["subject"] == "legacy_review_archive"
    assert result["records"]["left"]["archive"] == left["archive"]
    assert result["records"]["right"]["archive"] == right["archive"]
    assert (left, right) == original
    assert "aligned" not in result and "conflicting" not in result


def test_a_self_comparison_is_explicitly_identified():
    value = _functional(2)
    result = compare_generations(value, deepcopy(value))
    assert result["same_generation"] is True
    assert result["left"] == result["right"]
    assert result["records"]["left"] == result["records"]["right"]
    assert any("same" in caveat.lower() for caveat in result["caveats"])


def test_swapping_sides_only_swaps_the_original_records():
    left, right = _functional(1), _functional(2)
    forward, backward = compare_generations(left, right), compare_generations(right, left)
    assert forward["records"]["left"] == backward["records"]["right"]
    assert forward["records"]["right"] == backward["records"]["left"]
    assert forward["left"] == backward["right"]
    assert forward["same_generation"] is False

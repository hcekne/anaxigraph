"""Read two saved generations together without generating a new architecture judgment."""

from __future__ import annotations

from typing import Any

FRESH_EYES_ALIGNMENT_VERSION = "fresh-eyes-generation-records-v2"
ALIGNMENT_CAVEATS = (
    "These are recorded alternatives and comparisons, preserved as written. No new agreement, conflict or architecture verdict was generated.",
)


def compare_generations(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    identities = {"left": _identity(left), "right": _identity(right)}
    same = all(
        identities["left"].get(key) == identities["right"].get(key)
        for key in ("review_generation", "snapshot_id")
    )
    return {
        "contract_version": FRESH_EYES_ALIGNMENT_VERSION,
        "method": "recorded_side_by_side",
        "subject": "retained_functional_alternatives"
        if "scope_reviews" in left or "scope_reviews" in right
        else "legacy_review_archive",
        **identities,
        "same_generation": same,
        "records": {"left": _records(left), "right": _records(right)},
        "caveats": [
            *ALIGNMENT_CAVEATS,
            *(
                ["Both sides name the same recorded generation; this is not independent agreement."]
                if same
                else []
            ),
        ],
    }


def _identity(payload):
    return {
        "review_generation": payload.get("review_generation"),
        "snapshot_id": payload.get("snapshot_id"),
        "state": payload.get("state"),
        "alternative_count": payload.get("counts", {}).get("retained_alternatives", 0),
        "document_ids": [
            item["document_id"] for item in payload.get("stages", []) if item.get("document_id")
        ],
    }


def _records(payload):
    if "scope_reviews" in payload:
        return {
            "functional_brief": payload.get("functional_brief"),
            "scope_reviews": payload["scope_reviews"],
        }
    return {
        "archive": payload.get("archive"),
        "strategy": payload.get("strategy"),
        "comparison": payload.get("comparison"),
        "input_manifests": payload.get("input_manifests", []),
    }

"""Small review placeholders and lossless, explicitly read-only v1 archives."""

from __future__ import annotations

from anaxigraph.semantic_fresh_eyes_contract import (
    FRESH_EYES_PROTOCOL_VERSION,
    FRESH_EYES_REVIEW_VERSION,
)
from anaxigraph.semantic_fresh_eyes_telemetry import telemetry_totals


def missing_review(repository_id):
    return {
        "contract_version": FRESH_EYES_REVIEW_VERSION,
        "protocol_version": "fresh-eyes-recipe-v2",
        "repository_id": repository_id,
        "snapshot_id": None,
        "state": "not_indexed",
        "ready": False,
        "stages": [],
        "generations": [],
        "telemetry": {"stages": [], **telemetry_totals([])},
        "recommendations": [],
        "caveats": [],
        "next_action": "Run a structural scan.",
    }


def not_started_payload(repository_id, snapshot_id, semantic_status, generations):
    previous = next(
        (item for item in reversed(generations) if item.get("review_document_id")), None
    )
    return {
        **missing_review(repository_id),
        "snapshot_id": snapshot_id,
        "state": "stale" if previous else "not_started",
        "generations": generations,
        "previous_review": {
            "generation": previous["generation"],
            "snapshot_id": previous["snapshot_id"],
            "document_id": previous["review_document_id"],
        }
        if previous
        else None,
        "next_action": "Run the functional Fresh Eyes workflow; saved earlier reviews remain available.",
    }


def archive_payload(repository_id, bundle, generations, documents, manifests, *, details=True):
    by_id = {item["id"]: item for item in documents}
    by_key = {
        entry["key"]: by_id[entry["document_id"]]
        for entry in bundle["stages"]
        if entry["document_id"] in by_id
    }
    review = (by_key.get("review") or {}).get("value")
    stages = [
        {
            **entry,
            "state": "current" if entry.get("document_id") else "missing",
            "provenance": _provenance(by_key.get(entry["key"])),
        }
        for entry in bundle["stages"]
    ]
    return {
        "contract_version": FRESH_EYES_REVIEW_VERSION,
        "protocol_version": FRESH_EYES_PROTOCOL_VERSION,
        "repository_id": repository_id,
        "snapshot_id": bundle["snapshot_id"],
        "review_generation": bundle["generation"],
        "state": "archived",
        "ready": False,
        "read_only": True,
        "generation_inferred": bundle.get("generation_inferred", False),
        "identity": f"{FRESH_EYES_REVIEW_VERSION}:{repository_id}:{bundle['snapshot_id']}:generation-{bundle['generation']}",
        "archive": {
            "documents": documents if details else [_reference(item) for item in documents],
            "document_ids": [item["id"] for item in documents],
            "read_only": True,
            "details_available": True,
        },
        "stages": stages,
        "generations": generations,
        "telemetry": bundle.get("telemetry", {}),
        **_saved_views(by_key, review, details),
        "input_manifests": manifests,
        "diversity": bundle.get("diversity", {}),
        "caveats": _archive_caveats(bundle),
        "next_action": "Start a new functional review; the original v1 documents remain archived.",
    }


def _reference(document):
    return {
        **{
            key: document.get(key)
            for key in (
                "id",
                "scope_key",
                "document_kind",
                "input_hash",
                "schema_version",
                "prompt_version",
            )
        },
        "provenance": _provenance(document),
        "summary": (document.get("value") or {}).get("summary"),
    }


def _provenance(document):
    return {
        key: (document or {}).get(key)
        for key in (
            "source",
            "provider",
            "model",
            "executor_id",
            "executor_model",
            "executor_effort",
            "created_at",
        )
    }


def _summary(value):
    return {key: value.get(key) for key in ("contract_version", "summary")} if value else None


def _saved_views(by_key, review, details):
    return {
        "proposals": [
            {
                "key": key,
                "document_id": item["id"],
                "provenance": _provenance(item),
                **({"value": item["value"]} if details else {}),
            }
            for key, item in by_key.items()
            if key.startswith("proposal:")
        ],
        "adjudication": (by_key.get("adjudication") or {}).get("value") if details else None,
        "comparison": (by_key.get("comparison") or {}).get("value") if details else None,
        "strategy": review if details else _summary(review),
        "recommendations": list((review or {}).get("recommendations") or []) if details else [],
        "recommendation_count": len((review or {}).get("recommendations") or []),
    }


def _archive_caveats(bundle):
    result = [
        "Read-only archive of the original v1 analysis and provenance. It is not a current functional review or verification of this checkout."
    ]
    if bundle.get("generation_inferred"):
        result.append(
            "The original generation number was not retained; this archive groups legacy records without inventing their order."
        )
    return result

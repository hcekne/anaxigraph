"""Read archived grounding evidence exactly as saved; new reviews never re-ground v1 advice."""

from __future__ import annotations

import json
from typing import Any

from anaxigraph.semantic_freshness import semantic_digest

FRESH_EYES_GROUNDING_VERSION = "fresh-eyes-grounding-v2"
LEGACY_GROUNDING_VERSIONS = ("fresh-eyes-grounding-v1",)
GROUNDING_CAVEAT = "Archived grounding records describe the original review; they do not verify behavior in another revision."


def read_review_grounding(
    connection: Any, *, repository_id: int, snapshot_id: int, review_id: Any
) -> dict[str, Any] | None:
    if not review_id:
        return None
    hashes = [
        _grounding_hash(int(review_id), version)
        for version in (FRESH_EYES_GROUNDING_VERSION, *LEGACY_GROUNDING_VERSIONS)
    ]
    row = connection.execute(
        "SELECT value_json FROM semantic_document_values WHERE repository_id=? "
        "AND scope_type='fresh_eyes' AND scope_key='grounding' AND document_kind='fresh_grounding' "
        "AND (previous_document_id=? OR input_hash IN (?,?)) ORDER BY id DESC LIMIT 1",
        (repository_id, int(review_id), *hashes),
    ).fetchone()
    return json.loads(row["value_json"]) if row else None


def with_grounding(connection: Any, payload: dict[str, Any], *, review_id: Any) -> dict[str, Any]:
    grounding = read_review_grounding(
        connection,
        repository_id=int(payload["repository_id"]),
        snapshot_id=int(payload["snapshot_id"]),
        review_id=review_id,
    )
    payload["grounding_summary"] = grounding.get("summary") if grounding else None
    if grounding is not None:
        by_rank = {item["rank"]: item for item in grounding.get("recommendations", [])}
        payload["recommendations"] = [
            {
                **item,
                **({"grounding": by_rank[item["rank"]]} if item.get("rank") in by_rank else {}),
            }
            for item in payload.get("recommendations", [])
        ]
        payload["caveats"] = [*payload.get("caveats", []), GROUNDING_CAVEAT]
    return payload


def _grounding_hash(review_id: int, contract: str = FRESH_EYES_GROUNDING_VERSION) -> str:
    return semantic_digest({"contract": contract, "review_document_id": int(review_id)})

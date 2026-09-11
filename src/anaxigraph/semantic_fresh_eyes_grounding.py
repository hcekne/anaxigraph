"""Resolve the identifiers a fresh-eyes recommendation cites against the reviewed snapshot.

The report is evidence for a reader, never a verdict: it says whether the paths, symbols,
findings, commits, routes, and declared Charter keys a recommendation names can still be found,
not whether the recommendation is right.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from anaxigraph.architecture_charter_corrections import read_charter_corrections
from anaxigraph.semantic_fresh_eyes_contract import semantic_digest
from anaxigraph.semantic_fresh_eyes_references import (
    SnapshotIndex,
    cited_identifiers,
    resolve_identifier,
    snapshot_index,
)

FRESH_EYES_GROUNDING_VERSION = "fresh-eyes-grounding-v2"
LEGACY_GROUNDING_VERSIONS = ("fresh-eyes-grounding-v1",)
GROUNDING_SCOPE_TYPE = "fresh_eyes"
GROUNDING_SCOPE_KEY = "grounding"
GROUNDING_DOCUMENT_KIND = "fresh_grounding"
GROUNDING_METHOD = (
    "regular-expression identifier extraction from free-text evidence, resolved against the "
    "reviewed snapshot's files, symbols, findings, commits, routes, and declared context"
)
GROUNDING_CAVEAT = (
    "Grounding resolves references only. It does not support the recommendation's claim and it "
    "does not verify behavior."
)
GROUNDING_CAVEATS = (
    GROUNDING_CAVEAT,
    "Evidence fields are free text, so extraction is regular expressions and heuristics: prose "
    "that names nothing checkable is reported as needs_test, never as wrong, and a common symbol "
    "name can resolve against unrelated code.",
)

_STATUSES = (
    "references_resolved",
    "name_already_present",
    "already_satisfied",
    "needs_test",
    "stale",
)
# Reference resolution, claim support, and behavior verification are different evidence states.
# Only the first is checked here, so the other two are reported as unchecked rather than implied.
_UNCHECKED = "unchecked"
_INTRODUCES = re.compile(r"\b(add|adds|introduce|introduces|create|creates|expose|exposes|new)\b")
_STORED_SQL = """
SELECT id, value_json FROM semantic_documents
WHERE repository_id = ? AND scope_type = ? AND scope_key = ? AND document_kind = ?
  AND input_hash = ? ORDER BY id DESC LIMIT 1
"""
_INSERT_SQL = """
INSERT INTO semantic_documents(
    repository_id, snapshot_id, scope_type, scope_key, previous_document_id, document_kind,
    input_hash, intent_fingerprint, value_json, source, provider, model, prompt_version,
    schema_version, confidence, created_at
) VALUES (?, ?, 'fresh_eyes', 'grounding', ?, 'fresh_grounding', ?, ?, ?, 'deterministic',
    'deterministic', '', 'fresh-eyes-grounding-v1', 'fresh-eyes-grounding-v1', 1.0, ?)
"""
_STAGE_SQL = """
SELECT context_document_id FROM semantic_scope_states
WHERE snapshot_id = ? AND scope_type = 'fresh_eyes' AND scope_key = ?
"""
_CHANGED_SQL = """
SELECT DISTINCT c.artifact_id FROM snapshot_file_changes c
JOIN snapshots s ON s.id = c.snapshot_id
WHERE s.repository_id = ? AND c.snapshot_id > ? AND c.snapshot_id <= ?
  AND c.artifact_id IN ({placeholders})
"""


def write_review_grounding(
    connection: Any, *, repository_id: int, snapshot_id: int, review_id: int
) -> int | None:
    """Write one grounding report per review document; later planning passes are no-ops."""

    digest = _grounding_hash(review_id)
    if (stored := _stored(connection, repository_id, digest)) is not None:
        return int(stored["id"])
    review = _value(connection, review_id)
    if review is None:
        return None
    stage = connection.execute(_STAGE_SQL, (snapshot_id, "comparison")).fetchone()
    value = ground_review(
        connection,
        repository_id=repository_id,
        snapshot_id=snapshot_id,
        review_value=review,
        comparison_value=_value(connection, stage["context_document_id"] if stage else 0),
        declared_context=read_charter_corrections(connection, repository_id),
    )
    encoded = json.dumps(value, sort_keys=True)
    now = datetime.now(UTC).isoformat()
    cursor = connection.execute(
        _INSERT_SQL, (repository_id, snapshot_id, int(review_id), digest, digest, encoded, now)
    )
    return int(cursor.lastrowid)


def read_review_grounding(
    connection: Any, *, repository_id: int, snapshot_id: int, review_id: Any
) -> dict[str, Any] | None:
    """Read the stored report and overlay staleness for the reported snapshot; never writes."""

    if not review_id:
        return None
    value = _stored_value(connection, repository_id, int(review_id))
    if value is None:
        return None
    return _with_staleness(connection, repository_id, value, int(snapshot_id))


def with_grounding(connection: Any, payload: dict[str, Any], *, review_id: Any) -> dict[str, Any]:
    """Attach the deterministic grounding report to one review status payload."""

    grounding = read_review_grounding(
        connection,
        repository_id=int(payload["repository_id"]),
        snapshot_id=int(payload["snapshot_id"]),
        review_id=review_id,
    )
    payload["grounding_summary"] = grounding["summary"] if grounding else None
    if grounding is None:
        return payload
    by_rank = {int(item["rank"]): item for item in grounding["recommendations"]}
    payload["recommendations"] = [
        {**item, "grounding": _for_rank(by_rank, item)} for item in payload["recommendations"]
    ]
    payload["caveats"] = [*payload.get("caveats", []), GROUNDING_CAVEAT]
    return payload


def ground_review(
    connection: Any,
    *,
    repository_id: int,
    snapshot_id: int,
    review_value: dict[str, Any],
    comparison_value: dict[str, Any] | None = None,
    declared_context: Any = (),
) -> dict[str, Any]:
    """Label every recommendation from the identifiers it cites, and say how that was decided."""

    index = snapshot_index(connection, snapshot_id, declared_context)
    candidates = (comparison_value or {}).get("candidate_changes") or []
    classifications = {
        _normalized(item.get("title")): str(item.get("classification") or "") for item in candidates
    }
    grounded = [
        _ground_recommendation(connection, repository_id, index, item, classifications)
        for item in (review_value.get("recommendations") or [])
    ]
    return {
        "contract_version": FRESH_EYES_GROUNDING_VERSION,
        "method": GROUNDING_METHOD,
        "snapshot_id": int(snapshot_id),
        "recommendations": grounded,
        "summary": _summary(grounded, int(snapshot_id), int(snapshot_id)),
        "caveats": list(GROUNDING_CAVEATS),
    }


def _ground_recommendation(
    connection: Any,
    repository_id: int,
    index: SnapshotIndex,
    recommendation: dict[str, Any],
    classifications: dict[str, str],
) -> dict[str, Any]:
    checks = [
        resolve_identifier(connection, repository_id, index, kind, value, field)
        for kind, value, field in cited_identifiers(recommendation)
    ]
    status, reason = _status(recommendation, checks, classifications)
    return {
        "rank": int(recommendation.get("rank") or 0),
        "title": str(recommendation.get("title") or ""),
        "status": status,
        "reason": reason,
        "evidence_state": _evidence_state(checks),
        "checks": checks,
    }


def _evidence_state(checks: list[dict[str, Any]]) -> dict[str, str]:
    """Say which of the three evidence questions this pass actually answered."""

    if not checks:
        resolution = "none_cited"
    elif any(check["result"] != "exists" for check in checks):
        resolution = "unresolved"
    else:
        resolution = "resolved"
    return {
        "reference_resolution": resolution,
        "claim_support": _UNCHECKED,
        "behavior_verification": _UNCHECKED,
    }


def _status(
    recommendation: dict[str, Any], checks: list[dict[str, Any]], classifications: dict[str, str]
) -> tuple[str, str]:
    resolved = [check for check in checks if check["result"] == "exists"]
    missing = [check for check in checks if check["result"] == "missing"]
    if satisfied := _already_satisfied(recommendation, classifications):
        return "already_satisfied", satisfied
    if present := _name_already_present(recommendation, resolved):
        return "name_already_present", present
    if not checks:
        return "needs_test", "The recommendation cites no checkable identifier."
    if missing:
        names = ", ".join(f"{check['kind']} {check['value']}" for check in missing)
        return "needs_test", (
            f"{len(resolved)} of {len(checks)} cited identifiers resolve in the reviewed "
            f"snapshot; {names} could not be found."
        )
    return "references_resolved", (
        f"All {len(checks)} cited identifiers resolve in the reviewed snapshot. That locates the "
        "recommendation in real code; it does not support its claim."
    )


def _already_satisfied(recommendation: dict[str, Any], classifications: dict[str, str]) -> str:
    """Report only a judgment another stage actually made, never one inferred from a name."""

    if classifications.get(_normalized(recommendation.get("title"))) == "already_satisfies":
        return "The comparison stage classified the matching candidate already_satisfies."
    if str(recommendation.get("action") or "") == "retain":
        return "The recommendation asks to retain what the repository already does."
    return ""


def _name_already_present(recommendation: dict[str, Any], resolved: list[dict[str, Any]]) -> str:
    """A proposed name that already resolves is worth reading, but it is not proof of behavior."""

    introduced = [
        check
        for check in resolved
        if check["field"] == "smallest_change" and check["kind"] in {"route", "symbol"}
    ]
    smallest = str(recommendation.get("smallest_change") or "").lower()
    if introduced and _INTRODUCES.search(smallest):
        return (
            f"The proposed {introduced[0]['kind']} {introduced[0]['value']} already exists by "
            "name. Read what it does before treating the recommendation as already satisfied."
        )
    return ""
    return ""


def _normalized(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def _summary(grounded: list[dict[str, Any]], reviewed: int, current: int) -> dict[str, Any]:
    counts = dict.fromkeys(_STATUSES, 0)
    for item in grounded:
        counts[str(item["status"])] = counts.get(str(item["status"]), 0) + 1
    return {
        "contract_version": FRESH_EYES_GROUNDING_VERSION,
        "method": GROUNDING_METHOD,
        "reviewed_snapshot_id": reviewed,
        "current_snapshot_id": current,
        "recommendations": len(grounded),
        "checks": sum(len(item["checks"]) for item in grounded),
        "counts": counts,
    }


def _with_staleness(
    connection: Any, repository_id: int, value: dict[str, Any], snapshot_id: int
) -> dict[str, Any]:
    """Mark a recommendation stale when code it cited changed after the review was produced."""

    reviewed = int(value.get("snapshot_id") or 0)
    grounded = list(value.get("recommendations") or [])
    cited = {
        int(check["artifact_id"])
        for item in grounded
        for check in item.get("checks") or []
        if check.get("artifact_id") is not None
    }
    if cited and snapshot_id > reviewed:
        ordered = sorted(cited)
        rows = connection.execute(
            _CHANGED_SQL.format(placeholders=",".join("?" * len(ordered))),
            (repository_id, reviewed, snapshot_id, *ordered),
        ).fetchall()
        changed = frozenset(int(row["artifact_id"]) for row in rows)
        grounded = [_stale(item, changed) for item in grounded] if changed else grounded
    return {
        **value,
        "recommendations": grounded,
        "summary": _summary(grounded, reviewed, snapshot_id),
    }


def _stale(item: dict[str, Any], changed: frozenset[int]) -> dict[str, Any]:
    checks = item.get("checks") or []
    hits = [check for check in checks if check.get("artifact_id") in changed]
    if not hits:
        return item
    named = ", ".join(str(check["value"]) for check in hits)
    return {
        **item,
        "status": "stale",
        "reason": f"Cited code changed after the review was produced: {named}.",
        "evidence_state": {
            "reference_resolution": "changed",
            "claim_support": _UNCHECKED,
            "behavior_verification": _UNCHECKED,
        },
        "checks": [
            {**check, "result": "changed"} if check.get("artifact_id") in changed else check
            for check in checks
        ],
    }


def _for_rank(by_rank: dict[int, dict[str, Any]], recommendation: dict[str, Any]) -> dict[str, Any]:
    grounded = by_rank.get(int(recommendation.get("rank") or 0))
    if grounded is None:
        reason = "This recommendation was not part of the grounded review document."
        return {
            "status": "needs_test",
            "reason": reason,
            "evidence_state": {
                "reference_resolution": "none_cited",
                "claim_support": _UNCHECKED,
                "behavior_verification": _UNCHECKED,
            },
            "checks": [],
        }
    return {key: value for key, value in grounded.items() if key not in {"rank", "title"}}


def _stored_value(connection: Any, repository_id: int, review_id: int) -> dict[str, Any] | None:
    """Read this contract's report, falling back to one a previous contract wrote.

    A version bump changes the stored identity, so an older report would otherwise disappear.
    Earlier reports stay readable and keep the contract version they were written under; their
    status names are projected onto the current vocabulary without inventing evidence.
    """

    for contract in (FRESH_EYES_GROUNDING_VERSION, *LEGACY_GROUNDING_VERSIONS):
        stored = _stored(connection, repository_id, _grounding_hash(review_id, contract))
        if stored is None:
            continue
        value = json.loads(stored["value_json"] or "{}")
        return value if contract == FRESH_EYES_GROUNDING_VERSION else _projected(value)
    return None


def _projected(value: dict[str, Any]) -> dict[str, Any]:
    """Carry an earlier report forward: rename what it claimed, add nothing it did not check."""

    return {
        **value,
        "recommendations": [_projected_item(item) for item in value.get("recommendations") or []],
    }


def _projected_item(item: dict[str, Any]) -> dict[str, Any]:
    checks = item.get("checks") or []
    status = str(item.get("status") or "")
    reason = str(item.get("reason") or "")
    if status == "confirmed":
        status = "references_resolved"
    elif status == "already_satisfied" and "already exists" in reason:
        status = "name_already_present"
    return {**item, "status": status, "evidence_state": _evidence_state(checks)}


def _grounding_hash(review_id: int, contract: str = FRESH_EYES_GROUNDING_VERSION) -> str:
    return semantic_digest({"contract": contract, "review_document_id": int(review_id)})


def _value(connection: Any, document_id: Any) -> dict[str, Any] | None:
    """Read one stored document value without importing the fresh-eyes generation reader."""

    if not document_id:
        return None
    row = connection.execute(
        "SELECT value_json FROM semantic_documents WHERE id = ?", (document_id,)
    ).fetchone()
    return json.loads(row["value_json"] or "{}") if row else None


def _stored(connection: Any, repository_id: int, input_hash: str) -> dict[str, Any] | None:
    keys = (GROUNDING_SCOPE_TYPE, GROUNDING_SCOPE_KEY, GROUNDING_DOCUMENT_KIND)
    row = connection.execute(_STORED_SQL, (repository_id, *keys, input_hash)).fetchone()
    return dict(row) if row else None

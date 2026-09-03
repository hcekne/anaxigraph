"""Resolve the identifiers a fresh-eyes recommendation cites against the reviewed snapshot.

The report is evidence for a reader, never a verdict: it says whether the paths, symbols,
findings, commits, routes, and declared Charter keys a recommendation names can still be found,
not whether the recommendation is right.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from anaxigraph.architecture_charter_corrections import (
    CORRECTABLE_SECTIONS,
    read_charter_corrections,
)
from anaxigraph.persistence.temporal_reads import snapshot_files, symbols_for_files
from anaxigraph.semantic_fresh_eyes_contract import semantic_digest

FRESH_EYES_GROUNDING_VERSION = "fresh-eyes-grounding-v1"
GROUNDING_SCOPE_TYPE = "fresh_eyes"
GROUNDING_SCOPE_KEY = "grounding"
GROUNDING_DOCUMENT_KIND = "fresh_grounding"
GROUNDING_METHOD = (
    "regular-expression identifier extraction from free-text evidence, resolved against the "
    "reviewed snapshot's files, symbols, findings, commits, routes, and declared context"
)
GROUNDING_CAVEAT = (
    "Grounding checks identifiers only; it does not prove a recommendation is correct."
)
GROUNDING_CAVEATS = (
    GROUNDING_CAVEAT,
    "Evidence fields are free text, so extraction is regular expressions and heuristics: prose "
    "that names nothing checkable is reported as needs_test, never as wrong, and a common symbol "
    "name can resolve against unrelated code.",
)

_FIELDS = ("current_evidence", "affected_contracts", "expected_deletions", "smallest_change")
_STATUSES = ("confirmed", "needs_test", "already_satisfied", "stale")
_ENDPOINT_HINTS = ("api", "route", "endpoint", "handler", "controller", "server")
_INTRODUCES = re.compile(r"\b(add|adds|introduce|introduces|create|creates|expose|exposes|new)\b")
_SECTIONS = "|".join(sorted(CORRECTABLE_SECTIONS))
_SUFFIXES = "py|pyi|js|jsx|mjs|cjs|ts|tsx|rs|go|java|rb|kt|css|html|sql|toml|md|json|ya?ml"
_PATTERNS = tuple(
    (kind, re.compile(expression))
    for kind, expression in (
        ("finding", r"(?<![\w:.-])([a-z][\w.-]*:[0-9a-f]{20})(?!\w)"),
        ("declared", rf"(?<![\w.-])((?:{_SECTIONS}):[\w.-]+)(?!\w)"),
        ("path", rf"(?<![\w/.-])((?:[\w.-]+/)*[\w.-]+\.(?:{_SUFFIXES}))(?![\w/-])"),
        ("route", r"(?<!\w)(/(?:api|v[0-9])/[A-Za-z0-9_{}/-]+)"),
        ("commit", r"(?<!\w)([0-9a-f]{7,40})(?!\w)"),
        (
            "symbol",
            r"`([A-Za-z_][\w.]*)(?:\(\))?`"
            r"|(?<![\w.])((?:[A-Za-z_]\w*\.)+[A-Za-z_]\w*)(?![\w.])"
            r"|(?<![\w.])([a-z][a-z0-9]*(?:_[a-z0-9]+)+)(?![\w.])",
        ),
    )
)
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


@dataclass(frozen=True, slots=True)
class _Snapshot:
    """What one reviewed snapshot can resolve, reconstructed once per grounding report."""

    # Files are keyed by full path and by unambiguous basename; symbols by name and suffix.
    files: dict[str, int]
    symbols: frozenset[str]
    endpoints: frozenset[str]
    declared: frozenset[str]


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
    stored = _stored(connection, repository_id, _grounding_hash(int(review_id)))
    if stored is None:
        return None
    value = json.loads(stored["value_json"] or "{}")
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

    index = _snapshot_index(connection, snapshot_id, declared_context)
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
    index: _Snapshot,
    recommendation: dict[str, Any],
    classifications: dict[str, str],
) -> dict[str, Any]:
    checks = [
        _check(connection, repository_id, index, kind, value, field)
        for kind, value, field in _identifiers(recommendation)
    ]
    status, reason = _status(recommendation, checks, classifications)
    return {
        "rank": int(recommendation.get("rank") or 0),
        "title": str(recommendation.get("title") or ""),
        "status": status,
        "reason": reason,
        "checks": checks,
    }


def _identifiers(recommendation: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Extract each distinct checkable identifier once, naming the field that cited it."""

    seen: set[tuple[str, str]] = set()
    result: list[tuple[str, str, str]] = []
    for field in _FIELDS:
        value = recommendation.get(field)
        for text in [value] if isinstance(value, str) else list(value or ()):
            for kind, identifier in _extract(str(text)):
                if (kind, identifier) not in seen:
                    seen.add((kind, identifier))
                    result.append((kind, identifier, field))
    return result


def _extract(text: str) -> list[tuple[str, str]]:
    """Match the most specific identifier shapes first, removing each match before the next."""

    found: list[tuple[str, str]] = []
    remaining = text
    for kind, pattern in _PATTERNS:
        for match in pattern.finditer(remaining):
            value = next((group for group in match.groups() if group), "")
            if kind == "commit" and not any(character.isdigit() for character in value):
                continue
            if kind == "symbol" and "." in value and value.islower() and "_" not in value:
                continue
            found.append((kind, value))
        remaining = pattern.sub(" ", remaining)
    return found


def _check(
    connection: Any, repository_id: int, index: _Snapshot, kind: str, value: str, field: str
) -> dict[str, Any]:
    check: dict[str, Any] = {"kind": kind, "value": value, "field": field, "result": "missing"}
    if kind == "path":
        artifact = index.files.get(value) or index.files.get(value.rsplit("/", 1)[-1])
        if artifact is not None:
            check.update({"result": "exists", "artifact_id": artifact})
    elif kind == "symbol":
        check["result"] = _found(value in index.symbols)
    elif kind == "route":
        tail = value.rstrip("/").rsplit("/", 1)[-1]
        check["result"] = _found(value in index.endpoints or tail in index.endpoints)
    elif kind == "declared":
        check["result"] = _found(value in index.declared)
    elif kind == "finding":
        check["result"] = _row(connection, "findings", "stable_key = ?", repository_id, value)
    else:
        check["result"] = _row(connection, "git_changes", "commit_sha LIKE ?", repository_id, value)
    return check


def _found(resolved: bool) -> str:
    return "exists" if resolved else "missing"


def _row(connection: Any, table: str, clause: str, repository_id: int, value: str) -> str:
    row = connection.execute(
        f"SELECT 1 FROM {table} WHERE repository_id = ? AND {clause} LIMIT 1",
        (repository_id, f"{value}%" if "LIKE" in clause else value),
    ).fetchone()
    return _found(row is not None)


def _status(
    recommendation: dict[str, Any], checks: list[dict[str, Any]], classifications: dict[str, str]
) -> tuple[str, str]:
    resolved = [check for check in checks if check["result"] == "exists"]
    missing = [check for check in checks if check["result"] == "missing"]
    if satisfied := _already_satisfied(recommendation, resolved, classifications):
        return "already_satisfied", satisfied
    if not checks:
        return "needs_test", "The recommendation cites no checkable identifier."
    if missing:
        names = ", ".join(f"{check['kind']} {check['value']}" for check in missing)
        return "needs_test", (
            f"{len(resolved)} of {len(checks)} cited identifiers resolve in the reviewed "
            f"snapshot; {names} could not be found."
        )
    return "confirmed", f"All {len(checks)} cited identifiers resolve in the reviewed snapshot."


def _already_satisfied(
    recommendation: dict[str, Any], resolved: list[dict[str, Any]], classifications: dict[str, str]
) -> str:
    if classifications.get(_normalized(recommendation.get("title"))) == "already_satisfies":
        return "The comparison stage classified the matching candidate already_satisfies."
    if str(recommendation.get("action") or "") == "retain":
        return "The recommendation asks to retain what the repository already does."
    introduced = [
        check
        for check in resolved
        if check["field"] == "smallest_change" and check["kind"] in {"route", "symbol"}
    ]
    smallest = str(recommendation.get("smallest_change") or "").lower()
    if introduced and _INTRODUCES.search(smallest):
        return f"The proposed {introduced[0]['kind']} {introduced[0]['value']} already exists."
    return ""


def _normalized(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def _snapshot_index(connection: Any, snapshot_id: int, declared_context: Any) -> _Snapshot:
    files = snapshot_files(connection, snapshot_id, expand_metadata=False)
    paths = {str(item["path"]): int(item["artifact_id"]) for item in files}
    bases: dict[str, int] = {}
    ambiguous: set[str] = set()
    for path, artifact in paths.items():
        if bases.setdefault(path.rsplit("/", 1)[-1], artifact) != artifact:
            ambiguous.add(path.rsplit("/", 1)[-1])
    resolved = {name: artifact for name, artifact in bases.items() if name not in ambiguous}
    resolved.update(paths)
    names, endpoints = _symbol_index(symbols_for_files(connection, files))
    declared = {
        f"{item['section']}:{item['key']}"
        for item in declared_context or ()
        if isinstance(item, dict) and item.get("active", True)
    }
    return _Snapshot(resolved, frozenset(names), frozenset(endpoints), frozenset(declared))


def _symbol_index(symbols: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    """Index symbols by name and qualified-name suffix, and name the ones a route can reach."""

    names: set[str] = set()
    endpoints: set[str] = set()
    for symbol in symbols:
        name = str(symbol["name"])
        names.add(name)
        parts = str(symbol["qualified_name"]).split(".")
        names.update(".".join(parts[index:]) for index in range(len(parts)))
        if "/" in name:
            endpoints.add(name.rsplit(" ", 1)[-1])
        path = str(symbol.get("path") or "").lower()
        if str(symbol["symbol_type"]) == "api_endpoint" or any(h in path for h in _ENDPOINT_HINTS):
            endpoints.add(name)
    return names, endpoints


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
        "checks": [
            {**check, "result": "changed"} if check.get("artifact_id") in changed else check
            for check in checks
        ],
    }


def _for_rank(by_rank: dict[int, dict[str, Any]], recommendation: dict[str, Any]) -> dict[str, Any]:
    grounded = by_rank.get(int(recommendation.get("rank") or 0))
    if grounded is None:
        reason = "This recommendation was not part of the grounded review document."
        return {"status": "needs_test", "reason": reason, "checks": []}
    return {key: value for key, value in grounded.items() if key not in {"rank", "title"}}


def _grounding_hash(review_id: int) -> str:
    return semantic_digest(
        {"contract": FRESH_EYES_GROUNDING_VERSION, "review_document_id": int(review_id)}
    )


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

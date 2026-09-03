"""Optional declared overlays for an inferred Living Architecture Charter."""

from __future__ import annotations

import json
from typing import Any

from anaxigraph.clock import utc_now
from anaxigraph.semantic_freshness import semantic_digest

CORRECTION_VERSION = "architecture-charter-correction-v1"
CORRECTABLE_SECTIONS = frozenset(
    {
        "purpose",
        "actors",
        "capabilities",
        "responsibilities",
        "execution_flows",
        "public_contracts",
        "invariants",
        "extension_points",
        "patterns",
        "coherence_concerns",
    }
)
CORRECTION_DISPOSITIONS = frozenset({"correct", "refute"})


def save_charter_correction(
    database: Any,
    repository_id: int,
    *,
    section: str,
    key: str = "",
    statement: str = "",
    author: str,
    rationale: str,
    active: bool = True,
    disposition: str = "correct",
) -> dict[str, Any]:
    """Append one immutable declared overlay without rewriting inferred evidence.

    `disposition` is `correct` (the default: the statement replaces or adds a claim) or
    `refute` (the principal declares the targeted inferred claim a known non-issue; the
    statement is then optional and the rationale carries the reason).
    """

    value = _correction_value(
        section=section,
        key=key,
        statement=statement,
        author=author,
        rationale=rationale,
        active=active,
        disposition=disposition,
    )
    snapshot = database.latest_snapshot(repository_id)
    if snapshot is None:
        raise ValueError("Repository must have a current scan before adding Charter context")
    created_at = utc_now()
    with database.transaction() as connection:
        document_id = _insert_correction(
            connection, repository_id, int(snapshot["id"]), value, created_at
        )
    return {**value, "document_id": document_id, "created_at": created_at}


def _correction_value(
    *,
    section: str,
    key: str,
    statement: str,
    author: str,
    rationale: str,
    active: bool,
    disposition: str,
) -> dict[str, Any]:
    section = _section(section)
    disposition = _disposition(disposition)
    return {
        "contract_version": CORRECTION_VERSION,
        "section": section,
        "key": "purpose" if section == "purpose" else _text(key, "key", 200),
        "statement": _statement(statement, active=active, disposition=disposition),
        "author": _text(author, "author", 200),
        "rationale": _text(rationale, "rationale", 2_000),
        "active": bool(active),
        "disposition": disposition,
    }


def _insert_correction(
    connection: Any,
    repository_id: int,
    snapshot_id: int,
    value: dict[str, Any],
    created_at: str,
) -> int:
    scope_key = f"{value['section']}:{value['key']}"
    previous = connection.execute(
        """
        SELECT id FROM semantic_documents
        WHERE repository_id = ? AND scope_type = 'charter_correction' AND scope_key = ?
        ORDER BY id DESC LIMIT 1
        """,
        (repository_id, scope_key),
    ).fetchone()
    fingerprint = semantic_digest(value)
    cursor = connection.execute(
        """
        INSERT INTO semantic_documents(
            repository_id, snapshot_id, scope_type, scope_key, previous_document_id,
            document_kind, input_hash, intent_fingerprint, value_json, source, provider,
            model, prompt_version, schema_version, confidence, supporting_evidence_json, created_at
        ) VALUES (?, ?, 'charter_correction', ?, ?, 'charter_correction', ?, ?, ?,
            'declared', 'principal', '', ?, ?, 1, ?, ?)
        """,
        (
            repository_id,
            snapshot_id,
            scope_key,
            int(previous["id"]) if previous else None,
            fingerprint,
            fingerprint,
            json.dumps(value, sort_keys=True),
            CORRECTION_VERSION,
            CORRECTION_VERSION,
            json.dumps([value["rationale"]]),
            created_at,
        ),
    )
    return int(cursor.lastrowid)


def read_charter_corrections(connection: Any, repository_id: int) -> list[dict[str, Any]]:
    """Return the latest declared state for each Charter target, including withdrawals.

    Only the newest document per `section:key` survives, so a refutation and a wording
    correction on the same key never coexist: whichever was saved last is the declared
    state, and the earlier one stops being presented.
    """

    rows = connection.execute(
        """
        SELECT id, snapshot_id, scope_key, value_json, created_at
        FROM semantic_documents
        WHERE repository_id = ? AND scope_type = 'charter_correction'
          AND document_kind = 'charter_correction'
        ORDER BY id DESC
        """,
        (repository_id,),
    ).fetchall()
    result = []
    seen = set()
    for row in rows:
        if row["scope_key"] in seen:
            continue
        seen.add(row["scope_key"])
        value = json.loads(row["value_json"])
        if value.get("contract_version") != CORRECTION_VERSION:
            continue
        result.append(
            {
                **value,
                "document_id": int(row["id"]),
                "snapshot_id": int(row["snapshot_id"]),
                "created_at": row["created_at"],
            }
        )
    return sorted(result, key=lambda item: (item["section"], item["key"]))


def _disposition(value: str) -> str:
    disposition = str(value).strip() or "correct"
    if disposition not in CORRECTION_DISPOSITIONS:
        choices = ", ".join(sorted(CORRECTION_DISPOSITIONS))
        raise ValueError(f"disposition must be one of: {choices}")
    return disposition


def _statement(value: str, *, active: bool, disposition: str) -> str:
    if not active:
        return ""
    if disposition == "refute" and not str(value).strip():
        return ""
    return _text(value, "statement", 4_000)


def _section(value: str) -> str:
    section = str(value).strip()
    if section not in CORRECTABLE_SECTIONS:
        choices = ", ".join(sorted(CORRECTABLE_SECTIONS))
        raise ValueError(f"section must be one of: {choices}")
    return section


def _text(value: str, field: str, maximum: int) -> str:
    result = str(value).strip()
    if not result:
        raise ValueError(f"{field} is required")
    if len(result) > maximum or any(ord(character) < 32 for character in result):
        raise ValueError(f"{field} must be at most {maximum} printable characters")
    return result

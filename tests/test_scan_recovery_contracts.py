"""Recovery after a failed architecture scan must not erase or invent evidence.

Two defects sat behind one symptom. The repository synthesis could not reach the model at
all because optional storage fields are absent from `required`, which strict structured
output forbids; and once a Charter did arrive, reduction silently dropped any scoped
definition it carried. A third made the failure look cheaper than it was, because every
retry authorisation reset the attempt count to zero.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from anaxigraph.architecture_charter_contract import (
    ARCHITECTURE_CHARTER_SCHEMA,
    compact_architecture_charter,
)
from anaxigraph.semantic import _codex_schema
from anaxigraph.semantic_records import _reset_failed_job
from anaxigraph.semantic_taxonomy_contract import response_schema


def _strict_violations(node: Any, path: str = "$") -> list[str]:
    if isinstance(node, list):
        return [
            item
            for index, child in enumerate(node)
            for item in _strict_violations(child, f"{path}[{index}]")
        ]
    if not isinstance(node, dict):
        return []
    found = []
    if node.get("type") == "object":
        missing = sorted(set(node.get("properties") or {}) - set(node.get("required") or []))
        if missing:
            found.append(f"{path} omits {missing} from required")
    for key, child in node.items():
        found.extend(_strict_violations(child, f"{path}.{key}"))
    return found


def test_the_stored_charter_contract_alone_would_be_rejected_by_strict_output():
    # Documents the defect the wire adapter exists to absorb, so its removal is deliberate.
    assert _strict_violations(ARCHITECTURE_CHARTER_SCHEMA)


def test_every_optional_field_added_for_storage_is_still_sendable():
    for kind in ("synthesis", "synthesis_chunk", "context", "fresh_review"):
        payload = {"analysis_kind": kind, "scope_type": "repository", "detailed_reviews": True}
        assert _strict_violations(_codex_schema(response_schema(payload))) == []


def _charter(**extra: Any) -> dict[str, Any]:
    return {
        "contract_version": "v1",
        "purpose": "Explain this repository to a new reader.",
        "actors": [{"name": "operator", "owner_scope": "transport"}],
        **extra,
    }


_DEFINITION = {
    "term": "snapshot",
    "meaning": "One recorded scan of a repository.",
    "scope": "persistence",
    "evidence": ["src/anaxigraph/persistence/schema.py"],
    "distinct_from": ["the dashboard's snapshot view"],
}


def test_reduction_keeps_a_scoped_definition_it_was_given():
    compact = compact_architecture_charter(_charter(definitions=[_DEFINITION]))

    assert compact["definitions"] == [_DEFINITION]


def test_reduction_keeps_the_scope_that_owns_a_claim():
    compact = compact_architecture_charter(_charter())

    assert compact["actors"][0]["owner_scope"] == "transport"


def test_reduction_carries_every_section_the_contract_declares():
    full = _charter(
        definitions=[_DEFINITION],
        **{
            key: []
            for key in ARCHITECTURE_CHARTER_SCHEMA["properties"]
            if key not in {"contract_version", "purpose", "actors", "definitions"}
        },
    )

    assert set(compact_architecture_charter(full)) == set(ARCHITECTURE_CHARTER_SCHEMA["properties"])


def test_a_section_absent_from_a_partial_charter_is_not_invented_as_null():
    compact = compact_architecture_charter(_charter())

    assert "definitions" not in compact
    assert None not in compact.values()


def _job_row(connection: sqlite3.Connection) -> sqlite3.Row:
    connection.row_factory = sqlite3.Row
    return connection.execute(
        "SELECT attempts, max_attempts, status, error FROM semantic_jobs"
    ).fetchone()


def _failed_job(attempts: int = 3, max_attempts: int = 3) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE semantic_jobs (id INTEGER PRIMARY KEY, status TEXT, attempts INTEGER,"
        " max_attempts INTEGER, error TEXT, available_at TEXT, completed_at TEXT,"
        " worker_id TEXT, lease_expires_at TEXT, lease_token_hash TEXT)"
    )
    connection.execute(
        "INSERT INTO semantic_jobs (id, status, attempts, max_attempts, error)"
        " VALUES (1, 'failed', ?, ?, 'invalid_json_schema')",
        (attempts, max_attempts),
    )
    return connection


def test_authorising_a_retry_grants_one_attempt_and_keeps_the_history():
    connection = _failed_job(attempts=3)

    _reset_failed_job(connection, 1)
    row = _job_row(connection)

    assert row["attempts"] == 3
    assert row["max_attempts"] == 4
    assert row["error"] is None


def test_repeated_authorisation_does_not_restore_a_full_allowance():
    connection = _failed_job(attempts=3)

    for attempt in range(4, 8):
        _reset_failed_job(connection, 1)
        connection.execute("UPDATE semantic_jobs SET attempts = ?, status = 'failed'", (attempt,))
    row = _job_row(connection)

    # Each authorisation is worth exactly one try, and the cost stays visible.
    assert row["attempts"] == 7
    assert row["max_attempts"] == 7

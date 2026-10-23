"""Persist the exact catalogue scope independently of paginated assessments."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

PATTERN_MANIFEST_VERSION = "pattern-catalogue-manifest-v1"


def save_pattern_manifest(
    connection: sqlite3.Connection, repository_id: int, snapshot_id: int, plan: Any, catalog: Any
) -> int:
    value = {
        "contract_version": PATTERN_MANIFEST_VERSION,
        "catalogue_fingerprint": plan.catalog_fingerprint,
        "expected_ids": list(plan.expected_pattern_ids),
        "review_scope": "repository:root",
        "selection_version": plan.selection_version,
        "plan_fingerprint": plan.fingerprint,
        "cards": [card.as_dict() for card in catalog.cards],
    }
    existing = connection.execute(
        """SELECT id FROM semantic_document_values WHERE repository_id = ? AND snapshot_id = ?
        AND document_kind = 'pattern_manifest' AND input_hash = ? ORDER BY id DESC LIMIT 1""",
        (repository_id, snapshot_id, plan.fingerprint),
    ).fetchone()
    if existing:
        return int(existing["id"])
    cursor = connection.execute(
        """INSERT INTO semantic_documents(repository_id, snapshot_id, scope_type, scope_key,
        document_kind, input_hash, intent_fingerprint, value_json, source, provider, model,
        prompt_version, schema_version, confidence, supporting_evidence_json, created_at)
        VALUES (?, ?, 'pattern_plan', 'default', 'pattern_manifest', ?, ?, ?,
        'deterministic', 'local', 'catalogue', ?, ?, 1, '[]', ?)""",
        (
            repository_id,
            snapshot_id,
            plan.fingerprint,
            plan.catalog_fingerprint,
            json.dumps(value, sort_keys=True, separators=(",", ":")),
            PATTERN_MANIFEST_VERSION,
            PATTERN_MANIFEST_VERSION,
            datetime.now(UTC).isoformat(),
        ),
    )
    return int(cursor.lastrowid)


def read_pattern_manifest(
    connection: sqlite3.Connection, repository_id: int, snapshot_id: int
) -> dict[str, Any] | None:
    row = connection.execute(
        """SELECT sd.value_json FROM semantic_scope_states ss JOIN semantic_document_values sd
        ON sd.id = ss.context_document_id WHERE ss.repository_id = ? AND ss.snapshot_id = ?
        AND ss.scope_type = 'pattern_plan' AND ss.scope_key = 'default'
        AND sd.document_kind = 'pattern_manifest'""",
        (repository_id, snapshot_id),
    ).fetchone()
    return json.loads(row["value_json"]) if row else None


def manifest_card(connection, repository_id, snapshot_id, candidate) -> dict[str, Any]:
    manifest = read_pattern_manifest(connection, repository_id, snapshot_id)
    if manifest is None or manifest["catalogue_fingerprint"] != candidate["catalog_fingerprint"]:
        raise ValueError("Pattern catalogue manifest no longer matches this analysis")
    return next(
        card for card in manifest["cards"] if card["stable_key"] == candidate["pattern_key"]
    )

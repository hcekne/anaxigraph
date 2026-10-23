"""Canonical saved review documents and execution provenance for review readers."""

from __future__ import annotations

import json
from typing import Any


def document_record(connection: Any, document_id: Any) -> dict[str, Any] | None:
    if not document_id:
        return None
    row = connection.execute(
        "SELECT * FROM semantic_document_values WHERE id = ?", (document_id,)
    ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["value"] = json.loads(result.pop("value_json") or "{}")
    return result


def document_value(connection: Any, document_id: Any) -> dict[str, Any] | None:
    document = document_record(connection, document_id)
    return document["value"] if document else None


def provenance(document: dict[str, Any] | None) -> dict[str, Any] | None:
    if not document:
        return None
    return {
        key: document.get(key)
        for key in (
            "provider",
            "model",
            "executor_id",
            "executor_model",
            "executor_effort",
            "created_at",
        )
    }

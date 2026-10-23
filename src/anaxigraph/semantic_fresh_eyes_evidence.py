"""Read canonical charter documents; source-aware review producers are retired."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def current_charter(connection: sqlite3.Connection, snapshot_id: int) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT sd.* FROM semantic_scope_states ss
        JOIN semantic_document_values sd ON sd.id = ss.context_document_id
        WHERE ss.snapshot_id = ? AND ss.scope_type = 'repository' AND ss.status = 'current'
        LIMIT 1
        """,
        (snapshot_id,),
    ).fetchone()
    return parsed_document(dict(row)) if row else None


def parsed_document(document: dict[str, Any]) -> dict[str, Any]:
    result = dict(document)
    if "value" not in result:
        result["value"] = json.loads(result.get("value_json") or "{}")
    return result

"""Explain which saved Pattern evaluations a repository-aware comparison received."""

from __future__ import annotations

import json
from typing import Any


def comparison_pattern_inputs(connection: Any, snapshot_id: int) -> dict[str, Any]:
    row = connection.execute(
        "SELECT status,json_extract(metadata_json,'$.input_manifest.current_system.patterns') AS patterns "
        "FROM semantic_jobs WHERE snapshot_id = ? AND job_kind = 'fresh_comparison' ORDER BY id DESC LIMIT 1",
        (snapshot_id,),
    ).fetchone()
    if row is None:
        return {"state": "not_compared", "used": 0, "evaluations": []}
    patterns = json.loads(row["patterns"] or "[]")
    saved = connection.execute(
        "SELECT ss.scope_key,sd.input_hash FROM semantic_scope_states ss "
        "JOIN semantic_document_values sd ON sd.id = ss.context_document_id "
        "WHERE ss.snapshot_id = ? AND ss.scope_type = 'pattern' AND ss.status = 'current'",
        (snapshot_id,),
    ).fetchall()
    current = {item["scope_key"]: item["input_hash"] for item in saved}
    evaluations = [
        {
            "scope": item.get("scope"),
            "fingerprint": item.get("input_hash"),
            "current": current.get(item.get("scope")) == item.get("input_hash"),
        }
        for item in patterns
    ]
    return {
        "state": row["status"],
        "used": len(patterns),
        "available_now": len(current),
        "changed_since_comparison": sum(not item["current"] for item in evaluations),
        "evaluations": evaluations[:5],
        "omitted_evaluations": max(0, len(evaluations) - 5),
    }

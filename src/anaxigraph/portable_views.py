"""Readable architecture files alongside the complete portable logical record."""

from __future__ import annotations

import json
from typing import Any

from anaxigraph.architecture_plan_read import architecture_plan_status
from anaxigraph.portable_paths import canonical_json


def record_views(database: Any, repository_id: int) -> dict[str, bytes]:
    snapshot = database.latest_snapshot(repository_id)
    if snapshot is None:
        return {}
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT ss.scope_type,ss.scope_key,sd.value_json,sd.input_hash FROM semantic_scope_states ss "
            "JOIN semantic_documents sd ON sd.id = ss.context_document_id WHERE ss.snapshot_id = ? "
            "AND ss.scope_type IN ('repository','taxonomy','group') AND ss.status = 'current' ORDER BY ss.scope_type,ss.scope_key",
            (snapshot["id"],),
        ).fetchall()
    views = {
        "mapping/architecture.json": canonical_json(
            {
                "source_commit": snapshot["commit_sha"],
                "documents": [
                    {
                        "scope": row["scope_type"],
                        "key": row["scope_key"]
                        if row["scope_type"] != "repository"
                        else "repository",
                        "fingerprint": row["input_hash"],
                        "value": json.loads(row["value_json"]),
                    }
                    for row in rows
                ],
            }
        )
    }
    plan = architecture_plan_status(database, repository_id)
    if plan.get("value"):
        views.update(_plan_views(plan))
    return views


def _plan_views(plan: Any) -> dict[str, bytes]:
    target = plan["target"]
    value = {
        "plan": plan["value"],
        "selected_option": plan["selected_option"],
        "selection_source": plan["selection_source"],
        "progress": plan["progress"],
        "state": plan["state"],
        "provenance": plan["provenance"],
    }
    lines = [
        "# Architecture plan",
        "",
        plan["summary"],
        "",
        f"Direction: {plan['direction']}",
        "",
        f"Selected target: {target['title']} ({plan['selection_source']})",
        "",
        plan["selection_rationale"],
        "",
        "## Migration milestones",
        "",
    ]
    for item in target["milestones"]:
        status = plan["progress"].get(item["key"], {}).get("status", "pending")
        lines.extend(
            [
                f"- {item['title']} — {status}",
                f"  - Outcome: {item['outcome']}",
                f"  - Owners: {', '.join(item['owners'])}",
                f"  - Verify: {'; '.join(item['verification'])}",
                f"  - Rollback: {item['rollback']}",
            ]
        )
    return {
        "architecture/plan.json": canonical_json(value),
        "architecture/plan.md": ("\n".join(lines) + "\n").encode(),
        "architecture/current.mmd": plan["diagrams"]["current_mermaid"].encode(),
        "architecture/target.mmd": plan["diagrams"]["target_mermaid"].encode(),
    }

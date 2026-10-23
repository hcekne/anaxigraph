"""Readable architecture files alongside the complete portable logical record."""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any

from anaxigraph.architecture_plan_read import architecture_plan_status
from anaxigraph.portable_paths import canonical_json


class _RecordSnapshot:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def connect(self) -> Any:
        return nullcontext(self.connection)

    def latest_snapshot(self, repository_id: int) -> Any:
        return self.connection.execute(
            "SELECT s.* FROM snapshots s JOIN repositories r ON r.current_snapshot_id = s.id WHERE r.id = ?",
            (repository_id,),
        ).fetchone()


def record_views(connection: Any, repository_id: int, *, config: Any = None) -> dict[str, bytes]:
    database = _RecordSnapshot(connection)
    snapshot = database.latest_snapshot(repository_id)
    if snapshot is None:
        return {}
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT ss.scope_type,ss.scope_key,sd.value_json,sd.input_hash FROM semantic_scope_states ss "
            "JOIN semantic_document_values sd ON sd.id = ss.context_document_id WHERE ss.snapshot_id = ? "
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
                        "record": "../manifest.json",
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
        "record": "../manifest.json",
        "summary": plan["summary"],
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

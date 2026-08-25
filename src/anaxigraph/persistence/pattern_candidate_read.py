"""Read the persisted membership of the current sparse pattern plan."""

from __future__ import annotations

import sqlite3


def pattern_selection_state(
    connection: sqlite3.Connection,
    snapshot_id: int,
    pattern_key: str,
) -> tuple[set[str], bool]:
    suffix = f"|pattern:{pattern_key}"
    rows = connection.execute(
        """
        SELECT scope_key FROM semantic_scope_states
        WHERE snapshot_id = ? AND scope_type = 'pattern' AND scope_key LIKE ?
        """,
        (snapshot_id, f"%{suffix}"),
    ).fetchall()
    selected = {
        str(row["scope_key"]).removesuffix(suffix)
        for row in rows
        if str(row["scope_key"]).endswith(suffix)
    }
    plan = connection.execute(
        """
        SELECT status FROM semantic_scope_states
        WHERE snapshot_id = ? AND scope_type = 'pattern_plan' AND scope_key = 'default'
        """,
        (snapshot_id,),
    ).fetchone()
    return selected, bool(plan and plan["status"] == "current")

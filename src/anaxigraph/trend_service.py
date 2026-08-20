"""Repository trend read model kept outside the API transport factory."""

from __future__ import annotations

from typing import Any


def repository_trends(
    database: Any,
    repository_id: int,
    *,
    limit: int,
) -> dict[str, Any]:
    bounded = max(1, min(limit, 1_000))
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT s.id AS snapshot_id, s.commit_sha, s.analysis_timestamp,
                   m.name, m.value
            FROM snapshots s JOIN metrics m ON m.snapshot_id = s.id
            WHERE s.repository_id = ? AND m.entity_type = 'repository'
            ORDER BY COALESCE(datetime(s.commit_timestamp), s.analysis_timestamp) DESC,
                     s.id DESC LIMIT ?
            """,
            (repository_id, bounded * 20),
        ).fetchall()
    grouped: dict[int, dict[str, Any]] = {}
    for metric in rows:
        item = grouped.setdefault(
            int(metric["snapshot_id"]),
            {
                "snapshot_id": metric["snapshot_id"],
                "commit_sha": metric["commit_sha"],
                "analysis_timestamp": metric["analysis_timestamp"],
                "metrics": {},
            },
        )
        item["metrics"][metric["name"]] = metric["value"]
    return {"snapshots": list(reversed(list(grouped.values())[:bounded]))}

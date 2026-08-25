"""Repository trend read model kept outside the API transport factory."""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from typing import Any

from anaxigraph.persistence.snapshot_projection import install_snapshot_projection

CHANGE_COUPLING_VERSION = "change-coupling-v1"


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


def scoped_change_coupling(
    database: Any,
    repository_id: int,
    snapshot_id: int,
    paths: list[str],
    *,
    window_commits: int = 100,
    limit: int = 20,
) -> dict[str, Any]:
    """Find repeated co-change only around selected files, without inventing graph edges."""

    selected = list(dict.fromkeys(str(path) for path in paths if str(path).strip()))[:8]
    window = max(2, min(int(window_commits), 500))
    bounded_limit = max(1, min(int(limit), 50))
    if not selected:
        return _coupling_packet("no_selected_files", selected, window, [], {})
    with database.connect() as connection:
        commits = _recent_commits(connection, repository_id, selected, window)
        if len(commits) < 2:
            return _coupling_packet(
                "insufficient_history", selected, window, [], {"window_commits": len(commits)}
            )
        changes = _window_changes(connection, repository_id, commits)
        pairs, work = _cochange_pairs(changes, set(selected))
        static, current_paths = _snapshot_context(connection, snapshot_id, selected)
    all_items = _coupling_items(pairs, static, current_paths)
    work["repeated_pairs"] = len(all_items)
    items = all_items[:bounded_limit]
    work["returned_pairs"] = len(items)
    status = "available" if items else "no_repeated_change"
    return _coupling_packet(status, selected, window, items, work)


def _recent_commits(
    connection: sqlite3.Connection,
    repository_id: int,
    selected: list[str],
    limit: int,
) -> list[str]:
    placeholders = ",".join("?" for _ in selected)
    rows = connection.execute(
        f"""
        SELECT commit_sha, MAX(committed_at) AS committed_at FROM git_changes
        WHERE repository_id = ? AND path IN ({placeholders}) GROUP BY commit_sha
        ORDER BY COALESCE(MAX(committed_at), '') DESC, commit_sha DESC LIMIT ?
        """,
        [repository_id, *selected, limit],
    ).fetchall()
    return [str(row["commit_sha"]) for row in rows]


def _window_changes(
    connection: sqlite3.Connection, repository_id: int, commits: list[str]
) -> dict[str, set[str]]:
    placeholders = ",".join("?" for _ in commits)
    rows = connection.execute(
        f"""
        SELECT commit_sha, path FROM git_changes
        WHERE repository_id = ? AND commit_sha IN ({placeholders})
        ORDER BY commit_sha, path
        """,
        [repository_id, *commits],
    ).fetchall()
    result: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        result[str(row["commit_sha"])].add(str(row["path"]))
    return result


def _cochange_pairs(
    changes: dict[str, set[str]], selected: set[str]
) -> tuple[dict[tuple[str, str], tuple[int, int]], dict[str, int]]:
    selected_counts: Counter[str] = Counter()
    shared_counts: Counter[tuple[str, str]] = Counter()
    changed_rows = 0
    for changed in changes.values():
        changed_rows += len(changed)
        for source in changed & selected:
            selected_counts[source] += 1
            shared_counts.update((source, partner) for partner in changed - {source})
    pairs = {
        pair: (shared, selected_counts[pair[0]])
        for pair, shared in shared_counts.items()
        if shared >= 2
    }
    return pairs, {
        "window_commits": len(changes),
        "changed_file_rows": changed_rows,
        "selected_commit_hits": sum(selected_counts.values()),
        "candidate_pairs": len(shared_counts),
        "repeated_pairs": len(pairs),
    }


def _snapshot_context(
    connection: sqlite3.Connection, snapshot_id: int, selected: list[str]
) -> tuple[dict[tuple[str, str], set[str]], set[str]]:
    install_snapshot_projection(connection, snapshot_id, include_symbols=False)
    current_paths = {
        str(row["path"])
        for row in connection.execute("SELECT path FROM projected_file_versions").fetchall()
    }
    placeholders = ",".join("?" for _ in selected)
    rows = connection.execute(
        f"""
        SELECT source.path AS source_path, target.path AS target_path, r.relationship_type
        FROM projected_relationships r
        JOIN projected_file_versions source ON source.artifact_id = r.source_artifact_id
        JOIN projected_file_versions target ON target.artifact_id = r.target_artifact_id
        WHERE source.path IN ({placeholders}) OR target.path IN ({placeholders})
        """,
        [*selected, *selected],
    ).fetchall()
    result: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        source = str(row["source_path"])
        target = str(row["target_path"])
        relationship = str(row["relationship_type"])
        result[(source, target)].add(relationship)
        result[(target, source)].add(relationship)
    return result, current_paths


def _coupling_items(
    pairs: dict[tuple[str, str], tuple[int, int]],
    static: dict[tuple[str, str], set[str]],
    current_paths: set[str],
) -> list[dict[str, Any]]:
    result = []
    for (source, partner), (shared, source_commits) in pairs.items():
        if partner not in current_paths:
            continue
        conditional = shared / source_commits
        relationship_types = sorted(static.get((source, partner), set()))
        item = {
            "selected_path": source,
            "partner_path": partner,
            "shared_commits": shared,
            "selected_path_commits": source_commits,
            "share_of_selected_changes": round(conditional, 3),
            "relationship_kind": (
                "co_change_and_static" if relationship_types else "co_change_only"
            ),
            "static_relationship_types": relationship_types,
        }
        item["plain_language"] = _coupling_explanation(item)
        result.append(item)
    return sorted(
        result,
        key=lambda item: (
            -int(item["shared_commits"]),
            -float(item["share_of_selected_changes"]),
            str(item["selected_path"]),
            str(item["partner_path"]),
        ),
    )


def _coupling_explanation(item: dict[str, Any]) -> dict[str, str]:
    source = item["selected_path"]
    partner = item["partner_path"]
    shared = item["shared_commits"]
    total = item["selected_path_commits"]
    static = bool(item["static_relationship_types"])
    return {
        "observation": f"{source} and {partner} changed together in {shared} of {total} recent changes to {source}.",
        "why_it_may_matter": (
            "They also have a direct source-code link, so a change may need both files checked."
            if static
            else "No direct source-code link joins them; the shared changes may reveal a hidden responsibility or coordinated workflow."
        ),
        "what_to_do": (
            f"Read {partner} when a task changes {source}; merge or move code only if their jobs and contracts also support it."
        ),
        "reason_not_to_restructure": (
            "Files can change in the same commit for release, formatting, or broad maintenance reasons. Co-change is a clue, not a dependency or merge instruction."
        ),
    }


def _coupling_packet(
    status: str,
    selected: list[str],
    window: int,
    items: list[dict[str, Any]],
    work: dict[str, int],
) -> dict[str, Any]:
    return {
        "contract_version": CHANGE_COUPLING_VERSION,
        "status": status,
        "window_commits": window,
        "window_definition": "Most recent saved commits that changed at least one selected file.",
        "selected_paths": selected,
        "items": items,
        "work": work,
        "plain_language": {
            "conclusion": (
                f"AnaxiGraph found {len(items)} repeated change-history connection{'s' if len(items) != 1 else ''} around the selected files."
                if items
                else "AnaxiGraph did not find a repeated change-history connection in the available window."
            ),
            "limits": (
                "This reads saved Git changes. It does not create a source-code link, prove that files belong together, or inspect developer identity."
            ),
        },
    }

"""Bounded per-path observations; detailed Git rows are an explicit local option."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from anaxigraph.config import load_config

_KEY = "git-metrics-window:"
_FIELDS = (
    "repository_id,path,change_count,first_changed_at,last_changed_at,"
    "first_change_commit,last_change_commit,last_change_subject,additions,deletions"
)


def install_git_metrics_schema(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS git_path_metrics(
        repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
        path TEXT NOT NULL, change_count INTEGER NOT NULL,
        first_changed_at TEXT, last_changed_at TEXT,
        first_change_commit TEXT, last_change_commit TEXT, last_change_subject TEXT,
        additions INTEGER NOT NULL, deletions INTEGER NOT NULL,
        PRIMARY KEY(repository_id,path)) WITHOUT ROWID""")


def git_metrics_context(connection, repository_id):
    row = connection.execute(
        "SELECT value FROM schema_meta WHERE key=?", (_KEY + str(repository_id),)
    ).fetchone()
    return json.loads(row[0]) if row else {"scope": "unavailable"}


def migrate_git_metrics(connection):
    """Aggregate original rows before pruning optional cache; return changed/pruned counts."""
    install_git_metrics_schema(connection)
    changed = pruned = 0
    for repository in connection.execute("SELECT id,path FROM repositories").fetchall():
        repository_id = repository["id"]
        detailed = _history_enabled(connection, repository_id, repository["path"])
        state = git_metrics_context(connection, repository_id)
        count = connection.execute(
            "SELECT COUNT(*) FROM git_changes WHERE repository_id=?", (repository_id,)
        ).fetchone()[0]
        if state["scope"] == "unavailable" or (detailed and state["scope"] != "loaded_history"):
            _aggregate_saved(connection, repository_id)
            _save_context(
                connection,
                repository_id,
                "loaded_history" if detailed else "legacy_observed_history",
                _current_head(connection, repository_id),
                _commit_count(connection, repository_id),
            )
            changed += 1
        if not detailed and count:
            connection.execute("DELETE FROM git_changes WHERE repository_id=?", (repository_id,))
            pruned += count
    return {"changed": changed, "pruned_rows": pruned}


def observe_git_changes(connection, repository_id, changes, *, head, detailed=False):
    """Replace one observed window atomically, retaining migration totals on unchanged HEAD."""
    state = git_metrics_context(connection, repository_id)
    detailed = detailed or _history_marker(connection, repository_id)
    if detailed:
        _retain_changes(connection, repository_id, changes)
        _aggregate_saved(connection, repository_id)
        _save_context(
            connection,
            repository_id,
            "loaded_history",
            head,
            _commit_count(connection, repository_id),
        )
    elif not changes and state["scope"] != "unavailable":
        # A failed/unavailable Git read must not replace known counts and dates with zero.
        return
    elif state.get("observed_head") != head or not state.get("window_commit_count"):
        _replace_window(connection, repository_id, changes)
        _save_context(
            connection,
            repository_id,
            "observed_window",
            head,
            len({item.commit_sha for item in changes}),
        )
    if not detailed:
        connection.execute("DELETE FROM git_changes WHERE repository_id=?", (repository_id,))


def _replace_window(connection, repository_id, changes):
    by_path = defaultdict(list)
    seen = set()
    for item in changes:
        identity = (item.commit_sha, item.path)
        if identity not in seen:
            by_path[item.path].append(item)
            seen.add(identity)
    connection.execute("DELETE FROM git_path_metrics WHERE repository_id=?", (repository_id,))
    rows = [_window_row(repository_id, path, entries) for path, entries in by_path.items()]
    connection.executemany(
        f"INSERT INTO git_path_metrics({_FIELDS}) VALUES ({','.join('?' for _ in range(10))})",
        rows,
    )


def _window_row(repository_id, path, entries):
    first = min(entries, key=lambda item: item.committed_at or "")
    last = max(entries, key=lambda item: item.committed_at or "")
    dates = [item.committed_at for item in entries if item.committed_at]
    return (
        repository_id,
        path,
        len(entries),
        min(dates) if dates else None,
        max(dates) if dates else None,
        first.commit_sha,
        last.commit_sha,
        last.subject,
        sum(item.additions or 0 for item in entries),
        sum(item.deletions or 0 for item in entries),
    )


def _aggregate_saved(connection, repository_id):
    connection.execute("DELETE FROM git_path_metrics WHERE repository_id=?", (repository_id,))
    connection.execute(
        f"""INSERT INTO git_path_metrics({_FIELDS})
        SELECT h.repository_id,h.path,COUNT(*),MIN(h.committed_at),MAX(h.committed_at),
          (SELECT commit_sha FROM git_changes first WHERE first.repository_id=h.repository_id
           AND first.path=h.path ORDER BY committed_at,id LIMIT 1),
          (SELECT commit_sha FROM git_changes last WHERE last.repository_id=h.repository_id
           AND last.path=h.path ORDER BY committed_at DESC,id LIMIT 1),
          (SELECT subject FROM git_changes last WHERE last.repository_id=h.repository_id
           AND last.path=h.path ORDER BY committed_at DESC,id LIMIT 1),
          SUM(COALESCE(additions,0)),SUM(COALESCE(deletions,0))
        FROM git_changes h WHERE h.repository_id=? GROUP BY h.repository_id,h.path""",
        (repository_id,),
    )


def _retain_changes(connection, repository_id, changes):
    connection.executemany(
        """INSERT OR IGNORE INTO git_changes(repository_id,commit_sha,committed_at,
        author_name,subject,path,change_type,additions,deletions) VALUES (?,?,?,?,?,?,?,?,?)""",
        [
            (
                repository_id,
                item.commit_sha,
                item.committed_at,
                item.author_name,
                item.subject,
                item.path,
                item.change_type,
                item.additions,
                item.deletions,
            )
            for item in changes
        ],
    )


def _history_marker(connection, repository_id):
    return (
        connection.execute(
            "SELECT 1 FROM schema_meta WHERE key=?", (f"history-opt-in:{repository_id}",)
        ).fetchone()
        is not None
    )


def _history_enabled(connection, repository_id, root):
    if _history_marker(connection, repository_id):
        return True
    try:
        return load_config(Path(root)).storage.detailed_history
    except (OSError, ValueError):
        return False


def _current_head(connection, repository_id):
    row = connection.execute(
        """SELECT COALESCE(json_extract(s.metadata_json,'$.verified_commit_sha'),s.commit_sha)
        FROM repositories r JOIN snapshots s ON s.id=r.current_snapshot_id WHERE r.id=?""",
        (repository_id,),
    ).fetchone()
    return row[0] if row else None


def _commit_count(connection, repository_id):
    return connection.execute(
        "SELECT COUNT(DISTINCT commit_sha) FROM git_changes WHERE repository_id=?",
        (repository_id,),
    ).fetchone()[0]


def _save_context(connection, repository_id, scope, head, commits):
    value = {"scope": scope, "observed_head": head, "window_commit_count": commits}
    connection.execute(
        "INSERT OR REPLACE INTO schema_meta(key,value) VALUES (?,?)",
        (_KEY + str(repository_id), json.dumps(value, separators=(",", ":"))),
    )

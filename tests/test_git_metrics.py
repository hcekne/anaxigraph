"""Current mapping keeps bounded Git observations without an implicit commit biography."""

import subprocess
from dataclasses import replace

import pytest

from anaxigraph.architecture_dead_code import _last_changes
from anaxigraph.git import GitChange, recent_changes
from anaxigraph.knowledge_query import entity_page
from anaxigraph.persistence.git_metrics import (
    git_metrics_context,
    migrate_git_metrics,
    observe_git_changes,
)
from anaxigraph.scanner import RepositoryScanner


def _change(sha, date, *, path="pkg/core.py", additions=3):
    return GitChange(sha, date, "Fixture", sha + " subject", path, "modified", additions, 1)


def _legacy_rows(connection, repository_id, changes):
    connection.execute(
        "DELETE FROM schema_meta WHERE key=?", (f"git-metrics-window:{repository_id}",)
    )
    connection.executemany(
        "INSERT INTO git_changes(repository_id,commit_sha,committed_at,author_name,subject,"
        "path,change_type,additions,deletions) VALUES (?,?,?,?,?,?,?,?,?)",
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


def _rows(connection):
    return [
        tuple(row) for row in connection.execute("SELECT * FROM git_path_metrics ORDER BY path")
    ]


def test_migration_preserves_known_metrics_until_head_changes_and_never_doublecounts(
    repository, database
):
    scan = RepositoryScanner(database).scan(repository)
    changes = [_change("old", "2001-01-01"), _change("new", "2002-01-01", additions=None)]
    with database.transaction() as connection:
        _legacy_rows(connection, scan.repository_id, changes)
        assert migrate_git_metrics(connection) == {"changed": 1, "pruned_rows": 2}
        old = _rows(connection)
        metrics = connection.execute("SELECT * FROM git_path_metrics").fetchone()
        assert (
            metrics["change_count"],
            metrics["first_changed_at"],
            metrics["last_changed_at"],
        ) == (2, "2001-01-01", "2002-01-01")
        assert (
            metrics["first_change_commit"],
            metrics["last_change_commit"],
            metrics["last_change_subject"],
            metrics["additions"],
            metrics["deletions"],
        ) == ("old", "new", "new subject", 3, 2)
        state = git_metrics_context(connection, scan.repository_id)
        assert state["scope"] == "legacy_observed_history"
        assert migrate_git_metrics(connection) == {"changed": 0, "pruned_rows": 0}
        observe_git_changes(
            connection, scan.repository_id, changes[:1], head=state["observed_head"]
        )
        assert _rows(connection) == old
        observe_git_changes(connection, scan.repository_id, [], head="unavailable-new-head")
        assert _rows(connection) == old
        assert git_metrics_context(connection, scan.repository_id) == state
        window = [_change("next", "2003-01-01")]
        observe_git_changes(connection, scan.repository_id, window * 2, head="changed-head")
        assert connection.execute("SELECT change_count FROM git_path_metrics").fetchone()[0] == 1
        new = _rows(connection)
        observe_git_changes(connection, scan.repository_id, window, head="changed-head")
        assert _rows(connection) == new
        assert git_metrics_context(connection, scan.repository_id) == {
            "scope": "observed_window",
            "observed_head": "changed-head",
            "window_commit_count": 1,
        }
        assert connection.execute("SELECT COUNT(*) FROM git_changes").fetchone()[0] == 0


@pytest.mark.parametrize("opt_in", ["configuration", "history"])
def test_explicit_history_preserves_detailed_rows_and_exact_aggregates(
    repository, database, opt_in
):
    scan = RepositoryScanner(database).scan(repository)
    if opt_in == "configuration":
        policy = repository / ".anaxigraph.yml"
        policy.write_text(policy.read_text() + "\nstorage:\n  detailed_history: true\n")
    changes = [_change("older", "2001-01-01"), _change("later", "2002-01-01")]
    with database.transaction() as connection:
        if opt_in == "history":
            connection.execute(
                "INSERT INTO schema_meta(key,value) VALUES (?, 'true')",
                (f"history-opt-in:{scan.repository_id}",),
            )
        _legacy_rows(connection, scan.repository_id, changes)
        assert migrate_git_metrics(connection) == {"changed": 1, "pruned_rows": 0}
        assert git_metrics_context(connection, scan.repository_id)["scope"] == "loaded_history"
        observe_git_changes(connection, scan.repository_id, changes, head="same", detailed=True)
        observe_git_changes(connection, scan.repository_id, changes, head="same", detailed=True)
        assert connection.execute("SELECT COUNT(*) FROM git_changes").fetchone()[0] == 2
        assert connection.execute("SELECT change_count FROM git_path_metrics").fetchone()[0] == 2


def test_normal_scan_readers_preserve_dates_counts_and_unchanged_storage(repository, database):
    scan = RepositoryScanner(database).scan(repository)
    expected = next(item for item in recent_changes(repository) if item.path == "pkg/core.py")
    module = next(
        item for item in database.modules(scan.repository_id) if item["path"] == expected.path
    )
    assert module["change_count"] == 1
    assert module["first_changed_at"] == module["last_commit_at"] == expected.committed_at
    assert module["first_change_commit"] == module["last_change_commit"] == expected.commit_sha
    assert module["last_change_subject"] == expected.subject
    assert module["history_scope"] == "observed_window"
    details = database.file_details(scan.repository_id, expected.path)
    assert details["history"] == []
    assert details["history_summary"]["change_count"] == 1
    graph = entity_page(database, scan.repository_id, kind="module", q="core.py")
    assert graph["nodes"][0]["metrics"]["change_count"] == 1
    assert graph["nodes"][0]["metrics"]["last_commit_at"] == expected.committed_at
    with database.connect() as connection:
        before = _rows(connection)
        assert _last_changes(connection, scan.repository_id)[expected.path] == expected.committed_at
    for _ in range(2):
        RepositoryScanner(database).scan(repository)
    with database.connect() as connection:
        assert _rows(connection) == before
        assert connection.execute("SELECT COUNT(*) FROM git_changes").fetchone()[0] == 0


def test_unknown_dates_stay_unknown_instead_of_becoming_current_time(repository, database):
    scan = RepositoryScanner(database).scan(repository)
    changes = [replace(_change("undated", ""), committed_at=None)]
    with database.transaction() as connection:
        observe_git_changes(connection, scan.repository_id, changes, head="undated-head")
        row = connection.execute("SELECT * FROM git_path_metrics").fetchone()
        assert row["change_count"] == 1
        assert row["first_changed_at"] is None
        assert row["last_changed_at"] is None


def test_equal_commit_timestamps_keep_the_newest_git_log_subject(repository, database):
    scan = RepositoryScanner(database).scan(repository)
    changes = [_change("newest", "2001-01-01"), _change("older", "2001-01-01")]
    with database.transaction() as connection:
        observe_git_changes(connection, scan.repository_id, changes, head="new-head")
        row = connection.execute("SELECT * FROM git_path_metrics").fetchone()
        assert row["last_change_commit"] == "newest"
        assert row["last_change_subject"] == "newest subject"


def test_restoring_identical_source_refreshes_observed_graph_churn(repository, database):
    scanner = RepositoryScanner(database)
    first = scanner.scan(repository)
    path = repository / "pkg/core.py"
    original = path.read_text()
    for source, subject in ((original + "\n# temporary change\n", "change"), (original, "restore")):
        path.write_text(source)
        subprocess.run(["git", "-C", str(repository), "add", "pkg/core.py"], check=True)
        subprocess.run(["git", "-C", str(repository), "commit", "-qm", subject], check=True)
    scanner.scan(repository)
    module = next(
        item for item in database.modules(first.repository_id) if item["path"] == "pkg/core.py"
    )
    assert module["change_count"] == 3
    assert module["last_change_subject"] == "restore"
    graph = entity_page(database, first.repository_id, kind="module", q="core.py")
    assert graph["nodes"][0]["metrics"]["change_count"] == 3

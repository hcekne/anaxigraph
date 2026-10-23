"""Small edits remain atomic; large projections retain resumable bounded maintenance."""

import pytest
import yaml

import anaxigraph.scan_commit as commit
from anaxigraph.scanner import RepositoryScanner


def _graph(database):
    with database.connect() as connection:
        return {
            table: [tuple(row) for row in connection.execute(f"SELECT * FROM {table}")]
            for table in ("graph_entities", "graph_links", "graph_revisions")
        }


def test_small_edit_builds_atomically_without_exclusive_maintenance(
    repository, database, monkeypatch
):
    first = RepositoryScanner(database).scan(repository)

    def unexpected_maintenance():
        pytest.fail("A small atomic edit requested exclusive cache maintenance")

    monkeypatch.setattr(database, "finish_cache_maintenance", unexpected_maintenance)
    path = repository / "pkg/util.py"
    path.write_text(path.read_text() + "\nEXTRA=2\n")
    changed = RepositoryScanner(database).scan(repository)
    assert changed.snapshot_id != first.snapshot_id
    with database.connect() as connection:
        assert (
            connection.execute("SELECT snapshot_id FROM graph_revisions").fetchone()[0]
            == changed.snapshot_id
        )
        assert not connection.execute(
            "SELECT 1 FROM schema_meta WHERE key IN ('graph-import-pending','index-compaction-pending')"
        ).fetchone()


def test_failed_small_edit_keeps_the_previous_snapshot_and_entire_graph(
    repository, database, monkeypatch
):
    first = RepositoryScanner(database).scan(repository)
    saved = _graph(database)

    def failed_graph(*_arguments, **_options):
        raise RuntimeError("graph construction interrupted")

    monkeypatch.setattr(commit, "sync_knowledge", failed_graph)
    path = repository / "pkg/util.py"
    path.write_text(path.read_text() + "\nEXTRA=2\n")
    with pytest.raises(RuntimeError, match="graph construction interrupted"):
        RepositoryScanner(database).scan(repository)
    assert database.latest_snapshot(first.repository_id)["id"] == first.snapshot_id
    assert _graph(database) == saved


def test_edit_near_its_index_ceiling_keeps_durable_deferred_maintenance(
    repository, database, monkeypatch
):
    RepositoryScanner(database).scan(repository)
    with database.connect() as connection:
        allocated = (
            connection.execute("PRAGMA page_count").fetchone()[0]
            * connection.execute("PRAGMA page_size").fetchone()[0]
        )
    path = repository / ".anaxigraph.yml"
    config = yaml.safe_load(path.read_text())
    config["storage"] = {"index_bytes": allocated + allocated // 2}
    path.write_text(yaml.safe_dump(config))
    source = repository / "pkg/util.py"
    source.write_text(source.read_text() + "\nEXTRA=2\n")
    maintenance = database.finish_cache_maintenance
    pending = []

    def observed_maintenance():
        with database.connect() as connection:
            pending.append(
                connection.execute(
                    "SELECT value FROM schema_meta WHERE key='graph-import-pending'"
                ).fetchone()[0]
            )
            assert connection.execute("SELECT COUNT(*) FROM graph_entities").fetchone()[0] == 0
        maintenance()

    monkeypatch.setattr(database, "finish_cache_maintenance", observed_maintenance)
    changed = RepositoryScanner(database).scan(repository)
    assert pending == [str(changed.snapshot_id)]
    with database.connect() as connection:
        assert (
            connection.execute("SELECT snapshot_id FROM graph_revisions").fetchone()[0]
            == changed.snapshot_id
        )
        assert not connection.execute(
            "SELECT 1 FROM schema_meta WHERE key IN ('graph-import-pending','index-compaction-pending')"
        ).fetchone()
    assert database.path.stat().st_size <= config["storage"]["index_bytes"]

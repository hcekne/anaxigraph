from __future__ import annotations

import shutil

import anaxigraph.persistence.search_read as search_read
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.storage import AnaxiIndex


def test_shared_search_projection_is_current_bounded_and_reused(repository, database, monkeypatch):
    stats = RepositoryScanner(database).scan(repository)

    symbol_results = database.search(stats.repository_id, "Calculator", limit=3)
    exact_results = database.search(stats.repository_id, "pkg/core.py", limit=2)

    assert symbol_results[0]["path"] == "pkg/core.py"
    assert exact_results[0]["path"] == "pkg/core.py"
    assert len(symbol_results) <= 3
    assert all(
        item["search"]["contract_version"] == search_read.SEARCH_CONTRACT_VERSION
        for item in symbol_results
    )
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM module_search").fetchone()[0] == 8
        state = connection.execute(
            "SELECT value FROM schema_meta WHERE key = ?",
            (f"module_search_state:{stats.repository_id}",),
        ).fetchone()
        assert state is not None

    def unexpected_rebuild(*_args, **_kwargs):
        raise AssertionError("a current FTS projection must not rebuild during a query")

    monkeypatch.setattr(search_read, "_search_rows", unexpected_rebuild)
    monkeypatch.setattr(search_read, "_semantic_documents", unexpected_rebuild)
    assert database.search(stats.repository_id, "Calculator", limit=1)[0]["path"] == "pkg/core.py"
    assert database.search(stats.repository_id, "no-such-responsibility") == []


def test_search_projection_updates_additions_deletions_and_repository_boundaries(
    repository, database, tmp_path
):
    first = RepositoryScanner(database).scan(repository)
    second_root = tmp_path / "second"
    shutil.copytree(repository, second_root)
    distinctive = second_root / "pkg" / "quasar_dispatch.py"
    distinctive.write_text(
        '"""Own quasar dispatch and stellar routing responsibility."""\n', encoding="utf-8"
    )
    second = RepositoryScanner(database).scan(second_root)

    assert database.search(first.repository_id, "quasar dispatch") == []
    assert database.search(second.repository_id, "quasar dispatch", limit=1)[0]["path"] == (
        "pkg/quasar_dispatch.py"
    )

    distinctive.unlink()
    updated = RepositoryScanner(database).scan(second_root)

    assert updated.snapshot_id != second.snapshot_id
    assert database.search(second.repository_id, "quasar dispatch") == []


def test_existing_index_backfills_search_before_serving_reads(repository, database):
    stats = RepositoryScanner(database).scan(repository)
    with database.transaction() as connection:
        connection.execute("DELETE FROM module_search")
        connection.execute(
            "DELETE FROM schema_meta WHERE key = ?",
            (f"module_search_state:{stats.repository_id}",),
        )

    reopened = AnaxiIndex(database.path)

    assert reopened.search(stats.repository_id, "Calculator", limit=1)[0]["path"] == "pkg/core.py"

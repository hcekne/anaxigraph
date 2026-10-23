"""A saved import resumes derived caches after interruption without repeating paid work."""

import pytest
from fresh_eyes_support import baseline_review
from test_portable_record import _selected_values, publish_and_clone

import anaxigraph.storage as storage
from anaxigraph.config import load_config
from anaxigraph.portable_io import read_record
from anaxigraph.portable_record import load_record, save_record
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.storage import AnaxiIndex


def test_imported_paid_rows_survive_interrupted_graph_and_resume_on_open(
    repository, database, tmp_path, monkeypatch
):
    review = baseline_review(repository, database)
    with database.connect() as connection:
        original = _selected_values(connection, review.repository_id)
    save_record(database, review.repository_id)
    clone = publish_and_clone(repository, tmp_path / "interrupted-local")
    manifest, _ = read_record(clone)
    local = AnaxiIndex(tmp_path / "interrupted.db")
    rebuild = storage.sync_knowledge

    def interrupt(connection, *arguments, **options):
        if connection.execute("SELECT 1 FROM semantic_documents LIMIT 1").fetchone():
            raise RuntimeError("interrupted derived graph")
        return rebuild(connection, *arguments, **options)

    monkeypatch.setattr(storage, "sync_knowledge", interrupt)
    with pytest.raises(RuntimeError, match="interrupted derived graph"):
        RepositoryScanner(local).scan(clone)
    with local.connect() as connection:
        rows = [dict(row) for row in connection.execute("SELECT * FROM semantic_document_values")]
        assert rows
        assert connection.execute(
            "SELECT 1 FROM schema_meta WHERE key='graph-import-pending'"
        ).fetchone()
        assert _selected_values(connection, 1) == original
    monkeypatch.setattr(storage, "sync_knowledge", rebuild)
    resumed = AnaxiIndex(local.path)
    with resumed.connect() as connection:
        assert [
            dict(row) for row in connection.execute("SELECT * FROM semantic_document_values")
        ] == rows
        assert not connection.execute(
            "SELECT 1 FROM schema_meta WHERE key IN ('graph-import-pending','index-compaction-pending')"
        ).fetchone()
        assert connection.execute("SELECT COUNT(*) FROM graph_entities").fetchone()[0] > 0
    assert read_record(clone)[0] == manifest
    assert (
        load_record(resumed, 1, clone, config=load_config(clone), after_scan=True)["status"]
        == "unchanged"
    )


def test_import_reclaims_only_derived_graph_when_final_compaction_needs_headroom(
    repository, database, tmp_path, monkeypatch
):
    from anaxigraph.persistence import index_compaction

    review = baseline_review(repository, database)
    with database.connect() as connection:
        original = _selected_values(connection, review.repository_id)
    save_record(database, review.repository_id)
    clone = publish_and_clone(repository, tmp_path / "bounded-retry")
    manifest, _ = read_record(clone)
    local = AnaxiIndex(tmp_path / "bounded-retry.db")
    preflight = index_compaction._preflight
    failures = []

    def insufficient_graph_headroom(connection, *arguments):
        paid = connection.execute("SELECT COUNT(*) FROM semantic_documents").fetchone()[0]
        graph = connection.execute("SELECT COUNT(*) FROM graph_entities").fetchone()[0]
        if paid and graph and not failures:
            failures.append(True)
            raise index_compaction.CompactionHeadroomError("measured graph-stage headroom")
        return preflight(connection, *arguments)

    monkeypatch.setattr(index_compaction, "_preflight", insufficient_graph_headroom)
    RepositoryScanner(local).scan(clone)
    assert len(failures) == 1
    with local.connect() as connection:
        assert _selected_values(connection, 1) == original
        assert connection.execute("SELECT COUNT(*) FROM graph_entities").fetchone()[0] > 0
        assert not connection.execute(
            "SELECT 1 FROM schema_meta WHERE key IN ('graph-import-pending','index-compaction-pending')"
        ).fetchone()
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert read_record(clone)[0] == manifest

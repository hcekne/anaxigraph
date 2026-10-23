"""Offline owner replacement preserves paid data across failures and page reclamation."""

from contextlib import closing

import pytest
from test_cold_semantic_payloads import _saved_rows

import anaxigraph.persistence.index_compaction as compaction
from anaxigraph.persistence.schema import SCHEMA_VERSION


def _values(database):
    with closing(database.connect()) as connection:
        return (
            dict(connection.execute("SELECT * FROM semantic_document_values").fetchone()),
            dict(connection.execute("SELECT * FROM semantic_claim_values").fetchone()),
        )


def test_compaction_reclaims_pages_and_keeps_exact_saved_rows(repository, database):
    originals = _saved_rows(repository, database)
    with database.transaction() as connection:
        connection.execute("CREATE TABLE disposable_cache(value BLOB)")
        connection.execute("INSERT INTO disposable_cache VALUES (zeroblob(3000000))")
    with database.transaction() as connection:
        connection.execute("DELETE FROM disposable_cache")
    before = database.path.stat().st_size
    compaction.compact_closed_index(
        database.path, schema_version=SCHEMA_VERSION, record_bytes=25_000_000
    )
    assert database.path.stat().st_size < before
    assert _values(database) == originals
    with closing(database.connect()) as connection:
        assert connection.execute("PRAGMA page_size").fetchone()[0] == compaction.PAGE_BYTES
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert not list(database.path.parent.glob("*.compact.tmp*"))


@pytest.mark.parametrize("phase", ["validation", "publication", "preflight"])
def test_failed_compaction_keeps_the_last_valid_index(repository, database, monkeypatch, phase):
    originals = _saved_rows(repository, database)

    def fail(*args, **kwargs):
        raise RuntimeError("injected compaction failure")

    if phase == "validation":
        monkeypatch.setattr(compaction, "_validate_staged", fail)
    elif phase == "publication":
        monkeypatch.setattr(compaction, "_publish_staged", fail)
    reserve = 200_000_000 if phase == "preflight" else 25_000_000
    with pytest.raises((RuntimeError, ValueError), match="compaction"):
        compaction.compact_closed_index(
            database.path, schema_version=SCHEMA_VERSION, record_bytes=reserve
        )
    assert _values(database) == originals
    assert not list(database.path.parent.glob("*.compact.tmp*"))


def test_initializer_retries_interrupted_publication_after_schema_commit(
    repository, database, monkeypatch
):
    from anaxigraph.storage import AnaxiIndex

    originals = _saved_rows(repository, database)
    with database.transaction() as connection:
        connection.execute("UPDATE schema_meta SET value='12' WHERE key='schema_version'")
    publish = compaction._publish_staged

    def interrupt(*args, **kwargs):
        raise RuntimeError("interrupted index publication")

    monkeypatch.setattr(compaction, "_publish_staged", interrupt)
    with pytest.raises(RuntimeError, match="interrupted index publication"):
        AnaxiIndex(database.path)
    assert _values(database) == originals
    with closing(database.connect()) as connection:
        assert connection.execute(
            "SELECT 1 FROM schema_meta WHERE key='index-compaction-pending'"
        ).fetchone()
    monkeypatch.setattr(compaction, "_publish_staged", publish)
    recovered = AnaxiIndex(database.path)
    assert _values(recovered) == originals
    with closing(recovered.connect()) as connection:
        assert not connection.execute(
            "SELECT 1 FROM schema_meta WHERE key='index-compaction-pending'"
        ).fetchone()


def test_actual_stage_guard_is_a_headroom_failure_and_preserves_paid_rows(
    repository, database, monkeypatch
):
    original = _saved_rows(repository, database)
    monkeypatch.setattr(compaction, "_stage_over_budget", lambda *_arguments: 1)
    with pytest.raises(compaction.CompactionHeadroomError, match="within 200 MB"):
        compaction.compact_closed_index(
            database.path, schema_version=SCHEMA_VERSION, record_bytes=0
        )
    assert _values(database) == original
    assert not list(database.path.parent.glob("*.compact.tmp*"))


def test_exclusive_preflight_rechecks_current_record_bytes(repository, database, monkeypatch):
    _saved_rows(repository, database)
    monkeypatch.setattr(
        compaction, "registered_record_usage", lambda _connection: {"bytes": 200_000_000}
    )
    with pytest.raises(compaction.CompactionHeadroomError, match="within 200 MB"):
        compaction.compact_closed_index(
            database.path, schema_version=SCHEMA_VERSION, record_bytes=0
        )


def test_ram_cache_rebuild_preserves_canonical_values_and_rejects_bad_admission(
    repository, database
):
    original = _saved_rows(repository, database)
    with database.transaction() as connection:
        connection.execute("INSERT INTO schema_meta VALUES('graph-import-pending','1')")

    def build(connection):
        connection.execute("DELETE FROM schema_meta WHERE key='graph-import-pending'")
        connection.execute("INSERT INTO schema_meta VALUES('staged-cache','complete')")

    def reject(_connection, _path):
        raise ValueError("final retained budget rejected")

    with pytest.raises(ValueError, match="retained budget"):
        compaction.rebuild_compact_cache(
            database.path, schema_version=SCHEMA_VERSION, build=build, admit=reject
        )
    assert _values(database) == original
    with database.connect() as connection:
        assert (
            connection.execute(
                "SELECT value FROM schema_meta WHERE key='graph-import-pending'"
            ).fetchone()[0]
            == "1"
        )
        assert not connection.execute(
            "SELECT 1 FROM schema_meta WHERE key='staged-cache'"
        ).fetchone()
    assert not list(database.path.parent.glob("*.compact.tmp*"))


def test_ram_cache_publication_keeps_a_concurrent_canonical_writer(repository, database):
    import threading

    from anaxigraph.storage_policy import admit_index_write

    original = _saved_rows(repository, database)
    entered, finished = threading.Event(), threading.Event()
    errors = []

    def writer():
        entered.set()
        try:
            with database.transaction() as connection:
                connection.execute("INSERT INTO schema_meta VALUES('late-paid-update','preserved')")
        except Exception as error:
            errors.append(error)
        finally:
            finished.set()

    worker = threading.Thread(target=writer)

    def build(connection):
        worker.start()
        assert entered.wait(2)
        assert not finished.wait(0.1)
        connection.execute("INSERT INTO schema_meta VALUES('staged-cache','complete')")

    def admit(connection, staged):
        admit_index_write(connection, staged, database.storage_policy)

    compaction.rebuild_compact_cache(
        database.path, schema_version=SCHEMA_VERSION, build=build, admit=admit
    )
    worker.join(5)
    assert not worker.is_alive() and not errors
    assert _values(database) == original
    with database.connect() as connection:
        assert (
            connection.execute(
                "SELECT value FROM schema_meta WHERE key='late-paid-update'"
            ).fetchone()[0]
            == "preserved"
        )
        assert (
            connection.execute("SELECT value FROM schema_meta WHERE key='staged-cache'").fetchone()[
                0
            ]
            == "complete"
        )

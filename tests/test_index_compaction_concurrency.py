"""Compaction coordinates connection lifetimes before replacing a live SQLite inode."""

import select
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

import anaxigraph.persistence.index_compaction as compaction
import anaxigraph.persistence.index_lifetime as lifetime
from anaxigraph.persistence.schema import SCHEMA_VERSION


def _seed(database):
    with database.transaction() as connection:
        connection.execute("CREATE TABLE concurrency_probe(value TEXT NOT NULL)")
        connection.execute("INSERT INTO concurrency_probe VALUES ('initial')")


def _compact(database):
    compaction.compact_closed_index(database.path, schema_version=SCHEMA_VERSION, record_bytes=0)


def _value(database):
    with database.connect() as connection:
        return connection.execute("SELECT value FROM concurrency_probe").fetchone()[0]


def _inode(path):
    value = path.stat()
    return value.st_dev, value.st_ino


def _observe_exclusive_attempt(monkeypatch):
    entered = Event()
    original = compaction.index_file_lock

    def attempted(*args, **kwargs):
        if kwargs.get("exclusive"):
            entered.set()
        return original(*args, **kwargs)

    monkeypatch.setattr(compaction, "index_file_lock", attempted)
    return entered


@pytest.mark.parametrize("transaction", ["reader", "writer"])
def test_held_connection_prevents_replacement_and_late_commit_is_preserved(
    database, monkeypatch, transaction
):
    _seed(database)
    old_inode = _inode(database.path)
    held = database.connect()
    held.execute("BEGIN IMMEDIATE" if transaction == "writer" else "BEGIN")
    held.execute("SELECT value FROM concurrency_probe").fetchone()
    entered = _observe_exclusive_attempt(monkeypatch)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(_compact, database)
        try:
            assert entered.wait(3), "Compactor did not attempt the exclusive lifetime lock"
            assert not pending.done()
            assert _inode(database.path) == old_inode
            held.execute("UPDATE concurrency_probe SET value='late committed change'")
            held.commit()
            assert _inode(database.path) == old_inode
        finally:
            held.close()
        pending.result(timeout=8)
    assert _inode(database.path) != old_inode
    assert _value(database) == "late committed change"


def test_connection_starting_during_publication_writes_the_new_inode(database, monkeypatch):
    _seed(database)
    old_inode = _inode(database.path)
    publishing, release, opening, opened = Event(), Event(), Event(), Event()
    original = compaction._publish_staged

    def gated(*args):
        publishing.set()
        assert release.wait(8), "Test did not release staged publication"
        return original(*args)

    def new_connection():
        opening.set()
        with database.connect() as connection:
            opened.set()
            connection.execute("UPDATE concurrency_probe SET value='new inode write'")

    monkeypatch.setattr(compaction, "_publish_staged", gated)
    with ThreadPoolExecutor(max_workers=2) as pool:
        replacing = pool.submit(_compact, database)
        reader = None
        try:
            assert publishing.wait(5)
            reader = pool.submit(new_connection)
            assert opening.wait(3)
            assert not opened.wait(0.15), "A new SQLite handle bypassed exclusive publication"
            assert _inode(database.path) == old_inode
        finally:
            release.set()
        replacing.result(timeout=8)
        assert reader is not None
        reader.result(timeout=8)
    assert _inode(database.path) != old_inode
    assert _value(database) == "new inode write"


def test_ordinary_connections_share_the_lifetime_lock(database):
    _seed(database)
    first = database.connect()
    try:
        with database.connect() as second:
            assert first.execute("SELECT value FROM concurrency_probe").fetchone()[0] == "initial"
            second.execute("UPDATE concurrency_probe SET value='shared handles'")
        assert (
            first.execute("SELECT value FROM concurrency_probe").fetchone()[0] == "shared handles"
        )
    finally:
        first.close()


def test_exclusive_timeout_keeps_the_index_and_releases_its_failed_lease(database):
    _seed(database)
    before = _inode(database.path)
    with database.connect():
        with pytest.raises(TimeoutError, match="open SQLite handles"):
            lifetime.index_file_lock(database.path, exclusive=True, timeout=0)
        assert _inode(database.path) == before
    with lifetime.index_file_lock(database.path, exclusive=True, timeout=1):
        assert _inode(database.path) == before
    assert _value(database) == "initial"


def test_unsupported_platform_refuses_replacement_but_allows_ordinary_sqlite(database, monkeypatch):
    _seed(database)
    before = _inode(database.path)
    monkeypatch.setattr(lifetime, "fcntl", None)
    assert _value(database) == "initial"
    with pytest.raises(RuntimeError, match="requires POSIX"):
        _compact(database)
    assert _inode(database.path) == before
    assert _value(database) == "initial"


def test_another_process_late_commit_survives_owner_compaction(database, monkeypatch):
    _seed(database)
    code = """
import sys
from pathlib import Path
from anaxigraph.persistence.index_lifetime import locked_connection
connection = locked_connection(Path(sys.argv[1]))
connection.execute('SELECT value FROM concurrency_probe').fetchone()
print('holding', flush=True)
assert sys.stdin.readline().strip() == 'commit'
connection.execute("UPDATE concurrency_probe SET value='other process commit'")
connection.commit()
connection.close()
print('committed', flush=True)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(database.path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    entered = _observe_exclusive_attempt(monkeypatch)
    try:
        assert select.select([process.stdout], [], [], 5)[0], (
            "Child did not acquire its shared handle"
        )
        assert process.stdout.readline().strip() == "holding"
        old_inode = _inode(database.path)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(_compact, database)
            try:
                assert entered.wait(3)
                assert not pending.done()
                assert _inode(database.path) == old_inode
            finally:
                process.stdin.write("commit\n")
                process.stdin.flush()
            stdout, stderr = process.communicate(timeout=8)
            assert process.returncode == 0, stderr
            assert stdout.strip() == "committed"
            pending.result(timeout=8)
        assert _inode(database.path) != old_inode
        assert _value(database) == "other process commit"
    finally:
        if process.poll() is None:
            process.terminate()
            process.communicate(timeout=5)

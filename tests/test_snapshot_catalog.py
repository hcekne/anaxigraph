from __future__ import annotations

import sqlite3

from anaxigraph.persistence.snapshot_catalog import read_snapshots
from anaxigraph.persistence.temporal_reads import snapshot_files, snapshot_relationship_edges
from anaxigraph.scanner import RepositoryScanner


def test_catalog_counts_match_reconstruction_without_reading_file_metadata(repository, database):
    scanner = RepositoryScanner(database)
    first = scanner.scan(repository)
    (repository / "pkg" / "consumer.py").unlink()
    (repository / "pkg" / "util.py").write_text("def double(value):\n    return value * 2\n")
    second = scanner.scan(repository)
    with database.connect() as connection:
        expected = {}
        for snapshot_id in (first.snapshot_id, second.snapshot_id):
            files = snapshot_files(connection, snapshot_id)
            expected[snapshot_id] = {
                "file_count": len(files),
                "lines_of_code": sum(file["lines_of_code"] for file in files),
                "relationship_count": len(snapshot_relationship_edges(connection, snapshot_id)),
            }

        def deny_expensive_columns(operation, table, column, *_args):
            if operation == sqlite3.SQLITE_READ and table == "file_facts":
                assert column in {"id", "lines_of_code"}, f"Catalog expanded {column}"
            return sqlite3.SQLITE_OK

        connection.set_authorizer(deny_expensive_columns)
        actual = read_snapshots(connection, first.repository_id, limit=100)
    assert len(actual) == 2
    for snapshot in actual:
        assert {key: snapshot[key] for key in expected[snapshot["id"]]} == expected[snapshot["id"]]
        assert snapshot["reconstruction"]["files"]["returned_rows"] == snapshot["file_count"]


def test_catalog_aggregates_large_and_empty_fact_sets():
    from anaxigraph.persistence.snapshot_catalog import _edge_count, _file_lines

    with sqlite3.connect(":memory:") as connection:
        connection.execute("CREATE TABLE file_facts(id INTEGER PRIMARY KEY, lines_of_code INTEGER)")
        connection.execute("CREATE TABLE relationship_edges(relationship_set_id INTEGER)")
        connection.executemany(
            "INSERT INTO file_facts VALUES (?, ?)", [(index, index) for index in range(1, 1801)]
        )
        connection.executemany(
            "INSERT INTO relationship_edges VALUES (?)", [(index,) for index in range(1, 1801)] * 2
        )
        identifiers = list(range(1, 1801))
        assert _file_lines(connection, identifiers) == sum(identifiers)
        assert _edge_count(connection, identifiers) == 3600
        assert _file_lines(connection, []) == _edge_count(connection, []) == 0
        try:
            _file_lines(connection, [9999])
        except RuntimeError as error:
            assert "missing file fact" in str(error)
        else:
            raise AssertionError("Missing canonical facts must not silently become zero lines")

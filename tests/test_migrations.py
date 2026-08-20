from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from anaxigraph.persistence import SUPPORTED_SCHEMA_VERSIONS
from anaxigraph.storage import SCHEMA_VERSION, AnaxiIndex


def _schema_version(database: AnaxiIndex) -> int:
    with database.connect() as connection:
        return int(
            connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()[0]
        )


def _columns(database: AnaxiIndex, table: str) -> set[str]:
    with database.connect() as connection:
        return {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}


def test_fresh_and_current_schema_initialization_is_idempotent(tmp_path):
    path = tmp_path / "current.db"

    first = AnaxiIndex(path)
    second = AnaxiIndex(path)

    assert SUPPORTED_SCHEMA_VERSIONS == frozenset({2, 6, 7, 8, 9})
    assert _schema_version(first) == _schema_version(second) == SCHEMA_VERSION == 9
    assert {"base_snapshot_id", "sequence"} <= _columns(first, "snapshots")
    assert _columns(first, "file_facts")
    assert _columns(first, "snapshot_file_changes")
    assert _columns(first, "relationship_sets")
    assert "file_fact_id" in _columns(first, "semantic_jobs")


def test_released_v2_schema_migrates_without_losing_repository_data(tmp_path):
    path = tmp_path / "v2.db"
    fixture = Path(__file__).parent / "fixtures" / "schema-v2.sql"
    with sqlite3.connect(path) as connection:
        connection.executescript(fixture.read_text(encoding="utf-8"))

    database = AnaxiIndex(path)

    assert _schema_version(database) == 9
    assert database.repository(1)["name"] == "Preserved v2 repository"
    assert {"worker_id", "lease_expires_at", "lease_token_hash", "executor_id"} <= _columns(
        database, "semantic_jobs"
    )
    assert {"previous_document_id", "executor_id", "executor_model"} <= _columns(
        database, "semantic_documents"
    )
    assert {"executor_id", "executor_model"} <= _columns(database, "semantic_claims")


@pytest.mark.parametrize("version", [1, 3, 4, 5, 10])
def test_untested_or_future_schema_versions_fail_closed(tmp_path, version):
    path = tmp_path / f"unsupported-{version}.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute(
            "INSERT INTO schema_meta(key, value) VALUES ('schema_version', ?)",
            (str(version),),
        )

    with pytest.raises(RuntimeError, match="newer than supported|no tested migration path"):
        AnaxiIndex(path)

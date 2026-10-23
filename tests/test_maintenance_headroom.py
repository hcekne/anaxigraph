"""Disposable rewrites use bounded transient space and still meet final storage limits."""

import pytest

import anaxigraph.storage_policy as policy
from anaxigraph.storage_policy import StoragePolicy, maintenance_headroom


def test_disposable_rewrite_compacts_before_normal_budget_admission(database):
    database.storage_policy = StoragePolicy(
        index_bytes=2_000_000, budget_bytes=3_000_000, record_bytes=1_000_000
    )
    with database.transaction(maintenance=True) as connection:
        with maintenance_headroom(connection, database.path):
            connection.execute("CREATE TABLE scratch_cache(value BLOB)")
            connection.execute("INSERT INTO scratch_cache VALUES(zeroblob(3000000))")
            connection.execute("DELETE FROM scratch_cache")
        connection.execute(
            "INSERT OR REPLACE INTO schema_meta VALUES('index-compaction-pending','true')"
        )
    assert database.path.stat().st_size > database.storage_policy.index_bytes
    database.finish_cache_maintenance()
    assert database.path.stat().st_size < database.storage_policy.index_bytes
    with pytest.raises(ValueError, match="budget reached"):
        with database.transaction() as connection:
            connection.execute("INSERT INTO scratch_cache VALUES(zeroblob(3000000))")


def test_positive_physical_guard_rolls_back_only_the_rewrite(database, monkeypatch):
    actual = policy.index_file_usage
    samples = []

    def usage(path):
        samples.append(True)
        if len(samples) > 1:
            return {"index_bytes": 200_000_000, "wal_bytes": 0, "shm_bytes": 0}
        return actual(path)

    monkeypatch.setattr(policy, "index_file_usage", usage)
    with pytest.raises(ValueError, match="physical storage ceiling"):
        with database.transaction(maintenance=True) as connection:
            with maintenance_headroom(connection, database.path):
                connection.execute(
                    "INSERT INTO schema_meta VALUES('uncommitted',zeroblob(3000000))"
                )
    with database.connect() as connection:
        assert not connection.execute(
            "SELECT 1 FROM schema_meta WHERE key='uncommitted'"
        ).fetchone()
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

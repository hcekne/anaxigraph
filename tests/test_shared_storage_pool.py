"""Actual index and portable bytes compete for one pool without reserving unused maxima."""

import json
from dataclasses import replace

import pytest

from anaxigraph.config import load_config
from anaxigraph.portable_io import publish_record, read_record
from anaxigraph.portable_record import save_record
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.storage_policy import StoragePolicy, storage_policy
from anaxigraph.storage_status import storage_status
from anaxigraph.storage_usage import index_file_usage, managed_record_usage, registered_record_usage


def _managed(root, size):
    directory = root / "anaxigraph"
    directory.mkdir(exist_ok=True)
    (directory / "record.json").write_text(json.dumps({"format": "anaxigraph-record-v4"}))
    (directory / "payload.bin").write_bytes(b"x" * size)


def test_component_maxima_compete_for_unchanged_default_pool():
    policy = storage_policy()
    assert (policy.budget_bytes, policy.index_bytes, policy.record_bytes) == (
        100_000_000,
        95_000_000,
        25_000_000,
    )
    assert policy.index_bytes + policy.record_bytes > policy.budget_bytes
    smaller = storage_policy({"index_bytes": 1_000_000})
    assert smaller.index_bytes == 1_000_000
    with pytest.raises(ValueError, match="component ceiling"):
        storage_policy({"index_bytes": 101_000_000})
    with pytest.raises(ValueError, match="200 MB"):
        storage_policy({"budget_bytes": 201_000_000})


def test_unused_record_ceiling_does_not_reserve_space_but_actual_record_growth_blocks_writes(
    repository, database
):
    RepositoryScanner(database).scan(repository)
    _managed(repository, 10_000)
    database.storage_policy = StoragePolicy(
        budget_bytes=6_000_000, index_bytes=5_500_000, record_bytes=4_000_000
    )
    with database.transaction() as connection:
        connection.execute("INSERT INTO schema_meta VALUES('kept',zeroblob(3500000))")
    assert database.path.stat().st_size > 2_000_000
    _managed(repository, 2_500_000)
    with pytest.raises(ValueError, match="shared storage budget"):
        with database.transaction() as connection:
            connection.execute("INSERT INTO schema_meta VALUES('blocked','must not commit')")
    with database.connect() as connection:
        assert (
            connection.execute("SELECT length(value) FROM schema_meta WHERE key='kept'").fetchone()[
                0
            ]
            == 3_500_000
        )
        assert (
            connection.execute("SELECT 1 FROM schema_meta WHERE key='blocked'").fetchone() is None
        )


def test_pending_database_growth_rolls_back_when_it_would_take_the_record_space(
    repository, database
):
    RepositoryScanner(database).scan(repository)
    _managed(repository, 1_500_000)
    ceiling = database.path.stat().st_size + 3_000_000
    database.storage_policy = StoragePolicy(
        budget_bytes=ceiling, index_bytes=ceiling, record_bytes=2_500_000
    )
    with pytest.raises(ValueError, match="shared storage budget"):
        with database.transaction() as connection:
            connection.execute("INSERT INTO schema_meta VALUES('too-much',zeroblob(2500000))")
    with database.connect() as connection:
        assert (
            connection.execute("SELECT 1 FROM schema_meta WHERE key='too-much'").fetchone() is None
        )
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_every_registered_checkout_record_counts_toward_the_same_pool(
    repository, database, tmp_path
):
    first = RepositoryScanner(database).scan(repository)
    other = tmp_path / "other"
    other.mkdir()
    (other / "x.py").write_text("VALUE=1\n")
    RepositoryScanner(database).scan(other)
    _managed(repository, 500_000)
    _managed(other, 600_000)
    with database.connect() as connection:
        usage = registered_record_usage(connection)
        assert usage["records"] == 2 and usage["bytes"] > 1_100_000
    status = storage_status(database, repository, StoragePolicy())
    assert status["all_record_bytes"] == usage["bytes"]
    assert status["record_bytes"] < status["all_record_bytes"]
    database.storage_policy = StoragePolicy(
        budget_bytes=status["index_bytes"] + 900_000,
        index_bytes=status["index_bytes"] + 900_000,
        record_bytes=1_000_000,
    )
    with pytest.raises(ValueError, match="shared storage budget"):
        with database.transaction() as connection:
            connection.execute("INSERT INTO schema_meta VALUES('multi-overflow','rejected')")
    assert database.repository(first.repository_id) is not None


def test_rejected_export_keeps_last_valid_record_and_receipt(repository, database, monkeypatch):
    import anaxigraph.portable_io as io
    import anaxigraph.portable_record as records

    stats = RepositoryScanner(database).scan(repository)
    save_record(database, stats.repository_id)
    directory = repository / "anaxigraph"
    before = {
        str(path.relative_to(directory)): path.read_bytes()
        for path in directory.rglob("*")
        if path.is_file()
    }
    with database.connect() as connection:
        receipt = connection.execute(
            "SELECT value FROM schema_meta WHERE key=?", (f"portable-record:{stats.repository_id}",)
        ).fetchone()[0]
        active = (
            sum(index_file_usage(database.path).values())
            + managed_record_usage(repository)["bytes"]
        )
    ceiling = active + 100_000
    config = replace(
        load_config(repository),
        storage=StoragePolicy(budget_bytes=ceiling, index_bytes=ceiling, record_bytes=ceiling),
    )
    monkeypatch.setattr(
        records, "record_views", lambda *_args, **_kwargs: {"architecture/plan.md": b"x" * 300_000}
    )
    monkeypatch.setattr(
        io, "_write_if_changed", lambda *_args: pytest.fail("budget checked after a file write")
    )
    with pytest.raises(ValueError, match="shared storage budget"):
        save_record(database, stats.repository_id, config=config)
    assert {
        str(path.relative_to(directory)): path.read_bytes()
        for path in directory.rglob("*")
        if path.is_file()
    } == before
    read_record(repository)
    with database.connect() as connection:
        assert (
            connection.execute(
                "SELECT value FROM schema_meta WHERE key=?",
                (f"portable-record:{stats.repository_id}",),
            ).fetchone()[0]
            == receipt
        )


def test_managed_record_walk_is_bounded_and_never_follows_symlinks(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    _managed(root, 1)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "anaxigraph" / "external").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        managed_record_usage(root)
    (root / "anaxigraph" / "external").unlink()
    for index in range(63):
        (root / "anaxigraph" / f"extra-{index}").touch()
    with pytest.raises(ValueError, match="64-file"):
        managed_record_usage(root)


def _overwrite_blob(connection, row, value, size):
    with connection.blobopen("schema_meta", "value", row) as blob:
        block = value * 1_000_000
        for _ in range(size // len(block)):
            blob.write(block)


def test_near_default_pool_allows_atomic_rewrite_but_denies_steady_growth_and_hard_wal_overflow(
    repository, database
):
    RepositoryScanner(database).scan(repository)
    _managed(repository, 15_000_000)
    with database.transaction() as connection:
        connection.execute("INSERT INTO schema_meta VALUES('near-pool',zeroblob(78000000))")
        row = connection.execute("SELECT rowid FROM schema_meta WHERE key='near-pool'").fetchone()[
            0
        ]
    reader = database.connect()
    try:
        reader.execute("BEGIN")
        reader.execute("SELECT length(value) FROM schema_meta WHERE key='near-pool'").fetchone()
        with database.transaction() as connection:
            _overwrite_blob(connection, row, b"y", 78_000_000)
        status = storage_status(database, repository, StoragePolicy())
        assert status["steady_bytes"] < 100_000_000 < status["active_bytes"] < 200_000_000
        assert status["within_budget"] and status["checkpoint_or_truncate_pending"]
        assert status["transient_bytes"] > 50_000_000
        with pytest.raises(ValueError, match="shared storage budget"):
            with database.transaction() as connection:
                connection.execute(
                    "INSERT INTO schema_meta VALUES('steady-overflow',zeroblob(8000000))"
                )
        with database.transaction() as connection:
            _overwrite_blob(connection, row, b"w", 20_000_000)
        with database.connect() as connection:
            with pytest.raises(ValueError, match="publication.*200 MB hard"):
                publish_record(
                    repository,
                    {},
                    {},
                    {f"architecture/part-{i}.md": b"x" * 3_000_000 for i in range(3)},
                    pool=(connection, database.path),
                )
        assert (repository / "anaxigraph" / "payload.bin").stat().st_size == 15_000_000
        assert not (repository / "anaxigraph" / "manifest.json").exists()
        with pytest.raises(ValueError, match="200 MB hard"):
            with database.transaction() as connection:
                _overwrite_blob(connection, row, b"z", 78_000_000)
    finally:
        reader.close()
    with database.connect() as connection:
        assert (
            connection.execute(
                "SELECT hex(substr(value,1,1)) FROM schema_meta WHERE key='near-pool'"
            ).fetchone()[0]
            == "77"
        )
        assert (
            connection.execute("SELECT 1 FROM schema_meta WHERE key='steady-overflow'").fetchone()
            is None
        )
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    assert storage_status(database, repository, StoragePolicy())["active_bytes"] < 100_000_000

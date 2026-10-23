"""Checkpoint removal is harmless during measurement; other stat errors stay visible."""

import errno
from pathlib import Path

import pytest

from anaxigraph.history_jobs import HistoryJobService
from anaxigraph.storage_usage import index_file_usage


def _disappearing_stat(monkeypatch, target, *, remove=False, failure=None):
    stat, exists = Path.stat, Path.exists
    attempts = []

    def positive_exists(path):
        return True if path == target else exists(path)

    def disappearing(path, *args, **options):
        if path != target:
            return stat(path, *args, **options)
        attempts.append(path)
        if failure is not None:
            raise failure
        if remove:
            path.unlink(missing_ok=True)
            return stat(path, *args, **options)
        raise FileNotFoundError(errno.ENOENT, "checkpoint removed sidecar", str(path))

    monkeypatch.setattr(Path, "exists", positive_exists)
    monkeypatch.setattr(Path, "stat", disappearing)
    return attempts


@pytest.mark.parametrize("suffix,field", [("-wal", "wal_bytes"), ("-shm", "shm_bytes")])
def test_storage_measurement_tolerates_sidecar_disappearing_after_positive_exists(
    tmp_path, monkeypatch, suffix, field
):
    database = tmp_path / "index.db"
    database.write_bytes(b"main data")
    target = Path(str(database) + suffix)
    target.write_bytes(b"ephemeral sidecar")
    attempts = _disappearing_stat(monkeypatch, target, remove=True)
    result = index_file_usage(database)
    assert attempts
    assert result["index_bytes"] == len(b"main data")
    assert result[field] == 0


def test_history_measurement_tolerates_wal_disappearing_after_positive_exists(
    database, monkeypatch
):
    target = Path(str(database.path) + "-wal")
    attempts = _disappearing_stat(monkeypatch, target)
    rows, size = HistoryJobService(database)._measure()
    assert attempts
    assert rows >= 0
    assert size == database.path.stat().st_size


@pytest.mark.parametrize("context", ["storage", "history"])
@pytest.mark.parametrize("error_type", [PermissionError, OSError])
def test_size_measurement_does_not_hide_other_filesystem_errors(
    database, monkeypatch, context, error_type
):
    target = Path(str(database.path) + "-wal")
    failure = error_type(
        errno.EACCES if error_type is PermissionError else errno.EIO, "stat failed"
    )
    _disappearing_stat(monkeypatch, target, failure=failure)
    with pytest.raises(error_type) as caught:
        if context == "storage":
            index_file_usage(database.path)
        else:
            HistoryJobService(database)._measure()
    assert caught.value is failure

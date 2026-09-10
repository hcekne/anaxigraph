from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from anaxigraph.cli import main
from anaxigraph.persistence import (
    create_index_backup,
    restore_index_backup,
    validate_index_backup,
)
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.storage import AnaxiIndex


def test_backup_closes_all_handles_before_atomic_restore(database, tmp_path, monkeypatch):
    original_connect = sqlite3.connect
    connections = []

    def retained_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connections.append(connection)  # Do not let garbage collection hide leaked handles.
        return connection

    monkeypatch.setattr(sqlite3, "connect", retained_connect)
    backup = create_index_backup(database.path, tmp_path / "portable.backup")
    restore_index_backup(database.path, backup.path)
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
    with closing(original_connect(backup.path)) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    assert not Path(f"{backup.path}-wal").exists()


def test_restore_accepts_a_closed_legacy_wal_backup_from_read_only_storage(database, tmp_path):
    directory = tmp_path / "read-only"
    directory.mkdir()
    backup = directory / "legacy.backup"
    with closing(database.connect()) as source, closing(sqlite3.connect(backup)) as target:
        source.backup(target)  # Old releases retained WAL mode in the backup header.
    before = backup.read_bytes()
    backup.chmod(0o444)
    directory.chmod(0o555)
    try:
        restored = restore_index_backup(tmp_path / "restored.db", backup)
        assert restored.schema_version == 11
        assert backup.read_bytes() == before
        assert sorted(path.name for path in directory.iterdir()) == ["legacy.backup"]
    finally:
        directory.chmod(0o755)
        backup.chmod(0o644)


def test_backup_validation_refuses_to_ignore_nonempty_wal(database, tmp_path):
    backup = create_index_backup(database.path, tmp_path / "journaled.backup")
    with closing(sqlite3.connect(backup.path)) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("INSERT INTO schema_meta VALUES('pending-journal', 'value')")
        connection.commit()
        assert Path(f"{backup.path}-wal").stat().st_size > 0
        with pytest.raises(ValueError, match="journal"):
            validate_index_backup(backup.path)
        with pytest.raises(ValueError, match="journal"):
            restore_index_backup(tmp_path / "must-not-exist.db", backup.path)
    assert not (tmp_path / "must-not-exist.db").exists()


def test_operator_backup_round_trip_preserves_source_and_replaces_index(
    repository: Path,
    database: AnaxiIndex,
    tmp_path: Path,
) -> None:
    stats = RepositoryScanner(database).scan(repository)
    original = database.repository(stats.repository_id)
    backup_path = tmp_path / "recovery" / "anaxi-index.backup"

    created = create_index_backup(database.path, backup_path)
    with database.transaction() as connection:
        connection.execute(
            "UPDATE repositories SET name = 'changed after backup' WHERE id = ?",
            (stats.repository_id,),
        )

    restored = restore_index_backup(database.path, created.path)
    reopened = AnaxiIndex(database.path)

    assert reopened.repository(stats.repository_id)["name"] == original["name"]
    assert restored.path == database.path
    assert created.path.exists()
    assert validate_index_backup(created.path).sha256 == created.sha256


def test_operator_backup_fails_closed_for_existing_output_and_invalid_source(
    database: AnaxiIndex,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    destination = tmp_path / "existing.backup"
    destination.write_text("do not overwrite", encoding="utf-8")

    with pytest.raises(ValueError, match="already exists"):
        create_index_backup(database.path, destination)
    with pytest.raises((RuntimeError, sqlite3.DatabaseError)):
        restore_index_backup(database.path, destination)
    assert destination.read_text(encoding="utf-8") == "do not overwrite"

    with pytest.raises(SystemExit, match="2"):
        main(["restore", str(destination), "--db", str(database.path), "--yes"])
    assert "Invalid SQLite backup" in capsys.readouterr().err


def test_backup_and_restore_cli_require_explicit_replacement_confirmation(
    repository: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "cli-index.db"
    database = AnaxiIndex(database_path)
    stats = RepositoryScanner(database).scan(repository)
    original_name = database.repository(stats.repository_id)["name"]
    backup_path = tmp_path / "cli-index.backup"

    main(["backup", "--db", str(database_path), "--output", str(backup_path), "--json"])
    backup_report = json.loads(capsys.readouterr().out)
    with database.transaction() as connection:
        connection.execute(
            "UPDATE repositories SET name = 'changed after backup' WHERE id = ?",
            (stats.repository_id,),
        )

    with pytest.raises(SystemExit, match="2"):
        main(["restore", str(backup_path), "--db", str(database_path)])
    assert "stop its services and pass --yes" in capsys.readouterr().err

    main(["restore", str(backup_path), "--db", str(database_path), "--yes", "--json"])
    restore_report = json.loads(capsys.readouterr().out)

    assert backup_report["status"] == "complete"
    assert backup_report["backup"]["path"] == str(backup_path)
    assert restore_report["status"] == "complete"
    assert restore_report["health"] == "healthy"
    assert restore_report["final_schema_version"] == 11
    assert AnaxiIndex(database_path).repository(stats.repository_id)["name"] == original_name

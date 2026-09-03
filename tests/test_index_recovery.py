from __future__ import annotations

import json
import sqlite3
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

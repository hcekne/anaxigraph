"""Saved AI work can be recovered without backing up gigabytes of deterministic caches."""

import sqlite3

import pytest
from fresh_eyes_support import baseline_review

from anaxigraph.persistence.index_backup import restore_index_backup
from anaxigraph.persistence.understanding_backup import create_understanding_backup
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.storage import AnaxiIndex
from anaxigraph.understanding import SemanticEngine


def test_recovery_rebuilds_graph_and_reuses_preserved_file_analyses(repository, database, tmp_path):
    review = baseline_review(repository, database)
    archive = tmp_path / "understanding.backup"
    create_understanding_backup(database, archive)
    with sqlite3.connect(archive) as saved:
        assert saved.execute("SELECT COUNT(*) FROM relationship_edges").fetchone()[0] == 0
        assert saved.execute("SELECT COUNT(*) FROM fact_symbols").fetchone()[0] == 0
        assert saved.execute("SELECT COUNT(*) FROM semantic_documents").fetchone()[0] > 0
        assert saved.execute("PRAGMA foreign_key_check").fetchall() == []
    recovered_path = tmp_path / "recovered.db"
    restore_index_backup(recovered_path, archive)
    recovered = AnaxiIndex(recovered_path)
    stats = RepositoryScanner(recovered).scan(repository)
    assert recovered.overview(stats.repository_id)["files"] == 8
    assert stats.relationships > 0
    SemanticEngine(recovered).plan(stats.repository_id, repository, review.config)
    with recovered.connect() as connection:
        assert not connection.execute(
            "SELECT 1 FROM semantic_jobs WHERE snapshot_id=? AND job_kind='intrinsic' AND status='pending'",
            (stats.snapshot_id,),
        ).fetchone()
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_recovery_budget_rejection_does_not_write_an_archive(repository, database, tmp_path):
    RepositoryScanner(database).scan(repository)
    target = tmp_path / "recovery.backup"
    with pytest.raises(ValueError, match="budget"):
        create_understanding_backup(database, target, limit=1)
    assert not target.exists()
    assert not list(tmp_path.glob(".*.tmp*"))

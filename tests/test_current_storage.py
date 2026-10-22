"""Storage acceptance: bounded current records, independent clones and safe migration."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace

import pytest
from fresh_eyes_support import baseline_review
from semantic_support import _agent_dossier, _enable_agent_semantics
from test_portable_record import publish_and_clone

from anaxigraph.config import load_config
from anaxigraph.persistence.current_retention import retain_current_index
from anaxigraph.portable_io import publish_record, read_record
from anaxigraph.portable_record import save_record
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_freshness import semantic_input_hash
from anaxigraph.storage import AnaxiIndex
from anaxigraph.storage_policy import StoragePolicy, storage_policy
from anaxigraph.understanding import SemanticEngine


def files(root):
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


def test_export_cannot_resurrect_excluded_historical_runtime_files(repository, database):
    policy = repository / ".anaxigraph.yml"
    policy.write_text(policy.read_text() + "\nstorage:\n  detailed_history: true\n")
    data = repository / "data"
    data.mkdir()
    for number in range(60):
        (data / f"runtime-{number}.json").write_text(json.dumps({"payload": "X" * 8_000}))
    scanner = RepositoryScanner(database)
    for generation in range(4):
        (repository / "pkg/util.py").write_text(f"VERSION = {generation}\n")
        stats = scanner.scan(repository)
    policy.write_text(policy.read_text() + "\nignore: [data/**]\n")
    scanner.scan(repository)
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM file_facts").fetchone()[0] > 60
    saved = save_record(database, stats.repository_id)
    manifest, tables = read_record(repository)
    assert manifest["contents"] == "current_understanding"
    assert not set(tables) & {
        "snapshots",
        "file_facts",
        "fact_symbols",
        "relationship_edges",
        "git_changes",
        "metrics",
    }
    assert not any(row["value"]["path"].startswith("data/") for row in tables["source_files"])
    assert saved["bytes"] < 20_000
    assert saved["files"] <= 32


@pytest.mark.parametrize("constraint", ["bytes", "files"])
def test_export_budget_is_checked_before_any_write_and_keeps_previous_record(
    tmp_path, monkeypatch, constraint
):
    import anaxigraph.portable_io as io

    publish_record(tmp_path, {}, {}, {"architecture/plan.md": b"Keep me\n"})
    previous = files(tmp_path)
    policy = (
        replace(StoragePolicy(), record_bytes=200)
        if constraint == "bytes"
        else replace(StoragePolicy(), record_files=2)
    )

    def unexpected(*args):
        raise AssertionError("budget rejection must happen before writing")

    monkeypatch.setattr(io, "_write_if_changed", unexpected)
    with pytest.raises(ValueError, match="budget"):
        publish_record(tmp_path, {}, {}, {"architecture/plan.md": b"New value\n"}, policy=policy)
    assert files(tmp_path) == previous
    read_record(tmp_path)


def test_failed_partition_write_cleans_new_output_and_keeps_last_valid_record(
    tmp_path, monkeypatch
):
    import anaxigraph.portable_io as io

    publish_record(tmp_path, {}, {})
    before = files(tmp_path)
    original = io._write_if_changed

    def interrupted(path, content):
        if path.name.startswith("second-"):
            raise OSError("disk write interrupted")
        return original(path, content)

    monkeypatch.setattr(io, "_write_if_changed", interrupted)
    with pytest.raises(OSError, match="interrupted"):
        publish_record(
            tmp_path,
            {
                "first": [{"key": "first:a", "value": 1}],
                "second": [{"key": "second:b", "value": 2}],
            },
            {},
        )
    assert files(tmp_path) == before


def test_repeated_unchanged_scans_and_exports_have_bounded_storage(repository, database):
    scanner = RepositoryScanner(database)
    first = scanner.scan(repository)
    save_record(database, first.repository_id)
    before = files(repository / "anaxigraph")
    for _ in range(24):
        assert scanner.scan(repository).analyzed == 0
        assert save_record(database, first.repository_id)["changed_files"] == 0
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM analysis_runs").fetchone()[0] <= 16
        assert (
            connection.execute("SELECT COUNT(*) FROM file_facts").fetchone()[0] == first.discovered
        )
    assert files(repository / "anaxigraph") == before
    assert database.path.stat().st_size < 1_000_000


def test_bounded_comparison_checkpoints_are_still_reconstructable(repository, database):
    scanner = RepositoryScanner(database)
    for version in range(9):
        (repository / "pkg/util.py").write_text(f"VERSION={version}\n")
        current = scanner.scan(repository)
    with database.connect() as connection:
        snapshots = [row[0] for row in connection.execute("SELECT id FROM snapshots")]
        assert len(snapshots) == 3
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    for identifier in snapshots:
        assert database.overview(current.repository_id, identifier)["files"] == 8
    assert database.path.with_name(database.path.name + ".before-current-storage.backup").is_file()


def test_backed_up_compaction_preserves_saved_reviews_and_clone_reuses_them(
    repository, database, tmp_path
):
    review = baseline_review(repository, database)
    review.engine.start_fresh_eyes_review(review.repository_id, repository, review.config)
    review.run_until_complete()
    for number in range(5):
        (repository / "pkg/util.py").write_text(f"VERSION={number}\n")
        RepositoryScanner(database).scan(repository)
    compacted = retain_current_index(
        database, review.repository_id, load_config(repository).storage, migrate=True
    )
    with sqlite3.connect(compacted["recovery_backup"]) as backup:
        assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert backup.execute("SELECT COUNT(*) FROM semantic_documents").fetchone()[0] > 0
    with database.connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM semantic_documents WHERE document_kind='fresh_review'"
            ).fetchone()[0]
            > 0
        )
    save_record(database, review.repository_id)
    root = publish_and_clone(repository, tmp_path / "second-machine")
    local = AnaxiIndex(tmp_path / "second.db")
    stats = RepositoryScanner(local).scan(root)
    with local.connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM semantic_documents WHERE document_kind='fresh_review'"
            ).fetchone()[0]
            > 0
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert not SemanticEngine(local).status(stats.repository_id, load_config(root).semantic)[
        "semantically_ready"
    ]


def test_storage_configuration_cannot_raise_the_hard_ceiling():
    with pytest.raises(ValueError, match="200 MB"):
        storage_policy({"budget_bytes": 201_000_000})
    with pytest.raises(ValueError, match="fit"):
        storage_policy({"budget_bytes": 50_000_000})


def test_concise_output_preserves_the_083_input_cache_contract():
    evidence = {"raw_hash": "a" * 64, "detailed_reviews": False}
    golden = "3605ebabaa220b7089879f2253d7523abcd795afd31b1be78eae2b566d0fd0e7"
    assert semantic_input_hash("module-intrinsic-v1", "v1", evidence) == golden
    assert semantic_input_hash("module-intrinsic-v1", "v2", evidence) != golden
    assert (
        semantic_input_hash("module-intrinsic-v1", "v1", {**evidence, "raw_hash": "b" * 64})
        != golden
    )


def test_local_index_budget_rolls_back_a_write_instead_of_growing(database):
    database.storage_policy = replace(StoragePolicy(), index_bytes=1_000_000)
    with pytest.raises(ValueError, match="budget"):
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO schema_meta(key,value) VALUES ('oversized',?)", ("X" * 2_000_000,)
            )
    with database.connect() as connection:
        assert (
            connection.execute("SELECT 1 FROM schema_meta WHERE key='oversized'").fetchone() is None
        )
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert database.path.stat().st_size <= 1_000_000


def test_changed_file_is_not_imported_as_current_understanding(repository, database, tmp_path):
    review = baseline_review(repository, database)
    save_record(database, review.repository_id)
    root = publish_and_clone(repository, tmp_path / "other")
    (root / "pkg/core.py").write_text("CHANGED=True\n")
    local = AnaxiIndex(tmp_path / "other.db")
    stats = RepositoryScanner(local).scan(root)
    with local.connect() as connection:
        assert (
            connection.execute(
                "SELECT 1 FROM semantic_scope_states WHERE snapshot_id=? AND scope_key='pkg/core.py' AND status='current'",
                (stats.snapshot_id,),
            ).fetchone()
            is None
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM semantic_scope_states WHERE snapshot_id=? AND scope_type='module' AND status='current'",
                (stats.snapshot_id,),
            ).fetchone()[0]
            > 0
        )


def test_scanning_changes_preserves_and_exports_unchanged_partial_file_understanding(
    repository, database, tmp_path
):
    _enable_agent_semantics(repository)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    work = engine.claim_agent_work(stats.repository_id, repository, config, agent_id="worker")
    path = work["analysis_request"]["path"]
    engine.submit_agent_work(
        stats.repository_id,
        repository,
        config,
        job_id=work["job"]["id"],
        lease_token=work["lease"]["token"],
        dossier=_agent_dossier(work["analysis_request"]),
    )
    for number in range(8):
        (repository / "pkg/new_feature.py").write_text(f"FEATURE={number}\n")
        RepositoryScanner(database).scan(repository)
    with database.connect() as connection:
        assert connection.execute(
            "SELECT 1 FROM semantic_documents WHERE scope_key=? AND document_kind='intrinsic'",
            (path,),
        ).fetchone()
    save_record(database, stats.repository_id)
    root = publish_and_clone(repository, tmp_path / "resumed")
    local = AnaxiIndex(tmp_path / "resumed.db")
    resumed = RepositoryScanner(local).scan(root)
    SemanticEngine(local).plan(resumed.repository_id, root, load_config(root))
    with local.connect() as connection:
        assert not connection.execute(
            "SELECT 1 FROM semantic_jobs WHERE scope_key=? AND job_kind='intrinsic' AND status='pending'",
            (path,),
        ).fetchone()

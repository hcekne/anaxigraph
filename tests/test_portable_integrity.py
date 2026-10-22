"""Interrupted publication, stable Git diffs and independent local caches."""

from __future__ import annotations

import hashlib
import json

import pytest
from test_portable_record import git, publish_and_clone

from anaxigraph.config import load_config
from anaxigraph.portable_io import publish_record, read_record
from anaxigraph.portable_record import load_record, record_status, save_record
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.storage import AnaxiIndex


def test_unchanged_source_scan_and_reexport_do_not_churn_git_files(repository, database):
    stats = RepositoryScanner(database).scan(repository)
    save_record(database, stats.repository_id)
    git(repository, "add", "anaxigraph")
    git(repository, "commit", "-qm", "Architecture record")
    before = {
        str(path.relative_to(repository)): path.read_bytes()
        for path in (repository / "anaxigraph").rglob("*")
        if path.is_file()
    }
    rescanned = RepositoryScanner(database).scan(repository)
    assert rescanned.snapshot_id == stats.snapshot_id
    assert rescanned.analyzed == 0
    result = save_record(database, stats.repository_id)
    after = {
        str(path.relative_to(repository)): path.read_bytes()
        for path in (repository / "anaxigraph").rglob("*")
        if path.is_file()
    }
    assert result["changed_files"] == 0
    assert before == after
    assert git(repository, "status", "--porcelain", "--", "anaxigraph") == ""


def test_first_publication_can_resume_after_manifest_write_is_interrupted(
    repository, database, monkeypatch
):
    stats = RepositoryScanner(database).scan(repository)
    import anaxigraph.portable_io as portable_io

    write = portable_io._write_if_changed

    def interrupted(path, content):
        if path.name == "manifest.json":
            raise OSError("simulated interruption")
        return write(path, content)

    monkeypatch.setattr(portable_io, "_write_if_changed", interrupted)
    with pytest.raises(OSError, match="interruption"):
        save_record(database, stats.repository_id)
    assert (
        load_record(database, stats.repository_id, repository, config=load_config(repository))[
            "status"
        ]
        == "publication_incomplete"
    )
    monkeypatch.setattr(portable_io, "_write_if_changed", write)
    assert save_record(database, stats.repository_id)["status"] == "saved"
    read_record(repository)


def test_interrupted_update_retains_the_previous_complete_record(repository, database, monkeypatch):
    stats = RepositoryScanner(database).scan(repository)
    save_record(database, stats.repository_id)
    original, _ = read_record(repository)
    (repository / "pkg" / "new.py").write_text("NEW = 1\n")
    RepositoryScanner(database).scan(repository)
    import anaxigraph.portable_io as portable_io

    write = portable_io._write_if_changed

    def interrupted(path, content):
        if path.name == "manifest.json":
            raise OSError("simulated interruption")
        return write(path, content)

    monkeypatch.setattr(portable_io, "_write_if_changed", interrupted)
    with pytest.raises(OSError):
        save_record(database, stats.repository_id)
    current, _ = read_record(repository)
    assert current == original


def test_checked_foreign_keys_cannot_point_at_another_local_repository(
    repository, database, tmp_path
):
    from fresh_eyes_support import baseline_review

    review = baseline_review(repository, database)
    stats = RepositoryScanner(database).scan(repository)
    save_record(database, review.repository_id)
    manifest, _ = read_record(repository)
    part = next(item for item in manifest["parts"] if item["table"] == "semantic_documents")
    path = repository / "anaxigraph" / part["path"]
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]["value"]["repository_id"] = 999
    content = ("\n".join(json.dumps(row) for row in rows) + "\n").encode()
    path.write_bytes(content)
    part.update(bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
    (repository / "anaxigraph" / "manifest.json").write_text(json.dumps(manifest))
    local = AnaxiIndex(tmp_path / "local.db")
    with pytest.raises(ValueError, match="foreign keys"):
        RepositoryScanner(local).scan(repository)
    assert database.latest_snapshot(stats.repository_id)["id"] == stats.snapshot_id
    with local.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 1


def test_cached_record_is_not_decoded_again_on_each_scan(
    repository, database, tmp_path, monkeypatch
):
    stats = RepositoryScanner(database).scan(repository)
    save_record(database, stats.repository_id)
    local_root = publish_and_clone(repository, tmp_path / "local")
    local = AnaxiIndex(tmp_path / "local.db")
    RepositoryScanner(local).scan(local_root)

    def unexpected_read(*args):
        raise AssertionError("unchanged partitions were decoded again")

    monkeypatch.setattr("anaxigraph.portable_record.read_record", unexpected_read)
    assert RepositoryScanner(local).scan(local_root).analyzed == 0


def test_large_partitions_split_stably_and_unchanged_save_is_empty(tmp_path):
    rows = [
        {"key": "artifacts:a" + suffix + "0" * 62, "value": {"text": "a" * 1_100_000}}
        for suffix in ("0", "1", "2")
    ]
    result = publish_record(tmp_path, {"artifacts": rows}, {"index_schema": 11})
    assert result["parts"] == 3
    assert publish_record(tmp_path, {"artifacts": rows}, {"index_schema": 11})["changed_files"] == 0
    manifest, restored = read_record(tmp_path)
    assert all(part["bytes"] < 2_000_000 for part in manifest["parts"])
    assert len(restored["artifacts"]) == 3


def test_interrupted_changed_readable_views_keep_previous_manifest_valid(tmp_path, monkeypatch):
    import anaxigraph.portable_io as portable_io

    publish_record(tmp_path, {}, {}, {"architecture/plan.md": b"Previous target\n"})
    previous, _ = read_record(tmp_path)
    write = portable_io._write_if_changed

    def interrupted(path, content):
        if path.name == "manifest.json":
            raise OSError("interrupted before manifest publication")
        return write(path, content)

    monkeypatch.setattr(portable_io, "_write_if_changed", interrupted)
    with pytest.raises(OSError, match="interrupted"):
        publish_record(tmp_path, {}, {}, {"architecture/plan.md": b"Different target\n"})
    assert read_record(tmp_path)[0] == previous
    assert (tmp_path / "anaxigraph/architecture/plan.md").read_bytes() == b"Previous target\n"
    monkeypatch.setattr(portable_io, "_write_if_changed", write)
    publish_record(tmp_path, {}, {}, {"architecture/plan.md": b"Different target\n"})
    assert read_record(tmp_path)[0] != previous
    assert (
        publish_record(tmp_path, {}, {}, {"architecture/plan.md": b"Different target\n"})[
            "changed_files"
        ]
        == 0
    )


def test_export_uses_one_read_snapshot_for_tables_and_readable_views(
    repository, database, monkeypatch
):
    import anaxigraph.portable_record as portable_record

    first = RepositoryScanner(database).scan(repository)
    snapshot = database.latest_snapshot(first.repository_id)
    views = portable_record.record_views

    def concurrent_edit(connection, repository_id, **options):
        (repository / "pkg" / "changed.py").write_text("CHANGED = True\n")
        RepositoryScanner(database).scan(repository)
        return views(connection, repository_id, **options)

    monkeypatch.setattr(portable_record, "record_views", concurrent_edit)
    save_record(database, first.repository_id)
    manifest, tables = read_record(repository)
    assert manifest["source"]["fingerprint"] == snapshot["content_fingerprint"]
    assert database.latest_snapshot(first.repository_id)["id"] != first.snapshot_id
    assert "snapshots" not in tables
    readable = json.loads((repository / "anaxigraph/mapping/architecture.json").read_bytes())
    assert readable["source_commit"] == snapshot["commit_sha"]
    assert record_status(database, first.repository_id)["snapshot_id"] == first.snapshot_id


def test_orphan_cleanup_failure_blocks_new_output_before_it_can_accumulate(tmp_path, monkeypatch):
    from pathlib import Path

    import anaxigraph.portable_io as io

    publish_record(tmp_path, {}, {})
    orphan = tmp_path / "anaxigraph/mapping/artifacts-0-000000000000000000000000.jsonl"
    orphan.parent.mkdir(exist_ok=True)
    orphan.write_text("left by an earlier interrupted writer")
    before = {str(path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    unlink = Path.unlink

    def cannot_remove(path, *args, **kwargs):
        if path == orphan:
            raise PermissionError("orphan cleanup blocked")
        return unlink(path, *args, **kwargs)

    def no_write(*args):
        raise AssertionError("a blocked cleanup must stop before writing more partitions")

    monkeypatch.setattr(Path, "unlink", cannot_remove)
    monkeypatch.setattr(io, "_write_if_changed", no_write)
    with pytest.raises(PermissionError, match="cleanup blocked"):
        publish_record(tmp_path, {"new": [{"key": "new:a", "value": 1}]}, {})
    assert {
        str(path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()
    } == before
    read_record(tmp_path)

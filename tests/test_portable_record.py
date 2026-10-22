"""A real Git/cloud/local round trip for reusable architecture evidence."""

from __future__ import annotations

import json
import subprocess

import pytest
from fresh_eyes_support import baseline_review
from semantic_support import _agent_dossier, _enable_agent_semantics

from anaxigraph.config import load_config
from anaxigraph.operational_health import served_map_status
from anaxigraph.portable_io import read_record
from anaxigraph.portable_record import save_record
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.storage import AnaxiIndex
from anaxigraph.understanding import SemanticEngine


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout


def publish_and_clone(repository, target):
    git(repository, "add", ".")
    git(repository, "commit", "-qm", "Save architecture record")
    git(repository.parent, "clone", "-q", str(repository), str(target))
    return target


def test_git_record_rebuilds_structure_without_transferring_workers(repository, database, tmp_path):
    first = RepositoryScanner(database).scan(repository)
    saved = save_record(database, first.repository_id)
    assert saved["bytes"] > 0
    assert save_record(database, first.repository_id)["changed_files"] == 0
    local_root = publish_and_clone(repository, tmp_path / "local")
    assert (
        served_map_status(repository, database.latest_snapshot(first.repository_id))["state"]
        == "current"
    )
    local = AnaxiIndex(tmp_path / "local.db")
    restored = RepositoryScanner(local).scan(local_root)
    assert restored.analyzed == first.discovered
    assert restored.discovered == first.discovered
    assert local.overview(restored.repository_id)["files"] == first.discovered
    with local.connect() as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert not connection.execute(
            "SELECT 1 FROM semantic_jobs WHERE status = 'running'"
        ).fetchall()


def test_full_ai_map_and_fresh_eyes_survive_clone(repository, database, tmp_path):
    review = baseline_review(repository, database)
    review.engine.start_fresh_eyes_review(review.repository_id, repository, review.config)
    review.run_until_complete()
    before = review.engine.fresh_eyes_status(review.repository_id, review.config.semantic)
    assert before["ready"]
    save_record(database, review.repository_id)
    local_root = publish_and_clone(repository, tmp_path / "local")
    local = AnaxiIndex(tmp_path / "local.db")
    restored = RepositoryScanner(local).scan(local_root)
    engine = SemanticEngine(local)
    config = load_config(local_root)
    status = engine.status(restored.repository_id, config.semantic)
    assert status["semantically_ready"], status
    after = engine.fresh_eyes_status(restored.repository_id, config.semantic)
    assert after["ready"], after
    assert after["recommendations"] == before["recommendations"]
    plan = engine.plan(restored.repository_id, local_root, config)
    assert plan.enqueued == 0


def test_bad_partition_leaves_local_cache_unchanged(repository, database, tmp_path):
    first = RepositoryScanner(database).scan(repository)
    save_record(database, first.repository_id)
    manifest, _ = read_record(repository)
    part = repository / "anaxigraph" / manifest["views"][0]["path"]
    part.write_text("interrupted write")
    local = AnaxiIndex(tmp_path / "local.db")
    with pytest.raises(ValueError, match="incomplete or changed"):
        RepositoryScanner(local).scan(repository)
    with local.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 0


def test_existing_unrelated_directory_is_preserved(repository, database):
    stats = RepositoryScanner(database).scan(repository)
    existing = repository / "anaxigraph"
    existing.mkdir()
    (existing / "application.py").write_text("VALUE = 42\n")
    with pytest.raises(ValueError, match="not a managed record"):
        save_record(database, stats.repository_id)
    assert load_config(repository).is_ignored("anaxigraph/application.py") is False
    assert (existing / "application.py").read_text() == "VALUE = 42\n"


def test_local_edits_and_other_repositories_remain_separate(repository, database, tmp_path):
    first = RepositoryScanner(database).scan(repository)
    save_record(database, first.repository_id)
    local_root = publish_and_clone(repository, tmp_path / "local")
    (local_root / "pkg" / "new_feature.py").write_text("FEATURE = 42\n")
    restored = RepositoryScanner(database).scan(local_root)
    assert restored.repository_id != first.repository_id
    assert restored.discovered == first.discovered + 1
    assert database.repository(first.repository_id)["path"] == str(repository)
    assert (local_root / "pkg" / "new_feature.py").read_text() == "FEATURE = 42\n"
    with database.connect() as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_unsupported_format_is_not_silently_loaded(repository, database):
    stats = RepositoryScanner(database).scan(repository)
    save_record(database, stats.repository_id)
    path = repository / "anaxigraph" / "manifest.json"
    value = json.loads(path.read_text())
    value["format"] = "anaxigraph-record-v999"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="Unsupported AnaxiGraph record format"):
        RepositoryScanner(database).scan(repository)


def test_interrupted_model_work_reuses_success_and_never_imports_live_worker(
    repository, database, tmp_path
):
    _enable_agent_semantics(repository)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    completed = engine.claim_agent_work(
        stats.repository_id, repository, config, agent_id="cloud-worker"
    )
    path = completed["analysis_request"]["path"]
    engine.submit_agent_work(
        stats.repository_id,
        repository,
        config,
        job_id=completed["job"]["id"],
        lease_token=completed["lease"]["token"],
        dossier=_agent_dossier(completed["analysis_request"]),
    )
    held = engine.claim_agent_work(
        stats.repository_id, repository, config, agent_id="cloud-held-worker"
    )
    assert held["status"] == "work"
    save_record(database, stats.repository_id)
    local_root = publish_and_clone(repository, tmp_path / "local")
    local = AnaxiIndex(tmp_path / "local.db")
    restored = RepositoryScanner(local).scan(local_root)
    local_engine = SemanticEngine(local)
    local_config = load_config(local_root)
    status = local_engine.status(restored.repository_id, local_config.semantic)
    assert not status["semantically_ready"]
    assert status["jobs"]["running_live"] == 0
    local_engine.plan(restored.repository_id, local_root, local_config)
    with local.connect() as connection:
        duplicate = connection.execute(
            "SELECT 1 FROM semantic_jobs WHERE scope_key = ? AND job_kind = 'intrinsic' AND status IN ('pending','running','retry')",
            (path,),
        ).fetchone()
    assert duplicate is None

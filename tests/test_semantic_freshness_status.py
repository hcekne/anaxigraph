"""A new structural scan must not erase the last available semantic understanding."""

from semantic_support import _fake_provider, _semantic_config

from anaxigraph.architecture_charter import architecture_charter
from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.understanding import SemanticEngine


def test_prior_summary_is_stale_until_incremental_work_finishes(repository, database, tmp_path):
    _semantic_config(repository, _fake_provider(tmp_path), tmp_path / "semantic.log")
    config = load_config(repository)
    scanner, engine = RepositoryScanner(database), SemanticEngine(database)
    first = scanner.scan(repository)
    baseline = engine.bootstrap(first.repository_id, repository, config)["semantic"]
    assert baseline["semantically_ready"]
    source = repository / "pkg" / "core.py"
    source.write_text(source.read_text() + "\nREVISION = 2\n")
    changed = scanner.scan(repository)
    before = database.overview(first.repository_id)
    status = engine.status(first.repository_id, config.semantic)
    charter = architecture_charter(database.repository(first.repository_id), before, status)

    assert not status["semantically_ready"]
    assert status["freshness"]["previous_semantic_snapshot_id"] == first.snapshot_id
    assert charter["state"] == "stale"
    assert charter["source_snapshot_id"] == first.snapshot_id
    assert charter["snapshot_id"] == changed.snapshot_id
    assert charter["purpose"] == baseline["architecture_charter"]["value"]["purpose"]
    assert any("stale context" in text for text in status["plain_language"]["how_to_read_progress"])
    assert database.overview(first.repository_id)["snapshot"] == before["snapshot"]

    other = tmp_path / "other"
    other.mkdir()
    (other / "app.py").write_text("print('other repository')\n")
    unrelated = scanner.scan(other)
    other_status = engine.status(unrelated.repository_id, config.semantic)
    assert other_status["architecture_charter"] is None
    assert other_status["freshness"]["previous_semantic_snapshot_id"] is None

    refreshed = engine.bootstrap(first.repository_id, repository, config)["semantic"]
    assert refreshed["semantically_ready"]
    assert refreshed["freshness"]["intrinsic_reused"] >= 1
    assert refreshed["freshness"]["context_reused"] >= 1
    assert refreshed["architecture_charter"]["source_snapshot_id"] == changed.snapshot_id

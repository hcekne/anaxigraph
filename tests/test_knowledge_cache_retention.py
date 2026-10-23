"""Only the focused graph is cached; durable facts and paid history remain reusable."""

from dataclasses import replace

import pytest
from test_knowledge_graph import _annotation, _repository

import anaxigraph.knowledge_sync as synchronization
from anaxigraph.config import load_config
from anaxigraph.knowledge_annotation_contract import validated_annotation
from anaxigraph.knowledge_detail import entity_detail
from anaxigraph.knowledge_query import entity_page
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.understanding import SemanticEngine


def _saved_annotation(database, root):
    stats = RepositoryScanner(database).scan(root)
    config = load_config(root)
    config = replace(config, semantic=replace(config.semantic, enabled=True, provider="agent"))
    engine = SemanticEngine(database)
    engine.plan(stats.repository_id, root, config)
    with database.connect() as connection:
        identifier = connection.execute(
            "SELECT id FROM semantic_jobs WHERE job_kind='annotation' AND scope_key='service.py'"
        ).fetchone()[0]
    job = engine._services.leases.claim_job(
        stats.repository_id, config.semantic, job_ids=(identifier,)
    )
    engine._services.persistence.complete_job(
        job, validated_annotation(_annotation()), "agent", config.semantic
    )
    return stats, config


def _documents(database):
    with database.connect() as connection:
        return [dict(row) for row in connection.execute("SELECT * FROM semantic_document_values")]


def _projection(database):
    with database.connect() as connection:
        return {
            table: [tuple(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY 1,2")]
            for table in ("graph_entities", "graph_links", "graph_revisions")
        }


def test_repeated_edits_keep_one_graph_and_rebuild_saved_baselines(tmp_path, database):
    root = _repository(tmp_path)
    (root / ".anaxigraph.yml").write_text("storage:\n  detailed_history: true\n")
    first, config = _saved_annotation(database, root)
    saved = _documents(database)
    original = entity_detail(database, first.repository_id, "module:service.py")
    first_count = len(_projection(database)["graph_entities"])
    for number in range(5):
        with (root / "ui.py").open("a") as file:
            file.write(f"\n# Edit {number}\n")
        latest = RepositoryScanner(database).scan(root)
        SemanticEngine(database).plan(latest.repository_id, root, config)
        projection = _projection(database)
        assert {row[0] for row in projection["graph_revisions"]} == {latest.snapshot_id}
        assert len(projection["graph_entities"]) == first_count
        assert _documents(database) == saved
    assert len(database.snapshots(first.repository_id)) >= 6
    (root / "service.py").unlink()  # Saved graph regeneration does not reread source or run models.
    baseline = entity_detail(
        database, first.repository_id, "module:service.py", snapshot_id=first.snapshot_id
    )
    assert baseline["node"]["overview"] == original["node"]["overview"]
    assert baseline["contracts"] == original["contracts"]
    assert {row[0] for row in _projection(database)["graph_revisions"]} == {first.snapshot_id}
    current = entity_detail(database, first.repository_id, "module:service.py")
    assert current["node"]["overview"] == original["node"]["overview"]
    assert database.latest_snapshot(first.repository_id)["id"] == latest.snapshot_id
    assert _documents(database) == saved


def test_failed_rebuild_rolls_back_cache_eviction_and_keeps_current_graph(
    tmp_path, database, monkeypatch
):
    root = _repository(tmp_path)
    first = RepositoryScanner(database).scan(root)
    (root / "ui.py").write_text((root / "ui.py").read_text() + "\n# Edit\n")
    latest = RepositoryScanner(database).scan(root)
    saved = _projection(database)

    def interrupt(*arguments):
        raise RuntimeError("interrupted graph rebuild")

    monkeypatch.setattr(synchronization, "_install_nodes", interrupt)
    with pytest.raises(RuntimeError, match="interrupted graph rebuild"):
        entity_page(database, first.repository_id, snapshot_id=first.snapshot_id)
    assert _projection(database) == saved
    assert database.latest_snapshot(first.repository_id)["id"] == latest.snapshot_id

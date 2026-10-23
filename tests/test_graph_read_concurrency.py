"""Graph readers retry pre-transaction eviction and keep pinned revisions coherent."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from test_knowledge_graph import _repository

import anaxigraph.knowledge_sync as synchronization
from anaxigraph.agent import architecture_guidance, impact_analysis
from anaxigraph.api import create_app
from anaxigraph.config import load_config
from anaxigraph.knowledge_detail import entity_detail, neighborhood
from anaxigraph.knowledge_query import entity_page
from anaxigraph.scanner import RepositoryScanner


def _change(root, database):
    path = root / "ui.py"
    path.write_text(path.read_text() + "\ndef later_only():\n    return 3\n")
    return RepositoryScanner(database).scan(root)


def _revisions(tmp_path, database):
    root = _repository(tmp_path)
    first = RepositoryScanner(database).scan(root)
    latest = _change(root, database)
    return first, latest


def _read(kind, database, first):
    if kind == "page":
        return entity_page(database, first.repository_id, first.snapshot_id, kind="function")
    if kind == "detail":
        return entity_detail(database, first.repository_id, "module:ui.py", first.snapshot_id)
    return neighborhood(database, first.repository_id, "module:ui.py", first.snapshot_id)


@pytest.mark.parametrize("kind", ["page", "detail", "neighborhood"])
def test_public_reader_retries_once_when_another_revision_evicts_pre_begin(
    tmp_path, database, monkeypatch, kind
):
    first, latest = _revisions(tmp_path, database)
    expected = _read(kind, database, first)
    original = synchronization.ensure_knowledge
    interleaved = []

    def competing_read(*args, **kwargs):
        chosen = original(*args, **kwargs)
        if not interleaved:
            interleaved.append(chosen)
            other = entity_page(database, latest.repository_id, latest.snapshot_id, kind="function")
            assert other["context"]["snapshot_id"] == latest.snapshot_id
            assert any("later_only" in node["id"] for node in other["nodes"])
        return chosen

    monkeypatch.setattr(synchronization, "ensure_knowledge", competing_read)
    result = _read(kind, database, first)
    assert interleaved == [first.snapshot_id]
    assert result == expected


def test_current_selection_stays_fixed_when_new_snapshot_arrives_before_begin(
    tmp_path, database, monkeypatch
):
    root = _repository(tmp_path)
    first = RepositoryScanner(database).scan(root)
    expected = entity_page(database, first.repository_id, kind="function")
    original = synchronization.ensure_knowledge
    intervening = []

    def advance_current(*args, **kwargs):
        chosen = original(*args, **kwargs)
        if not intervening:
            intervening.append(True)
            latest = _change(root, database)
            entity_page(database, latest.repository_id, latest.snapshot_id)
        return chosen

    monkeypatch.setattr(synchronization, "ensure_knowledge", advance_current)
    result = entity_page(database, first.repository_id, kind="function")
    assert database.latest_snapshot(first.repository_id)["id"] != first.snapshot_id
    assert result == expected


def test_pinned_read_keeps_original_rows_after_other_revision_commits(tmp_path, database):
    first, latest = _revisions(tmp_path, database)
    with synchronization.graph_read(database, first.repository_id, first.snapshot_id) as (
        connection,
        snapshot,
    ):
        query = "SELECT entity_id FROM graph_entities WHERE snapshot_id=? ORDER BY entity_id"
        before = [row[0] for row in connection.execute(query, (snapshot,))]
        other = entity_page(database, latest.repository_id, latest.snapshot_id, kind="function")
        assert other["context"]["snapshot_id"] == latest.snapshot_id
        assert any("later_only" in node["id"] for node in other["nodes"])
        assert [row[0] for row in connection.execute(query, (snapshot,))] == before
        assert before and not any("later_only" in value for value in before)
    with database.connect() as connection:
        assert [
            row[0] for row in connection.execute("SELECT snapshot_id FROM graph_revisions")
        ] == [latest.snapshot_id]


def test_two_same_revision_readers_overlap_without_exclusive_serialization(tmp_path, database):
    first, _latest = _revisions(tmp_path, database)
    entity_page(database, first.repository_id, first.snapshot_id)
    barrier = Barrier(2)

    def read():
        with synchronization.graph_read(database, first.repository_id, first.snapshot_id) as (
            connection,
            snapshot,
        ):
            barrier.wait(timeout=10)
            return snapshot, [
                row[0]
                for row in connection.execute(
                    "SELECT entity_id FROM graph_entities WHERE snapshot_id=? ORDER BY entity_id",
                    (snapshot,),
                )
            ]

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: read(), range(2)))
    assert results[0] == results[1]
    assert results[0][0] == first.snapshot_id and results[0][1]


def _continuous_eviction(database, first, latest, monkeypatch):
    original = synchronization.ensure_knowledge
    attempts = []

    def evict(*args, **kwargs):
        chosen = original(*args, **kwargs)
        attempts.append(chosen)
        original(database, latest.repository_id, latest.snapshot_id)
        return chosen

    monkeypatch.setattr(synchronization, "ensure_knowledge", evict)
    return attempts


def test_continuous_pre_begin_churn_is_explicit_busy_instead_of_empty(
    tmp_path, database, monkeypatch
):
    first, latest = _revisions(tmp_path, database)
    attempts = _continuous_eviction(database, first, latest, monkeypatch)
    with pytest.raises(synchronization.GraphCacheBusyError):
        entity_page(database, first.repository_id, first.snapshot_id)
    assert attempts == [first.snapshot_id] * 3


@pytest.mark.parametrize("path", ["entities", "entity", "neighborhood"])
def test_rest_churn_reports_retryable_503(tmp_path, database, monkeypatch, path):
    first, latest = _revisions(tmp_path, database)
    with TestClient(create_app(database=database, enable_mcp=False)) as client:
        attempts = _continuous_eviction(database, first, latest, monkeypatch)
        response = client.get(
            "/api/graph/" + path,
            params={
                "repository_id": first.repository_id,
                "snapshot_id": first.snapshot_id,
                "entity_id": "module:ui.py",
            },
        )
    assert response.status_code == 503
    assert "retry" in response.json()["detail"].lower()
    assert attempts == [first.snapshot_id] * 3


def _agent_read(kind, database, repository, config):
    arguments = {"repository_id": repository, "config": config}
    selected = "function:service.py#service.calculate"
    if kind == "impact":
        return impact_analysis(database, target=selected, **arguments)
    return architecture_guidance(
        database, goal="Improve calculation internals", focus=selected, **arguments
    )


@pytest.mark.parametrize("kind", ["impact", "guide"])
def test_coding_agent_function_focus_survives_pre_begin_eviction(
    tmp_path, database, monkeypatch, kind
):
    root = _repository(tmp_path)
    with (root / "service.py").open("a") as source:
        source.write("\ndef unrelated():\n    return 5\n")
    (root / "other_view.py").write_text(
        "from service import unrelated\ndef display():\n    return unrelated()\n"
    )
    first = RepositoryScanner(database).scan(root)
    latest = _change(root, database)
    config = load_config(root)
    expected = _agent_read(kind, database, latest.repository_id, config)
    original = synchronization.ensure_knowledge
    interleaved = []

    def competing_read(*args, **kwargs):
        chosen = original(*args, **kwargs)
        if not interleaved:
            interleaved.append(chosen)
            entity_page(database, first.repository_id, first.snapshot_id)
        return chosen

    monkeypatch.setattr(synchronization, "ensure_knowledge", competing_read)
    result = _agent_read(kind, database, latest.repository_id, config)
    assert interleaved == [latest.snapshot_id]
    assert result["snapshot_id"] == latest.snapshot_id
    assert result["entity_context"] == expected["entity_context"]
    if kind == "impact":
        assert result["direct_dependants"] == expected["direct_dependants"]
        consumers = {item["path"] for item in result["direct_dependants"]}
        assert "ui.py" in consumers and "other_view.py" not in consumers
        assert result["tests_relevant"] == expected["tests_relevant"] == ["tests/test_service.py"]
    else:
        assert result["primary_files"] == expected["primary_files"]
        assert [item["path"] for item in result["primary_files"]] == ["service.py"]

"""Historical graphs disclose extractor changes separately from unchanged source revisions."""

import json

import pytest

import anaxigraph.scanner as scanner
from anaxigraph.knowledge_query import entity_page
from anaxigraph.scanner import RepositoryScanner


@pytest.mark.parametrize("changed", [False, True])
def test_graph_context_discloses_complete_or_partial_same_source_reindex(
    repository, database, monkeypatch, changed
):
    monkeypatch.setattr(scanner, "ANALYSIS_VERSION", 5)
    first = RepositoryScanner(database).scan(repository)
    original = database.resolve_snapshot(first.repository_id, first.snapshot_id)
    if changed:
        path = repository / "pkg/util.py"
        path.write_text(path.read_text() + "\nCHANGED_BEHAVIOR = 1\n")
    monkeypatch.setattr(scanner, "ANALYSIS_VERSION", 6)
    current = RepositoryScanner(database).scan(repository)
    value = entity_page(database, first.repository_id, first.snapshot_id, kind="module")
    context = value["context"]
    notice = context["structural_analysis"]
    assert notice["reindexed"] is True
    assert notice["scope"] == "matching_files"
    assert notice["reindexed_files"] == (7 if changed else 8)
    assert notice["interpretation"] == "Matching source files reanalyzed with current extractor."
    assert "original_analysis_signature" not in notice
    assert "effective_analysis_signatures" not in notice
    assert context["snapshot"]["commit_sha"] == original["commit_sha"]
    assert context["snapshot"]["analysis_timestamp"] == original["analysis_timestamp"]
    saved = database.resolve_snapshot(first.repository_id, first.snapshot_id)
    metadata = json.loads(saved["metadata_json"])
    assert (
        metadata["analysis_signature"]
        == json.loads(original["metadata_json"])["analysis_signature"]
    )
    assert metadata["structural_cache_reindex"]["effective_analysis_signatures"]
    assert (
        "structural_analysis"
        not in entity_page(database, first.repository_id, current.snapshot_id, kind="module")[
            "context"
        ]
    )

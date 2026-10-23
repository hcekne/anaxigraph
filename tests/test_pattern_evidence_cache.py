"""Evicted parser facts are rebuilt from matching source, never mistaken for absence."""

from __future__ import annotations

import json
from pathlib import Path

import anaxigraph.persistence.temporal_files as fact_writer
from anaxigraph.ir_codec import decode_metadata, project_evidence_cache
from anaxigraph.pattern_evidence_source import read_pattern_evidence
from anaxigraph.persistence.pattern_evidence_read import read_pattern_evidence as cached_evidence
from anaxigraph.persistence.temporal_files import compact_file_fact_metadata
from anaxigraph.persistence.temporal_reads import snapshot_files
from anaxigraph.scanner import RepositoryScanner


def test_eviction_preserves_projection_and_does_not_reparse_again(
    repository, database, monkeypatch
):
    with monkeypatch.context() as patch:
        patch.setattr(fact_writer, "project_evidence_cache", lambda value: value)
        stats = RepositoryScanner(database).scan(repository)
    with database.connect() as connection:
        before = cached_evidence(connection, stats.repository_id, stats.snapshot_id)
    with database.transaction() as connection:
        assert compact_file_fact_metadata(connection) > 0
        stored = [
            decode_metadata(row[0])
            for row in connection.execute("SELECT metadata_json FROM file_facts")
        ]
        assert any(item.get("evidence_cache_evicted") for item in stored)
        assert all(
            fact.get("fact") in {"entry_points", "registrations"}
            for item in stored
            for fact in item.get("ir", {}).get("evidence_facts", [])
        )
    with database.connect() as connection:
        after = read_pattern_evidence(connection, stats.repository_id, stats.snapshot_id)
        assert after.as_dict() == before.as_dict()
        raw = cached_evidence(connection, stats.repository_id, stats.snapshot_id)
        assert any(
            feature.name == "analyzer.evidence_cache" and feature.availability == "unavailable"
            for item in raw.items
            for feature in item.features
        )

    def forbidden(*args, **kwargs):
        raise AssertionError("A compatible cached projection must not reread module source")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    with database.connect() as connection:
        assert (
            read_pattern_evidence(connection, stats.repository_id, stats.snapshot_id).as_dict()
            == before.as_dict()
        )


def test_changed_source_is_explicitly_unavailable_instead_of_false_zero(repository, database):
    stats = RepositoryScanner(database).scan(repository)
    source = repository / "pkg/core.py"
    source.write_text(source.read_text() + "\nCHANGED = True\n")
    with database.connect() as connection:
        projection = read_pattern_evidence(
            connection, stats.repository_id, stats.snapshot_id, target="module:pkg/core.py"
        )
    module = next(item for item in projection.items if item.target.key == "module:pkg/core.py")
    missing = module.feature("analyzer.evidence_cache")
    assert missing and missing.availability == "unavailable" and missing.confidence == 0
    assert "differs" in missing.value
    assert module.feature("syntax.symbol_documentation") is None


def test_function_calls_aliases_and_analyzer_contract_survive_cache_projection(
    repository, database
):
    stats = RepositoryScanner(database).scan(repository)
    with database.connect() as connection:
        module = next(
            row
            for row in snapshot_files(connection, stats.snapshot_id)
            if row["path"] == "pkg/core.py"
        )
    metadata = json.loads(module["metadata_json"])
    assert metadata["call_sites"] and metadata["symbol_aliases"]
    assert metadata["ir"]["analyzer_capabilities"]["fingerprint"]
    assert metadata["evidence_cache_evicted"]
    plugin = {
        "ir": {
            "analyzer_capabilities": {"analyzer": "custom-plugin"},
            "evidence_facts": [{"fact": "calls"}],
        }
    }
    assert project_evidence_cache(plugin) == plugin

"""Saved catalogue reads and bounded witnesses avoid unrelated hydration."""

from dataclasses import replace

from test_pattern_catalogue_review import _prepare

from anaxigraph.config import load_config
from anaxigraph.pattern_catalog import bundled_pattern_catalog
from anaxigraph.pattern_intelligence import PatternIntelligenceService
from anaxigraph.persistence import pattern_catalogue_read, temporal_reads
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_pattern_requests import _parent_source_evidence


def test_saved_catalogue_keeps_run_identity_without_rehashing_current_cards(
    repository, database, monkeypatch
):
    stats, _semantic = _prepare(repository, database)
    service = PatternIntelligenceService(database)
    original = service.catalogue(stats.repository_id)

    class UnserializedCurrentCatalogue:
        @property
        def fingerprint(self):
            raise AssertionError("Saved run coverage must use its immutable manifest identity")

    monkeypatch.setattr(
        pattern_catalogue_read, "bundled_pattern_catalog", UnserializedCurrentCatalogue
    )
    result = service.catalogue(stats.repository_id)

    assert result == original
    assert result["catalogue"]["manifest_saved"]
    assert result["catalogue"]["considered"] == len(bundled_pattern_catalog().cards)


def test_unplanned_catalogue_still_uses_the_current_card_identity(
    repository, database, monkeypatch
):
    stats = RepositoryScanner(database).scan(repository)
    catalog = bundled_pattern_catalog()
    changed = replace(catalog.cards[0], intent="A changed current catalogue intent.")
    current = replace(catalog, cards=(changed, *catalog.cards[1:]))
    assert current.fingerprint != catalog.fingerprint
    monkeypatch.setattr(pattern_catalogue_read, "bundled_pattern_catalog", lambda: current)

    result = PatternIntelligenceService(database).catalogue(stats.repository_id)

    assert not result["catalogue"]["manifest_saved"]
    assert result["catalogue"]["fingerprint"] == current.fingerprint
    assert result["catalogue"]["expected"] == result["catalogue"]["missing"] == len(current.cards)


def test_parent_witnesses_hydrate_only_selected_facts_with_exact_source(
    repository, database, monkeypatch
):
    for index in range(20):
        (repository / "pkg" / f"unrelated_{index}.py").write_text(
            f"def unrelated_{index}():\n    return {index}\n"
        )
    stats = RepositoryScanner(database).scan(repository)
    selected = ("pkg/core.py", "pkg/util.py")
    expanded = []
    original_expand = temporal_reads._expanded_metadata_json

    def expand_selected(value, placement):
        assert value["path"] in selected, "Unrelated module facts must remain unhydrated"
        expanded.append(value["path"])
        return original_expand(value, placement)

    monkeypatch.setattr(temporal_reads, "_expanded_metadata_json", expand_selected)
    job = {
        "snapshot_id": stats.snapshot_id,
        "metadata": {
            "target_evidence": {
                "features": [
                    {
                        "name": "architecture.witnesses",
                        "value": {"items": [{"path": path} for path in selected]},
                    }
                ]
            }
        },
    }

    result = _parent_source_evidence(database, job, repository, load_config(repository).semantic)

    assert expanded == list(selected)
    assert [item["path"] for item in result["source_witnesses"]] == list(selected)
    for item in result["source_witnesses"]:
        assert item["source"] == (repository / item["path"]).read_text()
        assert item["source_range"] == {
            "start_line": 1,
            "end_line": len(item["source"].splitlines()),
        }
        assert not item["source_truncated"]

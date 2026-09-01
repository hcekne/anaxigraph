from __future__ import annotations

from dataclasses import replace

from semantic_support import _calls, _fake_provider, _semantic_config

from anaxigraph.analyzer_capabilities import CapabilitySupport
from anaxigraph.analyzers import builtin_registry
from anaxigraph.analyzers.python import PythonAnalyzer
from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_scan_refresh import semantic_refresh_after_scan
from anaxigraph.understanding import SemanticEngine


def test_capability_change_reanalyzes_only_languages_owned_by_that_analyzer(repository, database):
    initial = RepositoryScanner(database).scan(repository)

    class ExpandedPythonAnalyzer(PythonAnalyzer):
        capabilities = replace(
            PythonAnalyzer.capabilities,
            facts=tuple(
                sorted(
                    (
                        *PythonAnalyzer.capabilities.facts,
                        CapabilitySupport("data_flow", "structural"),
                    ),
                    key=lambda item: item.fact,
                )
            ),
        )

    registry = builtin_registry()
    registry.register(ExpandedPythonAnalyzer())
    changed = RepositoryScanner(database, registry=registry).scan(repository)

    assert changed.snapshot_id != initial.snapshot_id
    assert changed.discovered == initial.discovered
    assert changed.analyzed == 5
    assert changed.reused == initial.discovered - 5


def test_package_version_change_reuses_semantics_and_reports_incompatible_comparison(
    repository, database, tmp_path, monkeypatch
):
    log = tmp_path / "semantic-release-change.log"
    _semantic_config(repository, _fake_provider(tmp_path), log)
    config = load_config(repository)
    first = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    assert engine.bootstrap(first.repository_id, repository, config)["semantic"][
        "semantically_ready"
    ]
    baseline_calls = len(_calls(log))

    monkeypatch.setattr("anaxigraph.scan_preparation.__version__", "next-release-test")
    current = RepositoryScanner(database).scan(repository, run_type="update")
    repeated = semantic_refresh_after_scan(
        database,
        repository_id=current.repository_id,
        repository=repository,
        snapshot_id=current.snapshot_id,
        baseline_snapshot_id=first.snapshot_id,
        config=config,
        prepare=True,
    )

    assert "different analysis contracts" in repeated["refresh"]["comparison_caveat"]
    assert repeated["refresh"]["preparation"]["enqueued"] == 0
    assert repeated["semantic"]["current"] == repeated["semantic"]["eligible_modules"]
    assert repeated["semantic"]["semantically_ready"] is True
    assert len(_calls(log)) == baseline_calls

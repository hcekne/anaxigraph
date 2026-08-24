from __future__ import annotations

from dataclasses import replace

from anaxigraph.analyzer_capabilities import CapabilitySupport
from anaxigraph.analyzers import builtin_registry
from anaxigraph.analyzers.python import PythonAnalyzer
from anaxigraph.scanner import RepositoryScanner


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

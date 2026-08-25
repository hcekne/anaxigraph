"""Stable identities for deterministic repository analysis."""

from __future__ import annotations

from dataclasses import replace

from anaxigraph.config import (
    AgentConfig,
    AnaxiGraphConfig,
    ArchitectureConfig,
    FindingConfig,
    MapConfig,
    SemanticConfig,
)
from anaxigraph.scan_preparation import analysis_signature, structural_config_projection


def test_semantic_execution_policy_does_not_change_source_analysis_signature():
    baseline = AnaxiGraphConfig()
    semantic = SemanticConfig(
        enabled=True,
        provider="agent",
        model="temporary-model-name",
        reasoning_effort="medium",
        prompt_version="v-next",
        timeout_seconds=900,
        max_parallel_jobs=30,
        max_source_chars=250_000,
        include=("src/**",),
    )

    assert analysis_signature(baseline, analysis_version=7) == analysis_signature(
        replace(baseline, semantic=semantic), analysis_version=7
    )


def test_source_analysis_policy_still_changes_source_analysis_signature():
    baseline = AnaxiGraphConfig()

    assert analysis_signature(baseline, analysis_version=7) != analysis_signature(
        replace(baseline, max_file_bytes=baseline.max_file_bytes + 1),
        analysis_version=7,
    )


def test_query_and_interpretation_policy_is_outside_structural_projection():
    baseline = AnaxiGraphConfig()
    changed = replace(
        baseline,
        project_name="Renamed repository",
        architecture=ArchitectureConfig(protected_paths=("src/core.py",)),
        map=MapConfig(hints=("Organize by responsibility",)),
        agent=AgentConfig(context_limit=99),
        findings=FindingConfig(attention_page_size=99),
        coverage_files=("reports/coverage.xml",),
        coverage_required=True,
    )

    assert structural_config_projection(changed) == structural_config_projection(baseline)
    assert analysis_signature(changed, analysis_version=7) == analysis_signature(
        baseline, analysis_version=7
    )

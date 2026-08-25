from __future__ import annotations

import json

import pytest

from anaxigraph.agent import agent_scope, impact_analysis
from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.storage import AnaxiIndex
from benchmarks.repository_factory import create_history_repository


@pytest.mark.parametrize("file_count", [120, 1_000, 3_000])
def test_core_coding_loop_stays_precise_bounded_and_change_aware(tmp_path, file_count):
    repository = tmp_path / "repository"
    manifest = create_history_repository(repository, file_count=file_count, commits=1)
    database = AnaxiIndex(tmp_path / "index.db")
    scanner = RepositoryScanner(database)
    config = load_config(repository)

    first_scan = scanner.scan(repository)
    before = agent_scope(
        database,
        repository_id=first_scan.repository_id,
        goal=manifest["scope_goal"],
        branch=None,
        config=config,
    )

    expected = set(manifest["scope_expected_candidates"])
    primary = {item["path"] for item in before["primary_files"]}
    decision = before["architecture_decision"]
    baseline = decision["verification"]["post_change_baseline"]
    encoded = json.dumps(before, separators=(",", ":"), sort_keys=True).encode()

    assert primary == expected
    assert len(encoded) <= config.agent.payload_limit_bytes
    assert decision["contract_version"] == "architecture-decision-v1"
    assert decision["task_path"]["module"]["path"] == "src/sample/analyzers/base.py"
    assert decision["placement"]["preferred_path"] == "src/sample/languages.py"
    assert baseline["contract_version"] == "architecture-verification-baseline-v2"

    impact = impact_analysis(
        database,
        repository_id=first_scan.repository_id,
        target="src/sample/languages.py",
        branch=None,
        config=config,
    )
    dependant_paths = {item["path"] for item in impact["direct_dependants"]}
    assert {"src/sample/service.py", "tests/test_analyzers.py"} <= dependant_paths

    languages = repository / "src/sample/languages.py"
    original = languages.read_text(encoding="utf-8")
    languages.write_text(
        "from sample.service import analyze_file\n\n" + original,
        encoding="utf-8",
    )
    second_scan = scanner.scan(repository)
    introduced = agent_scope(
        database,
        repository_id=second_scan.repository_id,
        goal=manifest["scope_goal"],
        branch=None,
        config=config,
        verification_baseline=baseline,
    )

    assert second_scan.analyzed == 1
    introduced_effects = introduced["architecture_decision"]["verification"][
        "post_change_comparison"
    ]["changes"]["structural_effects"]
    assert "dependency_cycle" in {item["category"] for item in introduced_effects["introduced"]}

    harmful_baseline = introduced["architecture_decision"]["verification"]["post_change_baseline"]
    safe_change = original.replace(
        '".ts": "typescript"}',
        '".ts": "typescript", ".go": "go"}',
    )
    languages.write_text(safe_change, encoding="utf-8")
    third_scan = scanner.scan(repository)
    resolved = agent_scope(
        database,
        repository_id=third_scan.repository_id,
        goal=manifest["scope_goal"],
        branch=None,
        config=config,
        verification_baseline=harmful_baseline,
    )

    assert third_scan.analyzed == 1
    resolved_effects = resolved["architecture_decision"]["verification"]["post_change_comparison"][
        "changes"
    ]["structural_effects"]
    assert "dependency_cycle" in {item["category"] for item in resolved_effects["resolved"]}

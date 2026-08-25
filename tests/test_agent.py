from __future__ import annotations

import json
from dataclasses import replace

import pytest

from anaxigraph.agent import agent_scope, impact_analysis
from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner


def test_agent_scope_is_bounded_and_includes_tests_protection_and_rules(repository, database):
    stats = RepositoryScanner(database).scan(repository)
    value = agent_scope(
        database,
        repository_id=stats.repository_id,
        goal="Change the Calculator calculation behavior",
        branch=None,
        config=load_config(repository),
    )

    assert value["primary_files"][0]["path"] == "pkg/core.py"
    assert "tests/test_core.py" in value["tests"]
    assert any(item["path"] == "pkg/core.py" for item in value["protected_files"])
    assert value["risk"] == "high"
    assert len(value["recommended_context"]) <= 12
    encoded_size = len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    assert encoded_size <= value["payload_budget"]["limit_bytes"]
    assert encoded_size == value["payload_budget"]["estimated_bytes"]
    assert len(value["known_findings"]) <= 12
    assert all("priority_score" in item for item in value["known_findings"])
    assert all(
        item["plain_language"]["version"] == "plain-language-v2" for item in value["known_findings"]
    )
    assert all(item["plain_language"]["how_to_check"] for item in value["known_findings"])
    assert all("repository_id" not in item for item in value["architecture_rules"])
    assert value["architecture_decision"]["contract_version"] == "architecture-decision-v1"
    assert value["architecture_decision"]["status"] == "deterministic_only"
    assert (
        "source structure and repository facts only"
        in (value["architecture_decision"]["plain_language"]["conclusion"])
    )


def test_impact_follows_reverse_edges_and_relevant_tests(repository, database):
    stats = RepositoryScanner(database).scan(repository)
    value = impact_analysis(
        database,
        repository_id=stats.repository_id,
        target="pkg/core.py",
        branch=None,
        config=load_config(repository),
    )

    paths = {item["path"] for item in value["direct_dependants"]}
    assert "pkg/consumer.py" in paths
    assert "tests/test_core.py" in paths
    assert "tests/test_core.py" in value["tests_relevant"]
    assert value["risk"] == "high"


def test_impact_reports_an_unknown_repository_or_target(repository, database):
    config = load_config(repository)
    with pytest.raises(ValueError, match="Repository not found"):
        impact_analysis(
            database,
            repository_id=999,
            target="pkg/core.py",
            branch=None,
            config=config,
        )

    stats = RepositoryScanner(database).scan(repository)
    with pytest.raises(ValueError, match="Target not found: pkg/missing.py"):
        impact_analysis(
            database,
            repository_id=stats.repository_id,
            target="pkg/missing.py",
            branch=None,
            config=config,
        )


def test_agent_scope_compares_tracked_facts_after_a_rescan(repository, database):
    first_scan = RepositoryScanner(database).scan(repository)
    config = load_config(repository)
    before = agent_scope(
        database,
        repository_id=first_scan.repository_id,
        goal="Change the Calculator calculation behavior",
        branch=None,
        config=config,
    )
    baseline = before["architecture_decision"]["verification"]["post_change_baseline"]
    core = repository / "pkg/core.py"
    core.write_text(core.read_text(encoding="utf-8") + "\nNEW_DEFAULT = 1\n", encoding="utf-8")

    second_scan = RepositoryScanner(database).scan(repository)
    after = agent_scope(
        database,
        repository_id=second_scan.repository_id,
        goal="Change the Calculator calculation behavior",
        branch=None,
        config=config,
        verification_baseline=baseline,
    )

    comparison = after["architecture_decision"]["verification"]["post_change_comparison"]
    assert comparison["status"] == "changed"
    assert comparison["baseline_snapshot_id"] == first_scan.snapshot_id
    assert comparison["current_snapshot_id"] == second_scan.snapshot_id
    assert any(
        item["path"] == "pkg/core.py" and item["source_structure_changed"]
        for item in comparison["changes"]["modules"]["changed"]
    )


def test_agent_scope_trims_optional_context_to_the_configured_wire_budget(repository, database):
    for index in range(18):
        (repository / "pkg" / f"calculator_helper_{index}.py").write_text(
            f'"""Calculator helper {index} ' + ("with detailed context " * 25) + '"""\n'
            "from pkg.core import Calculator\n",
            encoding="utf-8",
        )
    stats = RepositoryScanner(database).scan(repository)
    config = load_config(repository)
    baseline_scope = agent_scope(
        database,
        repository_id=stats.repository_id,
        goal="Change Calculator behavior and its web presentation dependencies",
        branch=None,
        config=replace(config, agent=replace(config.agent, payload_limit_bytes=100_000)),
    )
    baseline = baseline_scope["architecture_decision"]["verification"]["post_change_baseline"]
    config = replace(
        config,
        agent=replace(config.agent, payload_limit_bytes=4_000),
    )

    value = agent_scope(
        database,
        repository_id=stats.repository_id,
        goal="Change Calculator behavior and its web presentation dependencies",
        branch=None,
        config=config,
        verification_baseline=baseline,
    )
    encoded_size = len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    assert encoded_size <= 4_000
    assert value["payload_budget"]["truncated"] is True
    assert value["primary_files"]
    assert all(item["path"] for item in value["primary_files"])
    assert value["architecture_decision"]["contract_version"] == "architecture-decision-v1"
    assert value["architecture_decision"]["plain_language"]["conclusion"]
    assert value["architecture_decision"]["placement"]["plain_language"]["conclusion"]
    assert (
        value["architecture_decision"]["verification"]["post_change_comparison"]["status"]
        == "rescan_required"
    )

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from anaxigraph.agent import agent_scope, impact_analysis
from anaxigraph.agent_graph import _select_primary
from anaxigraph.agent_lexicon import goal_terms
from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner


def test_token_usage_goals_include_status_and_telemetry_vocabulary():
    terms = goal_terms("Show how many model tokens these actions use")

    assert {"token", "usage", "cost", "status", "telemetry", "duration"} <= terms


def test_agent_scope_is_bounded_and_includes_tests_protection_and_rules(repository, database):
    stats = RepositoryScanner(database).scan(repository)
    value = agent_scope(
        database,
        repository_id=stats.repository_id,
        goal="Change the Calculator calculation behavior",
        config=load_config(repository),
    )

    assert value["primary_files"][0]["path"] == "pkg/core.py"
    assert value["map_status"]["state"] == "current"
    assert "tests/test_core.py" in value["tests"]
    assert any(item["path"] == "pkg/core.py" for item in value["protected_files"])
    assert value["risk"] == "high"
    assert "does not mean the code is broken" in value["plain_language"]["risk"]["meaning"]
    assert "not a code-quality grade" in value["plain_language"]["file_measurements"]["complexity"]
    assert len(value["recommended_context"]) <= 12
    encoded_size = len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    assert encoded_size <= value["payload_budget"]["limit_bytes"]
    assert encoded_size == value["payload_budget"]["estimated_bytes"]
    assert value["telemetry"]["contract_version"] == "action-telemetry-v1"
    assert value["telemetry"]["action"] == "scope"
    assert value["telemetry"]["duration_ms"] >= 0
    assert value["telemetry"]["payload_bytes"] == encoded_size
    assert value["telemetry"]["input_tokens"] == 0
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
        value["architecture_decision"]["history_evidence"]["change_coupling"]["status"]
        == "insufficient_history"
    )
    assert (
        "facts AnaxiGraph read directly"
        in value["architecture_decision"]["plain_language"]["conclusion"]
    )
    path = value["architecture_decision"]["task_path"]
    assert path["contract_version"] == "task-path-v1"
    assert path["module"]["path"] == "pkg/core.py"
    assert "Calculator" in {item["name"] for item in path["symbols"]}
    assert "tests/test_core.py" in path["module"]["focused_tests"]


def test_agent_scope_follows_a_declared_area_and_subsystem(repository, database):
    policy = repository / ".anaxigraph.yml"
    policy.write_text(
        policy.read_text(encoding="utf-8").replace(
            "groups:\n  domain:\n    paths: [pkg/**]",
            """groups:
  domain-core:
    level: subsystem
    parent: domain
    description: Core domain behavior.
    paths: [pkg/core.py]
  domain:
    level: area
    description: Domain implementation.
    paths: [pkg/**]""",
        ),
        encoding="utf-8",
    )
    stats = RepositoryScanner(database).scan(repository)

    value = agent_scope(
        database,
        repository_id=stats.repository_id,
        goal="Change Calculator behavior",
        config=load_config(repository),
    )

    path = value["architecture_decision"]["task_path"]
    assert path["status"] == "policy_with_symbols"
    assert path["area"]["name"] == "Domain"
    assert path["subsystem"]["name"] == "Domain Core"
    assert path["area"]["responsibility"] == "Domain implementation."
    assert path["subsystem"]["responsibility"] == "Core domain behavior."


def test_agent_scope_prefers_the_roadmap_document_for_a_roadmap_goal(repository, database):
    roadmap = repository / "docs" / "feature-development-plan.md"
    roadmap.write_text(
        "# Feature development plan\n\n"
        "This roadmap records the remaining product work and the proof needed to finish it.\n",
        encoding="utf-8",
    )
    noisy_source = repository / "pkg" / "pattern_evidence_features.py"
    noisy_source.write_text(
        "\n".join(
            [
                '"""Build code features for coding agents."""',
                *[
                    f"def module_feature_{index}():\n    return 'code feature {index}'"
                    for index in range(20)
                ],
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    stats = RepositoryScanner(database).scan(repository)

    value = agent_scope(
        database,
        repository_id=stats.repository_id,
        goal="Narrow the remaining roadmap to core features in the development plan",
        config=load_config(repository),
    )

    expected = "docs/feature-development-plan.md"
    assert value["primary_files"][0]["path"] == expected
    decision = value["architecture_decision"]
    assert decision["placement"]["preferred_path"] == expected
    assert decision["task_path"]["module"]["path"] == expected
    assert decision["task_path"]["symbols"] == []


def test_agent_scope_prefers_a_test_for_an_explicit_test_goal(repository, database):
    stats = RepositoryScanner(database).scan(repository)

    value = agent_scope(
        database,
        repository_id=stats.repository_id,
        goal="Change the Calculator test behavior",
        config=load_config(repository),
    )

    expected = "tests/test_core.py"
    assert value["primary_files"][0]["path"] == expected
    decision = value["architecture_decision"]
    assert decision["placement"]["preferred_path"] == expected
    assert decision["task_path"]["module"]["path"] == expected


def test_agent_scope_places_a_concept_level_architecture_verification_goal(repository, database):
    implementation = repository / "src" / "product" / "agent_decision_verification.py"
    implementation.parent.mkdir(parents=True)
    implementation.write_text(
        '"""Save architecture baselines and compare repository structure after a change."""\n\n'
        "def verification_baseline():\n    return {}\n\n"
        "def compare_verification_baselines():\n    return {}\n",
        encoding="utf-8",
    )
    effects = repository / "src" / "product" / "agent_change_effects.py"
    effects.write_text(
        '"""Classify structural changes as worse, better, new, fixed, or unchanged."""\n\n'
        "def structural_effects():\n    return []\n",
        encoding="utf-8",
    )
    release_check = repository / "scripts" / "verify_release_artifacts.py"
    release_check.parent.mkdir()
    release_check.write_text(
        '"""Verify repository release files before publishing."""\n\n'
        "def verify_distribution():\n    return True\n",
        encoding="utf-8",
    )
    stats = RepositoryScanner(database).scan(repository)

    value = agent_scope(
        database,
        repository_id=stats.repository_id,
        goal=(
            "Verify whether a code change improved the repository structure without making "
            "files larger or dependencies more tangled"
        ),
        config=load_config(repository),
    )

    expected = "src/product/agent_decision_verification.py"
    assert value["primary_files"][0]["path"] == expected
    decision = value["architecture_decision"]
    assert decision["placement"]["preferred_path"] == expected
    assert decision["task_path"]["module"]["path"] == expected
    assert "verification_baseline" in {
        symbol["name"] for symbol in decision["task_path"]["symbols"]
    }


def test_primary_scope_uses_the_reviewed_responsibility_instead_of_unrelated_matches():
    def module(path, area, subsystem):
        return {
            "path": path,
            "declared_group": None,
            "inferred_group": "sample",
            "semantic_taxonomy": {"area": area, "subsystem": subsystem},
            "architecture_placement": {
                "area": area,
                "subsystem": subsystem,
                "source": "AI-created map checked by a separate AI pass",
            },
        }

    files = {
        1: module("src/architecture_verification.py", "change-help", "verification"),
        2: module("scripts/verify_release.py", "release", "packages"),
        3: module("src/verification_contract.py", "change-help", "verification"),
        4: module("src/change_effects.py", "change-help", "verification"),
        5: module("src/architecture_rules.py", "change-help", "findings"),
        6: module("src/generic_change_helper.py", "change-help", "verification"),
    }

    assert _select_primary(
        [(100.0, 1), (95.0, 2), (90.0, 3), (85.0, 4), (80.0, 5), (20.0, 6)],
        files,
        limit=8,
    ) == [1, 3, 4]


def test_impact_follows_reverse_edges_and_relevant_tests(repository, database):
    stats = RepositoryScanner(database).scan(repository)
    value = impact_analysis(
        database,
        repository_id=stats.repository_id,
        target="pkg/core.py",
        config=load_config(repository),
    )

    paths = {item["path"] for item in value["direct_dependants"]}
    assert value["map_status"]["state"] == "current"
    assert "pkg/consumer.py" in paths
    assert "tests/test_core.py" in paths
    assert "tests/test_core.py" in value["tests_relevant"]
    assert value["risk"] == "high"
    assert value["risk_reasons"]
    assert "possible follow-on effects" in value["plain_language"]["how_to_use_this"]
    assert (
        "registers behavior when the application starts or runs"
        in value["plain_language"]["limits"]
    )
    assert "runtime registration" not in value["plain_language"]["limits"]
    assert value["telemetry"]["contract_version"] == "action-telemetry-v1"
    assert value["telemetry"]["action"] == "impact"
    assert value["telemetry"]["duration_ms"] >= 0
    assert value["telemetry"]["payload_bytes"] == len(
        json.dumps(value, separators=(",", ":"), default=str).encode()
    )


def test_impact_reports_an_unknown_repository_or_target(repository, database):
    config = load_config(repository)
    with pytest.raises(ValueError, match="Repository not found"):
        impact_analysis(
            database,
            repository_id=999,
            target="pkg/core.py",
            config=config,
        )

    stats = RepositoryScanner(database).scan(repository)
    with pytest.raises(ValueError, match="Target not found: pkg/missing.py"):
        impact_analysis(
            database,
            repository_id=stats.repository_id,
            target="pkg/missing.py",
            config=config,
        )


def test_agent_scope_refreshes_findings_after_structural_harm(repository, database):
    first_scan = RepositoryScanner(database).scan(repository)
    config = load_config(repository)
    helper = repository / "pkg/util.py"
    helper.write_text(
        helper.read_text(encoding="utf-8")
        + "\nfrom pkg.core import Calculator\n\ndef triple(value: int) -> int:\n"
        "    return Calculator().calculate(value) + value\n",
        encoding="utf-8",
    )
    (repository / "web/bridge.py").write_text(
        "from pkg.util import double\n\ndef presentation_value(value: int) -> int:\n"
        "    return double(value)\n",
        encoding="utf-8",
    )

    second_scan = RepositoryScanner(database).scan(repository)
    after = agent_scope(
        database,
        repository_id=second_scan.repository_id,
        goal="Change the double arithmetic helper",
        config=config,
    )

    assert second_scan.snapshot_id != first_scan.snapshot_id
    finding_types = {item["finding_type"] for item in after["known_findings"]}
    assert {"dependency_cycle", "architecture_violation"} <= finding_types
    assert all(item["plain_language"]["how_to_check"] for item in after["known_findings"])


def test_agent_scope_trims_optional_context_to_the_configured_wire_budget(repository, database):
    for index in range(18):
        (repository / "pkg" / f"calculator_helper_{index}.py").write_text(
            f'"""Calculator helper {index} ' + ("with detailed context " * 25) + '"""\n'
            "from pkg.core import Calculator\n",
            encoding="utf-8",
        )
    stats = RepositoryScanner(database).scan(repository)
    config = load_config(repository)
    config = replace(
        config,
        agent=replace(config.agent, payload_limit_bytes=4_000),
    )

    value = agent_scope(
        database,
        repository_id=stats.repository_id,
        goal="Change Calculator behavior and its web presentation dependencies",
        config=config,
    )
    encoded_size = len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    assert encoded_size <= 4_000
    assert value["payload_budget"]["truncated"] is True
    assert value["primary_files"]
    assert all(item["path"] for item in value["primary_files"])
    assert value["architecture_decision"]["contract_version"] == "architecture-decision-v1"
    assert value["architecture_decision"]["plain_language"]["conclusion"]
    assert value["architecture_decision"]["placement"]["plain_language"]["conclusion"]
    assert value["architecture_decision"]["task_path"]["module"]["path"]
    assert value["architecture_decision"]["history_evidence"]["change_coupling"]["status"]
    verification = value["architecture_decision"]["verification"]
    assert verification["rescan_argv"] == ["anaxigraph", "update", ".", "--json"]
    assert "History" in verification["next_step"]

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from anaxigraph.agent import architecture_guidance, impact_analysis
from anaxigraph.agent_graph import _select_primary
from anaxigraph.agent_lexicon import goal_terms
from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner


def test_token_usage_goals_include_status_and_telemetry_vocabulary():
    terms = goal_terms("Show how many model tokens these actions use")

    assert {"token", "usage", "cost", "status", "telemetry", "duration"} <= terms


def test_architecture_guidance_is_bounded_and_includes_tests_protection_and_rules(
    repository, database
):
    stats = RepositoryScanner(database).scan(repository)
    value = architecture_guidance(
        database,
        repository_id=stats.repository_id,
        goal="Change the Calculator calculation behavior",
        config=load_config(repository),
    )

    assert value["primary_files"][0]["path"] == "pkg/core.py"
    assert value["contract_version"] == "architecture-guidance-v1"
    assert value["identity"].startswith("architecture-guidance-v1:")
    assert value["intent"] == "build"
    assert value["recommendation"]["action"] == "extend"
    assert value["recommendation"]["starting_point"] == "pkg/core.py"
    journey = value["agent_journey"]
    assert journey["contract_version"] == "agent-journey-v1"
    assert journey["intent"] == "build"
    assert journey["next_action"] == {
        "tool": "ANAXIGRAPH_IMPACT",
        "arguments": {"target": "pkg/core.py"},
    }
    assert journey["after_change"][0]["arguments"] == {"refresh_semantics": True}
    assert journey["after_change"][1]["arguments"]["intent"] == "reassess"
    assert value["understanding"]["charter"]["state"] == "provisional"
    assert value["impact_summary"]["target"] == "pkg/core.py"
    assert value["impact_summary"]["bounded"] is True
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
    assert value["telemetry"]["action"] == "guidance"
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


def test_architecture_guidance_uses_parser_backed_typescript_contracts(repository, database):
    (repository / "web" / "App.test.tsx").write_text(
        "import { App } from './App';\ntest('renders the application label', () => App());\n",
        encoding="utf-8",
    )
    stats = RepositoryScanner(database).scan(repository)

    value = architecture_guidance(
        database,
        repository_id=stats.repository_id,
        goal="Change the App component label behavior",
        config=load_config(repository),
    )

    assert value["primary_files"][0]["path"] == "web/App.tsx"
    assert "web/App.test.tsx" in value["tests"]
    assert any(
        item["path"] == "web/App.tsx"
        and item["name"] == "App"
        and item["symbol_type"] == "react_component"
        and item["visibility"] == "public"
        for item in value["interfaces"]
    )
    task = value["architecture_decision"]["task_path"]
    assert any(item["name"] == "App" for item in task["symbols"])
    assert "web/App.test.tsx" in task["module"]["focused_tests"]


def test_refactor_guidance_is_distinct_and_does_not_invent_a_change(repository, database):
    stats = RepositoryScanner(database).scan(repository)
    config = load_config(repository)
    build = architecture_guidance(
        database,
        repository_id=stats.repository_id,
        goal="Improve Calculator structure",
        config=config,
        intent="build",
    )
    refactor = architecture_guidance(
        database,
        repository_id=stats.repository_id,
        goal="Improve Calculator structure",
        config=config,
        intent="refactor",
    )
    improve = architecture_guidance(
        database,
        repository_id=stats.repository_id,
        goal="Improve Calculator structure",
        config=config,
        intent="improve",
    )

    assert build["identity"] != refactor["identity"]
    assert refactor["intent"] == "refactor"
    assert refactor["recommendation"]["action"] == "retain"
    assert refactor["recommendation"]["reasons_not_to_change"]
    assert refactor["confidence"]["label"] == "limited"
    assert improve["intent"] == "improve"
    assert improve["recommendation"]["action"] == "retain"
    assert improve["agent_journey"]["intent"] == "improve"


def test_guidance_rejects_an_unknown_intent(repository, database):
    stats = RepositoryScanner(database).scan(repository)

    with pytest.raises(ValueError, match="Guidance intent"):
        architecture_guidance(
            database,
            repository_id=stats.repository_id,
            goal="Change Calculator behavior",
            config=load_config(repository),
            intent="rewrite-everything",
        )


def test_architecture_guidance_follows_a_declared_area_and_subsystem(repository, database):
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

    value = architecture_guidance(
        database,
        repository_id=stats.repository_id,
        goal="Change Calculator behavior",
        config=load_config(repository),
    )

    path = value["architecture_decision"]["task_path"]
    assert path["status"] == "declared_with_symbols"
    assert path["area"]["name"] == "Domain"
    assert path["subsystem"]["name"] == "Domain Core"
    assert path["area"]["responsibility"] == "Domain implementation."
    assert path["subsystem"]["responsibility"] == "Core domain behavior."


def test_architecture_guidance_prefers_the_roadmap_document_for_a_roadmap_goal(
    repository, database
):
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

    value = architecture_guidance(
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


def test_architecture_guidance_prefers_a_test_for_an_explicit_test_goal(repository, database):
    stats = RepositoryScanner(database).scan(repository)

    value = architecture_guidance(
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


def test_architecture_guidance_places_a_concept_level_architecture_verification_goal(
    repository, database
):
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

    value = architecture_guidance(
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
                "source": "inferred responsibility map",
                "map_layer": "responsibility",
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


def test_architecture_guidance_refreshes_findings_after_structural_harm(repository, database):
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
    after = architecture_guidance(
        database,
        repository_id=second_scan.repository_id,
        goal="Change the double arithmetic helper",
        config=config,
    )

    assert second_scan.snapshot_id != first_scan.snapshot_id
    finding_types = {item["finding_type"] for item in after["known_findings"]}
    assert {"dependency_cycle", "architecture_violation"} <= finding_types
    assert all(item["plain_language"]["how_to_check"] for item in after["known_findings"])


def test_architecture_guidance_trims_optional_context_to_the_configured_wire_budget(
    repository, database
):
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

    value = architecture_guidance(
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
    assert value["contract_version"] == "architecture-guidance-v1"
    assert value["recommendation"]["summary"]
    assert value["recommendation"]["starting_point"]
    assert value["understanding"]["summary"]
    assert value["impact_summary"]["bounded"] is True
    assert value["architecture_decision"]["contract_version"] == "architecture-decision-v1"

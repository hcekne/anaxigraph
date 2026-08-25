from __future__ import annotations

import json
from dataclasses import replace

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
    assert all("repository_id" not in item for item in value["architecture_rules"])
    assert value["architecture_decision"]["contract_version"] == "architecture-decision-v1"
    assert value["architecture_decision"]["status"] == "deterministic_only"


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
        branch=None,
        config=config,
    )
    encoded_size = len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    assert encoded_size <= 4_000
    assert value["payload_budget"]["truncated"] is True
    assert value["primary_files"]
    assert all(item["path"] for item in value["primary_files"])
    assert value["architecture_decision"]["contract_version"] == "architecture-decision-v1"

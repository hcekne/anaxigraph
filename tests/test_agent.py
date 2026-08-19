from __future__ import annotations

from codeintel.agent import agent_scope, impact_analysis
from codeintel.config import load_config
from codeintel.scanner import RepositoryScanner


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

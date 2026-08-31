from __future__ import annotations

from pathlib import Path

from anaxigraph.architecture_vocabulary import inferred_group
from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner


def test_root_support_files_use_regular_architecture_roles(repository: Path, database):
    (repository / "package-lock.json").write_text('{"lockfileVersion": 3}\n', encoding="utf-8")
    (repository / "package.json").write_text('{"name": "sample"}\n', encoding="utf-8")
    (repository / "pyproject.toml").write_text('[project]\nname = "sample"\n', encoding="utf-8")
    (repository / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    (repository / ".agents" / "plugins").mkdir(parents=True)
    (repository / ".agents" / "plugins" / "marketplace.json").write_text(
        '{"plugins": []}\n', encoding="utf-8"
    )
    (repository / "src").mkdir()
    (repository / "src" / "service.py").write_text("VALUE = 1\n", encoding="utf-8")

    stats = RepositoryScanner(database).scan(repository)
    nodes = {item["path"]: item for item in database.graph(stats.repository_id)["nodes"]}

    assert "package-lock.json" not in nodes
    assert nodes["package.json"]["architecture_area"] == "infrastructure"
    assert nodes["package.json"]["architecture_subsystem"] == "build-and-packaging"
    assert nodes["pyproject.toml"]["architecture_area"] == "infrastructure"
    assert nodes["Dockerfile"]["architecture_subsystem"] == "delivery-and-operations"
    assert nodes[".agents/plugins/marketplace.json"]["architecture_area"] == ("developer-tooling")
    assert nodes[".agents/plugins/marketplace.json"]["architecture_subsystem"] == (
        "agent-integrations"
    )
    assert nodes["src/service.py"]["architecture_area"] == "application"
    assert nodes["src/service.py"]["architecture_subsystem"] == "application-code"
    assert all(
        not item["architecture_area"].endswith((".json", ".toml", ".yml"))
        for item in nodes.values()
    )


def test_inferred_layer_keeps_fallback_parent_areas(repository: Path, database):
    (repository / "pyproject.toml").write_text('[project]\nname = "sample"\n', encoding="utf-8")
    stats = RepositoryScanner(database).scan(repository)

    hierarchy = database.group_hierarchy(stats.repository_id, layer="inferred")
    infrastructure = next(item for item in hierarchy if item["name"] == "infrastructure")

    assert any(child["name"] == "build-and-packaging" for child in infrastructure["children"])


def test_dependency_lockfiles_are_not_application_modules(repository: Path):
    config = load_config(repository)

    assert config.is_ignored("package-lock.json")
    assert config.is_ignored("frontend/pnpm-lock.yaml")
    assert inferred_group("pyproject.toml", "toml", "configuration") == "build-and-packaging"

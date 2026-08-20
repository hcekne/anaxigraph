from __future__ import annotations

from pathlib import Path

from anaxigraph.onboarding_detection import (
    detect_architecture_policy,
    detect_coverage_files,
    detect_project_name,
    detect_repository_groups,
)


def test_project_name_prefers_package_then_pyproject_then_directory(tmp_path: Path):
    repository = tmp_path / "sample-repository"
    repository.mkdir()
    assert detect_project_name(repository) == "Sample Repository"

    (repository / "pyproject.toml").write_text(
        '[project]\nname = "python-service"\n', encoding="utf-8"
    )
    assert detect_project_name(repository) == "Python Service"

    (repository / "package.json").write_text('{"name": "@scope/web-client"}\n', encoding="utf-8")
    assert detect_project_name(repository) == "Web Client"


def test_unversioned_repository_discovers_groups_policy_and_coverage(tmp_path: Path):
    repository = tmp_path / "workspace"
    (repository / "src").mkdir(parents=True)
    (repository / "src" / "main.py").write_text("value = 1\n", encoding="utf-8")
    (repository / "web").mkdir()
    (repository / "web" / "app.ts").write_text("export const value = 1;\n", encoding="utf-8")
    (repository / "coverage").mkdir()
    (repository / "coverage" / "lcov.info").write_text("TN:\n", encoding="utf-8")
    (repository / "docs").mkdir()
    (repository / "docs" / "architecture.md").write_text("# Architecture\n", encoding="utf-8")

    groups = detect_repository_groups(repository)
    assert [(name, path) for name, path, _description in groups] == [
        ("frontend", "web/**"),
        ("source", "src/**"),
        ("documentation", "docs/**"),
    ]
    assert detect_architecture_policy(repository) == "docs/architecture.md"
    assert detect_coverage_files(repository) == ["coverage/lcov.info"]

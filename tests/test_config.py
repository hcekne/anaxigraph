from __future__ import annotations

from pathlib import Path

from anaxigraph.config import load_config, path_matches


def test_config_loads_groups_rules_and_ignore(repository):
    config = load_config(repository)

    assert config.project_name == "Sample Observatory"
    assert config.declared_group("pkg/core.py") == "domain"
    assert config.declared_group("web/App.tsx") == "presentation"
    assert config.is_ignored("ignored/secret.py")
    assert config.is_ignored(".git/config")
    assert config.is_ignored("coverage.xml")
    assert config.is_ignored("backend/coverage.xml")
    assert config.is_ignored("frontend/coverage/lcov.info")
    assert config.coverage_required is False
    assert not config.is_ignored("pkg/core.py")
    assert {rule.rule_id for rule in config.architecture.rules} == {
        "small-module-signal",
        "web-domain-boundary",
    }


def test_globs_match_root_and_nested_paths():
    assert path_matches("tests/test_unit.py", "tests/**")
    assert path_matches("frontend/src/App.test.tsx", "**/*.test.*")
    assert path_matches(".git/config", ".git/**")


def test_default_config_name_is_anaxigraph(tmp_path: Path):
    (tmp_path / ".anaxigraph.yml").write_text("project: {name: AnaxiGraph}\n", encoding="utf-8")

    config = load_config(tmp_path)

    assert config.project_name == "AnaxiGraph"
    assert config.config_path == tmp_path / ".anaxigraph.yml"


def test_coverage_warning_can_be_explicitly_required(tmp_path: Path):
    (tmp_path / ".anaxigraph.yml").write_text(
        "coverage:\n  required: true\n  files: [reports/coverage.xml]\n",
        encoding="utf-8",
    )

    config = load_config(tmp_path)

    assert config.coverage_required is True
    assert config.coverage_files == ("reports/coverage.xml",)

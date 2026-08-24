from __future__ import annotations

import json
import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest

from scripts.check_architecture import check_architecture
from scripts.check_changed_coverage import check_changed_coverage
from scripts.check_code_quality import check_quality
from scripts.check_forbidden_files import forbidden_paths
from scripts.check_javascript_syntax import syntax_errors
from scripts.check_module_size import check_repository
from scripts.check_semantic_cohesion import cohesion_issues
from scripts.quality_metrics import scan_functions
from scripts.run_quality_gate import _container_browser_command, quality_commands


def _policy(root: Path, legacy: list[dict] | None = None) -> Path:
    path = root / "policy.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "limits": {
                    "implementation_warning": 400,
                    "implementation_hard": 500,
                    "test_warning": 550,
                    "test_hard": 800,
                    "asset_warning": 600,
                },
                "implementation_extensions": [".py", ".js", ".ts"],
                "test_patterns": ["tests/**"],
                "exclusions": [],
                "legacy_exceptions": legacy or [],
            }
        ),
        encoding="utf-8",
    )
    return path.relative_to(root)


def _lines(count: int) -> str:
    return "\n".join(f"VALUE_{index} = {index}" for index in range(count)) + "\n"


def _exception(path: str, baseline: int, expires: str = "2099-01-01") -> dict:
    return {
        "path": path,
        "baseline_lines": baseline,
        "rationale": "Test legacy module",
        "owner": "tests",
        "removal_phase": "Test phase",
        "expires_on": expires,
    }


def test_new_oversized_module_fails_with_extraction_guidance(tmp_path):
    source = tmp_path / "src" / "large.py"
    source.parent.mkdir()
    source.write_text("def cohesive_service():\n" + "    value = 1\n" * 500, encoding="utf-8")

    issues = check_repository(
        tmp_path,
        policy_path=_policy(tmp_path),
        paths=["src/large.py"],
    )

    assert [item.level for item in issues] == ["error"]
    assert "hard 500-line ceiling" in issues[0].message
    assert any("cohesive_service" in value for value in issues[0].suggestions)


def test_whole_repository_check_includes_untracked_modules(tmp_path):
    source = tmp_path / "src" / "new_large.py"
    source.parent.mkdir()
    source.write_text(_lines(501), encoding="utf-8")
    policy_path = _policy(tmp_path)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)

    issues = check_repository(tmp_path, policy_path=policy_path)

    assert any(item.path == "src/new_large.py" and item.level == "error" for item in issues)


def test_oversized_dashboard_asset_fails_the_hard_ceiling(tmp_path):
    asset = tmp_path / "src" / "dashboard" / "large.css"
    asset.parent.mkdir(parents=True)
    asset.write_text(".rule {}\n" * 501, encoding="utf-8")

    issues = check_repository(
        tmp_path, policy_path=_policy(tmp_path), paths=["src/dashboard/large.css"]
    )

    assert any(item.level == "error" and "hard 500-line ceiling" in item.message for item in issues)


def test_legacy_ratchet_requires_exact_baseline_update(tmp_path):
    source = tmp_path / "src" / "legacy.py"
    source.parent.mkdir()
    source.write_text(_lines(502), encoding="utf-8")
    policy_path = _policy(tmp_path, [_exception("src/legacy.py", 502)])

    assert check_repository(tmp_path, policy_path=policy_path, paths=["src/legacy.py"]) == []

    source.write_text(_lines(503), encoding="utf-8")
    growth = check_repository(tmp_path, policy_path=policy_path, paths=["src/legacy.py"])
    assert any("grew above" in item.message for item in growth)

    source.write_text(_lines(501), encoding="utf-8")
    stale = check_repository(tmp_path, policy_path=policy_path, paths=["src/legacy.py"])
    assert any("lower baseline_lines" in item.message for item in stale)

    policy_path = _policy(tmp_path, [_exception("src/legacy.py", 501)])
    assert check_repository(tmp_path, policy_path=policy_path, paths=["src/legacy.py"]) == []


def test_legacy_exception_must_be_removed_at_or_below_ceiling(tmp_path):
    source = tmp_path / "src" / "legacy.py"
    source.parent.mkdir()
    source.write_text(_lines(500), encoding="utf-8")
    policy_path = _policy(tmp_path, [_exception("src/legacy.py", 501)])

    issues = check_repository(tmp_path, policy_path=policy_path, paths=["src/legacy.py"])

    assert any("exception is stale" in item.message for item in issues)


def test_tests_have_a_separate_temporary_split_threshold(tmp_path):
    source = tmp_path / "tests" / "test_large.py"
    source.parent.mkdir()
    source.write_text(_lines(700), encoding="utf-8")
    policy_path = _policy(tmp_path)

    warnings = check_repository(tmp_path, policy_path=policy_path, paths=["tests/test_large.py"])
    source.write_text(_lines(801), encoding="utf-8")
    errors = check_repository(tmp_path, policy_path=policy_path, paths=["tests/test_large.py"])

    assert [item.level for item in warnings] == ["warning"]
    assert [item.level for item in errors] == ["error"]


def test_expired_exception_fails_whole_repository_check(tmp_path):
    source = tmp_path / "src" / "legacy.py"
    source.parent.mkdir()
    source.write_text(_lines(501), encoding="utf-8")
    policy_path = _policy(tmp_path, [_exception("src/legacy.py", 501, "2026-01-01")])
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)

    issues = check_repository(
        tmp_path,
        policy_path=policy_path,
        today=date(2026, 8, 20),
    )

    assert any("expired on 2026-01-01" in item.message for item in issues)


def _architecture_policy(
    root: Path,
    forbidden: list[dict] | None = None,
    **overrides,
) -> Path:
    path = root / "architecture.json"
    value = {
        "schema_version": 1,
        "source_root": "src",
        "package": "sample",
        "forbidden_dependencies": forbidden or [],
    }
    value.update(overrides)
    path.write_text(
        json.dumps(value),
        encoding="utf-8",
    )
    return path.relative_to(root)


def test_architecture_checker_detects_internal_cycle(tmp_path):
    package = tmp_path / "src" / "sample"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "alpha.py").write_text("from . import beta\n", encoding="utf-8")
    (package / "beta.py").write_text("from . import alpha\n", encoding="utf-8")

    issues = check_architecture(tmp_path, policy_path=_architecture_policy(tmp_path))

    assert len(issues) == 1
    assert issues[0].issue_type == "dependency_cycle"
    assert set(issues[0].modules) == {"sample.alpha", "sample.beta"}


def test_architecture_checker_enforces_declared_boundary(tmp_path):
    package = tmp_path / "src" / "sample"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "domain.py").write_text("VALUE = 1\n", encoding="utf-8")
    (package / "transport.py").write_text("from sample import domain\n", encoding="utf-8")
    rule = {"from": "sample.transport", "to": "sample.domain", "reason": "test boundary"}

    issues = check_architecture(
        tmp_path,
        policy_path=_architecture_policy(tmp_path, [rule]),
    )

    assert any(item.issue_type == "forbidden_dependency" for item in issues)


def test_architecture_checker_enforces_layer_direction_and_legacy_ratchet(tmp_path):
    package = tmp_path / "src" / "sample"
    package.mkdir(parents=True)
    (package / "domain.py").write_text("VALUE = 1\n", encoding="utf-8")
    (package / "transport.py").write_text("from sample import domain\n", encoding="utf-8")
    layers = {
        "domain": {"modules": ["sample.domain"], "may_import": ["domain"]},
        "transport": {"modules": ["sample.transport"], "may_import": ["transport"]},
    }
    policy = _architecture_policy(
        tmp_path,
        layers=layers,
        require_layer_classification=True,
        legacy_layer_violations=[],
    )
    issues = check_architecture(tmp_path, policy_path=policy)
    assert any(item.issue_type == "layer_violation" for item in issues)

    policy = _architecture_policy(
        tmp_path,
        layers=layers,
        require_layer_classification=True,
        legacy_layer_violations=["sample.transport->sample.domain"],
    )
    assert check_architecture(tmp_path, policy_path=policy) == []
    (package / "transport.py").write_text("VALUE = 2\n", encoding="utf-8")
    stale = check_architecture(tmp_path, policy_path=policy)
    assert any(item.issue_type == "stale_layer_exception" for item in stale)


def test_forbidden_file_checker_distinguishes_examples_from_secrets():
    values = forbidden_paths(
        [
            ".env.example",
            ".env",
            "state/anaxi.db",
            "keys/id_ed25519",
            "src/module.py",
        ]
    )

    assert values == [".env", "keys/id_ed25519", "state/anaxi.db"]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
def test_javascript_syntax_checker_reports_invalid_module(tmp_path):
    valid = tmp_path / "valid.js"
    invalid = tmp_path / "invalid.js"
    valid.write_text("const value = 1;\n", encoding="utf-8")
    invalid.write_text("const = ;\n", encoding="utf-8")

    assert syntax_errors([valid]) == []
    assert invalid.name in syntax_errors([invalid])[0]


def _maintainability_policy(root: Path, **overrides) -> Path:
    value = {
        "schema_version": 1,
        "source_root": "src",
        "package": "sample",
        "exclude": [],
        "function_limits": {
            "warning_lines": 40,
            "hard_lines": 50,
            "warning_complexity": 12,
            "hard_complexity": 15,
        },
        "coupling_limits": {"warning": 8, "hard": 12},
        "legacy_functions": {},
        "legacy_coupling": {},
    }
    value.update(overrides)
    path = root / "maintainability.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path.relative_to(root)


def test_function_budget_rejects_new_growth_and_ratchets_legacy(tmp_path):
    module = tmp_path / "src" / "sample" / "service.py"
    module.parent.mkdir(parents=True)
    module.write_text("def oversized():\n" + "    value = 1\n" * 50, encoding="utf-8")
    policy = _maintainability_policy(tmp_path)

    issues = check_quality(tmp_path, policy_path=policy)

    assert any(item.issue_type == "function_budget" and item.level == "error" for item in issues)
    metric = scan_functions(
        tmp_path,
        {
            "source_root": "src",
            "package": "sample",
            "exclude": [],
        },
    )[0]
    policy = _maintainability_policy(
        tmp_path,
        legacy_functions={"src/sample/service.py::oversized": [metric.lines, metric.complexity]},
    )
    assert check_quality(tmp_path, policy_path=policy) == []

    module.write_text(module.read_text(encoding="utf-8") + "    value = 2\n", encoding="utf-8")
    growth = check_quality(tmp_path, policy_path=policy)
    assert any(item.issue_type == "function_growth" for item in growth)


def test_coupling_budget_ratchets_high_fan_in(tmp_path):
    package = tmp_path / "src" / "sample"
    package.mkdir(parents=True)
    (package / "core.py").write_text("VALUE = 1\n", encoding="utf-8")
    for name in ("one", "two"):
        (package / f"{name}.py").write_text("from sample import core\n", encoding="utf-8")
    limits = {"warning": 1, "hard": 1}
    policy = _maintainability_policy(tmp_path, coupling_limits=limits)
    assert any(
        item.issue_type == "coupling_budget" for item in check_quality(tmp_path, policy_path=policy)
    )

    policy = _maintainability_policy(
        tmp_path,
        coupling_limits=limits,
        legacy_coupling={"sample.core": [2, 0]},
    )
    assert check_quality(tmp_path, policy_path=policy) == []
    (package / "three.py").write_text("from sample import core\n", encoding="utf-8")
    assert any(
        item.issue_type == "coupling_growth" for item in check_quality(tmp_path, policy_path=policy)
    )


def _write_coverage(path: Path, *, second_line_hits: int) -> None:
    path.write_text(
        f"""<?xml version="1.0" ?>
<coverage line-rate="0.9">
  <packages><package name="sample"><classes>
    <class name="module.py" filename="module.py"><lines>
      <line number="1" hits="1"/>
      <line number="2" hits="{second_line_hits}"/>
      <line number="3" hits="1"/>
    </lines></class>
  </classes></package></packages>
</coverage>
""",
        encoding="utf-8",
    )


def test_changed_coverage_uses_only_changed_executable_lines(tmp_path):
    module = tmp_path / "src" / "sample" / "module.py"
    module.parent.mkdir(parents=True)
    module.write_text("def value():\n    return 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@example.invalid"], check=True
    )
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "base"], check=True)
    base = subprocess.check_output(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True
    ).strip()
    module.write_text("def value():\n    current = 2\n    return current\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "change"], check=True)
    report = tmp_path / "coverage.xml"
    _write_coverage(report, second_line_hits=0)

    failed = check_changed_coverage(
        tmp_path,
        report=report,
        base=base,
        source_prefix="src/sample/",
    )
    _write_coverage(report, second_line_hits=1)
    passed = check_changed_coverage(
        tmp_path,
        report=report,
        base=base,
        source_prefix="src/sample/",
    )

    assert failed.changed_percent == 50.0
    assert failed.passed is False
    assert passed.changed_percent == 100.0
    assert passed.passed is True


def test_semantic_cohesion_requires_confident_evidence():
    policy = {
        "minimum_confidence": 0.7,
        "responsibility_warning": 2,
        "split_score_warning": 80,
    }
    dossiers = [
        {
            "path": "weak.py",
            "confidence": 0.4,
            "value": {
                "responsibilities": ["one", "two", "three"],
                "consolidation_assessment": {"recommendation": "split", "score": 95},
            },
        },
        {
            "path": "grounded.py",
            "confidence": 0.9,
            "value": {
                "responsibilities": ["one", "two", "three"],
                "consolidation_assessment": {"recommendation": "split", "score": 88},
            },
        },
    ]

    issues = cohesion_issues(dossiers, policy)

    assert {item.issue_type for item in issues} == {
        "responsibility_breadth",
        "semantic_split_candidate",
    }
    assert {item.path for item in issues} == {"grounded.py"}


def test_complete_quality_gate_includes_coverage_compose_benchmark_and_browser_contract():
    commands = quality_commands(Path("/workspace"), base="origin/main", skip_benchmark=False)
    flattened = [" ".join(command) for command in commands]
    browser = _container_browser_command(Path("/workspace"), 9123)

    assert any("pytest --cov=anaxigraph" in command for command in flattened)
    assert any(
        "check_changed_coverage.py" in command and "origin/main" in command for command in flattened
    )
    assert sum("docker compose" in command for command in flattened) == 2
    assert any("benchmarks.baseline" in command for command in flattened)
    assert any("benchmarks.first_user --runs 3" in command for command in flattened)
    assert any("smoke_container_sidecar.py" in command for command in flattened)
    assert "mcr.microsoft.com/playwright:v1.61.1-noble" in browser
    assert browser[browser.index("--network") + 1] == "host"
    assert "ANAXIGRAPH_VISUAL_URL=http://127.0.0.1:9123" in browser

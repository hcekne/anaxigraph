"""The maintainability ratchets: production size, function budgets, coupling, and depth.

These are judgments about the shape of the package, so they live apart from the
module-size tests, which judge one file at a time.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.check_code_quality import check_quality
from scripts.quality_metrics import scan_functions


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


def test_production_source_budget_is_an_exact_shrinking_ratchet(tmp_path):
    package = tmp_path / "src" / "sample"
    package.mkdir(parents=True)
    module = package / "service.py"
    asset = package / "dashboard.js"
    module.write_text("VALUE = 1\nVALUE = 2\n", encoding="utf-8")
    asset.write_text("const value = 1;\n", encoding="utf-8")
    policy = _maintainability_policy(
        tmp_path,
        production_source_budget={
            "root": "src/sample",
            "extensions": [".py", ".js"],
            "baseline_lines": 3,
        },
    )

    assert check_quality(tmp_path, policy_path=policy) == []

    asset.write_text("const value = 1;\nconst other = 2;\n", encoding="utf-8")
    growth = check_quality(tmp_path, policy_path=policy)
    assert any(item.issue_type == "production_source_growth" for item in growth)

    module.write_text("VALUE = 1\n", encoding="utf-8")
    asset.write_text("", encoding="utf-8")
    reduced = check_quality(tmp_path, policy_path=policy)
    assert any(item.issue_type == "stale_source_baseline" for item in reduced)
    assert "lower baseline_lines to 1" in reduced[0].message


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


def _package(root: Path, modules: dict[str, str]) -> Path:
    for name, source in modules.items():
        module = root / "src" / "sample" / f"{name}.py"
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_text(source, encoding="utf-8")
    return _maintainability_policy(root)


def _shallow(root: Path, policy: Path) -> list[str]:
    return [
        issue.path
        for issue in check_quality(root, policy_path=policy)
        if issue.issue_type == "shallow_module"
    ]


def test_a_module_that_only_renames_one_neighbour_is_offered_for_inlining(tmp_path):
    policy = _package(
        tmp_path,
        {
            "engine": "def run(value, deep=True):\n    return value\n",
            "rename": (
                "from sample.engine import run\n\n\ndef run_shallow(value):\n"
                "    return run(value, deep=False)\n"
            ),
        },
    )

    assert _shallow(tmp_path, policy) == ["sample.rename"]


def test_a_forwarder_several_callers_share_states_one_decision_and_is_left_alone(tmp_path):
    policy = _package(
        tmp_path,
        {
            "engine": "def run(value, deep=True):\n    return value\n",
            "rename": (
                "from sample.engine import run\n\n\ndef run_shallow(value):\n"
                "    return run(value, deep=False)\n"
            ),
            "reader_one": "from sample.rename import run_shallow\n\n\nx = run_shallow\n",
            "reader_two": "from sample.rename import run_shallow\n\n\ny = run_shallow\n",
        },
    )

    assert _shallow(tmp_path, policy) == []


def test_a_facade_over_several_collaborators_is_left_alone(tmp_path):
    policy = _package(
        tmp_path,
        {
            "engine": "def run(value):\n    return value\n",
            "store": "def save(value):\n    return value\n",
            "facade": (
                "from sample.engine import run\nfrom sample.store import save\n\n\n"
                "def handle(value):\n    return run(value)\n\n\n"
                "def keep(value):\n    return save(value)\n"
            ),
        },
    )

    assert _shallow(tmp_path, policy) == []


def test_a_module_that_forwards_outside_the_package_keeps_its_name(tmp_path):
    policy = _package(
        tmp_path,
        {
            "engine": "def run(value):\n    return value\n",
            "clock": (
                "from datetime import UTC, datetime\n\n\n"
                "def utc_now():\n    return datetime.now(UTC).isoformat()\n"
            ),
            "caller": "from sample.clock import utc_now\n\n\nz = utc_now\n",
        },
    )

    assert _shallow(tmp_path, policy) == []

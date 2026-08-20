from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path

from scripts.check_module_size import check_repository


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

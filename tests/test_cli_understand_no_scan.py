from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

import anaxigraph.cli_services as cli_services
from anaxigraph.cli import main


def _agent_policy(repository: Path) -> None:
    policy_path = repository / ".anaxigraph.yml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    policy["semantic"] = {
        "enabled": True,
        "provider": "agent",
        "refresh": "manual",
        "include": ["pkg/**"],
        "agent_lease_seconds": 120,
    }
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")


def _call(arguments: list[str], capsys) -> dict:
    main(arguments)
    return json.loads(capsys.readouterr().out)


def _refuse_scanning(monkeypatch) -> None:
    def refuse(_database):
        raise AssertionError("--no-scan must not start a structural scan")

    monkeypatch.setattr(cli_services, "scanner", refuse)


def _commit(repository: Path, message: str) -> None:
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-qm", message], check=True)


def test_understand_local_no_scan_reports_scan_required_without_scanning(
    repository: Path, tmp_path: Path, capsys, monkeypatch
):
    _agent_policy(repository)
    _refuse_scanning(monkeypatch)

    result = _call(
        [
            "understand",
            str(repository),
            "--db",
            str(tmp_path / "fresh.db"),
            "--no-scan",
            "--executor",
            "mcp",
            "--json",
        ],
        capsys,
    )

    assert result["status"] == "scan_required"
    assert result["complete"] is False
    assert result["scan"] == {}
    assert result["index"]["authority"] == "local"
    assert "anaxigraph scan" in result["recommended_action"]
    assert "map_status" not in result


def test_understand_local_no_scan_plans_against_current_snapshot(
    repository: Path, tmp_path: Path, capsys, monkeypatch
):
    _agent_policy(repository)
    database = tmp_path / "current.db"
    main(["scan", str(repository), "--db", str(database), "--json"])
    capsys.readouterr()
    _refuse_scanning(monkeypatch)

    result = _call(
        [
            "understand",
            str(repository),
            "--db",
            str(database),
            "--no-scan",
            "--plan-only",
            "--json",
        ],
        capsys,
    )

    assert result["status"] == "planned"
    assert result["scan"] == {}
    assert "map_status" not in result
    assert result["semantic"]["enabled"] is True


def test_understand_local_no_scan_detects_stale_map(
    repository: Path, tmp_path: Path, capsys, monkeypatch
):
    _agent_policy(repository)
    database = tmp_path / "stale.db"
    main(["scan", str(repository), "--db", str(database), "--json"])
    capsys.readouterr()
    (repository / "pkg" / "util.py").write_text(
        '"""Small arithmetic helpers."""\n\ndef triple(value: int) -> int:\n    return value * 3\n',
        encoding="utf-8",
    )
    _commit(repository, "Change util")
    _refuse_scanning(monkeypatch)

    result = _call(
        ["understand", str(repository), "--db", str(database), "--no-scan", "--json"],
        capsys,
    )

    assert result["status"] == "scan_required"
    assert result["map_status"]["state"] == "stale"
    assert str(database) in result["recommended_action"]


def test_understand_local_no_scan_until_complete_raises(
    repository: Path, tmp_path: Path, capsys, monkeypatch
):
    _agent_policy(repository)
    _refuse_scanning(monkeypatch)

    with pytest.raises(SystemExit, match="2"):
        main(
            [
                "understand",
                str(repository),
                "--db",
                str(tmp_path / "missing.db"),
                "--no-scan",
                "--until-complete",
                "--json",
            ]
        )

    assert "requires a current saved repository scan" in capsys.readouterr().err

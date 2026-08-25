from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "anaxigraph", *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_process_help_exposes_every_supported_command_family():
    result = _run("--help")

    assert result.returncode == 0
    for command in (
        "init",
        "scan",
        "understand",
        "history",
        "up",
        "doctor",
        "serve",
        "scope",
        "impact",
        "export",
    ):
        assert command in result.stdout


def test_process_scan_scope_and_export_share_one_index(repository: Path, tmp_path: Path):
    database = tmp_path / "process-index.db"
    scanned = _run("scan", str(repository), "--db", str(database), "--json")
    scoped = _run(
        "scope",
        str(repository),
        "--db",
        str(database),
        "--goal",
        "Change the calculator",
        "--json",
    )
    export_path = tmp_path / "exports/result.json"
    exported = _run(
        "export",
        str(repository),
        "--db",
        str(database),
        "--output",
        str(export_path),
        "--json",
    )

    assert scanned.returncode == scoped.returncode == exported.returncode == 0
    assert json.loads(scanned.stdout)["status"] == "ok"
    assert json.loads(scoped.stdout)["goal"] == "Change the calculator"
    assert json.loads(exported.stdout) == {"output": str(export_path), "status": "ok"}
    payload = json.loads(export_path.read_text(encoding="utf-8"))
    assert payload["overview"]["files"] == 8
    assert payload["graph"]["nodes"]


def test_process_validation_error_has_stable_exit_and_message(repository: Path, tmp_path: Path):
    result = _run(
        "semantic-worker",
        str(repository),
        "--db",
        str(tmp_path / "index.db"),
        "--interval",
        "0.5",
        "--once",
    )

    assert result.returncode == 2
    assert result.stderr == "anaxigraph: Semantic worker interval must be at least one second\n"

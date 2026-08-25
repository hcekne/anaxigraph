from __future__ import annotations

import subprocess
from pathlib import Path

from anaxigraph.finding_history import finding_history
from anaxigraph.history import import_git_history


def _commit(root: Path, message: str) -> str:
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", message], check=True)
    return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()


def _cycle_source(original: str) -> str:
    return "from .core import Calculator\n\n" + original


def test_retained_frames_identify_cycle_introduction_resolution_and_regression(
    repository, database
):
    utility = repository / "pkg" / "util.py"
    original = utility.read_text(encoding="utf-8")

    utility.write_text(_cycle_source(original), encoding="utf-8")
    introduced = _commit(repository, "Introduce calculator dependency cycle")
    utility.write_text(original, encoding="utf-8")
    resolved = _commit(repository, "Remove calculator dependency cycle")

    import_git_history(database, repository, every_commit=True)
    repository_row = database.repository(repository)
    assert repository_row is not None
    repository_id = int(repository_row["id"])
    finding = next(
        item
        for item in database.findings(repository_id)
        if item["finding_type"] == "dependency_cycle"
    )
    history = finding_history(database, repository_id, int(finding["id"]))

    assert finding["status"] == "resolved"
    assert history["status"] == "available"
    assert history["state"] == "resolved"
    assert history["introduction"]["kind"] == "introduced"
    assert history["introduction"]["frame"]["commit_sha"] == introduced
    assert history["resolution"]["frame"]["commit_sha"] == resolved
    assert [item["kind"] for item in history["transitions"]] == ["introduced", "resolved"]
    assert history["work"]["indexed_frames"] == history["work"]["retained_frames"]
    assert "not every Git commit" in history["plain_language"]["limits"]

    utility.write_text(_cycle_source(original), encoding="utf-8")
    returned = _commit(repository, "Reintroduce calculator dependency cycle")
    import_git_history(database, repository, every_commit=True)
    regressed = database.finding(repository_id, int(finding["id"]))
    history = finding_history(database, repository_id, int(finding["id"]))

    assert regressed["status"] == "regressed"
    assert history["state"] == "regressed"
    assert history["recurrence"]["frame"]["commit_sha"] == returned
    assert [item["kind"] for item in history["transitions"]] == [
        "introduced",
        "resolved",
        "regressed",
    ]
    assert "disappeared" in history["plain_language"]["conclusion"]


def test_current_frame_alone_does_not_invent_an_introduction(repository, database):
    from anaxigraph.scanner import RepositoryScanner

    stats = RepositoryScanner(database).scan(repository)
    finding = database.findings(stats.repository_id)[0]

    history = finding_history(database, stats.repository_id, int(finding["id"]))

    assert history["status"] == "current_frame_only"
    assert history["state"] == "history_unavailable"
    assert history["introduction"]["kind"] == "already_present"
    assert "not enough indexed frames" in history["plain_language"]["conclusion"]

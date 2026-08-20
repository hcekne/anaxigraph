from __future__ import annotations

import subprocess

from anaxigraph import git
from anaxigraph.history import (
    adaptive_history_limit,
    import_git_history,
    representative_revisions,
    sampled_revisions,
)
from anaxigraph.registry import load_repository_registry
from anaxigraph.scanner import RepositoryScanner


def test_lifetime_sampling_keeps_initial_and_head():
    revisions = [f"commit-{index}" for index in range(11)]

    sampled = sampled_revisions(revisions, 4)

    assert len(sampled) == 4
    assert sampled[0] == revisions[0]
    assert sampled[-1] == revisions[-1]


def test_adaptive_history_limits_follow_repository_size_budgets():
    assert adaptive_history_limit(1) == 32
    assert adaptive_history_limit(500) == 32
    assert adaptive_history_limit(501) == 24
    assert adaptive_history_limit(2_001) == 16
    assert adaptive_history_limit(5_001) == 12


def test_representative_history_prioritizes_tags_and_architecture_changes(repository):
    commits = [git.revisions(repository, limit=1)[0]]
    for index in range(1, 9):
        if index == 5:
            config = repository / ".anaxigraph.yml"
            config.write_text(
                config.read_text(encoding="utf-8") + "\n# architecture checkpoint\n",
                encoding="utf-8",
            )
        else:
            path = repository / "pkg" / "util.py"
            path.write_text(
                path.read_text(encoding="utf-8") + f"\nMARKER_{index} = {index}\n",
                encoding="utf-8",
            )
        subprocess.run(["git", "-C", str(repository), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(repository), "commit", "-qm", f"Checkpoint {index}"], check=True
        )
        commits.append(git.revisions(repository, limit=1)[0])
        if index == 2:
            subprocess.run(["git", "-C", str(repository), "tag", "v0.2.0"], check=True)

    selected = representative_revisions(repository, commits, 4)
    selected_three = representative_revisions(repository, commits, 3)

    assert selected == [commits[0], commits[2], commits[5], commits[-1]]
    assert selected_three == [commits[0], commits[2], commits[-1]]


def test_history_import_uses_git_lifetime_without_duplicate_scan_frames(repository, database):
    initial = subprocess.check_output(
        ["git", "-C", str(repository), "rev-parse", "HEAD"], text=True
    ).strip()
    for index in range(1, 5):
        path = repository / "pkg" / "util.py"
        path.write_text(
            path.read_text(encoding="utf-8") + f"\nVALUE_{index} = {index}\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "-C", str(repository), "add", "pkg/util.py"], check=True)
        subprocess.run(
            ["git", "-C", str(repository), "commit", "-qm", f"Change {index}"],
            check=True,
        )
    head = subprocess.check_output(
        ["git", "-C", str(repository), "rev-parse", "HEAD"], text=True
    ).strip()
    RepositoryScanner(database).scan(repository)

    result = import_git_history(database, repository, max_snapshots=3)
    timeline = database.timeline_snapshots(1)
    with database.connect() as connection:
        snapshot_count = connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    import_git_history(database, repository, max_snapshots=3)
    with database.connect() as connection:
        repeated_count = connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]

    assert result.total_commits == 5
    assert result.selected_commits == 3
    assert len(timeline) == 3
    assert timeline[0]["commit_sha"] == initial
    assert timeline[-1]["commit_sha"] == head
    assert database.latest_snapshot(1)["id"] == result.current_snapshot_id
    assert repeated_count == snapshot_count


def test_repository_registry_resolves_relative_paths(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    third = tmp_path / "third"
    first.mkdir()
    second.mkdir()
    third.mkdir()
    registry = tmp_path / "repositories.yml"
    registry.write_text(
        """repositories:
  first:
    path: ./first
    history_snapshots: 24
  second:
    path: ./second
    history_snapshots: 0
  third:
    path: ./third
    history_snapshots: auto
""",
        encoding="utf-8",
    )

    targets = load_repository_registry(registry)

    assert [target.key for target in targets] == ["first", "second", "third"]
    assert targets[0].path == first.resolve()
    assert targets[0].history_snapshots == 24
    assert targets[1].history_snapshots == 0
    assert targets[2].history_snapshots == "auto"


def test_unborn_git_repository_scans_without_history_failure(tmp_path, database):
    repository = tmp_path / "unborn"
    repository.mkdir()
    (repository / "app.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repository)], check=True)

    stats = RepositoryScanner(database).scan(repository)
    result = import_git_history(database, repository, max_snapshots=12)

    assert stats.analyzed == 1
    assert database.latest_snapshot(stats.repository_id)["commit_sha"] == "unversioned"
    assert result.total_commits == 0
    assert result.selected_commits == 0

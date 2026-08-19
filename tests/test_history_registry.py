from __future__ import annotations

import subprocess

from anaxigraph.history import import_git_history, sampled_revisions
from anaxigraph.registry import load_repository_registry
from anaxigraph.scanner import RepositoryScanner


def test_lifetime_sampling_keeps_initial_and_head():
    revisions = [f"commit-{index}" for index in range(11)]

    sampled = sampled_revisions(revisions, 4)

    assert len(sampled) == 4
    assert sampled[0] == revisions[0]
    assert sampled[-1] == revisions[-1]


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
    first.mkdir()
    second.mkdir()
    registry = tmp_path / "repositories.yml"
    registry.write_text(
        """repositories:
  first:
    path: ./first
    history_snapshots: 24
  second:
    path: ./second
    history_snapshots: 0
""",
        encoding="utf-8",
    )

    targets = load_repository_registry(registry)

    assert [target.key for target in targets] == ["first", "second"]
    assert targets[0].path == first.resolve()
    assert targets[0].history_snapshots == 24


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

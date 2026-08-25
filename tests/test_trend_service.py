from __future__ import annotations

import subprocess
from pathlib import Path

import anaxigraph.trend_service as trends
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.trend_service import scoped_change_coupling


def _commit_changes(repository: Path, paths: list[str], marker: str) -> None:
    for relative in paths:
        path = repository / relative
        comment = "//" if path.suffix in {".js", ".ts", ".tsx"} else "#"
        path.write_text(
            path.read_text(encoding="utf-8") + f"\n{comment} {marker}\n",
            encoding="utf-8",
        )
    subprocess.run(["git", "-C", str(repository), "add", *paths], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-qm", marker],
        check=True,
    )


def test_change_coupling_distinguishes_history_clues_from_static_links(repository, database):
    _commit_changes(repository, ["pkg/core.py", "web/helper.ts"], "coordinate interface 1")
    _commit_changes(repository, ["pkg/core.py", "web/helper.ts"], "coordinate interface 2")
    _commit_changes(repository, ["pkg/core.py", "pkg/util.py"], "adjust calculation 1")
    _commit_changes(repository, ["pkg/core.py", "pkg/util.py"], "adjust calculation 2")
    stats = RepositoryScanner(database).scan(repository)

    result = scoped_change_coupling(
        database,
        stats.repository_id,
        stats.snapshot_id,
        ["pkg/core.py"],
    )

    assert result["status"] == "available"
    by_partner = {item["partner_path"]: item for item in result["items"]}
    hidden = by_partner["web/helper.ts"]
    assert hidden["shared_commits"] >= 2
    assert hidden["relationship_kind"] == "co_change_only"
    assert hidden["static_relationship_types"] == []
    assert "No direct source-code link" in hidden["plain_language"]["why_it_may_matter"]
    assert (
        "not a dependency or merge instruction"
        in hidden["plain_language"]["reason_not_to_restructure"]
    )
    direct = by_partner["pkg/util.py"]
    assert direct["relationship_kind"] == "co_change_and_static"
    assert direct["static_relationship_types"]
    assert result["work"]["candidate_pairs"] < result["work"]["changed_file_rows"]

    bounded = scoped_change_coupling(
        database,
        stats.repository_id,
        stats.snapshot_id,
        ["pkg/core.py", *(f"pkg/missing_{index}.py" for index in range(12))],
        window_commits=1_000,
        limit=1_000,
    )
    assert bounded["window_commits"] == 500
    assert len(bounded["selected_paths"]) == 8
    assert len(bounded["items"]) <= 50


def test_change_coupling_omits_one_off_shared_changes(repository, database):
    _commit_changes(repository, ["pkg/core.py"], "change core only")
    stats = RepositoryScanner(database).scan(repository)

    result = scoped_change_coupling(
        database,
        stats.repository_id,
        stats.snapshot_id,
        ["pkg/core.py"],
    )

    assert result["status"] == "no_repeated_change"
    assert result["items"] == []
    assert result["work"]["repeated_pairs"] == 0


def test_change_coupling_does_not_recommend_a_file_missing_from_the_current_map(
    repository, database
):
    retired = repository / "web" / "retired.ts"
    retired.write_text("export const retired = true;\n", encoding="utf-8")
    _commit_changes(repository, ["pkg/core.py", "web/retired.ts"], "use retired helper")
    _commit_changes(repository, ["pkg/core.py", "web/retired.ts"], "adjust retired helper")
    retired.unlink()
    subprocess.run(["git", "-C", str(repository), "add", "web/retired.ts"], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-qm", "remove retired helper"],
        check=True,
    )
    stats = RepositoryScanner(database).scan(repository)

    result = scoped_change_coupling(
        database,
        stats.repository_id,
        stats.snapshot_id,
        ["pkg/core.py"],
    )

    assert "web/retired.ts" not in {item["partner_path"] for item in result["items"]}
    assert result["work"]["repeated_pairs"] == len(result["items"])


def test_change_coupling_handles_empty_selection_and_too_little_history(repository, database):
    stats = RepositoryScanner(database).scan(repository)

    empty = scoped_change_coupling(database, stats.repository_id, stats.snapshot_id, [])
    shallow = scoped_change_coupling(
        database,
        stats.repository_id,
        stats.snapshot_id,
        ["pkg/core.py"],
    )

    assert empty["status"] == "no_selected_files"
    assert shallow["status"] == "insufficient_history"
    assert shallow["work"] == {"window_commits": 1}


def test_change_coupling_counts_only_pairs_touching_the_selected_files():
    other_files = {f"src/module_{index}.py" for index in range(1_000)}
    changes = {
        "commit-1": {"src/selected.py", *other_files},
        "commit-2": {"src/selected.py", *other_files},
    }

    pairs, work = trends._cochange_pairs(changes, {"src/selected.py"})

    assert len(pairs) == 1_000
    assert work["candidate_pairs"] == 1_000
    assert work["changed_file_rows"] == 2_002
    assert work["candidate_pairs"] < 1_000 * 999 // 2

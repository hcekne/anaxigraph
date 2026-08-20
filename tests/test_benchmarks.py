from __future__ import annotations

import json
import subprocess
from pathlib import Path

from anaxigraph.agent import agent_scope
from anaxigraph.analyzers import builtin_registry
from anaxigraph.config import load_config
from anaxigraph.history import import_git_history
from anaxigraph.languages import detect_language
from anaxigraph.storage import AnaxiIndex
from benchmarks.repository_factory import (
    DEFAULT_COMMITS,
    DEFAULT_FILE_COUNT,
    DEFAULT_SEED,
    create_history_repository,
)


def _revisions(root: Path) -> list[str]:
    return subprocess.check_output(
        ["git", "-C", str(root), "rev-list", "--reverse", "HEAD"],
        text=True,
    ).splitlines()


def test_history_fixture_is_deterministic(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"

    first_manifest = create_history_repository(first, file_count=120)
    second_manifest = create_history_repository(second, file_count=120)

    assert first_manifest == second_manifest
    assert _revisions(first) == _revisions(second)
    assert first_manifest["commits"] == 8
    assert first_manifest["final_files"] == 120
    assert first_manifest["expected_distinct_artifact_raw_versions"] == 135
    assert first_manifest["expected_distinct_artifact_structural_versions"] == 134


def test_history_fixture_has_exact_versions_and_agent_scope(tmp_path):
    repository = tmp_path / "history"
    manifest = create_history_repository(repository, file_count=120)
    database = AnaxiIndex(tmp_path / "index.db")

    result = import_git_history(database, repository, max_snapshots=8)

    with database.connect() as connection:
        snapshots = int(connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0])
        latest_files = int(
            connection.execute(
                "SELECT COUNT(*) FROM file_versions WHERE snapshot_id = ?",
                (result.current_snapshot_id,),
            ).fetchone()[0]
        )
        raw_versions = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT artifact_id, raw_hash FROM file_versions GROUP BY artifact_id, raw_hash
                )
                """
            ).fetchone()[0]
        )
        structural_versions = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT artifact_id, structural_hash FROM file_versions
                    GROUP BY artifact_id, structural_hash
                )
                """
            ).fetchone()[0]
        )
        ambiguous = int(
            connection.execute(
                "SELECT COUNT(*) FROM relationships WHERE metadata_json LIKE '%ambiguous_internal%'"
            ).fetchone()[0]
        )

    row = database.repository(repository)
    scope = agent_scope(
        database,
        repository_id=int(row["id"]),
        goal=manifest["scope_goal"],
        branch=None,
        config=load_config(repository),
    )
    primary = {item["path"] for item in scope["primary_files"]}

    assert snapshots == 8
    assert latest_files == manifest["final_files"]
    assert raw_versions == manifest["expected_distinct_artifact_raw_versions"]
    assert structural_versions == manifest["expected_distinct_artifact_structural_versions"]
    assert ambiguous >= 1
    assert len(primary.intersection(manifest["scope_expected_candidates"])) >= 6


def test_mixed_language_fixture_records_analyzer_depth():
    root = Path(__file__).parents[1] / "benchmarks" / "fixtures" / "mixed"
    expected = json.loads((root / "expected.json").read_text(encoding="utf-8"))
    registry = builtin_registry()

    actual = {}
    for path in sorted(root.iterdir()):
        if path.name == "expected.json":
            continue
        language = detect_language(path.name)
        analyzer = registry.for_language(language)
        analysis = analyzer.analyze(path.name, path.read_text(encoding="utf-8"))
        actual[path.name] = {"analyzer": analysis.analyzer, "language": language}

    assert actual == expected


def test_committed_benchmark_manifest_matches_generator_contract():
    root = Path(__file__).parents[1] / "benchmarks"
    expected = json.loads((root / "expected-manifest.json").read_text(encoding="utf-8"))
    history = expected["synthetic_history"]

    assert expected["generator_schema_version"] == 1
    assert expected["seed"] == DEFAULT_SEED
    assert history["commits"] == DEFAULT_COMMITS
    assert history["initial_files"] == DEFAULT_FILE_COUNT
    assert history["final_files"] == DEFAULT_FILE_COUNT
    assert history["expected_distinct_artifact_raw_versions"] == 3_217
    assert history["expected_distinct_artifact_structural_versions"] == 3_216

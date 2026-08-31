from __future__ import annotations

import json
import subprocess
from pathlib import Path

from anaxigraph.analyzers import builtin_registry
from anaxigraph.config import load_config
from anaxigraph.history import import_git_history
from anaxigraph.languages import detect_language
from anaxigraph.persistence import snapshot_files
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.storage import AnaxiIndex
from benchmarks.dashboard_fixture import create_dashboard_repository
from benchmarks.first_user import measure_first_user_path
from benchmarks.repository_factory import (
    DEFAULT_COMMITS,
    DEFAULT_FILE_COUNT,
    DEFAULT_SEED,
    create_history_repository,
)
from benchmarks.runtime_metrics import api_metrics, scope_metrics


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
        latest_files = len(snapshot_files(connection, result.current_snapshot_id))
        raw_versions = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT artifact_id, raw_hash FROM file_facts GROUP BY artifact_id, raw_hash
                )
                """
            ).fetchone()[0]
        )
        structural_versions = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT artifact_id, structural_hash FROM file_facts
                    GROUP BY artifact_id, structural_hash
                )
                """
            ).fetchone()[0]
        )
        ambiguous = int(
            connection.execute(
                """SELECT COUNT(*) FROM relationship_edges
                   WHERE metadata_json LIKE '%ambiguous_internal%'"""
            ).fetchone()[0]
        )
        file_facts = int(connection.execute("SELECT COUNT(*) FROM file_facts").fetchone()[0])
        file_deltas = int(
            connection.execute("SELECT COUNT(*) FROM snapshot_file_changes").fetchone()[0]
        )
        relationship_sets = int(
            connection.execute("SELECT COUNT(*) FROM relationship_sets").fetchone()[0]
        )
        relationship_edges = int(
            connection.execute("SELECT COUNT(*) FROM relationship_edges").fetchone()[0]
        )
        compatibility_tables = {
            row["name"]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        } & {"file_versions", "symbols", "relationships", "group_memberships"}

    scope = scope_metrics(
        database,
        repository,
        manifest["scope_goal"],
        manifest["scope_expected_candidates"],
    )
    primary = set(scope["primary_files"])
    graph_metrics = api_metrics(database, repository)

    assert snapshots == 8
    assert latest_files == manifest["final_files"]
    assert raw_versions == manifest["expected_distinct_artifact_raw_versions"]
    assert structural_versions == manifest["expected_distinct_artifact_structural_versions"]
    assert file_facts == manifest["expected_distinct_artifact_raw_versions"]
    assert file_deltas < snapshots * latest_files
    assert 0 < relationship_sets < relationship_edges
    assert compatibility_tables == set()
    assert ambiguous >= 1
    assert len(primary.intersection(manifest["scope_expected_candidates"])) >= 6
    assert scope["payload_bytes"] == scope["payload_budget"]["estimated_bytes"]
    assert scope["architecture_decision"]["rescan_included"] is True
    assert set(graph_metrics["temporal_reads"]) == {"current", "oldest", "middle"}
    for measurement in graph_metrics["temporal_reads"].values():
        assert measurement["reconstruction"]["files"]["traversed_deltas"] < 16
        assert measurement["reconstruction"]["relationships"]["traversed_deltas"] < 16


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


def test_dashboard_fixture_covers_stable_browser_contracts(tmp_path):
    repository = create_dashboard_repository(tmp_path / "dashboard")
    database = AnaxiIndex(tmp_path / "dashboard.db")

    stats = RepositoryScanner(database).scan(repository)
    overview = database.overview(stats.repository_id)
    modules = database.modules(stats.repository_id)
    findings = database.findings(stats.repository_id)

    groups = {item["name"]: item for item in overview["group_hierarchies"]["current"]}
    assert len(groups) > 5
    assert {item["name"] for item in groups["frontend"]["children"]} == {
        "frontend-features",
        "frontend-lib",
        "frontend-shell",
    }
    assert "testing" in groups
    assert overview["coverage"]["line_coverage"] is None
    assert load_config(repository).coverage_required is False
    assert overview["graph_quality"]["fallback_files"] >= 1
    assert len(findings) > 10
    feedback = next(item for item in modules if item["path"] == "docs/feedback-log.md")
    assert feedback["evaluation"]["monitored_by_default"] is False


def test_first_user_path_reaches_dashboard_and_submits_a_dossier():
    report = measure_first_user_path(Path(__file__).resolve().parents[1], runs=1)

    assert report["median_dashboard_seconds"] < report["budgets"]["dashboard_seconds"]
    assert report["median_first_dossier_seconds"] < report["budgets"]["first_dossier_seconds"]
    assert report["runs"][0]["submission_status"] == "completed"
    assert report["runs"][0]["project_connection_created"] is True

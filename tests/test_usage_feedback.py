"""Development journeys behind the October usage feedback."""

from __future__ import annotations

import json
import subprocess

import pytest
from starlette.testclient import TestClient

from anaxigraph.agent import architecture_guidance, impact_analysis
from anaxigraph.agent_response import small_agent_response
from anaxigraph.api import create_app
from anaxigraph.architecture_reassessment import architecture_reassessment
from anaxigraph.config import load_config
from anaxigraph.registry import RepositoryTarget
from anaxigraph.registry_worktrees import expand_worktree_targets
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_service import discover_semantic_service
from anaxigraph.service_checkout import matching_checkouts
from anaxigraph.understanding import SemanticEngine


def test_service_discovers_and_indexes_new_linked_worktree(repository, database, monkeypatch):
    first = RepositoryScanner(database).scan(repository)
    target = RepositoryTarget("sample", repository)
    assert len(expand_worktree_targets((target,))) == 1
    with TestClient(
        create_app(database=database, repository=repository, enable_mcp=False)
    ) as client:
        worktree = repository.parent / "feature-checkout"
        subprocess.run(
            ["git", "-C", str(repository), "worktree", "add", "-b", "feature-test", str(worktree)],
            check=True,
            capture_output=True,
        )
        assert worktree in {item.path for item in expand_worktree_targets((target,))}
        (worktree / "pkg" / "feature.py").write_text("FEATURE = True\n")

        def request(url, *, method="GET", **_kwargs):
            response = client.request(method, url.removeprefix("http://testserver"))
            if response.status_code >= 400:
                raise ValueError(f"HTTP {response.status_code}: {response.text}")
            return response.json()

        monkeypatch.setattr("anaxigraph.semantic_service._request_json", request)
        selected = discover_semantic_service(worktree, explicit_url="http://testserver")
        assert selected.repository_id != first.repository_id
        assert selected.repository_path == selected.requested_checkout == str(worktree)
        rows = client.get("/api/repositories").json()
        row = next(row for row in rows if row["id"] == selected.repository_id)
        assert row["scannable"]
        assert row["map_status"]["checkout"]["branch"] == "feature-test"
        assert row["map_status"]["checkout"]["is_worktree"]
        modules = client.get(
            "/api/modules", params={"repository_id": selected.repository_id}
        ).json()
        assert "pkg/feature.py" in {item["path"] for item in modules}
        rejected = client.post("/api/scan", params={"repository_path": str(repository.parent)})
        assert rejected.status_code == 403


def test_same_remote_does_not_select_a_different_checkout(repository, database):
    RepositoryScanner(database).scan(repository)
    other = repository.parent / "clone"
    subprocess.run(["git", "clone", "-q", str(repository), str(other)], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "remote", "add", "origin", str(repository)], check=True
    )
    assert matching_checkouts(other, database.repositories()) == []


def test_coherent_change_uses_existing_owner_dependencies_tests_and_pinned_baseline(
    repository, database
):
    (repository / "docs" / "calculator.md").write_text("# Calculator calculation behavior\n" * 50)
    first = RepositoryScanner(database).scan(repository)
    config = load_config(repository)
    guide = architecture_guidance(
        database,
        repository_id=first.repository_id,
        config=config,
        goal="Change Calculator calculation behavior; keep arithmetic in the existing domain service",
        details=True,
    )
    brief = architecture_guidance(
        database,
        repository_id=first.repository_id,
        config=config,
        goal="Change Calculator calculation behavior",
    )
    assert len(json.dumps(brief, ensure_ascii=False, separators=(",", ":")).encode()) <= 8_000
    assert brief["primary_files"][0]["path"] == "pkg/core.py"
    assert "tests/test_core.py" in brief["tests"]
    assert guide["recommendation"]["starting_point"] == "pkg/core.py"
    assert all(item["artifact_type"] != "documentation" for item in guide["primary_files"])
    impact = impact_analysis(
        database, repository_id=first.repository_id, config=config, target="pkg/core.py"
    )
    assert "pkg/consumer.py" in {item["path"] for item in impact["direct_dependants"]}
    assert "tests/test_core.py" in impact["tests_relevant"]
    baseline = guide["agent_journey"]["after_change"][1]["arguments"]["from_snapshot_id"]
    assert baseline == first.snapshot_id
    path = repository / "pkg" / "core.py"
    path.write_text(
        path.read_text().replace("return double(value)", "return double(max(0, value))")
    )
    second = RepositoryScanner(database).scan(repository)
    path.write_text(path.read_text().replace("max(0, value)", "max(1, value)"))
    third = RepositoryScanner(database).scan(repository)
    verdict = architecture_reassessment(
        database, repository_id=first.repository_id, config=config, from_snapshot_id=baseline
    )
    assert verdict["baseline_snapshot"]["id"] == first.snapshot_id
    assert verdict["target_snapshot"]["id"] == third.snapshot_id
    assert verdict["baseline_selection"] == "requested"
    assert verdict["comparison"]["baseline"]["checkout_path"] == str(repository)
    historical = architecture_reassessment(
        database,
        repository_id=first.repository_id,
        config=config,
        from_snapshot_id=baseline,
        target_snapshot_id=second.snapshot_id,
    )
    assert historical["semantic_refresh"]["snapshot_id"] == second.snapshot_id
    with pytest.raises(ValueError, match="precede"):
        architecture_reassessment(
            database,
            repository_id=first.repository_id,
            config=config,
            from_snapshot_id=third.snapshot_id,
            target_snapshot_id=second.snapshot_id,
        )


def test_measurements_are_supporting_changes_and_freshness_is_independent(repository, database):
    first = RepositoryScanner(database).scan(repository)
    benchmark = repository / "benchmarks"
    benchmark.mkdir()
    (benchmark / "timings.json").write_text(json.dumps({"elapsed_ms": 12}))
    second = RepositoryScanner(database).scan(repository)
    value = architecture_reassessment(
        database,
        repository_id=first.repository_id,
        config=load_config(repository),
        from_snapshot_id=first.snapshot_id,
    )
    module = next(
        item
        for item in value["observed_change"]["modules"]
        if item["path"] == "benchmarks/timings.json"
    )
    assert module["after"]["artifact_type"] == "measurement"
    effects = [
        item
        for item in value["architectural_effects"]
        if item["subject"] == "benchmarks/timings.json"
    ]
    assert effects and all(item["classification"] == "supporting_change" for item in effects)
    assert all("caller" not in item["smallest_safe_follow_up"].lower() for item in effects)
    status = SemanticEngine(database).status(first.repository_id, load_config(repository).semantic)
    freshness = status["analysis_freshness"]
    assert freshness["structural"]["snapshot_id"] == second.snapshot_id
    assert freshness["ai_mapping"]["current"] is False
    assert freshness["patterns"]["current"] is False
    assert freshness["fresh_eyes"]["current"] is False


def test_large_agent_journey_preserves_recommendations_within_default_budget():
    payload = {
        "repository_id": 1,
        "snapshot_id": 9,
        "map_status": {"checkout": {"path": "/repo/feature", "commit_sha": "abc"}},
        "recommendations": [
            {
                "title": f"Recommendation {index}",
                "explanation": "Long explanation. " * 1000,
                "evidence": ["source.py " * 1000] * 30,
            }
            for index in range(80)
        ],
    }
    value = small_agent_response(payload)
    assert len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()) <= 8000
    assert value["recommendations"][0]["title"] == "Recommendation 0"
    assert value["map_status"] == payload["map_status"]
    assert value["response_budget"]["omitted_collections"]["recommendations"]["total"] == 80
    assert len(payload["recommendations"]) == 80
    effects = small_agent_response(
        {
            "architectural_effects": [{"subject": f"file-{index}"} for index in range(40)],
            "counts": {"total": 60, "returned": 40, "omitted": 20},
        }
    )
    assert effects["counts"]["returned"] == len(effects["architectural_effects"]) == 5
    assert effects["counts"]["omitted"] == 55


def test_compact_inventory_keeps_counts_and_file_details_available(repository, database):
    RepositoryScanner(database).scan(repository)
    with TestClient(
        create_app(database=database, repository=repository, enable_mcp=False)
    ) as client:
        compact = client.get("/api/modules", params={"compact": True}).json()
        full = client.get("/api/modules").json()
        assert [item["path"] for item in compact] == [item["path"] for item in full]
        assert len(json.dumps(compact)) < len(json.dumps(full))
        assert all(item["details_available"] for item in compact)
        detail = client.get("/api/file", params={"path": compact[0]["path"]}).json()
        assert detail["file"]["responsibilities"]

from __future__ import annotations

import json

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from semantic_support import _calls, _fake_provider, _semantic_config

from anaxigraph.api import create_app
from anaxigraph.architecture_reassessment import architecture_reassessment
from anaxigraph.cli import main
from anaxigraph.config import load_config
from anaxigraph.mcp_server import create_anaxi_mcp_server
from anaxigraph.reassessment_advice import reassessment_advice
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.understanding import SemanticEngine


def _replace_core(repository, body: str) -> None:
    (repository / "pkg" / "core.py").write_text(body, encoding="utf-8")


def _complex_core() -> str:
    return (
        '"""Public calculation service."""\n\n'
        "from .util import double\n\n"
        "class Calculator:\n"
        "    def calculate(self, value: int) -> int:\n"
        "        if value < 0:\n"
        "            return 0\n"
        "        if value == 0:\n"
        "            return 1\n"
        "        return double(value)\n"
    )


def _simple_core() -> str:
    return (
        '"""Public calculation service."""\n\n'
        "from .util import double\n\n"
        "class Calculator:\n"
        "    def calculate(self, value: int) -> int:\n"
        "        return double(max(0, value))\n"
    )


def test_reassessment_bounds_one_module_change_and_explains_regression(repository, database):
    first = RepositoryScanner(database).scan(repository)
    _replace_core(repository, _complex_core())
    second = RepositoryScanner(database).scan(repository, run_type="update")

    value = architecture_reassessment(
        database,
        repository_id=second.repository_id,
        config=load_config(repository),
    )

    assert value["contract_version"] == "architecture-reassessment-v1"
    assert value["baseline_snapshot"]["id"] == first.snapshot_id
    assert value["target_snapshot"]["id"] == second.snapshot_id
    assert [item["path"] for item in value["observed_change"]["modules"]] == ["pkg/core.py"]
    affected = value["observed_change"]["affected_context"]
    assert "pkg/consumer.py" in affected["dependants"]
    assert "tests/test_core.py" in affected["dependants"]
    complexity = next(
        item for item in value["architectural_effects"] if item["category"] == "complexity"
    )
    assert complexity["classification"] == "worsened"
    assert complexity["counter_evidence"]
    assert complexity["reasons_to_leave_alone"]
    assert complexity["smallest_safe_follow_up"]
    assert complexity["verification"]
    assert value["safety"]["decision_or_approval_state_created"] is False
    assert value["semantic_refresh"]["full_repository_rerun_required"] is False


def test_reassessment_explains_improvement_and_coherent_no_change(repository, database):
    RepositoryScanner(database).scan(repository)
    _replace_core(repository, _complex_core())
    harmful = RepositoryScanner(database).scan(repository, run_type="update")
    _replace_core(repository, _simple_core())
    improved = RepositoryScanner(database).scan(repository, run_type="update")

    value = architecture_reassessment(
        database,
        repository_id=improved.repository_id,
        config=load_config(repository),
    )
    complexity = next(
        item for item in value["architectural_effects"] if item["category"] == "complexity"
    )
    assert complexity["classification"] == "improved"
    assert "Retain" in complexity["recommendation"]

    unchanged = architecture_reassessment(
        database,
        repository_id=improved.repository_id,
        config=load_config(repository),
        from_snapshot_id=improved.snapshot_id,
    )
    assert unchanged["state"] == "no_architectural_change"
    assert unchanged["recommendations"][0]["classification"] == "coherent_no_change"
    assert harmful.snapshot_id == value["baseline_snapshot"]["id"]


def test_reassessment_ignores_dependency_source_line_churn(repository, database):
    RepositoryScanner(database).scan(repository)
    core = repository / "pkg" / "core.py"
    core.write_text(
        "# Formatting-only line shift.\n" + core.read_text(encoding="utf-8"), encoding="utf-8"
    )
    changed = RepositoryScanner(database).scan(repository, run_type="update")

    value = architecture_reassessment(
        database,
        repository_id=changed.repository_id,
        config=load_config(repository),
    )

    assert value["observed_change"]["relationships"]["counts"] == {
        "added": 0,
        "removed": 0,
        "returned": 0,
        "omitted": 0,
    }
    assert not {item["category"] for item in value["architectural_effects"]} & {
        "dependencies",
        "boundary_coherence",
    }


def test_reassessment_calibrates_pattern_duplication_boundary_and_dead_code_advice():
    semantic = {
        "status": "current",
        "confidence": 0.72,
        "summary": "Routes requests to two similar adapters.",
        "architecture_role": "Provider routing",
        "responsibilities": ["Route provider requests"],
        "consolidation_assessment": {
            "recommendation": "merge",
            "score": 76,
            "rationale": "Two adapters repeat the same routing responsibility.",
            "evidence": ["Both expose the same request contract."],
            "counter_evidence": ["Provider error semantics may remain different."],
        },
        "dead_code_candidates": [
            {
                "path_or_symbol": "src/router.py:legacy_route",
                "reason": "No indexed caller reaches the legacy route.",
                "counter_evidence": ["Runtime plugin registration was not observed."],
            }
        ],
        "risks": [],
    }
    evidence = {
        "module_changes": [
            {
                "path": "src/router.py",
                "change": "changed",
                "changed_fields": ["structural_hash"],
                "before": {"semantic": {}, "complexity": 4, "group": "application"},
                "after": {"semantic": semantic, "complexity": 4, "group": "application"},
            }
        ],
        "relationship_changes": {"added": [], "removed": [], "counts": {}},
        "finding_changes": [
            {
                "stable_key": "boundary:router",
                "finding_type": "architecture_violation",
                "transition": "introduced",
                "confidence": 0.9,
                "summary": "Provider routing now crosses a forbidden boundary.",
                "explanation": "The dependency direction contradicts the configured boundary.",
                "recommended_action": "Inspect the boundary and move the smallest responsibility.",
                "affected_artifacts": ["src/router.py"],
                "evidence": ["src/router.py imports infrastructure/client.py"],
                "status": "new",
            }
        ],
        "semantic_scopes": {"states": []},
    }
    patterns = [
        {
            "target": {"key": "module:src/router.py", "path": "src/router.py"},
            "pattern": {"key": "adapter", "name": "Adapter"},
            "recommendation": "introduce",
            "summary": "A reviewed Adapter may isolate provider-specific behavior.",
            "rationale": "The repeated provider boundary has one stable contract.",
            "scores": {"opportunity": 74},
            "details": {
                "evidence": ["Both providers expose the same request shape."],
                "counter_evidence": ["The providers may diverge soon."],
            },
        }
    ]

    result = reassessment_advice(
        evidence,
        patterns=patterns,
        change_coupling={"status": "available", "items": []},
    )

    effects = {item["category"]: item for item in result["effects"]}
    categories = (
        "boundary_coherence",
        "duplication",
        "pattern_fit",
        "possible_unused_code",
    )
    assert set(categories) <= effects.keys()
    for category in categories:
        assert effects[category]["counter_evidence"]
        assert effects[category]["reasons_to_leave_alone"]
        assert effects[category]["smallest_safe_follow_up"]
        assert effects[category]["verification"]


def test_incremental_refresh_keeps_charter_current_without_repo_wide_rerun(
    repository, database, tmp_path
):
    log = tmp_path / "reassessment-semantic.log"
    _semantic_config(repository, _fake_provider(tmp_path), log)
    config = load_config(repository)
    first = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    assert engine.bootstrap(first.repository_id, repository, config)["semantic"][
        "semantically_ready"
    ]
    baseline_calls = len(_calls(log))

    core = repository / "pkg" / "core.py"
    core.write_text(
        core.read_text(encoding="utf-8").replace(
            "return double(value)", "return double(value) + 1"
        ),
        encoding="utf-8",
    )
    changed = RepositoryScanner(database).scan(repository, run_type="update")
    engine.bootstrap(changed.repository_id, repository, config, plan_only=True)
    pending = architecture_reassessment(
        database,
        repository_id=changed.repository_id,
        config=config,
    )
    assert pending["state"] == "semantic_refresh_pending"
    assert pending["semantic_refresh"]["changed_modules"] == ["pkg/core.py"]
    assert "pkg/consumer.py" in pending["semantic_refresh"]["affected_modules"]
    assert pending["semantic_refresh"]["full_repository_rerun_required"] is False

    refreshed = engine.bootstrap(changed.repository_id, repository, config)
    assert refreshed["semantic"]["semantically_ready"] is True
    current = architecture_reassessment(
        database,
        repository_id=changed.repository_id,
        config=config,
    )
    assert current["state"] == "current"
    assert current["architecture_charter"]["state"] == "current"
    new_calls = _calls(log)[baseline_calls:]
    assert new_calls[0] == {"path": "pkg/core.py", "kind": "intrinsic"}
    assert {item["kind"] for item in new_calls[1:]} == {
        "pattern_assessment",
        "pattern_review",
    }
    assert not {"context", "synthesis", "taxonomy_proposal", "taxonomy_review"} & {
        item["kind"] for item in new_calls
    }


def test_cli_reads_the_same_saved_reassessment(repository, database, capsys):
    first = RepositoryScanner(database).scan(repository)
    _replace_core(repository, _complex_core())
    second = RepositoryScanner(database).scan(repository, run_type="update")

    main(
        [
            "reassess",
            str(repository),
            "--db",
            str(database.path),
            "--from-snapshot",
            str(first.snapshot_id),
            "--json",
        ]
    )
    value = json.loads(capsys.readouterr().out)

    assert value["target_snapshot"]["id"] == second.snapshot_id
    assert value["observed_change"]["modules"][0]["path"] == "pkg/core.py"
    assert value["safety"]["automatic_code_changes"] is False


@pytest.mark.anyio
async def test_rest_and_existing_mcp_guide_share_reassessment_contract(repository, database):
    first = RepositoryScanner(database).scan(repository)
    _replace_core(repository, _complex_core())
    RepositoryScanner(database).scan(repository, run_type="update")
    app = create_app(database=database, repository=repository, enable_mcp=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            "/api/reassessment", params={"from_snapshot_id": first.snapshot_id}
        )
        assert response.status_code == 200
        rest = response.json()

    server = create_anaxi_mcp_server(
        database=database,
        repository=repository,
        config_path=None,
        allowed_hosts=["testserver"],
    )
    mcp_app = server.streamable_http_app()
    async with server.session_manager.run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=mcp_app),
            base_url="http://testserver",
            timeout=5,
        ) as http_client:
            async with streamable_http_client(
                "http://testserver/mcp",
                http_client=http_client,
                terminate_on_close=False,
            ) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    response = await session.call_tool(
                        "ANAXIGRAPH_GUIDE",
                        arguments={"reassess": True, "from_snapshot_id": first.snapshot_id},
                    )
                    assert response.isError is False
                    mcp = response.structuredContent

    for field in (
        "identity",
        "state",
        "observed_change",
        "architectural_effects",
        "recommendations",
        "architecture_charter",
        "safety",
    ):
        assert mcp[field] == rest[field]

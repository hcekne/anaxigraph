"""Default impact responses stay small even when dependencies have large AI dossiers."""

import json
from dataclasses import replace

import httpx
import pytest

from anaxigraph import agent_graph
from anaxigraph.agent import impact_analysis
from anaxigraph.agent_impact import _ImpactGraph
from anaxigraph.api import create_app
from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner


def test_impact_defaults_to_small_lists_with_honest_totals_and_opt_in_details(
    repository, database, monkeypatch
):
    for index in range(40):
        (repository / "pkg" / f"client_{index}.py").write_text("from pkg.core import Calculator\n")
    stats = RepositoryScanner(database).scan(repository)
    original = agent_graph._projected_graph_maps

    def described(*args):
        files, outgoing, incoming = original(*args)
        for item in files.values():
            item["summary"] = "A long saved explanation. " * 500
            item["semantic"] = {"risks": ["A detailed interpretation. " * 500]}
        return files, outgoing, incoming

    monkeypatch.setattr(agent_graph, "_projected_graph_maps", described)
    arguments = dict(
        database=database,
        repository_id=stats.repository_id,
        target="pkg/core.py",
        config=load_config(repository),
    )
    compact = impact_analysis(**arguments)
    detailed = impact_analysis(**arguments, details=True)
    compact_bytes = len(json.dumps(compact, separators=(",", ":")).encode())
    full_bytes = len(json.dumps(detailed, separators=(",", ":")).encode())
    assert compact_bytes < 8_000
    assert full_bytes > 100_000
    assert compact["metrics"] == detailed["metrics"]
    assert len(compact["direct_dependants"]) == 5
    assert compact["result_counts"]["direct_dependants"] == {
        "total": len(detailed["direct_dependants"]),
        "shown": 5,
    }
    assert "semantic" not in compact["direct_dependants"][0]
    assert "semantic" in detailed["direct_dependants"][0]
    assert compact["next_action"]["arguments"]["details"] is True
    assert compact["telemetry"]["payload_bytes"] == compact_bytes
    config = arguments["config"]
    smaller = impact_analysis(
        **{
            **arguments,
            "config": replace(config, agent=replace(config.agent, payload_limit_bytes=4_000)),
        }
    )
    assert smaller["telemetry"]["payload_bytes"] < 4_000
    assert smaller["metrics"] == detailed["metrics"]
    assert all(
        counts["shown"] == len(smaller[key]) for key, counts in smaller["result_counts"].items()
    )


def test_impact_counts_the_whole_dependency_chain(repository, database, monkeypatch):
    files = {
        index: {
            "path": f"src/file_{index}.py",
            "artifact_type": "source",
            "language": "python",
            "summary": "Source module",
            "lines_of_code": 1,
            "complexity": 1,
            "declared_group": "source",
            "inferred_group": "source",
        }
        for index in range(601)
    }
    incoming = {index: {index + 1} if index < 600 else set() for index in files}
    outgoing = {index: {index - 1} if index else set() for index in files}
    graph = _ImpactGraph(1, {}, files, outgoing, incoming, 0)
    monkeypatch.setattr("anaxigraph.agent_impact._impact_graph", lambda *args: graph)
    result = impact_analysis(
        database, repository_id=1, target=files[0]["path"], config=load_config(repository)
    )
    assert result["transitive_dependant_count"] == result["metrics"]["transitive_dependants"] == 600


@pytest.mark.anyio
async def test_http_impact_accepts_explicit_details(repository, database):
    RepositoryScanner(database).scan(repository)
    app = create_app(database=database, repository=repository, enable_mcp=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        compact = (await client.post("/api/impact", json={"target": "pkg/core.py"})).json()
        full = (
            await client.post("/api/impact", json={"target": "pkg/core.py", "details": True})
        ).json()
    assert compact["details_available"]
    assert "result_counts" not in full
    assert compact["metrics"] == full["metrics"]

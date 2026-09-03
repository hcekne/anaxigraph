from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from semantic_support import _agent_dossier, _enable_agent_semantics

from anaxigraph.api import create_app
from anaxigraph.cli import main
from anaxigraph.config import load_config
from anaxigraph.mcp_core import _journey_result
from anaxigraph.mcp_server import create_anaxi_mcp_server
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.understanding import SemanticEngine


def _complete_queue(engine, repository_id, repository, config) -> None:
    for index in range(500):
        packet = engine.claim_agent_work(
            repository_id,
            repository,
            config,
            agent_id=f"transport-{index}",
            agent_model="fixture-model",
        )
        if packet["status"] == "complete":
            return
        engine.submit_agent_work(
            repository_id,
            repository,
            config,
            job_id=packet["job"]["id"],
            lease_token=packet["lease"]["token"],
            dossier=_agent_dossier(packet["analysis_request"]),
        )
    raise AssertionError("Semantic queue did not converge")


def _prepare_completed_review(repository, database):
    _enable_agent_semantics(repository)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    _complete_queue(engine, stats.repository_id, repository, config)
    engine.start_fresh_eyes_review(stats.repository_id, repository, config)
    _complete_queue(engine, stats.repository_id, repository, config)
    return engine, stats.repository_id, config


async def _rest_fresh_eyes(database, repository, query: str = "") -> dict[str, Any]:
    app = create_app(database=database, repository=repository, enable_mcp=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        return (await client.get(f"/api/fresh-eyes{query}")).json()


async def _rest_status(database, repository, query: str) -> tuple[int, dict[str, Any]]:
    app = create_app(database=database, repository=repository, enable_mcp=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(f"/api/fresh-eyes{query}")
        return response.status_code, response.json()


async def _mcp_guide(database, repository, arguments: dict[str, Any]) -> Any:
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
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    return await session.call_tool("ANAXIGRAPH_GUIDE", arguments=arguments)


def _cli_fresh_eyes(repository, database, capsys, *flags: str) -> dict[str, Any]:
    main(["fresh-eyes", str(repository), "--db", str(database.path), "--json", *flags])
    return json.loads(capsys.readouterr().out)


def _review_facts(review: dict[str, Any]) -> dict[str, Any]:
    return {
        "generation": review["review_generation"],
        "identity": review["identity"],
        "state": review["state"],
        "declared_context": review.get("declared_context"),
        "stages": [(item["key"], item["state"], item["document_id"]) for item in review["stages"]],
    }


def _document_ids(review: dict[str, Any]) -> set[int]:
    return {item["document_id"] for item in review["stages"]}


@pytest.mark.anyio
async def test_dashboard_cli_contract_and_mcp_share_one_fresh_eyes_result(repository, database):
    _prepare_completed_review(repository, database)
    rest = await _rest_fresh_eyes(database, repository)
    response = await _mcp_guide(database, repository, {"fresh_eyes": True})
    assert response.isError is False
    mcp = response.structuredContent

    for field in (
        "identity",
        "state",
        "snapshot",
        "fingerprints",
        "declared_context",
        "recommendations",
        "caveats",
    ):
        assert mcp[field] == rest[field]
    assert rest["state"] == "current"
    assert rest["snapshot"]["dirty"] is True
    assert "dirty checkout" in rest["caveats"][0]
    assert rest["recommendations"][0]["action"] == "consolidate"


@pytest.mark.anyio
async def test_mcp_restart_and_cli_restart_produce_the_same_review_generation(
    repository, database, capsys
):
    engine, repository_id, config = _prepare_completed_review(repository, database)
    first = engine.fresh_eyes_status(repository_id, config.semantic)

    response = await _mcp_guide(
        database, repository, {"intent": "redesign", "start": True, "restart": True}
    )
    assert response.isError is False
    mcp_restart = response.structuredContent
    assert mcp_restart["status"] == "restarted"
    assert mcp_restart["agent_journey"]["next_action"]["arguments"] == {"intent": "redesign"}
    cli_view = _cli_fresh_eyes(repository, database, capsys)
    assert _review_facts(mcp_restart["review"]) == _review_facts(cli_view)
    assert cli_view["review_generation"] == 2
    assert cli_view["state"] == "in_progress"
    _complete_queue(engine, repository_id, repository, config)
    second = engine.fresh_eyes_status(repository_id, config.semantic)

    cli_restart = _cli_fresh_eyes(repository, database, capsys, "--restart")
    assert cli_restart["status"] == "restarted"
    response = await _mcp_guide(database, repository, {"intent": "redesign"})
    assert response.isError is False
    mcp_view = response.structuredContent
    assert _review_facts(cli_restart["review"]) == _review_facts(mcp_view)
    assert mcp_view["review_generation"] == 3
    assert mcp_view["agent_journey"]["next_action"]["arguments"] == {"intent": "redesign"}

    refused = await _mcp_guide(database, repository, {"intent": "redesign", "restart": True})
    assert refused.isError is True
    assert "Finish or retry" in refused.content[0].text
    with pytest.raises(SystemExit) as exit_info:
        _cli_fresh_eyes(repository, database, capsys, "--restart")
    assert exit_info.value.code == 2
    assert "Finish or retry" in capsys.readouterr().err

    _complete_queue(engine, repository_id, repository, config)
    rest = await _rest_fresh_eyes(database, repository)
    response = await _mcp_guide(database, repository, {"intent": "redesign"})
    final = response.structuredContent
    assert _review_facts(final) == _review_facts(rest)
    assert rest["state"] == "current"
    assert rest["review_generation"] == 3
    generations = [_document_ids(first), _document_ids(second), _document_ids(rest)]
    assert all(generations)
    assert len(set().union(*generations)) == sum(len(ids) for ids in generations)
    next_action = final["agent_journey"]["next_action"]
    assert next_action["arguments"]["intent"] == "build"
    assert "restart=true" in next_action["reason"]


@pytest.mark.parametrize(
    ("state", "arguments"),
    [
        ("not_started", {"intent": "redesign", "start": True, "proposal_count": 2}),
        ("stale", {"intent": "redesign", "start": True, "proposal_count": 2}),
        ("failed", {"intent": "redesign", "start": True, "retry_failed": True}),
        ("waiting_for_understanding", {"intent": "redesign"}),
        ("in_progress", {"intent": "redesign"}),
        ("current", {"intent": "build", "goal": "Tidy the calculator"}),
    ],
)
def test_redesign_journey_names_the_next_guide_call_for_every_review_state(state, arguments):
    status_reply = _journey_result(
        {"state": state, "next_action": "prose for people"}, "redesign", "Tidy the calculator"
    )
    start_reply = _journey_result(
        {"status": "restarted", "review": {"state": state}}, "redesign", "Tidy the calculator"
    )
    for reply in (status_reply, start_reply):
        next_action = reply["agent_journey"]["next_action"]
        assert next_action["tool"] == "ANAXIGRAPH_GUIDE"
        assert next_action["arguments"] == arguments
        assert ("restart=true" in next_action["reason"]) is (state == "current")


@pytest.mark.anyio
async def test_rest_cli_and_mcp_agree_on_a_selected_generation(repository, database, capsys):
    engine, repository_id, config = _prepare_completed_review(repository, database)
    first = engine.fresh_eyes_status(repository_id, config.semantic)
    engine.start_fresh_eyes_review(repository_id, repository, config, restart=True)
    _complete_queue(engine, repository_id, repository, config)
    engine.start_fresh_eyes_review(repository_id, repository, config, restart=True)
    _complete_queue(engine, repository_id, repository, config)

    rest = await _rest_fresh_eyes(database, repository, "?generation=2")
    response = await _mcp_guide(database, repository, {"intent": "redesign", "generation": 2})
    assert response.isError is False
    mcp = response.structuredContent
    cli = _cli_fresh_eyes(repository, database, capsys, "--generation", "2")

    assert _review_facts(rest) == _review_facts(mcp) == _review_facts(cli)
    for field in ("identity", "state", "ready", "recommendations", "caveats", "input_manifests"):
        assert rest[field] == mcp[field] == cli[field]
    assert rest["review_generation"] == 2
    assert rest["state"] == "superseded"
    assert rest["ready"] is False
    assert _document_ids(rest).isdisjoint(_document_ids(first))
    assert [item["generation"] for item in rest["generations"]] == [1, 2, 3]
    assert mcp["agent_journey"]["next_action"]["arguments"]["intent"] == "build"
    live = await _rest_fresh_eyes(database, repository)
    assert live["review_generation"] == 3
    assert live["generations"] == rest["generations"]


@pytest.mark.anyio
async def test_unknown_generation_is_a_bad_request_naming_the_recorded_ones(repository, database):
    _prepare_completed_review(repository, database)

    status, body = await _rest_status(database, repository, "?generation=99")

    assert status == 400
    assert "available generations: 1" in body["detail"]
    zero_status, _ = await _rest_status(database, repository, "?generation=0")
    assert zero_status == 422

from __future__ import annotations

import os
from types import SimpleNamespace

import httpx
import pytest
import yaml
from semantic_support import _agent_dossier

import anaxigraph.semantic_remote_worker as remote_worker
from anaxigraph.config import SemanticConfig, load_config
from anaxigraph.mcp_server import create_anaxi_mcp_server
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic import SemanticResult
from anaxigraph.semantic_agent_protocol import (
    packetize_agent_request,
    rehydrate_agent_request,
)
from anaxigraph.semantic_service import (
    SemanticServiceTarget,
    discover_semantic_service,
    prepare_semantic_service,
)


def test_service_discovery_matches_git_identity_across_container_paths(repository, monkeypatch):
    monkeypatch.setattr(
        "anaxigraph.semantic_service.git.metadata",
        lambda _root: SimpleNamespace(remote_url="git@github.com:Example/Project.git"),
    )
    monkeypatch.setattr(
        "anaxigraph.semantic_service._request_json",
        lambda *_args, **_kwargs: [
            {
                "id": 7,
                "name": "Project",
                "path": "/repo",
                "remote_url": "https://github.com/example/project.git",
                "config_authority": {
                    "registry_key": "project",
                    "service_config_path": "/repo/.anaxigraph.yml",
                    "sha256": "abc123",
                },
                "semantic_policy": {
                    "enabled": True,
                    "provider": "agent",
                    "max_parallel_jobs": 9,
                },
            }
        ],
    )

    target = discover_semantic_service(repository, explicit_url="http://127.0.0.1:9999")

    assert target == SemanticServiceTarget(
        base_url="http://127.0.0.1:9999",
        repository_id=7,
        repository_name="Project",
        repository_path="/repo",
        config_authority={
            "registry_key": "project",
            "service_config_path": "/repo/.anaxigraph.yml",
            "sha256": "abc123",
        },
        semantic_policy={
            "enabled": True,
            "provider": "agent",
            "max_parallel_jobs": 9,
        },
    )
    assert target.mcp_url == "http://127.0.0.1:9999/mcp"
    assert target.semantic_config().max_parallel_jobs == 9


def test_explicit_service_fails_when_it_indexes_another_repository(repository, monkeypatch):
    monkeypatch.setattr(
        "anaxigraph.semantic_service.git.metadata",
        lambda _root: SimpleNamespace(remote_url="git@github.com:Example/Project.git"),
    )
    monkeypatch.setattr(
        "anaxigraph.semantic_service._request_json",
        lambda *_args, **_kwargs: [
            {
                "id": 8,
                "name": "Different",
                "path": "/different",
                "remote_url": "git@github.com:example/different.git",
            }
        ],
    )

    with pytest.raises(ValueError, match="does not index"):
        discover_semantic_service(repository, explicit_url="http://127.0.0.1:9999")


def test_default_service_falls_back_only_on_connection_refusal(repository, monkeypatch):
    monkeypatch.setattr(
        "anaxigraph.semantic_service._request_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionRefusedError("refused")),
    )

    assert discover_semantic_service(repository) is None


def test_default_service_timeout_refuses_local_index_fallback(repository, monkeypatch):
    sleeps = []
    monkeypatch.setattr(
        "anaxigraph.semantic_service._request_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("timed out")),
    )
    monkeypatch.setattr("anaxigraph.semantic_service.time.sleep", sleeps.append)

    with pytest.raises(ValueError, match="refusing local-index fallback"):
        discover_semantic_service(repository)

    assert sleeps == [0.1, 0.2]


def test_service_preparation_is_lightweight_and_targets_one_index(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "anaxigraph.semantic_service._request_json",
        lambda url, **options: calls.append((url, options)) or {"status": "prepared"},
    )
    target = SemanticServiceTarget("http://127.0.0.1:8765", 4, "Example", "/repo")

    assert prepare_semantic_service(target, force=True, retry_failed=True) == {"status": "prepared"}
    assert "/api/semantic/prepare?" in calls[0][0]
    assert "repository_id=4" in calls[0][0]
    assert "force=true" in calls[0][0]
    assert "retry_failed=true" in calls[0][0]
    assert "wait=true" not in calls[0][0]
    assert calls[0][1]["method"] == "POST"


def test_service_preparation_retries_transient_writer_contention(monkeypatch):
    responses = iter(
        [
            ValueError("AnaxiGraph service returned HTTP 500: Internal Server Error"),
            {"status": "prepared"},
        ]
    )
    sleeps = []

    def request(*_args, **_kwargs):
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr("anaxigraph.semantic_service._request_json", request)
    monkeypatch.setattr("anaxigraph.semantic_service.time.sleep", sleeps.append)
    target = SemanticServiceTarget("http://127.0.0.1:8765", 1, "Example", "/repo")

    assert prepare_semantic_service(target, force=False, retry_failed=False) == {
        "status": "prepared"
    }
    assert sleeps == [0.25]


def test_agent_evidence_pages_reassemble_source_without_changing_bytes():
    source = "".join(f"value_{index} = {index}\n" for index in range(1_000))
    request = {
        "contract": "Return one dossier.",
        "schema_version": "test",
        "analysis_kind": "intrinsic",
        "path": "large.py",
        "deterministic_facts": {"symbols": []},
        "source": source,
    }
    bounded, manifest, pages = packetize_agent_request(
        request, SemanticConfig(max_source_chars=4_000)
    )

    assert manifest is not None
    assembled = rehydrate_agent_request(bounded, pages)
    assert assembled == request


def test_agent_evidence_pages_reassemble_taxonomy_memberships():
    members = [
        {
            "path": f"src/module_{index}.py",
            "confidence": 0.9,
            "rationale": "same responsibility " * 20,
            "evidence": ["module evidence"],
            "alternatives": [],
        }
        for index in range(80)
    ]
    taxonomy = {
        "summary": "Repository map",
        "areas": [
            {
                "key": "runtime",
                "name": "Runtime",
                "description": "Runtime code",
                "responsibility": "Execute work",
                "confidence": 0.9,
                "rationale": "Shared runtime behavior",
                "evidence": ["runtime evidence"],
                "counter_evidence": [],
                "subsystems": [
                    {
                        "key": "workers",
                        "name": "Workers",
                        "description": "Worker modules",
                        "responsibility": "Run work",
                        "confidence": 0.9,
                        "rationale": "Worker behavior",
                        "evidence": ["worker evidence"],
                        "counter_evidence": [],
                        "members": members,
                    }
                ],
            }
        ],
        "facets": [],
        "confidence": 0.9,
        "evidence": ["repository evidence"],
    }
    request = {
        "contract": "Review the taxonomy.",
        "analysis_kind": "taxonomy_review",
        "candidate_taxonomy": taxonomy,
    }
    bounded, manifest, pages = packetize_agent_request(
        request, SemanticConfig(max_source_chars=4_000)
    )

    assert manifest is not None
    assembled = rehydrate_agent_request(bounded, pages)
    assert assembled == request


@pytest.mark.anyio
async def test_unbounded_remote_worker_waits_through_busy_queue_states(monkeypatch):
    claims = iter(
        [
            ([], {"status": "busy", "semantic": {"jobs": {"running": 1}}}),
            ([{"job": {"kind": "context"}}], None),
            ([], {"status": "complete", "semantic": {"semantically_ready": True}}),
        ]
    )
    sleeps = []

    async def claim(*_args):
        return next(claims)

    async def execute(_session, _target, _execution, _packets, total, _latest):
        total["processed"] += 1
        total["completed"] += 1
        return {"jobs": {"pending": 0}}

    async def sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(remote_worker, "_claim_wave", claim)
    monkeypatch.setattr(remote_worker, "_execute_wave", execute)
    monkeypatch.setattr(remote_worker.asyncio, "sleep", sleep)
    total = remote_worker._empty_result()

    semantic = await remote_worker._run_queue(
        object(),
        SemanticServiceTarget("http://testserver", 1, "Sample", "/repo"),
        SemanticConfig(max_parallel_jobs=1),
        SemanticConfig(provider="codex"),
        None,
        False,
        total,
    )

    assert sleeps == [2]
    assert total["processed"] == 1
    assert semantic["semantically_ready"] is True


@pytest.mark.anyio
async def test_unbounded_remote_worker_retries_transient_wave_failures(monkeypatch):
    claims = iter(
        [
            ([{"job": {"kind": "context"}}], None),
            ([{"job": {"kind": "context"}}], None),
            ([], {"status": "complete", "semantic": {"semantically_ready": True}}),
        ]
    )
    attempts = 0
    sleeps = []

    async def claim(*_args):
        return next(claims)

    async def execute(_session, _target, _execution, _packets, total, latest):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary executor failure")
        total["processed"] += 1
        return latest

    async def sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(remote_worker, "_claim_wave", claim)
    monkeypatch.setattr(remote_worker, "_execute_wave", execute)
    monkeypatch.setattr(remote_worker.asyncio, "sleep", sleep)
    total = remote_worker._empty_result()

    semantic = await remote_worker._run_queue(
        object(),
        SemanticServiceTarget("http://testserver", 1, "Sample", "/repo"),
        SemanticConfig(max_parallel_jobs=1),
        SemanticConfig(provider="codex"),
        None,
        False,
        total,
    )

    assert attempts == 2
    assert sleeps == [2]
    assert total["processed"] == 1
    assert semantic["semantically_ready"] is True


@pytest.mark.anyio
async def test_host_executor_writes_to_sidecar_index_with_runtime_model_provenance(
    repository, database, monkeypatch
):
    policy_path = repository / ".anaxigraph.yml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    policy["semantic"] = {
        "enabled": True,
        "provider": "agent",
        "max_parallel_jobs": 2,
        "agent_lease_seconds": 120,
    }
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    server = create_anaxi_mcp_server(
        database=database,
        repository=repository,
        config_path=None,
        allowed_hosts=["testserver"],
    )

    class Provider:
        name = "test"

        def analyze(self, request):
            value = _agent_dossier(request)
            return SemanticResult(value, float(value["confidence"]), tuple(value["evidence"]))

    monkeypatch.setattr(remote_worker, "create_semantic_provider", lambda _config: Provider())
    execution = SemanticConfig(enabled=True, provider="codex", model="changing-model")
    app = server.streamable_http_app()
    async with server.session_manager.run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            result = await remote_worker._execute(
                SemanticServiceTarget(
                    "http://testserver", stats.repository_id, "Sample", str(repository)
                ),
                config.semantic,
                execution,
                limit=1,
                until_complete=False,
                retry_failed=False,
                http_client=client,
            )

    assert result["completed"] == 1
    with database.connect() as connection:
        document = connection.execute(
            "SELECT provider, model, executor_id, executor_model FROM semantic_documents"
        ).fetchone()
    assert tuple(document) == (
        "agent",
        "",
        f"cli:codex:{os.getpid()}",
        "changing-model",
    )

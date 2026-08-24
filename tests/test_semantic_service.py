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
            }
        ],
    )

    target = discover_semantic_service(repository, explicit_url="http://127.0.0.1:9999")

    assert target == SemanticServiceTarget(
        base_url="http://127.0.0.1:9999",
        repository_id=7,
        repository_name="Project",
        repository_path="/repo",
    )
    assert target.mcp_url == "http://127.0.0.1:9999/mcp"


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


def test_service_preparation_is_synchronous_and_targets_one_index(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "anaxigraph.semantic_service._request_json",
        lambda url, **options: calls.append((url, options)) or {"status": "prepared"},
    )
    target = SemanticServiceTarget("http://127.0.0.1:8765", 4, "Example", "/repo")

    assert prepare_semantic_service(target, force=True, retry_failed=True) == {"status": "prepared"}
    assert "/api/semantic/refresh?" in calls[0][0]
    assert "repository_id=4" in calls[0][0]
    assert "force=true" in calls[0][0]
    assert "retry_failed=true" in calls[0][0]
    assert "wait=true" in calls[0][0]
    assert calls[0][1]["method"] == "POST"


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

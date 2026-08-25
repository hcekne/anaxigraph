from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import httpx
import pytest
import yaml
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from anaxigraph.mcp_runtime import _INSTRUCTIONS
from anaxigraph.mcp_server import create_anaxi_mcp_server
from anaxigraph.scanner import RepositoryScanner
from scripts.build_agent_plugin import build_agent_plugin
from scripts.check_agent_package import validate_agent_package

ROOT = Path(__file__).resolve().parents[1]


def test_mcp_instructions_lead_with_durable_semantic_execution():
    opening = _INSTRUCTIONS[:512]

    assert "durable host executor" in opening
    assert "bounded/manual fallback" in opening
    assert "semantically_ready: true" in opening
    assert "Never edit source" in opening
    assert "--model" not in opening


def test_shared_agent_package_is_versioned_and_contract_complete():
    assert validate_agent_package(ROOT) == []


def test_agent_plugin_archive_is_complete_and_reproducible(tmp_path: Path):
    first = tmp_path / "first/anaxigraph-agent-plugin-0.3.0.zip"
    second = tmp_path / "second/anaxigraph-agent-plugin-0.3.0.zip"
    first_report = build_agent_plugin(ROOT, first, epoch=1_700_000_000)
    second_report = build_agent_plugin(ROOT, second, epoch=1_700_000_000)

    assert first.read_bytes() == second.read_bytes()
    assert first_report == second_report
    with zipfile.ZipFile(first) as archive:
        names = set(archive.namelist())
    assert {
        "anaxigraph/.codex-plugin/plugin.json",
        "anaxigraph/.claude-plugin/plugin.json",
        "anaxigraph/.mcp.json",
        "anaxigraph/LICENSE",
        "anaxigraph/skills/anaxigraph/SKILL.md",
        "anaxigraph/skills/anaxigraph/agents/openai.yaml",
        "anaxigraph/skills/anaxigraph/assets/anaxigraph.svg",
    } <= names


def test_agent_package_check_rejects_version_drift(tmp_path: Path):
    for path in ("pyproject.toml", ".agents", ".claude-plugin", "plugins"):
        source = ROOT / path
        destination = tmp_path / path
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)
    manifest = tmp_path / "plugins/anaxigraph/.codex-plugin/plugin.json"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace('"version": "0.3.0"', '"version": "9.9.9"'),
        encoding="utf-8",
    )

    errors = validate_agent_package(tmp_path)

    assert any(".codex-plugin/plugin.json version must match" in error for error in errors)


@pytest.mark.anyio
async def test_skill_semantic_release_resume_evidence_and_submit_contract(repository, database):
    policy_path = repository / ".anaxigraph.yml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    policy["semantic"] = {
        "enabled": True,
        "provider": "agent",
        "agent_lease_seconds": 120,
        "max_source_chars": 4_000,
        "include": ["pkg/core.py"],
    }
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")
    core = repository / "pkg/core.py"
    core.write_text(
        core.read_text(encoding="utf-8") + f"\nLARGE_EVIDENCE = {'x' * 8_000!r}\n",
        encoding="utf-8",
    )
    RepositoryScanner(database).scan(repository)
    server = create_anaxi_mcp_server(
        database=database,
        repository=repository,
        config_path=None,
        allowed_hosts=["testserver"],
        allow_scan_tool=True,
    )
    app = server.streamable_http_app()

    async with server.session_manager.run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            timeout=5,
        ) as http_client:
            async with streamable_http_client(
                "http://testserver/mcp",
                http_client=http_client,
                terminate_on_close=False,
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    schema = await session.call_tool("ANAXIGRAPH_SEMANTIC_SCHEMA", arguments={})
                    assert (
                        schema.structuredContent["schema_version"] == "repository-understanding-v5"
                    )
                    first = await _claim(session)
                    manifest = first["evidence_manifest"]
                    assert manifest["page_count"] >= 1
                    pages = [
                        await session.call_tool(
                            "ANAXIGRAPH_SEMANTIC_EVIDENCE",
                            arguments={
                                "job_id": first["job"]["id"],
                                "lease_token": first["lease"]["token"],
                                "page": page,
                            },
                        )
                        for page in range(1, manifest["page_count"] + 1)
                    ]
                    assert all(page.structuredContent["status"] == "evidence" for page in pages)
                    released = await session.call_tool(
                        "ANAXIGRAPH_SEMANTIC_RELEASE",
                        arguments={
                            "job_id": first["job"]["id"],
                            "lease_token": first["lease"]["token"],
                            "reason": "contract-test handoff",
                        },
                    )
                    assert released.structuredContent["status"] == "released"
                    resumed = await _claim(session)
                    assert resumed["job"]["id"] == first["job"]["id"]
                    submitted = await session.call_tool(
                        "ANAXIGRAPH_SEMANTIC_SUBMIT",
                        arguments={
                            "job_id": resumed["job"]["id"],
                            "lease_token": resumed["lease"]["token"],
                            "dossier": _dossier(resumed["job"]["scope_key"]),
                        },
                    )
                    assert submitted.structuredContent["status"] == "completed"
                    status = await session.call_tool("ANAXIGRAPH_SEMANTIC_STATUS", arguments={})
                    assert status.structuredContent["jobs"]["completed"] >= 1


async def _claim(session: ClientSession) -> dict:
    result = await session.call_tool(
        "ANAXIGRAPH_SEMANTIC_WORK",
        arguments={"agent_id": "agent-package-contract", "agent_model": "fixture"},
    )
    assert result.isError is False
    assert result.structuredContent["status"] == "work"
    return result.structuredContent


def _dossier(scope: str) -> dict:
    return {
        "summary": f"Agent understanding for {scope}",
        "detailed_summary": f"Evidence-grounded dossier for {scope}.",
        "responsibilities": [f"Own {scope}"],
        "inputs": [],
        "outputs": [],
        "side_effects": [],
        "public_contracts": [],
        "invariants": [],
        "architecture_role": "agent package contract fixture",
        "domain_concepts": [],
        "collaborators": [],
        "overlaps": [],
        "extension_points": [],
        "similar_modules": [],
        "pattern_opportunities": [],
        "consolidation_assessment": {
            "recommendation": "insufficient_evidence",
            "score": 0,
            "rationale": "",
            "candidates": [],
            "evidence": [],
            "counter_evidence": [],
        },
        "dead_code_candidates": [],
        "placement_guidance": "",
        "testing_guidance": [],
        "change_summary": "",
        "risks": [],
        "evidence": [scope],
        "confidence": 0.9,
    }

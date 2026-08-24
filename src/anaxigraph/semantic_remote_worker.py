"""Run host model executors against semantic work leased from AnaxiMCP."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from anaxigraph.config import SemanticConfig
from anaxigraph.semantic import create_semantic_provider
from anaxigraph.semantic_agent_protocol import rehydrate_agent_request
from anaxigraph.semantic_request_analysis import analyze_semantic_request
from anaxigraph.semantic_service import SemanticServiceTarget


def execute_remote_semantics(
    target: SemanticServiceTarget,
    semantic: SemanticConfig,
    execution_semantic: SemanticConfig,
    *,
    limit: int | None,
    until_complete: bool,
    retry_failed: bool,
) -> dict[str, Any]:
    """Execute a sidecar-owned queue with a model authenticated on this host."""

    try:
        return asyncio.run(
            _execute(
                target,
                semantic,
                execution_semantic,
                limit=limit,
                until_complete=until_complete,
                retry_failed=retry_failed,
            )
        )
    except (ValueError, RuntimeError, OSError):
        raise
    except Exception as exc:
        raise RuntimeError(f"Remote semantic execution failed: {exc}") from exc


async def _execute(
    target: SemanticServiceTarget,
    semantic: SemanticConfig,
    execution_semantic: SemanticConfig,
    *,
    limit: int | None,
    until_complete: bool,
    retry_failed: bool,
    http_client: Any | None = None,
) -> dict[str, Any]:
    maximum = None if until_complete else max(1, limit or semantic.max_jobs_per_run)
    total = _empty_result()
    async with streamable_http_client(
        target.mcp_url,
        http_client=http_client,
        terminate_on_close=False,
    ) as streams:
        read_stream, write_stream, _ = streams
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            latest_semantic = await _run_queue(
                session,
                target,
                semantic,
                execution_semantic,
                maximum,
                retry_failed,
                total,
            )
            if not latest_semantic or (maximum is not None and total["processed"] >= maximum):
                latest_semantic = await _semantic_status(session, target)
    total["semantic"] = latest_semantic
    return total


def _empty_result() -> dict[str, Any]:
    return {
        "planned": 0,
        "processed": 0,
        "completed": 0,
        "failed": 0,
        "retry": 0,
        "stages": [],
    }


async def _run_queue(
    session: ClientSession,
    target: SemanticServiceTarget,
    semantic: SemanticConfig,
    execution: SemanticConfig,
    maximum: int | None,
    retry_failed: bool,
    total: dict[str, Any],
) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    while maximum is None or total["processed"] < maximum:
        remaining = semantic.max_parallel_jobs
        if maximum is not None:
            remaining = min(remaining, maximum - total["processed"])
        packets, terminal = await _claim_wave(session, target, execution, remaining, retry_failed)
        if terminal:
            latest = dict(terminal.get("semantic") or latest)
        if not packets:
            break
        latest = await _execute_wave(session, target, execution, packets, total, latest)
    return latest


async def _execute_wave(
    session: ClientSession,
    target: SemanticServiceTarget,
    execution: SemanticConfig,
    packets: list[dict[str, Any]],
    total: dict[str, Any],
    latest: dict[str, Any],
) -> dict[str, Any]:
    requests = await asyncio.gather(
        *(_request_for_packet(session, target, packet) for packet in packets)
    )
    results = await asyncio.gather(
        *(asyncio.to_thread(_analyze, request, execution) for request in requests),
        return_exceptions=True,
    )
    failure = next((item for item in results if isinstance(item, BaseException)), None)
    if failure is not None:
        await _release_packets(session, target, packets, str(failure))
        raise RuntimeError(f"Semantic model execution failed: {failure}") from failure
    for index, (packet, result) in enumerate(zip(packets, results, strict=True)):
        try:
            submitted = await _submit(session, target, packet, result)
        except Exception:
            await _release_packets(session, target, packets[index + 1 :], "peer submit failed")
            raise
        total["processed"] += 1
        total["completed"] += int(submitted.get("status") in {"completed", "already_completed"})
        kind = str(packet.get("job", {}).get("kind") or "")
        if kind and kind not in total["stages"]:
            total["stages"].append(kind)
        latest = dict(submitted.get("semantic") or latest)
    return latest


async def _claim_wave(
    session: ClientSession,
    target: SemanticServiceTarget,
    execution: SemanticConfig,
    count: int,
    retry_failed: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    packets = []
    terminal = None
    for _ in range(count):
        result = await session.call_tool(
            "ANAXIGRAPH_SEMANTIC_WORK",
            arguments={
                "agent_id": f"cli:{execution.provider}:{os.getpid()}",
                "agent_model": execution.model,
                "retry_failed": retry_failed,
                "repository": str(target.repository_id),
            },
        )
        packet = _tool_value(result, "claim semantic work")
        if packet.get("status") != "work":
            terminal = packet
            break
        packets.append(packet)
    return packets, terminal


async def _request_for_packet(
    session: ClientSession,
    target: SemanticServiceTarget,
    packet: dict[str, Any],
) -> dict[str, Any]:
    manifest = packet.get("evidence_manifest") or {}
    pages = []
    for page in range(1, int(manifest.get("page_count") or 0) + 1):
        result = await session.call_tool(
            "ANAXIGRAPH_SEMANTIC_EVIDENCE",
            arguments={
                "job_id": int(packet["job"]["id"]),
                "lease_token": str(packet["lease"]["token"]),
                "page": page,
                "repository": str(target.repository_id),
            },
        )
        pages.append(_tool_value(result, "read semantic evidence"))
    return rehydrate_agent_request(dict(packet["analysis_request"]), pages)


def _analyze(request: dict[str, Any], execution: SemanticConfig) -> Any:
    provider = create_semantic_provider(execution)
    return analyze_semantic_request(provider, request, execution)


async def _submit(
    session: ClientSession,
    target: SemanticServiceTarget,
    packet: dict[str, Any],
    result: Any,
) -> dict[str, Any]:
    response = await session.call_tool(
        "ANAXIGRAPH_SEMANTIC_SUBMIT",
        arguments={
            "job_id": int(packet["job"]["id"]),
            "lease_token": str(packet["lease"]["token"]),
            "dossier": result.value,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "repository": str(target.repository_id),
        },
    )
    return _tool_value(response, "submit semantic work")


async def _release_packets(
    session: ClientSession,
    target: SemanticServiceTarget,
    packets: list[dict[str, Any]],
    reason: str,
) -> None:
    for packet in packets:
        await session.call_tool(
            "ANAXIGRAPH_SEMANTIC_RELEASE",
            arguments={
                "job_id": int(packet["job"]["id"]),
                "lease_token": str(packet["lease"]["token"]),
                "reason": reason[:1_000],
                "repository": str(target.repository_id),
            },
        )


async def _semantic_status(session: ClientSession, target: SemanticServiceTarget) -> dict[str, Any]:
    result = await session.call_tool(
        "ANAXIGRAPH_SEMANTIC_STATUS",
        arguments={"repository": str(target.repository_id)},
    )
    return _tool_value(result, "read semantic status")


def _tool_value(result: Any, action: str) -> dict[str, Any]:
    if result.isError:
        message = " ".join(
            str(getattr(item, "text", "")) for item in result.content if getattr(item, "text", "")
        )
        raise RuntimeError(f"AnaxiMCP could not {action}: {message[:1_000]}")
    value = result.structuredContent
    if isinstance(value, dict):
        return value
    for item in result.content:
        text = getattr(item, "text", "")
        if text:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
    raise RuntimeError(f"AnaxiMCP returned no structured result while trying to {action}")

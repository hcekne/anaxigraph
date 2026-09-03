"""Run host model executors against semantic work leased from AnaxiMCP."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from anaxigraph.config import SemanticConfig
from anaxigraph.semantic import create_semantic_provider
from anaxigraph.semantic_agent_protocol import rehydrate_agent_request
from anaxigraph.semantic_background_progress import report_background_progress
from anaxigraph.semantic_remote_errors import failure_summary, raise_remote_failure
from anaxigraph.semantic_remote_recovery import IdleRecovery
from anaxigraph.semantic_request_analysis import analyze_semantic_request
from anaxigraph.semantic_service import SemanticServiceTarget

_TERMINAL_STATES = frozenset({"complete", "complete_with_failures", "paused"})
_MCP_INITIALIZE_TIMEOUT_SECONDS = 20
_MCP_TOOL_TIMEOUT_SECONDS = 60
_SUBMIT_ATTEMPTS = 6


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
    report_background_progress(stage="connecting", completed=0)
    try:
        result = asyncio.run(
            _execute(
                target,
                semantic,
                execution_semantic,
                limit=limit,
                until_complete=until_complete,
                retry_failed=retry_failed,
            )
        )
        stage = "complete" if result.get("semantic", {}).get("semantically_ready") else "idle"
        report_background_progress(stage=stage, completed=int(result["completed"]))
        return result
    except Exception as exc:
        report_background_progress(stage="failed", last_error=failure_summary(exc))
        raise_remote_failure(exc)


async def _execute(
    target: SemanticServiceTarget,
    semantic: SemanticConfig,
    execution_semantic: SemanticConfig,
    *,
    limit: int | None,
    until_complete: bool,
    retry_failed: bool,
    http_client: Any | None = None,
    mcp_url: str | None = None,
) -> dict[str, Any]:
    maximum = None if until_complete else max(1, limit or semantic.max_jobs_per_run)
    total = _empty_result()
    async with streamable_http_client(
        mcp_url or target.executor_mcp_url,
        http_client=http_client,
        terminate_on_close=True,
    ) as streams:
        read_stream, write_stream, _ = streams
        async with ClientSession(
            read_stream,
            write_stream,
            read_timeout_seconds=timedelta(seconds=_MCP_TOOL_TIMEOUT_SECONDS),
        ) as session:
            await asyncio.wait_for(session.initialize(), timeout=_MCP_INITIALIZE_TIMEOUT_SECONDS)
            report_background_progress(stage="claiming", completed=0)
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
    consecutive_failures = 0
    recovery = IdleRecovery(target, retry_failed)
    while maximum is None or total["processed"] < maximum:
        remaining = min(semantic.max_parallel_jobs, execution.max_parallel_jobs)
        if maximum is not None:
            remaining = min(remaining, maximum - total["processed"])
        packets, terminal = await _claim_wave(session, target, execution, remaining, retry_failed)
        if terminal:
            latest = dict(terminal.get("semantic") or latest)
        if not packets:
            report_background_progress(
                stage=str((terminal or {}).get("status") or "waiting"),
                completed=int(total["completed"]),
            )
            should_stop, latest = await _wait_or_recover(recovery, terminal, latest, maximum, total)
            if should_stop:
                break
            continue
        recovery.reset()
        try:
            latest = await _execute_wave(session, target, execution, packets, total, latest)
        except RuntimeError as exc:
            consecutive_failures += 1
            if consecutive_failures >= 3:
                raise
            print(f"Semantic wave failed; retrying: {exc}", file=sys.stderr, flush=True)
            await asyncio.sleep(2**consecutive_failures)
            continue
        consecutive_failures = 0
        _report_progress(total, latest)
    return latest


async def _wait_or_recover(
    recovery: IdleRecovery,
    terminal: dict[str, Any] | None,
    latest: dict[str, Any],
    maximum: int | None,
    total: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    state = str((terminal or {}).get("status") or "waiting")
    if maximum is not None or state in _TERMINAL_STATES:
        return True, latest
    prepared = await recovery.recover(state, latest)
    if prepared is not None:
        total["planned"] += int(prepared.get("enqueued") or 0)
        return False, dict(prepared.get("semantic") or latest)
    await asyncio.sleep(2)
    return False, latest


def _report_progress(total: dict[str, Any], semantic: dict[str, Any]) -> None:
    jobs = semantic.get("jobs") or {}
    print(
        "Semantic progress: "
        f"processed={total['processed']} current={semantic.get('current', 0)} "
        f"pending={jobs.get('pending', 0)} retry={jobs.get('retry', 0)} "
        f"running={jobs.get('running', 0)}",
        file=sys.stderr,
        flush=True,
    )
    report_background_progress(
        stage=str(total["stages"][-1] if total["stages"] else "executing"),
        completed=int(total["completed"]),
    )


async def _execute_wave(
    session: ClientSession,
    target: SemanticServiceTarget,
    execution: SemanticConfig,
    packets: list[dict[str, Any]],
    total: dict[str, Any],
    latest: dict[str, Any],
) -> dict[str, Any]:
    requests = await _wave_requests(session, target, packets)
    call_budget = max(1, execution.max_parallel_jobs // len(packets))
    request_execution = replace(execution, max_parallel_jobs=call_budget)
    with ThreadPoolExecutor(
        max_workers=min(len(packets), execution.max_parallel_jobs),
        thread_name_prefix="anaxigraph-model",
    ) as pool:
        tasks = [
            asyncio.create_task(_analyze_indexed(index, request, request_execution, pool))
            for index, request in enumerate(requests)
        ]
        remaining = set(range(len(packets)))
        for completed in asyncio.as_completed(tasks):
            index, result = await completed
            if isinstance(result, BaseException):
                try:
                    latest = await _record_model_failure(
                        session, target, packets, remaining, index, result, total, latest
                    )
                except Exception as exc:
                    await _abort_wave(session, target, packets, tasks, remaining, str(exc))
                    raise RuntimeError(f"Semantic failure reporting failed: {exc}") from exc
                continue
            latest = await _submit_wave_result(
                session,
                target,
                packets,
                tasks,
                remaining,
                index,
                result,
                total,
                latest,
            )
    return latest


async def _record_model_failure(
    session: ClientSession,
    target: SemanticServiceTarget,
    packets: list[dict[str, Any]],
    remaining: set[int],
    index: int,
    error: BaseException,
    total: dict[str, Any],
    latest: dict[str, Any],
) -> dict[str, Any]:
    failed = await _fail_packet(session, target, packets[index], error)
    remaining.remove(index)
    total["processed"] += 1
    total["retry"] += int(failed.get("status") == "retry")
    total["failed"] += int(failed.get("status") == "failed")
    return dict(failed.get("semantic") or latest)


async def _wave_requests(
    session: ClientSession,
    target: SemanticServiceTarget,
    packets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    try:
        return await asyncio.gather(
            *(_request_for_packet(session, target, packet) for packet in packets)
        )
    except Exception as exc:
        await _release_packets(session, target, packets, "evidence read failed")
        raise RuntimeError(f"Semantic evidence read failed: {exc}") from exc


async def _abort_wave(
    session: ClientSession,
    target: SemanticServiceTarget,
    packets: list[dict[str, Any]],
    tasks: list[Any],
    remaining: set[int],
    reason: str,
) -> None:
    await asyncio.gather(*tasks, return_exceptions=True)
    await _release_packets(
        session,
        target,
        [packets[index] for index in sorted(remaining)],
        reason,
    )


async def _submit_wave_result(
    session: ClientSession,
    target: SemanticServiceTarget,
    packets: list[dict[str, Any]],
    tasks: list[Any],
    remaining: set[int],
    index: int,
    result: Any,
    total: dict[str, Any],
    latest: dict[str, Any],
) -> dict[str, Any]:
    packet = packets[index]
    try:
        submitted = await _submit(session, target, packet, result)
    except Exception as exc:
        await _abort_wave(session, target, packets, tasks, remaining, "peer submit failed")
        raise RuntimeError(f"Semantic submission failed: {exc}") from exc
    remaining.remove(index)
    total["processed"] += 1
    total["completed"] += int(submitted.get("status") in {"completed", "already_completed"})
    kind = str(packet.get("job", {}).get("kind") or "")
    if kind and kind not in total["stages"]:
        total["stages"].append(kind)
    return dict(submitted.get("semantic") or latest)


async def _analyze_indexed(
    index: int,
    request: dict[str, Any],
    execution: SemanticConfig,
    pool: ThreadPoolExecutor,
) -> tuple[int, Any]:
    try:
        loop = asyncio.get_running_loop()
        return index, await loop.run_in_executor(pool, _analyze, request, execution)
    except Exception as exc:
        return index, exc


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
        result = await _call_tool(
            session,
            "ANAXIGRAPH_SEMANTIC_WORK",
            {
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
        result = await _call_tool(
            session,
            "ANAXIGRAPH_SEMANTIC_EVIDENCE",
            {
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
    for attempt in range(_SUBMIT_ATTEMPTS):
        try:
            response = await _call_tool(
                session,
                "ANAXIGRAPH_SEMANTIC_SUBMIT",
                {
                    "job_id": int(packet["job"]["id"]),
                    "lease_token": str(packet["lease"]["token"]),
                    "dossier": result.value,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "repository": str(target.repository_id),
                },
            )
            return _tool_value(response, "submit semantic work")
        except RuntimeError as exc:
            if "database is locked" not in str(exc).lower() or attempt == _SUBMIT_ATTEMPTS - 1:
                raise
            await asyncio.sleep(2**attempt)
    raise RuntimeError("Unreachable semantic submission retry state")


async def _release_packets(
    session: ClientSession,
    target: SemanticServiceTarget,
    packets: list[dict[str, Any]],
    reason: str,
) -> None:
    await asyncio.gather(
        *(_release_packet(session, target, packet, reason) for packet in packets),
        return_exceptions=True,
    )


async def _fail_packet(
    session: ClientSession,
    target: SemanticServiceTarget,
    packet: dict[str, Any],
    error: BaseException,
) -> dict[str, Any]:
    response = await _call_tool(
        session,
        "ANAXIGRAPH_SEMANTIC_FAIL",
        {
            "job_id": int(packet["job"]["id"]),
            "lease_token": str(packet["lease"]["token"]),
            "reason": str(error)[:1_000],
            "input_tokens": int(getattr(error, "input_tokens", 0)),
            "output_tokens": int(getattr(error, "output_tokens", 0)),
            "repository": str(target.repository_id),
        },
    )
    return _tool_value(response, "record failed semantic work")


async def _release_packet(
    session: ClientSession,
    target: SemanticServiceTarget,
    packet: dict[str, Any],
    reason: str,
) -> None:
    await _call_tool(
        session,
        "ANAXIGRAPH_SEMANTIC_RELEASE",
        {
            "job_id": int(packet["job"]["id"]),
            "lease_token": str(packet["lease"]["token"]),
            "reason": reason[:1_000],
            "repository": str(target.repository_id),
        },
    )


async def _semantic_status(session: ClientSession, target: SemanticServiceTarget) -> dict[str, Any]:
    result = await _call_tool(
        session,
        "ANAXIGRAPH_SEMANTIC_STATUS",
        {"repository": str(target.repository_id)},
    )
    return _tool_value(result, "read semantic status")


async def _call_tool(session: ClientSession, name: str, arguments: dict[str, Any]) -> Any:
    try:
        return await asyncio.wait_for(
            session.call_tool(
                name,
                arguments=arguments,
                read_timeout_seconds=timedelta(seconds=_MCP_TOOL_TIMEOUT_SECONDS),
            ),
            timeout=_MCP_TOOL_TIMEOUT_SECONDS + 1,
        )
    except TimeoutError as exc:
        raise RuntimeError(
            f"AnaxiMCP tool {name} exceeded {_MCP_TOOL_TIMEOUT_SECONDS} seconds"
        ) from exc


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

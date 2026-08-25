"""Run host model executors against semantic work leased from AnaxiMCP."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import replace
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from anaxigraph.config import SemanticConfig
from anaxigraph.semantic import create_semantic_provider
from anaxigraph.semantic_agent_protocol import rehydrate_agent_request
from anaxigraph.semantic_request_analysis import analyze_semantic_request
from anaxigraph.semantic_service import SemanticServiceTarget, prepare_semantic_service

_TERMINAL_STATES = frozenset({"complete", "complete_with_failures", "paused"})


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
    consecutive_failures = 0
    recovery = _IdleRecovery(target, retry_failed)
    while maximum is None or total["processed"] < maximum:
        remaining = min(semantic.max_parallel_jobs, execution.max_parallel_jobs)
        if maximum is not None:
            remaining = min(remaining, maximum - total["processed"])
        packets, terminal = await _claim_wave(session, target, execution, remaining, retry_failed)
        if terminal:
            latest = dict(terminal.get("semantic") or latest)
        if not packets:
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
    recovery: _IdleRecovery,
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


class _IdleRecovery:
    """Rescan once when an until-complete queue is nonterminal but unclaimable."""

    def __init__(self, target: SemanticServiceTarget, retry_failed: bool) -> None:
        self.target = target
        self.retry_failed = retry_failed
        self.snapshot_id: int | None = None
        self.polls = 0
        self.refreshed: set[int] = set()

    def reset(self) -> None:
        self.snapshot_id = None
        self.polls = 0

    async def recover(self, state: str, semantic: dict[str, Any]) -> dict[str, Any] | None:
        if not _stranded_queue(state, semantic):
            self.reset()
            return None
        snapshot_id = int(semantic.get("snapshot_id") or 0)
        if self.snapshot_id != snapshot_id:
            self.snapshot_id = snapshot_id
            self.polls = 0
        self.polls += 1
        if self.polls < 3:
            return None
        if snapshot_id in self.refreshed:
            jobs = semantic.get("jobs") or {}
            raise RuntimeError(
                "Semantic queue remained nonterminal with no claimable work after a synchronous "
                f"rescan (snapshot={snapshot_id}, pending={semantic.get('pending', 0)}, "
                f"retry={jobs.get('retry', 0)}, running={jobs.get('running', 0)})."
            )
        try:
            prepared = await asyncio.to_thread(
                prepare_semantic_service,
                self.target,
                force=False,
                retry_failed=self.retry_failed,
            )
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"Could not recover the stranded semantic queue: {exc}") from exc
        self.refreshed.add(snapshot_id)
        self.reset()
        print(
            f"Semantic queue was stranded at snapshot {snapshot_id}; rescanned and replanned.",
            file=sys.stderr,
            flush=True,
        )
        return prepared


def _stranded_queue(state: str, semantic: dict[str, Any]) -> bool:
    jobs = semantic.get("jobs") or {}
    active = sum(int(jobs.get(key, 0)) for key in ("pending", "retry", "running"))
    return bool(
        state == "waiting"
        and not semantic.get("semantically_ready")
        and not (semantic.get("budget") or {}).get("paused")
        and active == 0
    )


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
    tasks = [
        asyncio.create_task(_analyze_indexed(index, request, request_execution))
        for index, request in enumerate(requests)
    ]
    remaining = set(range(len(packets)))
    for completed in asyncio.as_completed(tasks):
        index, result = await completed
        if isinstance(result, BaseException):
            await _abort_wave(session, target, packets, tasks, remaining, str(result))
            raise RuntimeError(f"Semantic model execution failed: {result}") from result
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
) -> tuple[int, Any]:
    try:
        return index, await asyncio.to_thread(_analyze, request, execution)
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

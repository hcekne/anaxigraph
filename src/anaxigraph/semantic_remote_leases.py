"""Renew remote work ownership while evidence, model calls, and writes are in flight."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from anaxigraph.semantic_background_progress import report_background_progress
from anaxigraph.semantic_remote_calls import call_tool_retrying_locks


@contextlib.asynccontextmanager
async def keep_remote_leases(session: Any, target: Any, packets: list[Any], remaining: set[int]):
    renewable = {
        index: packet
        for index, packet in enumerate(packets)
        if packet.get("lease", {}).get("renewal_tool") == "ANAXIGRAPH_SEMANTIC_RENEW"
    }
    if not renewable:
        yield
        return
    interval = min(float(packet["lease"]["renew_after_seconds"]) for packet in renewable.values())
    task = asyncio.create_task(_renew_loop(session, target, renewable, remaining, interval))
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def _renew_loop(
    session: Any, target: Any, packets: Any, remaining: set[int], interval: float
):
    while True:
        await asyncio.sleep(max(0.01, interval))
        await asyncio.gather(
            *(
                _renew_one(session, target, packet, index, remaining)
                for index, packet in packets.items()
                if index in remaining
            )
        )


async def _renew_one(session: Any, target: Any, packet: Any, index: int, remaining: set[int]):
    try:
        await call_tool_retrying_locks(
            session,
            "ANAXIGRAPH_SEMANTIC_RENEW",
            {
                "repository": str(target.repository_id),
                "job_id": int(packet["job"]["id"]),
                "lease_token": str(packet["lease"]["token"]),
            },
            action="renew semantic work",
        )
    except Exception as exc:
        if index in remaining:
            report_background_progress(
                stage="lease_renewal_retry", last_error=f"Lease renewal will retry: {exc}"
            )

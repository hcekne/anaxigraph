"""Refill remote executor slots as soon as each job saves its result."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any


async def drain_available(
    packets: list[Any],
    execution: Any,
    total: dict[str, Any],
    latest: dict[str, Any],
    *,
    maximum: int | None,
    claim: Any,
    execute: Any,
) -> dict[str, Any]:
    """Account for both file workers and nested calls inside a large review."""
    pending: dict[Any, int] = {}
    error: Exception | None = None
    capacity = execution.max_parallel_jobs

    def start(claimed: list[Any], available: int) -> None:
        budget = max(1, available // len(claimed))
        for packet in claimed:
            task = asyncio.create_task(
                execute(replace(execution, max_parallel_jobs=budget), [packet], total, latest)
            )
            pending[task] = budget

    start(packets, capacity)
    try:
        while pending:
            finished, _ = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in finished:
                pending.pop(task)
                try:
                    latest = task.result()
                except Exception as exc:
                    error = exc
            # Let successful peers save their work even if a transport operation failed.
            if error is not None or not pending:
                continue
            available = free_slots(capacity, pending, maximum, total["processed"])
            if available > 0:
                try:
                    claimed, _ = await claim(available)
                    if claimed:
                        start(claimed, available)
                except Exception as exc:
                    error = exc
        if error is not None:
            raise error
        return latest
    finally:
        # A caller cancellation must not abandon running model results or their leases.
        await asyncio.gather(*pending, return_exceptions=True)


def free_slots(capacity: int, pending: dict[Any, int], maximum: int | None, processed: int) -> int:
    available = capacity - sum(pending.values())
    return available if maximum is None else min(available, maximum - processed - len(pending))

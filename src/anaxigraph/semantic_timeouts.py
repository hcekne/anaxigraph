"""Optional model deadlines and bounded, renewable worker leases."""

from __future__ import annotations

import re
from typing import Any


def worker_lease_seconds(timeout_seconds: int | None) -> int:
    """Keep crash recovery bounded even when a model has no wall-clock deadline."""
    return max(90, (timeout_seconds or 300) + 60)


def timeout_message(
    provider: str,
    seconds: float,
    request: dict[str, Any] | None = None,
    model: str = "",
) -> str:
    """Describe the failing call without serializing its command or output schema."""
    request = request or {}
    stage = str(request.get("analysis_kind") or "").replace("_", " ")
    chunk = request.get("chunk") or {}
    context = f" during {stage}" if stage else ""
    if chunk:
        context += f" (partition {chunk.get('index')}/{chunk.get('total')})"
    return (
        f"{provider}{f' ({model})' if model else ''} timed out after {seconds:g} seconds{context}. "
        "AnaxiGraph stopped the call at its configured time limit. Increase "
        "semantic.timeout_seconds or set it to null to allow the call to finish."
    )


def readable_failure(error: str | None) -> str | None:
    """Recover the cause from older stored TimeoutExpired command dumps before truncation."""
    if error is None:
        return None
    legacy = re.search(
        r"(Claude|Codex|Semantic command) (?:semantic run )?failed: Command "
        r".* timed out after ([0-9.]+) seconds$",
        error,
        re.DOTALL,
    )
    if legacy:
        return timeout_message(legacy[1], float(legacy[2]))
    return error[:1_000]

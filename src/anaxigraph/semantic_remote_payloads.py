"""Exact MCP tool arguments the host executor sends for one leased semantic job.

Keeping the four argument shapes in one dependency-free module makes the host executor's side of
the ``ANAXIGRAPH_SEMANTIC_WORK``, ``_SUBMIT``, ``_FAIL``, and ``_RELEASE`` contract readable in one
place, and leaves the worker itself about scheduling and recovery.
"""

from __future__ import annotations

import os
from typing import Any


def claim_arguments(
    repository_id: int,
    *,
    provider: str,
    model: str,
    effort: str,
    retry_failed: bool,
) -> dict[str, Any]:
    """Name this host process, its model, and the effort it was asked to run at."""

    return {
        "agent_id": f"cli:{provider}:{os.getpid()}",
        "agent_model": model,
        "agent_effort": effort,
        "retry_failed": retry_failed,
        "repository": str(repository_id),
    }


def submit_arguments(
    repository_id: int,
    packet: dict[str, Any],
    result: Any,
) -> dict[str, Any]:
    """Send the completed dossier with whatever usage the executor actually reported."""

    return {
        **_lease_arguments(repository_id, packet),
        "dossier": result.value,
        **_usage_arguments(result),
    }


def fail_arguments(
    repository_id: int,
    packet: dict[str, Any],
    error: BaseException,
) -> dict[str, Any]:
    """Report the failure with any usage the executor emitted before it failed."""

    return {
        **_lease_arguments(repository_id, packet),
        "reason": str(error)[:1_000],
        **_usage_arguments(error),
    }


def release_arguments(
    repository_id: int,
    packet: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    """Return an unfinished job without counting a failed attempt."""

    return {**_lease_arguments(repository_id, packet), "reason": reason[:1_000]}


def _lease_arguments(repository_id: int, packet: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": int(packet["job"]["id"]),
        "lease_token": str(packet["lease"]["token"]),
        "repository": str(repository_id),
    }


def _usage_arguments(carrier: Any) -> dict[str, Any]:
    """Omit every token argument when the executor reported no usage at all.

    An omitted count is recorded as unknown usage on the receiving side, which is what a run that
    never saw a usage object should leave behind; sending zeros would claim a free model call.
    """

    if not getattr(carrier, "usage_reported", False):
        return {}
    return {
        "input_tokens": max(0, int(getattr(carrier, "input_tokens", 0))),
        "output_tokens": max(0, int(getattr(carrier, "output_tokens", 0))),
        "cache_read_input_tokens": max(0, int(getattr(carrier, "cache_read_input_tokens", 0))),
        "cache_creation_input_tokens": max(
            0, int(getattr(carrier, "cache_creation_input_tokens", 0))
        ),
    }

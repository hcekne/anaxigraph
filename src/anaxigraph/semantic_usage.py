"""Executor-neutral token usage parsed from local coding-agent CLI output."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ProviderUsage:
    """Token usage with one meaning for every executor.

    ``input_tokens`` counts every billed prompt token, cached categories included, so Codex and
    Claude totals are comparable. ``cache_read_input_tokens`` and ``cache_creation_input_tokens``
    are the cached portions of that total, never additions to it.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


def claude_usage(envelope: Any) -> ProviderUsage:
    """Read usage from a ``claude --print --output-format json`` result envelope.

    The envelope's ``usage`` reports the uncached remainder as ``input_tokens`` beside
    ``cache_creation_input_tokens`` and ``cache_read_input_tokens``; the prompt total is their
    sum (see tests/fixtures/claude-print-envelope.json). Without ``usage`` the per-model
    ``modelUsage`` map is summed instead; without either the usage is zero.
    """
    if not isinstance(envelope, dict):
        return ProviderUsage()
    usage = envelope.get("usage")
    if not isinstance(usage, dict) or not usage:
        return _summed_model_usage(envelope.get("modelUsage"))
    cache_read = _count(usage, "cache_read_input_tokens")
    cache_creation = _count(usage, "cache_creation_input_tokens")
    return ProviderUsage(
        input_tokens=_count(usage, "input_tokens") + cache_creation + cache_read,
        output_tokens=_count(usage, "output_tokens"),
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_creation,
    )


def _summed_model_usage(model_usage: Any) -> ProviderUsage:
    if not isinstance(model_usage, dict):
        return ProviderUsage()
    entries = [entry for entry in model_usage.values() if isinstance(entry, dict)]
    cache_read = sum(_count(entry, "cacheReadInputTokens") for entry in entries)
    cache_creation = sum(_count(entry, "cacheCreationInputTokens") for entry in entries)
    uncached = sum(_count(entry, "inputTokens") for entry in entries)
    return ProviderUsage(
        input_tokens=uncached + cache_creation + cache_read,
        output_tokens=sum(_count(entry, "outputTokens") for entry in entries),
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_creation,
    )


def codex_usage(events: str) -> ProviderUsage:
    """Read usage from the last ``usage`` event of a ``codex exec --json`` stream.

    Codex reports ``input_tokens`` as the whole prompt and ``cached_input_tokens`` plus
    ``cache_write_input_tokens`` as portions of it (see tests/fixtures/codex-exec-events.jsonl),
    so the total is taken as reported rather than summed.
    """
    usage: dict[str, Any] = {}
    for line in events.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and isinstance(event.get("usage"), dict):
            usage = event["usage"]
    return ProviderUsage(
        input_tokens=_count(usage, "input_tokens", "total_input_tokens"),
        output_tokens=_count(usage, "output_tokens", "total_output_tokens"),
        cache_read_input_tokens=_count(usage, "cached_input_tokens"),
        cache_creation_input_tokens=_count(usage, "cache_write_input_tokens"),
    )


def _count(mapping: dict[str, Any], *keys: str) -> int:
    """Return the first non-empty key as a non-negative count, or zero."""
    for key in keys:
        value = mapping.get(key)
        if not value:
            continue
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0
    return 0

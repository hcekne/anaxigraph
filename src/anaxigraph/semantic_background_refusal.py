"""Refusal guidance when a detached semantic worker already owns a repository."""

from __future__ import annotations

from typing import Any

DEFAULT_NEXT_ACTION = (
    "Use anaxigraph semantic-status for progress; the worker survives this session."
)
_OTHER_EXECUTORS = {"codex": "claude", "claude": "codex"}


def already_running(active: dict[str, Any], spec: Any) -> dict[str, Any]:
    """Refuse a second run in one executor's slot, naming the other executor's own slot.

    Every executor owns a separate background run slot for a repository, so the way to add a
    second host worker is to start a different executor, not to wait for this one.
    """

    record = {**active, "status": "already_running"}
    running = str(active.get("executor") or "")
    if not running:
        return record
    repository = str(spec.repository.expanduser().resolve())
    other = _OTHER_EXECUTORS.get(running, "")
    alternative = (
        f"anaxigraph understand {repository} --executor {other} --background"
        if other
        else f"anaxigraph understand {repository} --until-complete"
    )
    record["recommended_action"] = (
        f"A background {running} worker already owns this repository's {running} slot, and one "
        f"executor has one background run. Start a second host executor in its own slot: "
        f"{alternative}"
    )
    return record


def background_next_action(run: dict[str, Any]) -> str:
    """Prefer refusal guidance over the progress hint when a launch was declined."""

    return str(run.get("recommended_action") or DEFAULT_NEXT_ACTION)

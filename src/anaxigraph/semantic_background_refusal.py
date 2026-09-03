"""Refusal guidance when a detached semantic worker already owns a repository."""

from __future__ import annotations

from typing import Any

DEFAULT_NEXT_ACTION = (
    "Use anaxigraph semantic-status for progress; the worker survives this session."
)


def already_running(active: dict[str, Any], spec: Any) -> dict[str, Any]:
    """Refuse a second detached run, naming the foreground path for a different executor."""

    record = {**active, "status": "already_running"}
    running = str(active.get("executor") or "")
    requested = str(getattr(spec, "executor", "") or "")
    if not running or not requested or running == requested:
        return record
    repository = str(spec.repository.expanduser().resolve())
    record["recommended_action"] = (
        f"A background {running} worker already owns this repository, and one repository has one "
        f"background run. Run the second executor in the foreground instead: anaxigraph "
        f"understand {repository} --executor {requested} --until-complete"
    )
    return record


def background_next_action(run: dict[str, Any]) -> str:
    """Prefer refusal guidance over the progress hint when a launch was declined."""

    return str(run.get("recommended_action") or DEFAULT_NEXT_ACTION)

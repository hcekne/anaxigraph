"""Handoff guidance for detached semantic workers."""

from __future__ import annotations

from typing import Any

DEFAULT_NEXT_ACTION = (
    "The background worker owns scheduling, retries, and progress and survives this session. "
    "Return the run id to the user; check anaxigraph semantic-status <repository> --compact "
    "only when requested or after at least 300 seconds. Do not create supervisor scripts, "
    "poll in an LLM loop, or infer worker health from the short-lived understand command."
)


def already_running(active: dict[str, Any], spec: Any) -> dict[str, Any]:
    """Return the existing run without starting a competing coordinator."""

    return {
        **active,
        "status": "already_running",
        "recommended_action": f"Reuse this {spec.executor} run. {DEFAULT_NEXT_ACTION}",
    }


def background_next_action(run: dict[str, Any]) -> str:
    """Prefer refusal guidance over the progress hint when a launch was declined."""

    return str(run.get("recommended_action") or DEFAULT_NEXT_ACTION)

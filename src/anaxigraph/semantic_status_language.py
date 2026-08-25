"""Plain-language AI-mapping status for people and coding agents."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SEMANTIC_STATUS_LANGUAGE_VERSION = "semantic-status-explanation-v2"


def semantic_status_explanation(status: Mapping[str, Any]) -> dict[str, Any]:
    """Explain AI-mapping progress without making workflow-state names the answer."""

    enabled = bool(status.get("enabled"))
    ready = bool(status.get("semantically_ready"))
    running = _running(status)
    total = _count(status.get("eligible_modules"))
    current = _count(status.get("current"))
    pending = _count(status.get("pending"))
    pending_map = _count(status.get("pending_scopes"))
    failed = _count(status.get("failed"))
    failed_map = _count(status.get("failed_scopes"))
    excluded = _count(status.get("excluded"))
    return {
        "version": SEMANTIC_STATUS_LANGUAGE_VERSION,
        "conclusion": _conclusion(status, enabled, ready, running, failed, failed_map),
        "progress": _progress(enabled, total, current, excluded),
        "work_state": _work_state(
            enabled, ready, running, pending + pending_map, failed + failed_map
        ),
        "remaining_work": _remaining_work(status, pending, pending_map, failed, failed_map),
        "what_to_do": _actions(status, enabled, ready, running),
        "how_to_read_progress": _reading_guide(status, total),
    }


def _conclusion(
    status: Mapping[str, Any],
    enabled: bool,
    ready: bool,
    running: bool,
    failed: int,
    failed_map: int,
) -> str:
    state = str(status.get("state") or "not_started")
    if state == "not_indexed":
        return "AI mapping cannot start because this repository has not completed a read-only file scan yet."
    if not enabled:
        return "AI mapping is turned off for this repository."
    if ready:
        return "The AI map is up to date for this saved scan."
    if running:
        return "AI mapping is running now and still has work left."
    if failed + failed_map:
        return "AI mapping has unfinished failures and is not current."
    if state == "not_started":
        return "AI mapping has not been prepared for this saved scan."
    return "AI mapping is incomplete, and no worker is running right now."


def _progress(enabled: bool, total: int, current: int, excluded: int) -> str:
    if not enabled:
        return "The non-AI file and direct-link map remains available."
    if not total:
        return "No included files have been prepared for AI description yet."
    result = (
        f"{current} of {total} included files have a current AI description of both the file "
        "itself and its role in this repository."
    )
    if excluded:
        result += f" {_items(excluded, 'file is', 'files are')} deliberately outside AI mapping."
    return result


def _work_state(enabled: bool, ready: bool, running: bool, pending: int, failed: int) -> str:
    if not enabled:
        return "No AI worker is needed while this feature is off."
    if ready:
        return "No AI-mapping work remains for the current saved scan."
    if running:
        return "A worker is processing saved work now; each completed result is stored immediately."
    if pending:
        return (
            "No worker is processing the task list right now. Unfinished work is safely saved and can "
            "be resumed, but it will not finish until a worker starts."
        )
    if failed:
        return "No worker is running, and failed work must be retried before the map can become current."
    return "No worker is running, and final whole-repository map work still needs to be prepared."


def _remaining_work(
    status: Mapping[str, Any], pending: int, pending_map: int, failed: int, failed_map: int
) -> list[str]:
    values = []
    if pending:
        values.append(
            f"{_items(pending, 'file description is', 'file descriptions are')} unfinished or waiting for a refresh."
        )
    if pending_map:
        values.append(
            f"{_items(pending_map, 'repository-wide task is', 'repository-wide tasks are')} unfinished. These can include grouping files by their jobs, describing the whole repository, and checking patterns."
        )
    if failed:
        values.append(
            f"{_items(failed, 'file description', 'file descriptions')} failed and must be retried."
        )
    if failed_map:
        values.append(
            f"{_items(failed_map, 'repository-wide task', 'repository-wide tasks')} failed and must be retried."
        )
    taxonomy = _mapping(status.get("taxonomy"))
    if taxonomy.get("enabled") and not taxonomy.get("ready"):
        values.append("The AI-created grouping of files has not finished its automatic checks yet.")
    if _mapping(status.get("budget")).get("paused"):
        values.append(
            "AI work using a separate paid model is paused because the next call would exceed today's budget."
        )
    return values or ["No unfinished AI-mapping work is reported."]


def _actions(status: Mapping[str, Any], enabled: bool, ready: bool, running: bool) -> list[str]:
    if ready:
        return ["No action is needed unless the repository or analysis rules change."]
    action = _mapping(status.get("recommended_action"))
    kind = str(action.get("kind") or "")
    command = str(action.get("command") or "").strip()
    status_command = str(action.get("status_command") or "").strip()
    if not enabled or kind == "enable_semantics":
        return ["Enable AI mapping in the repository's active AnaxiGraph settings."]
    if kind == "scan_required":
        return ["Run a read-only repository scan, then prepare AI mapping again."]
    if running or kind == "monitor":
        return _monitor_actions(command)
    if kind == "durable_host_executor":
        return _durable_worker_actions(command, status_command)
    if kind == "bounded_mcp_fallback":
        return [
            "For a small task list, a connected coding agent can repeatedly request and submit one piece "
            "of saved work at a time until the tool reports that the map is complete."
        ]
    message = str(action.get("message") or "").strip()
    return [
        message or "Start or resume an AI worker, then keep it running until the map is complete."
    ]


def _monitor_actions(command: str) -> list[str]:
    result = ["Keep the current worker running until this status says the map is complete."]
    if command:
        result.append(f"Check saved progress with: {command}")
    return result


def _durable_worker_actions(command: str, status_command: str) -> list[str]:
    result = [
        "Start a background coding-agent worker. It resumes saved work and keeps taking the next task "
        "until the map is complete."
    ]
    if command:
        result.append(f"Start it with: {command}")
    if status_command:
        result.append(f"Check saved progress with: {status_command}")
    return result


def _reading_guide(status: Mapping[str, Any], total: int) -> list[str]:
    snapshot = status.get("snapshot_id")
    values = [
        (
            f"Up to date means the saved AI descriptions match saved scan {snapshot} and the current "
            "code-reading rules."
            if snapshot is not None
            else "Up to date means the saved AI descriptions match the selected saved scan and current code-reading rules."
        ),
        (
            f"Progress measures how many of the {total} included files have complete current "
            "descriptions; it is not a grade for the code."
            if total
            else "Progress counts complete current file descriptions; it is not a grade for the code."
        ),
        "AI mapping writes only to AnaxiGraph's external index; it does not edit repository source.",
    ]
    if str(status.get("provider") or "") == "agent":
        values.append(
            "The connected coding agent chooses its runtime model and reasoning effort. AnaxiGraph "
            "does not hardcode either one into the saved understanding of the code."
        )
    return values


def _running(status: Mapping[str, Any]) -> bool:
    jobs = _mapping(status.get("jobs"))
    worker = _mapping(status.get("worker"))
    return _count(jobs.get("running_live", jobs.get("running"))) > 0 or str(
        worker.get("status") or ""
    ) in {"queued", "running"}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _count(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _items(value: int, singular: str, plural: str) -> str:
    return f"{value} {singular if value == 1 else plural}"

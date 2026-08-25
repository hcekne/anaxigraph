from __future__ import annotations

import pytest

from anaxigraph.semantic_status_language import semantic_status_explanation


def _pending_status(**changes):
    value = {
        "enabled": True,
        "provider": "agent",
        "state": "pending",
        "snapshot_id": 42,
        "semantically_ready": False,
        "eligible_modules": 265,
        "current": 161,
        "pending": 100,
        "pending_scopes": 4,
        "failed": 0,
        "failed_scopes": 0,
        "excluded": 3,
        "jobs": {"running_live": 0},
        "worker": {"status": "idle"},
        "taxonomy": {"enabled": True, "ready": False},
        "patterns": {"pending": 2},
        "budget": {"paused": False},
        "recommended_action": {
            "kind": "durable_host_executor",
            "command": "anaxigraph understand <repository> --executor codex --background",
            "status_command": "anaxigraph semantic-status <repository>",
        },
    }
    value.update(changes)
    return value


def test_idle_queue_says_saved_work_will_not_finish_by_itself():
    result = semantic_status_explanation(_pending_status())

    assert result["version"] == "semantic-status-explanation-v1"
    assert result["conclusion"] == ("AI mapping is incomplete, and no worker is running right now.")
    assert result["progress"].startswith("161 of 265 included files")
    assert "will not finish until a worker starts" in result["work_state"]
    assert any("100 file descriptions are unfinished" in item for item in result["remaining_work"])
    assert any("Start a background coding-agent worker" in item for item in result["what_to_do"])
    assert any("does not hardcode" in item for item in result["how_to_read_progress"])
    assert "dossier" not in str(result)
    assert "synthesis scope" not in str(result)


def test_live_worker_says_work_is_running_and_saved_as_it_finishes():
    status = _pending_status(
        jobs={"running_live": 2},
        worker={"status": "running"},
        recommended_action={
            "kind": "monitor",
            "command": "anaxigraph semantic-status <repository>",
        },
    )

    result = semantic_status_explanation(status)

    assert result["conclusion"] == "AI mapping is running now and still has work left."
    assert "each completed result is stored immediately" in result["work_state"]
    assert result["what_to_do"][0].startswith("Keep the current worker running")


def test_current_map_explains_that_progress_is_not_code_quality():
    status = _pending_status(
        state="ready",
        semantically_ready=True,
        current=265,
        pending=0,
        pending_scopes=0,
        taxonomy={"enabled": True, "ready": True},
        recommended_action={"kind": "none", "message": "The semantic map is current."},
    )

    result = semantic_status_explanation(status)

    assert result["conclusion"] == "The AI map is current for this repository snapshot."
    assert result["work_state"] == "No AI-mapping work remains for the current snapshot."
    assert result["what_to_do"] == [
        "No action is needed unless the repository or analysis rules change."
    ]
    assert any("not a grade for the code" in item for item in result["how_to_read_progress"])
    assert any("does not edit repository source" in item for item in result["how_to_read_progress"])


def test_failures_and_budget_pause_are_described_as_blocking_work():
    result = semantic_status_explanation(
        _pending_status(
            pending=0,
            pending_scopes=0,
            failed=2,
            failed_scopes=1,
            budget={"paused": True},
            recommended_action={"kind": "bounded_mcp_fallback"},
        )
    )

    assert result["conclusion"] == "AI mapping has unfinished failures and is not current."
    assert any("2 file descriptions failed" in item for item in result["remaining_work"])
    assert any("Hosted-model work is paused" in item for item in result["remaining_work"])


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (
            {"enabled": False, "state": "not_started"},
            "AI mapping is turned off for this repository.",
        ),
        (
            {"enabled": True, "state": "not_indexed"},
            "AI mapping cannot start because this repository has not been scanned yet.",
        ),
    ],
)
def test_disabled_and_unscanned_states_have_direct_conclusions(status, expected):
    assert semantic_status_explanation(status)["conclusion"] == expected

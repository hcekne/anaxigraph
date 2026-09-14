"""A skipped stage must read as skipped, not as work that passed.

Pattern review is off by default because enabling it is expensive. With it off the status
still reported the pattern stage as ready and concluded that the map was up to date, so a
reader saw full coverage and no pattern findings and had nothing telling them why.
"""

from __future__ import annotations

from typing import Any

from anaxigraph.semantic_reporting import compact_semantic_status
from anaxigraph.semantic_status_language import semantic_status_explanation


def _status(**patterns: Any) -> dict[str, Any]:
    return {
        "state": "ready",
        "enabled": True,
        "semantically_ready": True,
        "current": 2018,
        "eligible_modules": 2018,
        "patterns": {"enabled": False, "ready": False, "pending": 0, "failed": 0, **patterns},
    }


def test_a_disabled_stage_is_not_reported_as_ready():
    assert _status()["patterns"]["ready"] is False


def test_the_conclusion_says_the_stage_was_turned_off():
    conclusion = semantic_status_explanation(_status())["conclusion"]

    assert "Detailed pattern review is turned off" in conclusion
    assert "no pattern findings were produced" in conclusion


def test_a_complete_run_with_the_stage_enabled_reads_as_before():
    conclusion = semantic_status_explanation(
        _status(enabled=True, ready=True),
    )["conclusion"]

    assert conclusion == "The AI map is up to date for this saved scan."


def test_compact_status_carries_the_stage_rather_than_hiding_it():
    compact = compact_semantic_status(_status())

    assert compact["patterns"]["enabled"] is False
    assert compact["patterns"]["ready"] is False


def test_a_status_without_a_pattern_object_keeps_the_plain_conclusion():
    status = _status()
    status.pop("patterns")

    assert semantic_status_explanation(status)["conclusion"] == (
        "The AI map is up to date for this saved scan."
    )

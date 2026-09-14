"""Ranking a ledger must not write prose for rows nobody will read.

A repository with 61,636 findings took over a minute to return a page of five, because
every row was written up in full before filtering and paging. Almost all of that work was
discarded. Ranking needs the score, the reasons and the actionability; the sentences are
needed only for the rows actually returned.
"""

from __future__ import annotations

from typing import Any

from anaxigraph.persistence import finding_read
from anaxigraph.persistence.finding_read import finding_priority, finding_prose


def _finding(index: int) -> dict[str, Any]:
    return {
        "id": index,
        "stable_key": f"key-{index}",
        "finding_type": "symbol_complexity",
        "severity": "warning",
        "confidence": 1.0,
        "status": "new",
        "affected_artifacts": ["pkg/core.py"],
        "evidence": ["estimated_cyclomatic_complexity=17"],
    }


def test_ranking_a_finding_does_not_write_its_prose():
    ranked = finding_priority(_finding(1), {})

    assert "priority_score" in ranked
    assert "actionability" in ranked
    assert "plain_language" not in ranked


def test_the_actionability_ranking_depends_on_is_still_computed_for_every_row():
    # _areas() reads actionability.affected.architecture_areas to filter and group, so
    # deferring it would break the architecture_area filter rather than merely slow it.
    ranked = finding_priority(_finding(1), {})

    assert "architecture_areas" in (ranked["actionability"].get("affected") or {})


def test_prose_is_written_once_and_reused():
    finding = _finding(1)
    finding.update(finding_priority(finding, {}))

    first = finding_prose(finding)["plain_language"]
    again = finding_prose(finding)["plain_language"]

    assert first is again


def test_prose_is_generated_only_for_the_rows_a_page_returns(monkeypatch):
    written: list[int] = []
    original = finding_read.plain_language_contract

    def counted(finding, **kwargs):
        written.append(int(finding.get("id") or 0))
        return original(finding, **kwargs)

    monkeypatch.setattr(finding_read, "plain_language_contract", counted)
    ledger = [_finding(index) for index in range(500)]
    for item in ledger:
        item.update(finding_priority(item, {}))

    assert written == []

    for item in ledger[:5]:
        finding_prose(item)

    assert written == [0, 1, 2, 3, 4]


def test_a_finding_that_already_carries_prose_is_left_alone():
    finding = _finding(1)
    finding["plain_language"] = {"version": "already-here"}

    assert finding_prose(finding)["plain_language"] == {"version": "already-here"}

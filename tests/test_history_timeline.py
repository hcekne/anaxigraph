from __future__ import annotations

from anaxigraph.api_history_routes import _timeline_summary


def _frame(identifier: int, revision: str, kind: str = "commit") -> dict:
    return {"id": identifier, "commit_sha": revision, "snapshot_kind": kind}


def test_timeline_marks_the_real_gap_before_a_current_working_tree():
    revisions = [f"commit-{index}" for index in range(10)]
    frames = [
        _frame(1, revisions[0]),
        _frame(2, revisions[2]),
        _frame(3, revisions[-1], "working_tree"),
    ]

    summary = _timeline_summary(frames, revisions, {"status": "not_started"})

    assert summary["state"] == "stale"
    assert summary["unmapped_tail_commits"] == 7
    assert summary["needs_update"] is True


def test_timeline_is_current_only_when_representative_commit_maps_reach_head():
    revisions = [f"commit-{index}" for index in range(6)]
    frames = [
        _frame(1, revisions[0]),
        _frame(2, revisions[2]),
        _frame(3, revisions[4]),
        _frame(4, revisions[5]),
    ]

    summary = _timeline_summary(
        frames, revisions, {"status": "complete", "result": {"latest_commit": revisions[-1]}}
    )

    assert summary["state"] == "current"
    assert summary["saved_commit_maps"] == 4
    assert summary["unmapped_tail_commits"] == 0
    assert summary["needs_update"] is False

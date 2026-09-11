"""The real-task harness must refuse to imply more than it measured.

The risk with a benchmark is not that it fails. It is that it prints a number nobody can
trace, from tasks the tool was already tuned on, graded by someone who knew which answer
came from the tool. These tests hold the harness to the opposite of each of those.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from benchmarks.architecture_tasks import (
    FIXTURE,
    blinded_labels,
    fixture_problems,
    grading_sheet,
    load_tasks,
    merge_grades,
    task_request,
    task_summary,
)


def _task(**overrides: Any) -> dict[str, Any]:
    task = {
        "id": "sample",
        "revision": "a" * 40,
        "question": "Should this module be split?",
        "held_out": True,
        "budget": {"max_output_tokens": 6000},
        "reference": {
            "answer": "Keep it; nothing in it is reached from nothing else.",
            "key_points": ["No seam exists.", "A split would spread one change."],
            "author": "a reviewer",
            "author_kind": "human",
            "recorded_at": "2026-09-11",
            "recorded_from": "a review",
        },
    }
    task.update(overrides)
    return task


def _graded(task: dict[str, Any], **grades: Any) -> list[dict[str, Any]]:
    sheet = grading_sheet([task], {task["id"]: "The model answer."})
    labels = blinded_labels(task)
    for label, source in labels.items():
        sheet["tasks"][0]["grade"][label] = grades[source]
    return merge_grades([task], sheet)


_FULL = {
    "covered_key_points": ["No seam exists.", "A split would spread one change."],
    "unsupported_claims": [],
    "grader_uncertain": False,
}


def test_the_committed_fixture_is_gradable():
    assert fixture_problems(load_tasks(FIXTURE)) == []


def test_a_task_without_a_recorded_author_is_refused_before_any_model_runs():
    broken = _task()
    broken["reference"] = {**broken["reference"], "author": ""}

    assert any("no author" in problem for problem in fixture_problems([broken]))


def test_a_task_that_was_already_acted_on_must_say_so():
    assert any("must say why" in problem for problem in fixture_problems([_task(held_out=False)]))


def test_one_key_point_is_too_few_to_grade_against():
    thin = _task()
    thin["reference"] = {**thin["reference"], "key_points": ["only one"]}

    assert any("fewer than two key points" in problem for problem in fixture_problems([thin]))


def test_the_model_is_asked_the_question_under_the_recorded_budget():
    request = task_request(_task())

    assert request["review_goal"] == "Should this module be split?"
    assert request["max_output_tokens"] == 6000


def test_the_grading_sheet_never_says_which_answer_came_from_where():
    sheet = grading_sheet([_task()], {"sample": "Split it along the seam."})
    text = json.dumps(sheet).lower()

    assert {entry["label"] for entry in sheet["tasks"][0]["answers"]} == {"answer-1", "answer-2"}
    assert set(sheet["tasks"][0]["grade"]) == {"answer-1", "answer-2"}
    assert "model" not in text
    assert "reference" not in text


def test_the_same_task_is_labelled_the_same_way_every_run():
    assert blinded_labels(_task()) == blinded_labels(_task())
    assert set(blinded_labels(_task()).values()) == {"model", "reference"}


def test_two_tasks_do_not_all_put_the_model_in_the_same_slot():
    labels = [blinded_labels(_task(id=f"task-{index}"))["answer-1"] for index in range(12)]

    assert len(set(labels)) == 2


def test_a_missed_key_point_is_named_rather_than_reduced_to_a_score():
    merged = _graded(
        _task(),
        model={
            "covered_key_points": ["No seam exists."],
            "unsupported_claims": [],
            "grader_uncertain": False,
        },
        reference=_FULL,
    )

    summary = task_summary(merged)

    assert summary["misses"] == {"sample": ["A split would spread one change."]}
    assert summary["coverage"] == {"model": 1, "reference": 2}


def test_an_unsupported_claim_is_disclosed_alongside_coverage():
    merged = _graded(
        _task(),
        model={**_FULL, "unsupported_claims": ["Claims a caller that does not exist."]},
        reference=_FULL,
    )

    summary = task_summary(merged)

    assert summary["unsupported_claims"] == {"sample": ["Claims a caller that does not exist."]}
    assert "model_key_point_rate" in summary


def test_a_headline_is_withheld_when_the_grader_was_unsure():
    merged = _graded(_task(), model={**_FULL, "grader_uncertain": True}, reference=_FULL)

    summary = task_summary(merged)

    assert "model_key_point_rate" not in summary
    assert summary["ungraded_for_uncertainty"] == ["sample"]
    assert any("not confident" in reason for reason in summary["headline_withheld"])


def test_a_headline_is_withheld_for_tasks_the_tool_was_already_changed_for():
    task = _task(held_out=False, disclosure="Acted on in an earlier commit.")

    summary = task_summary(_graded(task, model=_FULL, reference=_FULL))

    assert "model_key_point_rate" not in summary
    assert any("already acted on" in reason for reason in summary["headline_withheld"])


def test_a_headline_is_withheld_until_a_human_wrote_the_reference_answer():
    task = _task()
    task["reference"] = {**task["reference"], "author_kind": "model_panel"}

    summary = task_summary(_graded(task, model=_FULL, reference=_FULL))

    assert "model_key_point_rate" not in summary
    assert any("not written by a human" in reason for reason in summary["headline_withheld"])


def test_a_grade_naming_a_key_point_nobody_recorded_is_not_counted():
    merged = _graded(
        _task(),
        model={**_FULL, "covered_key_points": [*_FULL["covered_key_points"], "Invented point."]},
        reference=_FULL,
    )

    assert merged[0]["sources"]["model"]["covered"] == 2


def test_the_committed_fixture_reports_its_own_limits():
    tasks = copy.deepcopy(load_tasks(FIXTURE))
    sheet = grading_sheet(tasks, {task["id"]: "" for task in tasks})
    for entry in sheet["tasks"]:
        for label in entry["grade"]:
            entry["grade"][label] = _FULL

    summary = task_summary(merge_grades(tasks, sheet))

    assert "model_key_point_rate" not in summary
    assert summary["held_out_tasks"] == 0
    assert summary["human_reference_answers"] == 1
    assert Path(FIXTURE).is_file()

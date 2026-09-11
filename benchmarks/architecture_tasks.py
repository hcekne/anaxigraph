"""Real architecture tasks answered under a recorded budget and graded blind.

The judgment benchmark next door asks controlled synthetic questions whose answer is one
label from a fixed set. That measures whether a model applies a stated rule. It cannot
measure whether an answer to a real question is any good, because a real answer is prose
and its quality is whether it names the things a knowledgeable reader would name.

So this harness keeps the two jobs apart. It runs the model on each task under the budget
the reference answer was written to, then writes a grading sheet where the model answer and
the recorded reference answer appear under opaque labels, and a key file that maps the
labels back. A grader reads only the sheet. The report is assembled from the grades and the
key afterwards, and it leads with what was covered and what was missed rather than a score.

Nothing here claims accuracy on its own. A task that was already acted on is a rehearsal of
the protocol, not evidence about a model, and the summary withholds any headline number
until every task is held out and every reference answer names a human author.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from anaxigraph.config import SemanticConfig
from anaxigraph.semantic import CodexSemanticProvider
from anaxigraph.semantic_contract import SEMANTIC_SCHEMA_VERSION
from anaxigraph.semantic_evidence_selection import evidence_bytes
from anaxigraph.semantic_freshness import semantic_digest
from benchmarks.architecture_judgment import run_stage

FIXTURE = Path(__file__).parent / "fixtures" / "architecture-tasks.json"
TASK_CONTRACT = "architecture-tasks-v1"
_AUTHOR_KINDS = ("human", "model_panel", "model")
_REQUIRED = ("id", "revision", "question", "budget", "reference", "held_out")


def load_tasks(path: Path = FIXTURE) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))["tasks"]


def fixture_problems(tasks: list[dict[str, Any]]) -> list[str]:
    """Reject a task that cannot be graded honestly, before any model is paid for."""

    problems: list[str] = []
    seen: set[str] = set()
    for index, task in enumerate(tasks):
        name = str(task.get("id") or f"task {index}")
        problems.extend(f"{name}: {issue}" for issue in _task_problems(task, name in seen))
        seen.add(name)
    return problems


def _task_problems(task: dict[str, Any], duplicate: bool) -> list[str]:
    missing = [field for field in _REQUIRED if field not in task]
    if missing:
        return [f"missing {', '.join(missing)}"]
    reference = task["reference"]
    checks = [
        (duplicate, "duplicate task id"),
        (len(reference.get("key_points") or []) < 2, "fewer than two key points to grade against"),
        (
            str(reference.get("author_kind")) not in _AUTHOR_KINDS,
            f"author_kind must be one of {', '.join(_AUTHOR_KINDS)}",
        ),
        (
            not task["held_out"] and not str(task.get("disclosure") or "").strip(),
            "a task that is not held out must say why",
        ),
        (
            not int(task["budget"].get("max_output_tokens") or 0),
            "no output-token budget to match the reference answer",
        ),
    ]
    checks.extend(
        (not str(reference.get(field) or "").strip(), f"reference answer has no {field}")
        for field in ("answer", "author", "recorded_at", "recorded_from")
    )
    return [issue for failed, issue in checks if failed]


def task_request(task: dict[str, Any]) -> dict[str, Any]:
    """Ask the real question with the same sources and the same budget, nothing more."""

    return {
        "contract": (
            "Answer the review goal for the supplied sources. Rank only changes that materially "
            "advance the stated mission, say what each one replaces, and treat retaining the "
            "current design as a valid answer when the evidence supports it. This is advice, not "
            "permission to edit code."
        ),
        "schema_version": SEMANTIC_SCHEMA_VERSION,
        "analysis_kind": "fresh_review",
        "review_goal": task["question"],
        "mission": task.get("mission", "Explain this repository's architecture to a new reader."),
        "max_output_tokens": int(task["budget"]["max_output_tokens"]),
        "current_system": [
            {"path": path, "source": source} for path, source in (task.get("sources") or {}).items()
        ],
        "declared_context": task.get("facts") or [],
    }


def answer_task(task: dict[str, Any], provider: Any) -> dict[str, Any]:
    request = task_request(task)
    started = time.monotonic()
    stages: list[dict[str, Any]] = []
    try:
        result = run_stage(provider, request, stages)
        answer = _answer_text(result.value)
        error = None
    except Exception as failure:  # noqa: BLE001 - a failed task is reported, not raised
        answer, error = "", f"{type(failure).__name__}: {failure}"
    return {
        "id": task["id"],
        "revision": task["revision"],
        "answer": answer,
        "error": error,
        "request_bytes": evidence_bytes(request),
        "duration_seconds": round(time.monotonic() - started, 3),
        "stages": stages,
    }


def _answer_text(value: dict[str, Any]) -> str:
    lines = []
    for item in value.get("recommendations") or []:
        lines.append(f"{item.get('rank')}. {item.get('title')} [{item.get('action')}]")
        for field in ("smallest_change", "expected_benefit", "reference_insight"):
            if item.get(field):
                lines.append(f"   {field.replace('_', ' ')}: {item[field]}")
    return "\n".join(lines) or json.dumps(value, sort_keys=True)


def blinded_labels(task: dict[str, Any]) -> dict[str, str]:
    """Assign labels from the task itself, so the order is neither guessable nor random."""

    first = int(semantic_digest({"id": task["id"], "revision": task["revision"]})[:1], 16) % 2
    return (
        {"answer-1": "model", "answer-2": "reference"}
        if first == 0
        else {"answer-1": "reference", "answer-2": "model"}
    )


def grading_sheet(tasks: list[dict[str, Any]], answers: dict[str, str]) -> dict[str, Any]:
    """Everything a grader needs and nothing that says which answer came from where."""

    sheets = []
    for task in tasks:
        labels = blinded_labels(task)
        text = {"model": answers.get(task["id"], ""), "reference": task["reference"]["answer"]}
        sheets.append(
            {
                "id": task["id"],
                "question": task["question"],
                "key_points": task["reference"]["key_points"],
                "answers": [
                    {"label": label, "text": text[labels[label]]} for label in sorted(labels)
                ],
                "grade": {
                    label: {
                        "covered_key_points": [],
                        "unsupported_claims": [],
                        "grader_uncertain": True,
                    }
                    for label in sorted(labels)
                },
            }
        )
    return {"contract": TASK_CONTRACT, "instructions": _GRADER_INSTRUCTIONS, "tasks": sheets}


_GRADER_INSTRUCTIONS = (
    "For each answer, list the key points it actually covers, list claims it makes that the "
    "sources do not support, and set grader_uncertain to false only once you are confident in "
    "both lists. Do not try to work out which answer came from where; if you form a belief "
    "about it, say so in unsupported_claims so the report can disclose it."
)


def merge_grades(tasks: list[dict[str, Any]], sheet: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn labelled grades back into per-source results using the task's own labelling."""

    graded = {item["id"]: item for item in sheet["tasks"]}
    merged = []
    for task in tasks:
        entry = graded.get(task["id"])
        if entry is None:
            continue
        labels = blinded_labels(task)
        total = len(task["reference"]["key_points"])
        sources: dict[str, Any] = {}
        for label, source in labels.items():
            grade = entry["grade"][label]
            covered = [
                point
                for point in grade["covered_key_points"]
                if point in task["reference"]["key_points"]
            ]
            sources[source] = {
                "covered": len(covered),
                "missed": [
                    point for point in task["reference"]["key_points"] if point not in covered
                ],
                "unsupported_claims": list(grade["unsupported_claims"]),
                "grader_uncertain": bool(grade["grader_uncertain"]),
            }
        merged.append(
            {
                "id": task["id"],
                "key_points": total,
                "held_out": bool(task["held_out"]),
                "reference_author_kind": task["reference"]["author_kind"],
                "sources": sources,
            }
        )
    return merged


def _withheld_reasons(merged: list[dict[str, Any]]) -> list[str]:
    """Every reason a rate computed from these grades would mislead a reader."""

    reasons = [
        (not merged, "no graded tasks"),
        (
            any(not item["held_out"] for item in merged),
            "some tasks were already acted on, so they rehearse the protocol only",
        ),
        (
            any(item["reference_author_kind"] != "human" for item in merged),
            "some reference answers were not written by a human expert",
        ),
        (
            any(
                source["grader_uncertain"] for item in merged for source in item["sources"].values()
            ),
            "the grader was not confident on at least one answer",
        ),
    ]
    return [reason for failed, reason in reasons if failed]


def task_summary(merged: list[dict[str, Any]]) -> dict[str, Any]:
    """Report what was covered and what was missed first, and say what this cannot support."""

    withheld = _withheld_reasons(merged)
    summary: dict[str, Any] = {
        "tasks_graded": len(merged),
        "held_out_tasks": sum(item["held_out"] for item in merged),
        "human_reference_answers": sum(item["reference_author_kind"] == "human" for item in merged),
        "key_points_total": sum(item["key_points"] for item in merged),
        "coverage": {
            source: sum(item["sources"].get(source, {}).get("covered", 0) for item in merged)
            for source in ("model", "reference")
        },
        "misses": {
            item["id"]: item["sources"].get("model", {}).get("missed", []) for item in merged
        },
        "unsupported_claims": {
            item["id"]: item["sources"].get("model", {}).get("unsupported_claims", [])
            for item in merged
        },
        "ungraded_for_uncertainty": [
            item["id"]
            for item in merged
            if any(source["grader_uncertain"] for source in item["sources"].values())
        ],
    }
    summary["misses"] = {key: value for key, value in summary["misses"].items() if value}
    summary["unsupported_claims"] = {
        key: value for key, value in summary["unsupported_claims"].items() if value
    }
    if withheld:
        summary["headline_withheld"] = withheld
    else:
        summary["model_key_point_rate"] = round(
            summary["coverage"]["model"] / max(1, summary["key_points_total"]), 3
        )
    return summary


def _revision() -> dict[str, Any]:
    return {
        "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], text=True)),
    }


def _run(args: argparse.Namespace) -> int:
    tasks = load_tasks(args.fixture)
    problems = fixture_problems(tasks)
    if problems:
        print("\n".join(problems))
        return 2
    budget = max(int(task["budget"]["max_output_tokens"]) for task in tasks)
    provider = CodexSemanticProvider(
        SemanticConfig(
            enabled=True,
            provider="codex",
            model=args.model,
            reasoning_effort=args.reasoning_effort,
            timeout_seconds=1200,
            max_output_tokens=budget,
        )
    )
    answers = [answer_task(task, provider) for task in tasks]
    args.sheet.write_text(
        json.dumps(
            grading_sheet(tasks, {item["id"]: item["answer"] for item in answers}),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    args.answers.write_text(
        json.dumps(
            {
                "contract": TASK_CONTRACT,
                "created_at": datetime.now(UTC).isoformat(),
                "model": args.model,
                "reasoning_effort": args.reasoning_effort,
                **_revision(),
                "fixture_fingerprint": semantic_digest(tasks),
                "answers": answers,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Grade {args.sheet} without opening {args.answers}, then run the report command.")
    return 0


def _report(args: argparse.Namespace) -> int:
    tasks = load_tasks(args.fixture)
    sheet = json.loads(args.sheet.read_text(encoding="utf-8"))
    merged = merge_grades(tasks, sheet)
    report = {
        "contract": TASK_CONTRACT,
        "created_at": datetime.now(UTC).isoformat(),
        **_revision(),
        "fixture_fingerprint": semantic_digest(tasks),
        "tasks": merged,
        "summary": task_summary(merged),
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Answer every task and write a blinded grading sheet")
    run.add_argument("--model", required=True)
    run.add_argument("--reasoning-effort", required=True)
    run.add_argument("--sheet", type=Path, required=True)
    run.add_argument("--answers", type=Path, required=True)
    run.set_defaults(handler=_run)
    report = commands.add_parser("report", help="Assemble results from a completed grading sheet")
    report.add_argument("--sheet", type=Path, required=True)
    report.add_argument("--output", type=Path, required=True)
    report.set_defaults(handler=_report)
    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())

"""Opt-in paired maintenance tasks in fresh CLI contexts, with isolated change checks."""

from __future__ import annotations

import argparse
import json
import secrets
import statistics
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from anaxigraph.config import SemanticConfig
from anaxigraph.semantic import _codex_command
from anaxigraph.semantic_contract import _validate_schema
from anaxigraph.semantic_freshness import semantic_digest
from anaxigraph.semantic_usage import codex_usage

FIXTURE = Path(__file__).parent / "fixtures" / "understandability.json"
TASKS = {
    "locate_validation": "Locate the function rejecting nonpositive order quantities. Return its owner as path::function.",
    "trace_failure": "An order with qty=0 and shipping='standard' is submitted. Return the exception class and the number of sink.reserve calls.",
    "extend_shipping": "Support shipping='express' for a fee of 15. Preserve standard shipping, the public submit interface, and validation before reservation. Return complete replacement source for each changed existing Python file.",
}


def object_schema(**properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


SCHEMAS = {
    "locate_validation": object_schema(owner={"type": "string"}),
    "trace_failure": object_schema(
        exception={"type": "string"}, reservation_calls={"type": "integer"}
    ),
    "extend_shipping": object_schema(
        changes={
            "type": "array",
            "minItems": 1,
            "maxItems": 3,
            "items": object_schema(
                path={"type": "string"}, source={"type": "string", "maxLength": 20_000}
            ),
        }
    ),
}

CHECKS = """
import sys
sys.path.insert(0, '/workspace')
from checkout import submit
class Sink:
    def __init__(self): self.events = []
    def reserve(self, sku, qty): self.events.append((sku, qty))
for shipping, fee in [('standard', 5), ('express', 15)]:
    for qty, price in [(1, 0), (2, 10), (3, 7)]:
        sink = Sink()
        result = submit(order={'sku': 'book', 'qty': qty, 'price': price, 'shipping': shipping}, sink=sink)
        assert result == qty * price + fee
        assert sink.events == [('book', qty)]
for qty, shipping in [(0, 'standard'), (-1, 'express'), (2, 'unsupported')]:
    sink = Sink()
    try:
        submit({'sku': 'book', 'qty': qty, 'price': 10, 'shipping': shipping}, sink)
    except ValueError:
        pass
    else:
        raise AssertionError('invalid order accepted')
    assert sink.events == []
"""


def task_request(fixture, phase, task):
    # Never reveal phase names, expected answers, the other implementation, or hidden checks.
    return {
        "task": TASKS[task],
        "files": {**fixture["common_files"], **fixture[phase]["files"]},
        "instructions": (
            "Use only these repository files, including the glossary, decision, and navigation. "
            "You have no prior repository context or generated architecture explanation. "
            "Return JSON matching the supplied output schema. Do not use outside tools or sources."
        ),
    }


def solve(request, schema, config):
    with tempfile.TemporaryDirectory(prefix="anaxigraph-reader-") as directory:
        root = Path(directory)
        schema_path, result_path = root / "schema.json", root / "answer.json"
        schema_path.write_text(json.dumps(schema))
        completed = subprocess.run(
            _codex_command(config, schema_path, result_path),
            input=json.dumps(request),
            text=True,
            capture_output=True,
            cwd=root,
            timeout=config.timeout_seconds,
            check=True,
        )
        answer = json.loads(result_path.read_text())
        _validate_schema(answer, schema, "reader answer")
        usage = codex_usage(completed.stdout)
        return answer, {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "usage_reported": usage.reported,
        }


def grade(fixture, phase, task, answer, image):
    _validate_schema(answer, SCHEMAS[task], "reader answer")
    if task == "locate_validation":
        return answer["owner"] == fixture[phase]["owner"]
    if task == "trace_failure":
        return answer == {"exception": "ValueError", "reservation_calls": 0}
    return verify_change(fixture[phase]["files"], answer["changes"], image)


def verify_change(files, changes, image):
    paths = [item["path"] for item in changes]
    if len(paths) != len(set(paths)) or any(
        path not in files or not path.endswith(".py") for path in paths
    ):
        raise ValueError("Changes must name unique existing Python files")
    with tempfile.TemporaryDirectory(prefix="anaxigraph-reader-check-") as directory:
        success = f"reader-checks-passed-{secrets.token_hex(16)}"
        root = Path(directory)
        root.chmod(0o755)
        for path, source in {**files, **{item["path"]: item["source"] for item in changes}}.items():
            (root / path).write_text(source)
        completed = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--pull=never",
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--pids-limit=64",
                "--memory=128m",
                "--cpus=1",
                "--user=65534:65534",
                "--mount",
                f"type=bind,src={root},dst=/workspace,readonly",
                "--workdir=/workspace",
                image,
                "python",
                "-I",
                "-B",
                "-c",
                CHECKS + f"\nprint({success!r})",
            ],
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        if completed.returncode in {125, 126, 127}:
            raise RuntimeError(f"Isolated verifier unavailable: {completed.stderr[:300]}")
        return completed.returncode == 0 and success in completed.stdout.splitlines()


def summarize(results):
    comparison = {}
    for task in TASKS:
        comparison[task] = {}
        for phase in ("before", "after"):
            trials = [item for item in results if item["task"] == task and item["phase"] == phase]
            successes = [item for item in trials if item.get("correct") is True]
            comparison[task][phase] = {
                "trials": len(trials),
                "correct": len(successes),
                "errors": sum("error" in item for item in trials),
                "median_success_reader_seconds": statistics.median(
                    item["reader_seconds"] for item in successes
                )
                if successes
                else None,
            }
    return comparison


def run_trial(fixture, phase, task, config, image):
    started = time.monotonic()
    result = {"phase": phase, "task": task, "correct": None}
    try:
        answer, usage = solve(task_request(fixture, phase, task), SCHEMAS[task], config)
        result.update(
            answer=answer, usage=usage, reader_seconds=round(time.monotonic() - started, 3)
        )
        result["correct"] = grade(fixture, phase, task, answer, image)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        result["error"] = f"{type(error).__name__}: {error}"[:1_000]
    return {**result, "seconds": round(time.monotonic() - started, 3)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--reasoning-effort", required=True)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument(
        "--verification-image",
        required=True,
        help="Locally available Python image; prefer an immutable digest",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.trials < 1 or args.timeout < 1 or args.output.exists():
        parser.error("Use positive trials/timeout and a new output path")
    inspected = subprocess.run(
        ["docker", "image", "inspect", args.verification_image], check=True, capture_output=True
    )
    verification_image = json.loads(inspected.stdout)[0]["Id"]
    fixture = json.loads(FIXTURE.read_text())
    config = SemanticConfig(
        enabled=True,
        provider="codex",
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        timeout_seconds=args.timeout,
    )
    report = {
        "contract": "repository-reader-benchmark-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "fixture_fingerprint": semantic_digest(fixture),
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "timeout_seconds": args.timeout,
        "verification_image": verification_image,
        "trials_per_task": args.trials,
        "information_boundary": "fresh ephemeral CLI; user config ignored; only fixture files supplied",
        "limits": "Small synthetic tasks with all sources supplied, not a navigation study. CLI isolation is not OS-enforced information isolation. Reader time includes CLI overhead; total time also includes verification. No universal understandability score or production improvement claim.",
        "results": [],
        "complete": False,
    }
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2)
    for repeat in range(args.trials):
        for task in TASKS:
            for phase in ("before", "after") if repeat % 2 == 0 else ("after", "before"):
                result = run_trial(fixture, phase, task, config, verification_image)
                report["results"].append({**result, "trial": repeat + 1})
                report["comparison"] = summarize(report["results"])
                args.output.write_text(json.dumps(report, indent=2) + "\n")
                print(
                    json.dumps(
                        {key: result[key] for key in ("phase", "task", "correct", "seconds")}
                    ),
                    flush=True,
                )
    report["complete"] = True
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    return 1 if any("error" in item for item in report["results"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())

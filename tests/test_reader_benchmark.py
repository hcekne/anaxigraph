from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from anaxigraph.config import SemanticConfig
from benchmarks import understandability as benchmark


@pytest.fixture
def fixture():
    return json.loads(benchmark.FIXTURE.read_text())


@pytest.fixture
def authored_source_verifier(monkeypatch):
    # Only repository-authored synthetic sources in these tests run on the host.
    # The public benchmark always executes model changes in the restricted container.
    run = subprocess.run

    def run_known_fixture(command, **kwargs):
        assert command[:3] == ["docker", "run", "--rm"]
        assert {"--network=none", "--read-only", "--cap-drop=ALL", "--pull=never"} <= set(command)
        mount = command[command.index("--mount") + 1]
        root = mount.split("src=", 1)[1].split(",", 1)[0]
        assert "readonly" in mount
        checks = command[-1].replace("/workspace", root)
        return run([sys.executable, "-I", "-B", "-c", checks], **kwargs)

    monkeypatch.setattr(benchmark.subprocess, "run", run_known_fixture)


def test_reader_receives_only_one_repository_and_no_answers(fixture):
    for phase in ("before", "after"):
        for task in benchmark.TASKS:
            request = benchmark.task_request(fixture, phase, task)
            assert set(request) == {"task", "files", "instructions"}
            assert request["files"] == {**fixture["common_files"], **fixture[phase]["files"]}
            assert "owner" not in request
            assert benchmark.CHECKS not in json.dumps(request)
            assert "GLOSSARY.md" in request["files"]


def test_reading_tasks_check_correctness(fixture):
    for phase in ("before", "after"):
        assert benchmark.grade(
            fixture, phase, "locate_validation", {"owner": fixture[phase]["owner"]}, "unused"
        )
        assert not benchmark.grade(
            fixture, phase, "locate_validation", {"owner": "checkout.py::submit"}, "unused"
        )
        assert benchmark.grade(
            fixture,
            phase,
            "trace_failure",
            {"exception": "ValueError", "reservation_calls": 0},
            "unused",
        )
        assert not benchmark.grade(
            fixture,
            phase,
            "trace_failure",
            {"exception": "ValueError", "reservation_calls": 1},
            "unused",
        )


@pytest.mark.parametrize("phase", ["before", "after"])
def test_executable_change_checks_require_new_behavior_and_preserve_contracts(
    fixture, authored_source_verifier, phase
):
    files = fixture[phase]["files"]
    path = "util.py" if phase == "before" else "orders.py"
    assert not benchmark.verify_change(files, [{"path": path, "source": files[path]}], "test-image")
    if phase == "before":
        source = files[path].replace("!= 'standard'", "not in {'standard', 'express'}")
        source = source.replace("+ 5", "+ (15 if x['shipping'] == 'express' else 5)")
    else:
        source = files[path].replace("{'standard': 5}", "{'standard': 5, 'express': 15}")
    assert benchmark.verify_change(files, [{"path": path, "source": source}], "test-image")
    wrong = source.replace("<= 0", "< -1")
    assert not benchmark.verify_change(files, [{"path": path, "source": wrong}], "test-image")
    assert not benchmark.verify_change(
        files, [{"path": path, "source": "raise SystemExit(0)"}], "test-image"
    )


@pytest.mark.parametrize(
    "paths", [["../escape.py"], ["/tmp/escape.py"], ["orders.py", "orders.py"]]
)
def test_changes_cannot_escape_or_ambiguously_replace_fixture_files(fixture, paths):
    with pytest.raises(ValueError, match="unique existing Python files"):
        benchmark.verify_change(
            fixture["after"]["files"], [{"path": path, "source": ""} for path in paths], "unused"
        )


def test_verifier_failure_is_an_error_not_an_incorrect_answer(fixture, monkeypatch):
    monkeypatch.setattr(
        benchmark.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 125, "", "image missing"),
    )
    with pytest.raises(RuntimeError, match="verifier unavailable"):
        benchmark.verify_change(
            fixture["after"]["files"], [{"path": "orders.py", "source": ""}], "missing"
        )


def test_summary_preserves_failures_and_does_not_invent_effort_for_missing_successes():
    summary = benchmark.summarize(
        [
            {"task": "trace_failure", "phase": "before", "correct": True, "reader_seconds": 2},
            {"task": "trace_failure", "phase": "before", "correct": False, "reader_seconds": 1},
            {"task": "trace_failure", "phase": "after", "correct": None, "error": "timeout"},
        ]
    )
    assert summary["trace_failure"]["before"] == {
        "trials": 2,
        "correct": 1,
        "errors": 0,
        "median_success_reader_seconds": 2,
    }
    assert summary["trace_failure"]["after"] == {
        "trials": 1,
        "correct": 0,
        "errors": 1,
        "median_success_reader_seconds": None,
    }


def test_solver_starts_a_fresh_context_and_validates_the_answer(fixture, monkeypatch):
    def execute(command, **kwargs):
        assert "--ephemeral" in command
        assert "--ignore-user-config" in command
        assert command[command.index("--sandbox") + 1] == "read-only"
        assert kwargs["cwd"] != Path.cwd()
        request = json.loads(kwargs["input"])
        assert set(request) == {"task", "files", "instructions"}
        output = Path(command[command.index("--output-last-message") + 1])
        output.write_text(json.dumps({"owner": "orders.py::validate_order"}))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(benchmark.subprocess, "run", execute)
    answer, usage = benchmark.solve(
        benchmark.task_request(fixture, "after", "locate_validation"),
        benchmark.SCHEMAS["locate_validation"],
        SemanticConfig(model="test-model"),
    )
    assert answer["owner"] == "orders.py::validate_order"
    assert usage["usage_reported"] is False


def test_trial_retains_answer_when_verification_is_unavailable(fixture, monkeypatch):
    monkeypatch.setattr(
        benchmark, "solve", lambda *args: ({"changes": []}, {"usage_reported": False})
    )

    def unavailable(*args):
        raise RuntimeError("Verifier unavailable")

    monkeypatch.setattr(benchmark, "grade", unavailable)
    trial = benchmark.run_trial(fixture, "after", "extend_shipping", SemanticConfig(), "missing")
    assert trial["correct"] is None
    assert trial["answer"] == {"changes": []}
    assert "Verifier unavailable" in trial["error"]


def test_cli_records_repeated_paired_trials_and_preserves_existing_reports(tmp_path, monkeypatch):
    output = tmp_path / "trials.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "reader",
            "--model",
            "test-model",
            "--reasoning-effort",
            "low",
            "--verification-image",
            "fixture",
            "--trials",
            "2",
            "--output",
            str(output),
        ],
    )
    monkeypatch.setattr(
        benchmark.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args, 0, '[{"Id":"sha256:fixture"}]', ""
        ),
    )
    monkeypatch.setattr(
        benchmark, "solve", lambda *args: ({"owner": "fixture"}, {"usage_reported": False})
    )
    monkeypatch.setattr(benchmark, "grade", lambda *args: True)
    assert benchmark.main() == 0
    report = json.loads(output.read_text())
    assert report["complete"] is True
    assert report["verification_image"] == "sha256:fixture"
    assert len(report["results"]) == 12
    assert [item["phase"] for item in report["results"][:2]] == ["before", "after"]
    assert [item["phase"] for item in report["results"][6:8]] == ["after", "before"]
    before = output.read_bytes()
    with pytest.raises(SystemExit):
        benchmark.main()
    assert output.read_bytes() == before

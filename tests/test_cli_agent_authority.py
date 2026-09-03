from __future__ import annotations

import json
from pathlib import Path

import pytest

import anaxigraph.cli_agent_commands as agent_commands
import anaxigraph.semantic_service as semantic_service
from anaxigraph.cli import main
from anaxigraph.semantic_service import SemanticServiceTarget


def test_guidance_uses_the_matching_service_instead_of_a_separate_local_index(
    repository: Path,
    capsys,
    monkeypatch,
):
    target = SemanticServiceTarget("http://127.0.0.1:9999", 7, "Fixture", "/repo")
    captured = {}
    monkeypatch.setattr(agent_commands, "discover_semantic_service", lambda *_a, **_k: target)

    def guidance(service, *, goal, intent, focus):
        captured.update(
            service=service,
            goal=goal,
            intent=intent,
            focus=focus,
        )
        return {"snapshot_id": 42, "goal": goal}

    monkeypatch.setattr(agent_commands, "service_architecture_guidance", guidance)
    main(
        [
            "guide",
            str(repository),
            "--service-url",
            target.base_url,
            "--goal",
            "Measure semantic work",
            "--json",
        ]
    )
    result = json.loads(capsys.readouterr().out)

    assert result["snapshot_id"] == 42
    assert result["index"] == target.identity()
    assert captured == {
        "service": target,
        "goal": "Measure semantic work",
        "intent": "build",
        "focus": "",
    }


@pytest.mark.parametrize(
    ("timeout_arguments", "expected_timeout"),
    [([], 120.0), (["--timeout-seconds", "300"], 300.0)],
)
def test_fresh_eyes_uses_the_matching_service(
    repository: Path, capsys, monkeypatch, timeout_arguments, expected_timeout
):
    target = SemanticServiceTarget("http://127.0.0.1:9999", 7, "Fixture", "/repo")
    captured = {}
    monkeypatch.setattr(agent_commands, "discover_semantic_service", lambda *_a, **_k: target)

    def fresh_eyes(service, **options):
        captured.update(service=service, **options)
        return {"contract_version": "fresh-eyes-review-v1", "state": "in_progress"}

    monkeypatch.setattr(agent_commands, "service_fresh_eyes_review", fresh_eyes)
    main(
        [
            "fresh-eyes",
            str(repository),
            "--service-url",
            target.base_url,
            "--start",
            "--proposals",
            "3",
            "--restart",
            *timeout_arguments,
            "--json",
        ]
    )
    result = json.loads(capsys.readouterr().out)

    assert result["state"] == "in_progress"
    assert result["index"] == target.identity()
    assert captured == {
        "service": target,
        "start": True,
        "proposal_count": 3,
        "retry_failed": False,
        "restart": True,
        "generation": None,
        "compare_with": None,
        "timeout": expected_timeout,
    }


def test_fresh_eyes_generation_reaches_the_service_query(repository: Path, capsys, monkeypatch):
    target = SemanticServiceTarget("http://127.0.0.1:9999", 7, "Fixture", "/repo")
    requested = []
    monkeypatch.setattr(agent_commands, "discover_semantic_service", lambda *_a, **_k: target)
    monkeypatch.setattr(
        semantic_service,
        "_request_json",
        lambda url, **kwargs: requested.append(url) or {"state": "superseded"},
    )

    main(
        [
            "fresh-eyes",
            str(repository),
            "--service-url",
            target.base_url,
            "--generation",
            "2",
            "--json",
        ]
    )

    assert json.loads(capsys.readouterr().out)["state"] == "superseded"
    assert requested == [f"{target.base_url}/api/fresh-eyes?repository_id=7&generation=2"]


@pytest.mark.parametrize("error", [OSError("timed out"), OSError("<urlopen error timed out>")])
def test_fresh_eyes_start_timeout_explains_that_the_service_may_still_be_planning(
    repository: Path, capsys, monkeypatch, error
):
    target = SemanticServiceTarget("http://127.0.0.1:9999", 7, "Fixture", "/repo")
    calls = []
    monkeypatch.setattr(agent_commands, "discover_semantic_service", lambda *_a, **_k: target)

    def request(url, **kwargs):
        calls.append((url, kwargs))
        raise error

    monkeypatch.setattr(semantic_service, "_request_json", request)

    with pytest.raises(SystemExit) as exit_info:
        main(
            [
                "fresh-eyes",
                str(repository),
                "--service-url",
                target.base_url,
                "--restart",
                "--timeout-seconds",
                "0.5",
                "--json",
            ]
        )

    assert exit_info.value.code == 2
    stderr = capsys.readouterr().err
    assert "fresh-eyes restart within 0.5 s; it may still be planning" in stderr
    assert f"`anaxigraph fresh-eyes {repository}`" in stderr
    assert "--timeout-seconds" in stderr
    assert [(call[1]["method"], call[1]["timeout"]) for call in calls] == [("POST", 0.5)]


@pytest.mark.parametrize(
    ("arguments", "error", "expected"),
    [
        (["--start"], OSError("connection reset"), "anaxigraph: connection reset\n"),
        ([], OSError("timed out"), "anaxigraph: timed out\n"),
    ],
)
def test_fresh_eyes_other_service_errors_keep_their_bare_message(
    repository: Path, capsys, monkeypatch, arguments, error, expected
):
    target = SemanticServiceTarget("http://127.0.0.1:9999", 7, "Fixture", "/repo")
    monkeypatch.setattr(agent_commands, "discover_semantic_service", lambda *_a, **_k: target)

    def request(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(semantic_service, "_request_json", request)

    with pytest.raises(SystemExit) as exit_info:
        main(["fresh-eyes", str(repository), "--service-url", target.base_url, *arguments])

    assert exit_info.value.code == 2
    assert capsys.readouterr().err == expected

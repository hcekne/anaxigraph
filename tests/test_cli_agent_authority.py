from __future__ import annotations

import json
from pathlib import Path

import anaxigraph.cli_agent_commands as agent_commands
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


def test_fresh_eyes_uses_the_matching_service(repository: Path, capsys, monkeypatch):
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
    }

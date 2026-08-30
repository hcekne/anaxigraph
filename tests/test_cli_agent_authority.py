from __future__ import annotations

import json
from pathlib import Path

import anaxigraph.cli_agent_commands as agent_commands
from anaxigraph.cli import main
from anaxigraph.semantic_service import SemanticServiceTarget


def test_scope_uses_the_matching_service_instead_of_a_separate_local_index(
    repository: Path,
    capsys,
    monkeypatch,
):
    target = SemanticServiceTarget("http://127.0.0.1:9999", 7, "Fixture", "/repo")
    captured = {}
    monkeypatch.setattr(agent_commands, "discover_semantic_service", lambda *_a, **_k: target)

    def scope(service, *, goal, branch):
        captured.update(
            service=service,
            goal=goal,
            branch=branch,
        )
        return {"snapshot_id": 42, "goal": goal}

    monkeypatch.setattr(agent_commands, "service_agent_scope", scope)
    main(
        [
            "scope",
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
        "branch": None,
    }

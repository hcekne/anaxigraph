from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import anaxigraph.semantic_background as background
import anaxigraph.semantic_background_refusal as refusal


def _spec(repository: Path, executor: str) -> background.SemanticBackgroundSpec:
    return background.SemanticBackgroundSpec(
        repository=repository,
        executor=executor,
        model="",
        reasoning_effort="",
        index={"authority": "local", "database": "/tmp/anaxi.db"},
    )


def test_same_executor_refusal_keeps_the_bare_already_running_record(repository: Path):
    record = refusal.already_running(
        {"executor": "codex", "active": True}, _spec(repository, "codex")
    )

    assert record["status"] == "already_running"
    assert "recommended_action" not in record


def test_different_executor_refusal_names_the_foreground_alternative(repository: Path):
    record = refusal.already_running(
        {"executor": "codex", "active": True}, _spec(repository, "claude")
    )

    action = record["recommended_action"]
    assert record["status"] == "already_running"
    assert f"anaxigraph understand {repository.resolve()}" in action
    assert "--executor claude --until-complete" in action
    assert "background codex worker" in action


def test_refusal_guidance_replaces_the_progress_hint_in_next_action():
    assert refusal.background_next_action({"status": "running"}) == refusal.DEFAULT_NEXT_ACTION
    assert refusal.background_next_action({"recommended_action": "run it here"}) == "run it here"


def test_second_background_executor_is_refused_with_the_foreground_command(
    repository: Path, tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(background, "local_state_root", lambda: tmp_path)
    monkeypatch.setattr(background, "_spawn_wrapper", lambda *_args: SimpleNamespace(pid=4321))
    codex = _spec(repository, "codex")
    background.launch_semantic_background(codex)

    refused = background.launch_semantic_background(replace(codex, executor="claude"))

    assert refused["status"] == "already_running"
    assert refused["executor"] == "codex"
    assert "--executor claude --until-complete" in refused["recommended_action"]


def test_background_handoff_surfaces_the_refusal_as_the_next_action(repository: Path, monkeypatch):
    monkeypatch.setattr(
        background,
        "launch_semantic_background",
        lambda spec: refusal.already_running(
            {"executor": "codex", "active": True}, _spec(repository, "claude")
        ),
    )
    args = SimpleNamespace(
        limit=None, plan_only=False, db=None, config=None, force=False, retry_failed=False
    )
    execution = SimpleNamespace(
        model="", reasoning_effort="", max_parallel_jobs=2, timeout_seconds=420
    )

    result = background.launch_understand_background(args, repository, execution, "claude", None)

    assert result["status"] == "already_running"
    assert "--executor claude --until-complete" in result["next_action"]

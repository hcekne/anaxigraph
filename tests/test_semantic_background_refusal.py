from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import anaxigraph.semantic_background as background
import anaxigraph.semantic_background_refusal as refusal
import anaxigraph.semantic_background_slots as slots


def _spec(repository: Path, executor: str) -> background.SemanticBackgroundSpec:
    return background.SemanticBackgroundSpec(
        repository=repository,
        executor=executor,
        model="",
        reasoning_effort="",
        index={"authority": "local", "database": "/tmp/anaxi.db"},
    )


def test_same_executor_refusal_names_the_other_executors_slot(repository: Path):
    record = refusal.already_running(
        {"executor": "codex", "active": True}, _spec(repository, "codex")
    )

    action = record["recommended_action"]
    assert record["status"] == "already_running"
    assert f"anaxigraph understand {repository.resolve()}" in action
    assert "--executor claude --background" in action
    assert "codex slot" in action


def test_a_refusal_without_a_recorded_executor_stays_a_bare_record(repository: Path):
    record = refusal.already_running({"active": True}, _spec(repository, "codex"))

    assert record["status"] == "already_running"
    assert "recommended_action" not in record


def test_an_unknown_executor_falls_back_to_the_foreground_command(repository: Path):
    record = refusal.already_running(
        {"executor": "gemini", "active": True}, _spec(repository, "gemini")
    )

    assert "--until-complete" in record["recommended_action"]


def test_refusal_guidance_replaces_the_progress_hint_in_next_action():
    assert refusal.background_next_action({"status": "running"}) == refusal.DEFAULT_NEXT_ACTION
    assert refusal.background_next_action({"recommended_action": "run it here"}) == "run it here"


def test_a_second_run_of_the_same_executor_is_refused(
    repository: Path, tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(slots, "local_state_root", lambda: tmp_path)
    monkeypatch.setattr(background, "_spawn_wrapper", lambda *_args: SimpleNamespace(pid=4321))
    codex = _spec(repository, "codex")
    background.launch_semantic_background(codex)

    refused = background.launch_semantic_background(replace(codex))

    assert refused["status"] == "already_running"
    assert refused["executor"] == "codex"
    assert "--executor claude --background" in refused["recommended_action"]


def test_background_handoff_surfaces_the_refusal_as_the_next_action(repository: Path, monkeypatch):
    monkeypatch.setattr(
        background,
        "launch_semantic_background",
        lambda spec: refusal.already_running(
            {"executor": "claude", "active": True}, _spec(repository, "claude")
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
    assert "--executor codex --background" in result["next_action"]

"""Per-run semantic executor selection and operational limits."""

from __future__ import annotations

import argparse

import pytest

import anaxigraph.cli_semantic_commands as semantic_commands
import anaxigraph.semantic_execution as semantic_execution
from anaxigraph.config import SemanticConfig


def test_reasoning_effort_is_passed_through_for_future_codex_values():
    parser = argparse.ArgumentParser()
    semantic_execution.add_semantic_execution_arguments(parser)

    args = parser.parse_args(["--reasoning-effort", "future-effort"])

    assert args.reasoning_effort == "future-effort"


def test_understand_auto_detects_codex_as_the_local_agent_executor(monkeypatch):
    args = argparse.Namespace(
        executor="auto",
        model="test-model",
        reasoning_effort="medium",
        parallel_jobs=30,
        timeout_seconds=420,
        plan_only=False,
    )
    monkeypatch.setenv("CODEX_THREAD_ID", "test-thread")
    monkeypatch.setattr(semantic_execution.shutil, "which", lambda command: f"/bin/{command}")

    execution, mode = semantic_commands._understand_execution(
        args, SemanticConfig(enabled=True, provider="agent", max_parallel_jobs=40)
    )

    assert mode == "codex"
    assert execution.provider == "codex"
    assert execution.model == "test-model"
    assert execution.reasoning_effort == "medium"
    assert execution.max_parallel_jobs == 30
    assert execution.timeout_seconds == 420


def test_agent_policy_model_cannot_pin_the_runtime_executor(monkeypatch):
    args = argparse.Namespace(executor="codex", model=None, reasoning_effort=None, plan_only=False)
    monkeypatch.setattr(semantic_execution.shutil, "which", lambda command: f"/bin/{command}")

    execution, mode = semantic_commands._understand_execution(
        args,
        SemanticConfig(enabled=True, provider="agent", model="obsolete-policy-model"),
    )

    assert mode == "codex"
    assert execution.model == ""


def test_understand_rejects_codex_reasoning_effort_for_claude(monkeypatch):
    args = argparse.Namespace(
        executor="claude", model=None, reasoning_effort="medium", plan_only=False
    )
    monkeypatch.setattr(semantic_execution.shutil, "which", lambda command: f"/bin/{command}")

    with pytest.raises(ValueError, match="supported only"):
        semantic_commands._understand_execution(
            args, SemanticConfig(enabled=True, provider="agent")
        )


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"executor": "codex", "model": None, "reasoning_effort": None}, "only valid"),
        ({"executor": "auto", "model": "runtime", "reasoning_effort": None}, "policy"),
        ({"executor": "auto", "model": None, "reasoning_effort": "high"}, "agent-funded"),
    ],
)
def test_configured_semantic_provider_rejects_agent_runtime_flags(options, message):
    args = argparse.Namespace(**options, plan_only=False)

    with pytest.raises(ValueError, match=message):
        semantic_commands._understand_execution(
            args, SemanticConfig(enabled=True, provider="command", command=("worker",))
        )


def test_configured_semantic_provider_keeps_its_policy_executor():
    args = argparse.Namespace(executor="auto", model=None, reasoning_effort=None, plan_only=False)

    execution, mode = semantic_commands._understand_execution(
        args,
        SemanticConfig(
            enabled=True,
            provider="command",
            command=("worker",),
            model="configured",
        ),
    )

    assert execution is None
    assert mode == "command"


def test_agent_executor_rejects_invalid_plan_mcp_and_missing_cli(monkeypatch):
    semantic = SemanticConfig(enabled=True, provider="agent")
    plan = argparse.Namespace(executor="codex", model=None, reasoning_effort=None, plan_only=True)
    mcp = argparse.Namespace(
        executor="mcp", model="runtime", reasoning_effort=None, plan_only=False
    )
    missing = argparse.Namespace(
        executor="codex", model=None, reasoning_effort=None, plan_only=False
    )

    with pytest.raises(ValueError, match="plan-only"):
        semantic_commands._understand_execution(plan, semantic)
    with pytest.raises(ValueError, match="local agent executor"):
        semantic_commands._understand_execution(mcp, semantic)
    monkeypatch.setattr(semantic_execution.shutil, "which", lambda _command: None)
    with pytest.raises(ValueError, match="not installed"):
        semantic_commands._understand_execution(missing, semantic)


@pytest.mark.parametrize(
    ("option", "message"),
    [("parallel_jobs", "at least one"), ("timeout_seconds", "at least one")],
)
def test_agent_executor_rejects_invalid_runtime_limits(option, message):
    values = {
        "executor": "codex",
        "model": None,
        "reasoning_effort": None,
        "parallel_jobs": None,
        "timeout_seconds": None,
        "plan_only": False,
    }
    values[option] = 0

    with pytest.raises(ValueError, match=message):
        semantic_commands._understand_execution(
            argparse.Namespace(**values), SemanticConfig(enabled=True, provider="agent")
        )


def test_agent_executor_detection_supports_claude_and_manual_mcp(monkeypatch):
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    for name in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_SESSION_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setattr(semantic_execution.shutil, "which", lambda command: f"/bin/{command}")
    assert semantic_execution.detected_agent_executor() == "claude"
    monkeypatch.delenv("CLAUDECODE")
    assert semantic_execution.detected_agent_executor() == "mcp"

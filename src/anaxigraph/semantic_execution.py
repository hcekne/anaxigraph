"""Per-run semantic executor selection for agent-funded understanding."""

from __future__ import annotations

import os
import shutil
from dataclasses import replace
from typing import Any


def add_semantic_execution_arguments(parser: Any) -> None:
    parser.add_argument(
        "--executor",
        choices=("auto", "mcp", "codex", "claude"),
        default="auto",
        help=(
            "How to execute provider=agent work: auto detects the invoking coding agent, "
            "mcp queues work for the connected agent, and codex/claude run the local CLI"
        ),
    )
    parser.add_argument(
        "--model",
        help="Optional model override for this local codex/claude execution",
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=("minimal", "low", "medium", "high", "xhigh"),
        help="Optional Codex reasoning effort for this run",
    )
    parser.add_argument(
        "--background",
        "--detach",
        action="store_true",
        help="Run the complete local Codex/Claude queue independently of this shell session",
    )


def understand_execution(args: Any, semantic: Any) -> tuple[Any | None, str]:
    reasoning_effort = getattr(args, "reasoning_effort", None)
    if semantic.provider != "agent":
        return _configured_provider_execution(args, semantic, reasoning_effort)
    if args.plan_only:
        if args.executor not in {"auto", "mcp"} or args.model or reasoning_effort:
            raise ValueError("--plan-only cannot be combined with a local agent executor or model")
        return None, "plan_only"
    executor = detected_agent_executor() if args.executor == "auto" else args.executor
    return _local_agent_execution(args, semantic, executor, reasoning_effort)


def _configured_provider_execution(
    args: Any, semantic: Any, reasoning_effort: str | None
) -> tuple[None, str]:
    if args.executor not in {"auto", "mcp"}:
        raise ValueError("--executor is only valid when semantic.provider is agent")
    if args.model:
        raise ValueError("Set semantic.model in policy for a configured model provider")
    if reasoning_effort:
        raise ValueError("--reasoning-effort is only valid for an agent-funded Codex run")
    return None, semantic.provider


def _local_agent_execution(
    args: Any,
    semantic: Any,
    executor: str,
    reasoning_effort: str | None,
) -> tuple[Any | None, str]:
    if executor == "mcp":
        if args.model or reasoning_effort:
            raise ValueError("--model and --reasoning-effort require a local agent executor")
        return None, "mcp"
    if reasoning_effort and executor != "codex":
        raise ValueError("--reasoning-effort is supported only by --executor codex")
    if shutil.which(executor) is None:
        raise ValueError(f"The {executor} CLI is not installed or not available on PATH")
    return replace(
        semantic,
        provider=executor,
        model=args.model or "",
        reasoning_effort=reasoning_effort or "",
    ), executor


def detected_agent_executor() -> str:
    if os.environ.get("CODEX_THREAD_ID") and shutil.which("codex"):
        return "codex"
    claude_environment = any(
        os.environ.get(name)
        for name in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_SESSION_ID")
    )
    if claude_environment and shutil.which("claude"):
        return "claude"
    return "mcp"

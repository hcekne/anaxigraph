"""Per-run semantic executor selection for agent-funded understanding."""

from __future__ import annotations

import os
import shutil
from dataclasses import replace
from typing import Any

from anaxigraph.semantic_stage_model import (
    STAGE_PROVIDERS,
    STAGE_TIERS,
    SemanticStageModel,
)


def add_semantic_execution_arguments(parser: Any) -> None:
    parser.add_argument(
        "--executor",
        choices=("auto", "mcp", "codex", "claude"),
        default="auto",
        help=(
            "Who processes AI tasks: auto finds the current coding agent; mcp leaves one task "
            "at a time for the connected agent; codex or claude starts that local command-line tool"
        ),
    )
    parser.add_argument(
        "--model",
        help="Worker model; choose explicitly for unattended mapping to avoid an expensive CLI default",
    )
    parser.add_argument(
        "--reasoning-effort",
        help=(
            "Optional reasoning effort for this run's local codex or claude executor; the value "
            "is passed through unvalidated so new effort levels do not require an AnaxiGraph "
            "release"
        ),
    )
    parser.add_argument(
        "--stage-model",
        action="append",
        metavar="TIER=[EXECUTOR:]MODEL[:EFFORT]",
        help=(
            "Override the model for one kind of work this run, repeatable. TIER is module, "
            "group, repository, or taxonomy. Examples: repository=gpt-6-astra:high, "
            "group=claude:claude-sonnet-5:medium. Overrides the repository's stage_models"
        ),
    )
    _add_runtime_limit_arguments(parser)


def _add_runtime_limit_arguments(parser: Any) -> None:
    """How hard to push this run, as opposed to what runs it."""

    parser.add_argument(
        "--parallel-jobs",
        type=int,
        help="Most model calls to run at once, up to the maximum in repository settings",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        help=(
            "Seconds allowed for each model call; this runtime choice does not make saved AI "
            "descriptions stale"
        ),
    )
    parser.add_argument(
        "--background",
        "--detach",
        action="store_true",
        help=(
            "Start or reuse a durable runner for parallel tasks. It owns retries and progress "
            "after this shell exits; no supervisor script or LLM polling loop is needed"
        ),
    )


def stage_model_overrides(values: list[str] | None) -> dict[str, SemanticStageModel]:
    """Read tiers given on the command line, in the same shape the policy file uses.

    A run is where the cost is felt, so the choice has to be available there and not only in
    a committed file. The parsed result replaces a tier outright rather than merging into it,
    so what a flag says is what runs.
    """

    tiers: dict[str, SemanticStageModel] = {}
    for raw in values or []:
        tier, _, spec = str(raw).partition("=")
        name = tier.strip().lower()
        if name not in STAGE_TIERS or not spec.strip():
            raise ValueError(
                f"--stage-model expects TIER=[EXECUTOR:]MODEL[:EFFORT] where TIER is one of "
                f"{', '.join(STAGE_TIERS)}; received {raw!r}"
            )
        parts = [item.strip() for item in spec.split(":")]
        provider = parts.pop(0).lower() if parts[0].lower() in STAGE_PROVIDERS else ""
        if not parts or not parts[0]:
            raise ValueError(f"--stage-model {name} names an executor but no model")
        tiers[name] = SemanticStageModel(
            provider=provider,
            model=parts[0],
            reasoning_effort=parts[1] if len(parts) > 1 else "",
        )
    return tiers


def understand_execution(args: Any, semantic: Any) -> tuple[Any | None, str]:
    reasoning_effort = getattr(args, "reasoning_effort", None)
    parallel_jobs = getattr(args, "parallel_jobs", None)
    timeout_seconds = getattr(args, "timeout_seconds", None)
    _validate_runtime_limits(parallel_jobs, timeout_seconds)
    if semantic.provider != "agent":
        return _configured_provider_execution(
            args, semantic, reasoning_effort, parallel_jobs, timeout_seconds
        )
    if args.plan_only:
        if (
            args.executor not in {"auto", "mcp"}
            or args.model
            or reasoning_effort
            or parallel_jobs
            or timeout_seconds
        ):
            raise ValueError("--plan-only cannot be combined with a local agent executor or model")
        return None, "plan_only"
    executor = detected_agent_executor() if args.executor == "auto" else args.executor
    return _local_agent_execution(
        args,
        semantic,
        executor,
        reasoning_effort,
        parallel_jobs,
        timeout_seconds,
    )


def _configured_provider_execution(
    args: Any,
    semantic: Any,
    reasoning_effort: str | None,
    parallel_jobs: int | None,
    timeout_seconds: int | None,
) -> tuple[None, str]:
    if args.executor not in {"auto", "mcp"}:
        raise ValueError("--executor is only valid when semantic.provider is agent")
    if args.model:
        raise ValueError("Set semantic.model in policy for a configured model provider")
    if reasoning_effort:
        raise ValueError(
            "--reasoning-effort is only valid for an agent-funded local Codex or Claude executor"
        )
    if parallel_jobs or timeout_seconds:
        raise ValueError(
            "--parallel-jobs and --timeout-seconds are only valid for an agent-funded local "
            "executor"
        )
    return None, semantic.provider


def _local_agent_execution(
    args: Any,
    semantic: Any,
    executor: str,
    reasoning_effort: str | None,
    parallel_jobs: int | None,
    timeout_seconds: int | None,
) -> tuple[Any | None, str]:
    if executor == "mcp":
        if args.model or reasoning_effort or parallel_jobs or timeout_seconds:
            raise ValueError("--model and --reasoning-effort require a local agent executor")
        return None, "mcp"
    if shutil.which(executor) is None:
        raise ValueError(f"The {executor} CLI is not installed or not available on PATH")
    return replace(
        semantic,
        provider=executor,
        model=args.model or "",
        reasoning_effort=reasoning_effort or "",
        stage_models={
            **(semantic.stage_models or {}),
            **stage_model_overrides(getattr(args, "stage_model", None)),
        },
        max_parallel_jobs=min(
            parallel_jobs or semantic.max_parallel_jobs, semantic.max_parallel_jobs
        ),
        timeout_seconds=timeout_seconds or semantic.timeout_seconds,
    ), executor


def _validate_runtime_limits(
    parallel_jobs: int | None,
    timeout_seconds: int | None,
) -> None:
    if parallel_jobs is not None and parallel_jobs < 1:
        raise ValueError("--parallel-jobs must be at least one")
    if timeout_seconds is not None and timeout_seconds < 1:
        raise ValueError("--timeout-seconds must be at least one")


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

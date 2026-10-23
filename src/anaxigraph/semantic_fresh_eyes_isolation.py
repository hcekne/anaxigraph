"""Tool-free fresh worker controls, separate from self-reported model isolation."""

from __future__ import annotations

import contextlib
import os
import subprocess
import tempfile
from typing import Any

from anaxigraph.semantic_fresh_eyes_functional import (
    FUNCTIONAL_PROTOCOL,
    SemanticAnalysisError,
    assert_functional,
)

_NO_SOURCE_TOOLS = (
    "shell_tool",
    "multi_agent",
    "apps",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "computer_use",
    "skill_search",
    "view_image",
    "image_generation",
    "memories",
    "code_mode",
    "shell_snapshot",
    "hooks",
    "plugins",
    "tool_suggest",
)


def blind_request(request: Any) -> bool:
    return request.get("protocol_version") == FUNCTIONAL_PROTOCOL


def codex_blind_flags(request: Any) -> list[str]:
    if not blind_request(request):
        return []
    assert_functional(request)
    flags = [part for feature in _NO_SOURCE_TOOLS for part in ("--disable", feature)]
    _verify_codex_flags(flags)
    # shell_tool disables both executor implementations; unified_exec itself is
    # permanently enabled in newer CLIs and does not grant access without it.
    return [
        *flags,
        "--config",
        'web_search="disabled"',
        "--config",
        "project_doc_max_bytes=0",
        "--config",
        "skills.include_instructions=false",
    ]


def claude_blind_flags(request: Any, instruction: str) -> list[str]:
    if not blind_request(request):
        return []
    assert_functional(request)
    _verify_claude_flags()
    return [
        "--restricted",
        "--setting-sources",
        "",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--system-prompt",
        instruction,
    ]


def _runtime_output(command: list[str]) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SemanticAnalysisError(
            "Cannot verify fresh worker tool-isolation capabilities"
        ) from error
    if result.returncode:
        raise SemanticAnalysisError(
            "Upgrade the worker CLI to support tool-free Fresh Eyes execution"
        )
    return result.stdout


def _verify_codex_flags(flags: list[str]) -> None:
    output = _runtime_output(["codex", *flags, "features", "list"])
    states = {
        parts[0]: parts[-1] for line in output.splitlines() if len(parts := line.split()) >= 3
    }
    if any(states.get(feature) != "false" for feature in _NO_SOURCE_TOOLS):
        raise SemanticAnalysisError("Codex cannot attest disabled source tools; upgrade its CLI")


def _verify_claude_flags() -> None:
    output = _runtime_output(["claude", "--help"])
    required = (
        "--tools",
        "--safe-mode",
        "--restricted",
        "--strict-mcp-config",
        "--setting-sources",
        "--system-prompt",
        "--no-session-persistence",
    )
    if any(flag not in output for flag in required):
        raise SemanticAnalysisError(
            "Claude cannot enforce fresh tool-free execution; upgrade its CLI"
        )


def worker_environment(request: Any) -> dict[str, str]:
    environment = dict(os.environ)
    if blind_request(request):
        for name in (
            "CODEX_THREAD_ID",
            "CLAUDECODE",
            "CLAUDE_SESSION_ID",
            "CLAUDE_CODE_ENTRYPOINT",
        ):
            environment.pop(name, None)
    return environment


@contextlib.contextmanager
def blind_directory(request: Any):
    if not blind_request(request):
        yield None
        return
    with tempfile.TemporaryDirectory(prefix="anaxigraph-functional-worker-") as directory:
        yield directory

"""Optional semantic analysis kept explicitly separate from deterministic facts."""

from __future__ import annotations

import json
import subprocess
from typing import Any

from codeintel.config import SemanticConfig
from codeintel.models import FileAnalysis, SemanticClaim

PROMPT_CONTRACT = """Analyze one source file. Return only a JSON object with keys:
summary (string), responsibilities (string array), inputs (string array), outputs (string array),
side_effects (string array), architectural_group (string or null), confidence (0..1), and
supporting_evidence (short string array). Distinguish evidence from inference. Do not suggest code
changes and do not repeat source text unnecessarily."""


class SemanticAnalysisError(RuntimeError):
    pass


class CommandSemanticProvider:
    """Provider-neutral JSON-over-stdin bridge to an operator-selected LLM command."""

    def __init__(self, config: SemanticConfig) -> None:
        if not config.command:
            raise ValueError("semantic.command is required when semantic analysis is enabled")
        self.config = config

    def analyze(self, *, path: str, content: str, facts: FileAnalysis) -> SemanticClaim:
        request = {
            "contract": PROMPT_CONTRACT,
            "prompt_version": self.config.prompt_version,
            "path": path,
            "language": facts.language,
            "deterministic_facts": {
                "summary": facts.summary,
                "symbols": [
                    {
                        "type": symbol.symbol_type,
                        "name": symbol.name,
                        "signature": symbol.signature,
                    }
                    for symbol in facts.symbols[:100]
                ],
                "dependencies": sorted({item.target for item in facts.dependencies})[:100],
                "lines_of_code": facts.lines_of_code,
                "complexity": facts.complexity,
            },
            "source": content[:100_000],
        }
        try:
            completed = subprocess.run(
                list(self.config.command),
                input=json.dumps(request),
                text=True,
                capture_output=True,
                timeout=self.config.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SemanticAnalysisError(f"Semantic provider failed: {exc}") from exc
        if completed.returncode != 0:
            stderr = completed.stderr.strip()[:500]
            raise SemanticAnalysisError(
                f"Semantic provider exited with {completed.returncode}: {stderr}"
            )
        try:
            value = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise SemanticAnalysisError("Semantic provider did not return valid JSON") from exc
        return _claim(value, self.config)


def _claim(value: Any, config: SemanticConfig) -> SemanticClaim:
    if not isinstance(value, dict) or not isinstance(value.get("summary"), str):
        raise SemanticAnalysisError("Semantic response requires a summary string")
    confidence = float(value.get("confidence", 0.5))
    if not 0 <= confidence <= 1:
        raise SemanticAnalysisError("Semantic confidence must be between 0 and 1")
    return SemanticClaim(
        summary=value["summary"][:4_000],
        responsibilities=_strings(value.get("responsibilities")),
        inputs=_strings(value.get("inputs")),
        outputs=_strings(value.get("outputs")),
        side_effects=_strings(value.get("side_effects")),
        architectural_group=(
            str(value["architectural_group"])[:200] if value.get("architectural_group") else None
        ),
        source="llm",
        provider="command",
        model=config.model,
        prompt_version=config.prompt_version,
        confidence=confidence,
        supporting_evidence=_strings(value.get("supporting_evidence")),
    )


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item)[:1_000] for item in value if isinstance(item, (str, int, float)))[:50]

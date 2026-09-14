"""Which model does which kind of work.

Most of a mapping run is one description per file. Those do not need the model that writes
the repository Charter, and paying for it there is the largest avoidable cost in a refresh.
The tier a request belongs to is already implied by what the request asks for, so naming a
model per tier needs no new plumbing through the planner or the worker protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

STAGE_TIERS = ("module", "group", "repository", "taxonomy")
STAGE_PROVIDERS = ("codex", "claude", "command")


@dataclass(frozen=True, slots=True)
class SemanticStageModel:
    """A model chosen for one kind of work rather than for the whole run.

    The executor belongs here too. Which command-line tool runs is part of naming a model:
    a tier cannot ask for a Claude model while the run is launched against Codex unless it
    can say so. An empty field keeps whatever the run was launched with.
    """

    provider: str = ""
    model: str = ""
    reasoning_effort: str = ""


def parse_stage_models(value: Any) -> dict[str, SemanticStageModel]:
    """Read the tiers a repository declares, rejecting a name nothing will ever match."""

    if not value:
        return {}
    if not isinstance(value, dict):
        raise ValueError("semantic.stage_models must be a mapping")
    tiers: dict[str, SemanticStageModel] = {}
    for tier, entry in value.items():
        name = str(tier).strip().lower()
        if name not in STAGE_TIERS:
            raise ValueError(f"semantic.stage_models keys must be one of {', '.join(STAGE_TIERS)}")
        if not isinstance(entry, dict):
            raise ValueError(f"semantic.stage_models.{name} must be a mapping")
        tiers[name] = _tier(name, entry)
    return tiers


def _tier(name: str, entry: dict[str, Any]) -> SemanticStageModel:
    provider = str(entry.get("provider", "")).strip().lower()
    if provider and provider not in STAGE_PROVIDERS:
        raise ValueError(
            f"semantic.stage_models.{name}.provider must be one of {', '.join(STAGE_PROVIDERS)}"
        )
    return SemanticStageModel(
        provider=provider,
        model=str(entry.get("model", "")).strip(),
        reasoning_effort=str(entry.get("reasoning_effort", "")).strip(),
    )


def stage_tier(request: dict[str, Any]) -> str:
    """Name the kind of work a request is, so a model can be chosen for it."""

    kind = str(request.get("analysis_kind") or "")
    if kind.startswith("taxonomy"):
        return "taxonomy"
    if kind.startswith("synthesis"):
        return "repository" if str(request.get("scope_type")) == "repository" else "group"
    return "module"

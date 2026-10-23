"""Durable, repository-specific model choices for the illustrated workflows."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Literal

from filelock import FileLock
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

FLOW_STEPS = {
    "architecture": ("architecture_plan",),
    "mapping": (
        "annotation",
        "contracts",
        "taxonomy_proposal",
        "taxonomy_review",
        "groups",
        "charter",
    ),
    "patterns": ("pattern_assessment", "pattern_review"),
    "fresh-eyes": ("adjudication", "proposals", "comparison", "mission_filter"),
}
STEP_MODES = {
    "architecture_plan": "single",
    "annotation": "parallel",
    "intrinsic": "parallel",
    "context": "parallel",
    "groups": "parallel",
    "taxonomy_proposal": "single",
    "taxonomy_review": "sequence",
    "charter": "single",
    "pattern_assessment": "parallel",
    "pattern_review": "parallel",
    "proposals": "proposals",
    "adjudication": "single",
    "comparison": "single",
    "mission_filter": "single",
}
SOFTWARE_STEPS = {"patterns": ("pattern_plan",), "fresh-eyes": ("brief", "grounding")}
MODEL_SUGGESTIONS = {
    "codex": ["gpt-6-luna", "gpt-6.1-sol", "gpt-6-astra"],
    "claude": ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"],
}


def required_steps(workflow: str, step: str | None) -> tuple[str, ...]:
    """Run the dependency prefix through the requested card, reusing current results."""
    chain = FLOW_STEPS[workflow]
    if workflow == "patterns":
        chain = ("pattern_plan", *chain)
    elif workflow == "fresh-eyes":
        chain = ("brief", *chain, "grounding")
    if step is not None:
        chain = chain[: chain.index(step) + 1]
    return chain if workflow == "mapping" else (*FLOW_STEPS["mapping"], *chain)


def canonical_model(provider: str, model: str) -> str:
    # Migrate old free-text family names to the exact IDs offered by the picker.
    if provider == "claude":
        for family in ("opus", "sonnet", "haiku"):
            if model in {family, f"claude-{family}"}:
                return f"claude-{family}-5-5"
    return model


class WorkerChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["codex", "claude"]
    model: str = Field(min_length=1, max_length=200)
    workers: int = Field(default=1, ge=1, le=64)
    reasoning_effort: Literal["", "low", "medium", "high", "xhigh", "max"] = "medium"

    @field_validator("model")
    @classmethod
    def clean_model(cls, value: str, info: ValidationInfo) -> str:
        provider = info.data.get("provider", "")
        value = canonical_model(provider, value.strip())
        if value not in MODEL_SUGGESTIONS.get(provider, []):
            raise ValueError(f"Choose a supported {provider} model from the dropdown")
        return value


class StepSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository_id: int | None = None
    step: str
    workers: list[WorkerChoice] = Field(min_length=1, max_length=3)


def suggested_settings(ceiling: int, review_passes: int = 2) -> dict[str, list[dict[str, Any]]]:
    def worker(model: str, count: int = 1) -> dict[str, Any]:
        return WorkerChoice(
            provider="claude" if model.startswith("claude-") else "codex",
            model=model,
            workers=min(count, ceiling),
        ).model_dump()

    luna, sol, opus = "gpt-6-luna", "gpt-6.1-sol", "claude-opus-5-5"
    return {
        "architecture_plan": [worker(sol)],
        "annotation": [worker(luna, 4)],
        "taxonomy_proposal": [worker(sol)],
        "taxonomy_review": [worker(sol, 4), worker(opus, 4)][: max(1, review_passes)],
        "groups": [worker(sol, 2)],
        "charter": [worker(sol)],
        "pattern_assessment": [worker(sol, 2)],
        "pattern_review": [worker(opus, 2)],
        "proposals": [worker(sol), worker(opus), worker(sol)],
        "adjudication": [worker(sol)],
        "comparison": [worker(opus)],
        "mission_filter": [worker(sol)],
    }


def validate_step(step: str, workers: list[WorkerChoice], ceiling: int) -> None:
    mode = STEP_MODES.get(step)
    if mode is None:
        raise ValueError("This step has no model settings")
    if mode == "single" and len(workers) != 1:
        raise ValueError("This step produces one result with one model")
    if mode == "proposals" and len(workers) != 3:
        raise ValueError("Fresh Eyes retains three alternatives per functional scope")
    counts = [worker.workers for worker in workers]
    if mode not in {"parallel", "sequence"} and max(counts, default=1) != 1:
        raise ValueError("Each proposal or single result uses one worker")
    capacity = sum(counts) if mode == "parallel" else max(counts, default=1)
    if capacity > ceiling:
        raise ValueError(f"The worker count exceeds the repository limit of {ceiling}")
    for worker in workers:
        if worker.provider == "claude" and worker.reasoning_effort == "xhigh":
            raise ValueError("Claude supports low, medium, high or max effort, not xhigh")


class WorkflowSettings:
    def __init__(self, database_path: Path) -> None:
        self.directory = database_path.with_name(database_path.name + ".workflows")

    def read(self, repository_id: int, ceiling: int, review_passes: int = 2) -> dict[str, Any]:
        suggested = suggested_settings(ceiling, review_passes)
        path = self.directory / f"{repository_id}.json"
        saved = json.loads(path.read_text()) if path.exists() else {}
        saved = _migrated_choices(saved)
        return {
            "steps": {**suggested, **saved},
            "suggested": suggested,
            "customized": list(saved),
            "modes": STEP_MODES,
            "models": MODEL_SUGGESTIONS,
        }

    def save(
        self, repository_id: int, request: StepSettingsRequest, ceiling: int, review_passes: int = 2
    ) -> dict[str, Any]:
        validate_step(request.step, request.workers, ceiling)
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{repository_id}.json"
        with FileLock(str(path) + ".lock"):
            saved = json.loads(path.read_text()) if path.exists() else {}
            saved[request.step] = [worker.model_dump() for worker in request.workers]
            _atomic_json(path, saved)
        return self.read(repository_id, ceiling, review_passes)

    def portable_choices(self, repository_id: int) -> dict[str, Any]:
        path = self.directory / f"{repository_id}.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def restore_choices(self, repository_id: int, choices: dict[str, Any]) -> None:
        choices = {
            step: [WorkerChoice.model_validate(row).model_dump() for row in rows]
            for step, rows in _migrated_choices(choices).items()
            if step in STEP_MODES and isinstance(rows, list) and 1 <= len(rows) <= 3
        }
        if not choices:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{repository_id}.json"
        with FileLock(str(path) + ".lock"):
            current = self.portable_choices(repository_id)
            restored = {**choices, **_migrated_choices(current)}
            if restored != current:
                _atomic_json(path, restored)


def _migrated_choices(choices: dict[str, Any]) -> dict[str, Any]:
    saved = dict(choices)
    if "annotation" not in saved and "intrinsic" in saved:
        saved["annotation"] = saved["intrinsic"]
    saved.pop("intrinsic", None)
    saved.pop("context", None)
    saved = {
        step: [{**row, "model": canonical_model(row["provider"], row["model"])} for row in rows]
        for step, rows in saved.items()
    }
    proposals = saved.get("proposals", [])
    if 0 < len(proposals) < 3:
        saved["proposals"] = [*proposals, *(dict(proposals[0]) for _ in range(3 - len(proposals)))]
    return saved


def _atomic_json(path: Path, value: Any) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".settings-")
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)

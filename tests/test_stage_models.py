"""A run may pay for synthesis without paying that price for every file description.

Most of a mapping run is one description per file. Those do not need the model that writes
the repository Charter, and paying for it there is the largest avoidable cost in a refresh.
A tier names the model for a kind of work; the record must then name the model that actually
wrote each document, not the one the run was launched with.
"""

from __future__ import annotations

from typing import Any

import pytest

from anaxigraph.config import SemanticConfig, SemanticStageModel, _semantic_config
from anaxigraph.semantic import execution_for, stage_tier
from anaxigraph.semantic_execution import stage_model_overrides
from anaxigraph.semantic_remote_payloads import submit_arguments

_TIERS = {
    "group": SemanticStageModel(model="gpt-6-astra", reasoning_effort="medium"),
    "repository": SemanticStageModel(model="gpt-6-astra", reasoning_effort="high"),
}


def _execution(**extra: Any) -> SemanticConfig:
    return SemanticConfig(
        enabled=True, provider="codex", model="gpt-5.6-terra", reasoning_effort="medium", **extra
    )


@pytest.mark.parametrize(
    ("request_value", "tier"),
    [
        ({"analysis_kind": "intrinsic"}, "module"),
        ({"analysis_kind": "context"}, "module"),
        ({"analysis_kind": "synthesis", "scope_type": "group"}, "group"),
        ({"analysis_kind": "synthesis_chunk", "scope_type": "group"}, "group"),
        ({"analysis_kind": "synthesis", "scope_type": "repository"}, "repository"),
        ({"analysis_kind": "synthesis_reduction", "scope_type": "repository"}, "repository"),
        ({"analysis_kind": "taxonomy_proposal"}, "taxonomy"),
        ({"analysis_kind": "taxonomy_review_chunk"}, "taxonomy"),
    ],
)
def test_each_kind_of_work_is_named_by_its_tier(request_value: dict[str, Any], tier: str):
    assert stage_tier(request_value) == tier


def test_routine_file_work_keeps_the_cheaper_default():
    staged = execution_for({"analysis_kind": "intrinsic"}, _execution(stage_models=_TIERS))

    assert (staged.model, staged.reasoning_effort) == ("gpt-5.6-terra", "medium")


def test_a_group_summary_uses_the_tier_named_for_it():
    staged = execution_for(
        {"analysis_kind": "synthesis", "scope_type": "group"}, _execution(stage_models=_TIERS)
    )

    assert (staged.model, staged.reasoning_effort) == ("gpt-6-astra", "medium")


def test_the_repository_charter_gets_the_highest_effort():
    staged = execution_for(
        {"analysis_kind": "synthesis", "scope_type": "repository"}, _execution(stage_models=_TIERS)
    )

    assert (staged.model, staged.reasoning_effort) == ("gpt-6-astra", "high")


def test_a_run_without_tiers_is_untouched():
    execution = _execution()

    assert (
        execution_for({"analysis_kind": "synthesis", "scope_type": "repository"}, execution)
        is execution
    )


def test_a_tier_changes_only_the_model_and_effort():
    execution = _execution(stage_models=_TIERS, max_parallel_jobs=12, timeout_seconds=900)
    staged = execution_for({"analysis_kind": "synthesis", "scope_type": "repository"}, execution)

    assert staged.max_parallel_jobs == 12
    assert staged.timeout_seconds == 900
    assert staged.provider == "codex"


def test_a_tier_naming_only_an_effort_keeps_the_run_model():
    execution = _execution(stage_models={"repository": SemanticStageModel(reasoning_effort="high")})
    staged = execution_for({"analysis_kind": "synthesis", "scope_type": "repository"}, execution)

    assert (staged.model, staged.reasoning_effort) == ("gpt-5.6-terra", "high")


def test_the_result_reports_the_model_that_wrote_it_not_the_one_claimed_with():
    packet = {"job": {"id": 7}, "lease": {"token": "t"}}
    result = type(
        "R",
        (),
        {
            "value": {"ok": True},
            "input_tokens": 1,
            "output_tokens": 1,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "usage_reported": True,
        },
    )()
    staged = execution_for(
        {"analysis_kind": "synthesis", "scope_type": "repository"}, _execution(stage_models=_TIERS)
    )

    arguments = submit_arguments(1, packet, result, staged)

    assert arguments["executor_model"] == "gpt-6-astra"
    assert arguments["executor_effort"] == "high"


def test_a_run_without_tiers_sends_no_correction():
    packet = {"job": {"id": 7}, "lease": {"token": "t"}}
    result = type(
        "R",
        (),
        {
            "value": {},
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "usage_reported": False,
        },
    )()

    assert "executor_model" not in submit_arguments(1, packet, result)


def test_configuration_reads_the_tiers_and_rejects_an_unknown_one():
    parsed = _semantic_config(
        {
            "enabled": True,
            "model": "gpt-5.6-terra",
            "reasoning_effort": "medium",
            "stage_models": {
                "group": {"model": "gpt-6-astra", "reasoning_effort": "medium"},
                "repository": {"model": "gpt-6-astra", "reasoning_effort": "high"},
            },
        }
    )

    assert parsed.model == "gpt-5.6-terra"
    assert parsed.stage_models["repository"].reasoning_effort == "high"
    with pytest.raises(ValueError, match="stage_models keys"):
        _semantic_config({"stage_models": {"final": {"model": "x"}}})


def test_a_tier_can_name_the_executor_so_another_tool_can_run_it():
    tiers = {"group": SemanticStageModel(provider="claude", model="claude-sonnet-5")}
    staged = execution_for(
        {"analysis_kind": "synthesis", "scope_type": "group"}, _execution(stage_models=tiers)
    )

    assert (staged.provider, staged.model) == ("claude", "claude-sonnet-5")


def test_a_tier_without_an_executor_stays_on_the_one_the_run_started():
    staged = execution_for(
        {"analysis_kind": "synthesis", "scope_type": "group"}, _execution(stage_models=_TIERS)
    )

    assert staged.provider == "codex"


def test_a_tier_may_not_name_an_executor_that_does_not_exist():
    with pytest.raises(ValueError, match="provider must be one of"):
        _semantic_config({"stage_models": {"group": {"provider": "openai", "model": "x"}}})


@pytest.mark.parametrize(
    ("flag", "expected"),
    [
        ("repository=gpt-6-astra:high", ("", "gpt-6-astra", "high")),
        ("group=claude:claude-sonnet-5:medium", ("claude", "claude-sonnet-5", "medium")),
        ("module=gpt-5.6-terra", ("", "gpt-5.6-terra", "")),
        ("taxonomy=codex:gpt-6-astra", ("codex", "gpt-6-astra", "")),
    ],
)
def test_a_run_can_name_its_tiers_on_the_command_line(flag: str, expected: tuple[str, str, str]):
    tier = next(iter(stage_model_overrides([flag]).values()))

    assert (tier.provider, tier.model, tier.reasoning_effort) == expected


@pytest.mark.parametrize("flag", ["bogus=x", "repository=", "repository=claude", "nonsense"])
def test_a_malformed_tier_flag_is_refused_rather_than_guessed(flag: str):
    with pytest.raises(ValueError, match="--stage-model"):
        stage_model_overrides([flag])


def test_a_flag_replaces_the_repository_tier_outright():
    committed = {
        "repository": SemanticStageModel(
            provider="codex", model="gpt-6-astra", reasoning_effort="high"
        )
    }
    merged = {**committed, **stage_model_overrides(["repository=claude:claude-sonnet-5"])}
    staged = execution_for(
        {"analysis_kind": "synthesis", "scope_type": "repository"},
        _execution(stage_models=merged),
    )

    assert (staged.provider, staged.model) == ("claude", "claude-sonnet-5")
    assert staged.reasoning_effort == "medium"


def test_the_result_reports_the_executor_that_ran_it():
    packet = {"job": {"id": 7}, "lease": {"token": "t"}}
    result = type(
        "R",
        (),
        {
            "value": {},
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "usage_reported": False,
        },
    )()
    staged = execution_for(
        {"analysis_kind": "synthesis", "scope_type": "group"},
        _execution(
            stage_models={"group": SemanticStageModel(provider="claude", model="claude-sonnet-5")}
        ),
    )

    arguments = submit_arguments(1, packet, result, staged)

    assert arguments["executor_id"].startswith("cli:claude:")
    assert arguments["executor_model"] == "claude-sonnet-5"


def _pool(provider: str, model: str, tiers: dict[str, SemanticStageModel]) -> SemanticConfig:
    return SemanticConfig(
        enabled=True, provider=provider, model=model, reasoning_effort="medium", stage_models=tiers
    )


_ONLY_REPOSITORY = {
    "repository": SemanticStageModel(provider="codex", model="gpt-6-astra", reasoning_effort="high")
}


@pytest.mark.parametrize(
    ("provider", "model"), [("codex", "gpt-5.6-terra"), ("claude", "claude-sonnet-5")]
)
@pytest.mark.parametrize(
    "request_value",
    [
        {"analysis_kind": "intrinsic"},
        {"analysis_kind": "synthesis", "scope_type": "group"},
        {"analysis_kind": "taxonomy_proposal"},
    ],
)
def test_an_unpinned_tier_runs_on_whichever_pool_claims_it(
    provider: str, model: str, request_value: dict[str, Any]
):
    # Two pools exist so the same code is read by two providers and neither is rate limited.
    # A tier that names nothing must therefore leave the claiming pool alone.
    staged = execution_for(request_value, _pool(provider, model, _ONLY_REPOSITORY))

    assert (staged.provider, staged.model) == (provider, model)


@pytest.mark.parametrize(
    ("provider", "model"), [("codex", "gpt-5.6-terra"), ("claude", "claude-sonnet-5")]
)
def test_the_one_pinned_synthesis_is_the_same_whichever_pool_claims_it(provider: str, model: str):
    staged = execution_for(
        {"analysis_kind": "synthesis", "scope_type": "repository"},
        _pool(provider, model, _ONLY_REPOSITORY),
    )

    assert (staged.provider, staged.model, staged.reasoning_effort) == (
        "codex",
        "gpt-6-astra",
        "high",
    )


def test_the_committed_policy_leaves_the_bulk_tiers_open_to_both_pools():
    from pathlib import Path

    from anaxigraph.config import load_config

    semantic = load_config(Path(__file__).resolve().parents[1]).semantic

    assert set(semantic.stage_models) == {"repository"}
    assert semantic.max_parallel_jobs >= 32

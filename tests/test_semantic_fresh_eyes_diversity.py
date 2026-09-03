from __future__ import annotations

from anaxigraph.semantic_fresh_eyes_diversity import executor_family, proposal_diversity


def _document(executor_id, *, provider="agent", model="", executor_model="fixture-model"):
    return {
        "provider": provider,
        "model": model,
        "executor_id": executor_id,
        "executor_model": executor_model,
    }


def test_executor_family_reads_only_the_host_worker_prefix():
    assert executor_family("cli:codex:11") == "codex"
    assert executor_family("cli:claude:22") == "claude"
    assert executor_family("cli:codex") == "codex"
    assert executor_family("proposal-a") == "unspecified"
    assert executor_family("cli:") == "unspecified"
    assert executor_family(None) == "unspecified"


def test_codex_and_claude_host_workers_are_cross_provider():
    result = proposal_diversity([_document("cli:codex:11"), _document("cli:claude:22")])

    assert result["cross_provider"] is True
    assert result["executor_families"] == ["claude", "codex"]
    assert result["providers"] == ["claude", "codex"]
    assert result["executors"] == ["cli:claude:22", "cli:codex:11"]
    assert result["models"] == ["fixture-model"]
    assert result["proposal_count"] == 2
    assert result["distinct_executor_processes"] == 2
    assert result["independent_sessions_recorded"] is True


def test_two_codex_processes_are_one_provider_with_the_caveat():
    result = proposal_diversity([_document("cli:codex:11"), _document("cli:codex:12")])

    assert result["cross_provider"] is False
    assert result["executor_families"] == ["codex"]
    assert result["providers"] == ["codex"]
    assert result["distinct_executor_processes"] == 2
    assert result["caveat"].startswith("Different recorded executors support diversity")


def test_opaque_agent_ids_never_count_as_a_second_provider():
    opaque = proposal_diversity([_document("proposal-a"), _document("proposal-b")])
    assert opaque["executor_families"] == ["unspecified"]
    assert opaque["providers"] == ["agent"]
    assert opaque["cross_provider"] is False

    mixed = proposal_diversity([_document("cli:codex:11"), _document("proposal-b")])
    assert mixed["executor_families"] == ["codex", "unspecified"]
    assert mixed["providers"] == ["agent", "codex"]
    assert mixed["cross_provider"] is False


def test_recorded_providers_and_missing_documents_are_reported_directly():
    command = proposal_diversity(
        [_document(None, provider="openai"), _document(None, provider="anthropic")]
    )
    assert command["providers"] == ["anthropic", "openai"]
    assert command["cross_provider"] is True
    assert command["executors"] == ["unspecified"]
    assert command["distinct_executor_processes"] == 0
    assert command["independent_sessions_recorded"] is False

    empty = proposal_diversity([])
    assert empty["proposal_count"] == 0
    assert empty["cross_provider"] is False
    assert empty["independent_sessions_recorded"] is False
    assert empty["executor_families"] == []
    assert empty["providers"] == []

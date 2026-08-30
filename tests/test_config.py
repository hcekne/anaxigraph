from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from anaxigraph.config import (
    AnaxiGraphConfig,
    SemanticConfig,
    load_config,
    path_matches,
    semantic_config_from_mapping,
)
from anaxigraph.config_authority import (
    effective_semantic_policy,
    service_config_authority,
)


def test_config_loads_groups_rules_and_ignore(repository):
    config = load_config(repository)

    assert config.project_name == "Sample Observatory"
    assert config.declared_group("pkg/core.py") == "domain"
    assert config.declared_group("web/App.tsx") == "presentation"
    assert config.is_ignored("ignored/secret.py")
    assert config.is_ignored(".git/config")
    assert config.is_ignored("coverage.xml")
    assert config.is_ignored("backend/coverage.xml")
    assert config.is_ignored("frontend/coverage/lcov.info")
    assert config.coverage_required is False
    assert not config.is_ignored("pkg/core.py")
    assert {rule.rule_id for rule in config.architecture.rules} == {
        "small-module-signal",
        "web-domain-boundary",
    }


def test_globs_match_root_and_nested_paths():
    assert path_matches("tests/test_unit.py", "tests/**")
    assert path_matches("frontend/src/App.test.tsx", "**/*.test.*")
    assert path_matches(".git/config", ".git/**")


def test_default_config_name_is_anaxigraph(tmp_path: Path):
    (tmp_path / ".anaxigraph.yml").write_text("project: {name: AnaxiGraph}\n", encoding="utf-8")

    config = load_config(tmp_path)

    assert config.project_name == "AnaxiGraph"
    assert config.config_path == tmp_path / ".anaxigraph.yml"


def test_coverage_warning_can_be_explicitly_required(tmp_path: Path):
    (tmp_path / ".anaxigraph.yml").write_text(
        "coverage:\n  required: true\n  files: [reports/coverage.xml]\n",
        encoding="utf-8",
    )

    config = load_config(tmp_path)

    assert config.coverage_required is True
    assert config.coverage_files == ("reports/coverage.xml",)


def test_semantic_executor_refresh_budget_and_path_policy_load(tmp_path: Path):
    (tmp_path / ".anaxigraph.yml").write_text(
        """semantic:
  enabled: true
  provider: command
  command: [semantic-fixture]
  model: example-model
  refresh: watch
  max_parallel_jobs: 3
  max_jobs_per_run: 25
  daily_budget_usd: 2.5
  input_cost_per_million: 1.25
  output_cost_per_million: 5
  include: [src/**]
  exclude: [src/generated/**]
  taxonomy:
    review_passes: 3
    max_areas: 8
    max_subsystems: 40
    stability_bias: 0.9
map:
  hints: [Keep durable boundaries visible]
  locked_memberships:
    src/ledger.py: billing-ledger
""",
        encoding="utf-8",
    )

    semantic = load_config(tmp_path).semantic

    assert semantic.enabled is True
    assert semantic.provider == "command"
    assert semantic.model == "example-model"
    assert semantic.refresh == "watch"
    assert semantic.max_parallel_jobs == 3
    assert semantic.daily_budget_usd == 2.5
    assert semantic.includes_path("src/service.py")
    assert not semantic.includes_path("src/generated/client.py")
    assert not semantic.includes_path("tests/test_service.py")
    assert semantic.taxonomy.enabled is True
    assert semantic.taxonomy.review_passes == 3
    assert semantic.taxonomy.max_areas == 8
    assert semantic.taxonomy.max_subsystems == 40
    assert semantic.taxonomy.stability_bias == 0.9
    map_config = load_config(tmp_path).map
    assert map_config.hints == ("Keep durable boundaries visible",)
    assert map_config.locked_memberships == {"src/ledger.py": "billing-ledger"}


def test_invalid_semantic_policy_fails_loudly(tmp_path: Path):
    (tmp_path / ".anaxigraph.yml").write_text(
        "semantic: {enabled: true, provider: mystery, refresh: whenever}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="semantic.provider"):
        load_config(tmp_path)


@pytest.mark.parametrize("provider", ("openai", "anthropic"))
def test_hosted_api_key_provider_is_rejected(tmp_path: Path, provider: str):
    (tmp_path / ".anaxigraph.yml").write_text(
        f"semantic: {{enabled: true, provider: {provider}}}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="no longer hosts"):
        load_config(tmp_path)


def test_agent_funded_semantic_policy_needs_no_model_or_command(tmp_path: Path):
    (tmp_path / ".anaxigraph.yml").write_text(
        """semantic:
  enabled: true
  provider: agent
  refresh: on_scan
  agent_lease_seconds: 900
""",
        encoding="utf-8",
    )

    semantic = load_config(tmp_path).semantic

    assert semantic.provider == "agent"
    assert semantic.model == ""
    assert semantic.command == ()
    assert semantic.agent_lease_seconds == 900
    assert semantic.timeout_seconds == 300
    assert semantic.taxonomy.enabled is True
    assert semantic.taxonomy.review_passes == 2


def test_effective_semantic_policy_round_trips_limits_without_private_command():
    semantic = SemanticConfig(
        enabled=True,
        provider="agent",
        command=("private-provider",),
        max_parallel_jobs=12,
        timeout_seconds=420,
        reasoning_effort="medium",
    )

    policy = effective_semantic_policy(semantic)
    transported = semantic_config_from_mapping(policy)

    assert transported.max_parallel_jobs == 12
    assert transported.timeout_seconds == 420
    assert transported.reasoning_effort == "medium"
    assert "command" not in policy


def test_service_config_authority_distinguishes_defaults_and_external_policy(tmp_path):
    defaults = service_config_authority(tmp_path, None, AnaxiGraphConfig())
    assert defaults["source_kind"] == "service_defaults"
    assert defaults["sha256"] is None

    external = tmp_path / "operator-policy.yml"
    external.write_text("semantic:\n  enabled: true\n", encoding="utf-8")
    target = SimpleNamespace(key="central", config_path=external)
    authority = service_config_authority(tmp_path / "repository", target, AnaxiGraphConfig())

    assert authority["source_kind"] == "external_registry_policy"
    assert authority["registry_key"] == "central"
    assert authority["sha256"]


def test_finding_attention_and_diagnostic_policy_loads(tmp_path: Path):
    (tmp_path / ".anaxigraph.yml").write_text(
        """findings:
  attention:
    minimum_priority: 55
    minimum_severity: error
    page_size: 12
    include_info_long_functions: true
  diagnostics:
    page_size: 80
""",
        encoding="utf-8",
    )

    findings = load_config(tmp_path).findings

    assert findings.attention_minimum_priority == 55
    assert findings.attention_minimum_severity == "error"
    assert findings.attention_page_size == 12
    assert findings.diagnostics_page_size == 80
    assert findings.include_info_long_functions is True


def test_invalid_finding_policy_fails_loudly(tmp_path: Path):
    (tmp_path / ".anaxigraph.yml").write_text(
        "findings: {attention: {minimum_severity: noisy}}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="minimum_severity"):
        load_config(tmp_path)

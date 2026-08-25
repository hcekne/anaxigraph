"""Construct semantic planning and execution workflows from core services."""

from __future__ import annotations

from dataclasses import dataclass

from anaxigraph.semantic_agent import SemanticAgentService
from anaxigraph.semantic_index_port import SemanticIndex
from anaxigraph.semantic_module_plan import SemanticModulePlanner
from anaxigraph.semantic_pattern_plan import SemanticPatternPlanner
from anaxigraph.semantic_runner import SemanticRunnerService
from anaxigraph.semantic_scope_plan import SemanticPlanningService
from anaxigraph.semantic_service_core import SemanticCoreServices
from anaxigraph.semantic_taxonomy_plan import SemanticTaxonomyPlanner


@dataclass(frozen=True, slots=True)
class SemanticWorkflowServices:
    planning: SemanticPlanningService
    runner: SemanticRunnerService
    agent: SemanticAgentService


def build_semantic_workflows(
    database: SemanticIndex,
    core: SemanticCoreServices,
) -> SemanticWorkflowServices:
    planning = SemanticPlanningService(
        database,
        core.reporting,
        core.leases,
        SemanticModulePlanner(),
        SemanticTaxonomyPlanner(),
        SemanticPatternPlanner(),
    )
    return SemanticWorkflowServices(
        planning=planning,
        runner=SemanticRunnerService(
            planning,
            core.reporting,
            core.leases,
            core.evidence,
            core.persistence,
        ),
        agent=SemanticAgentService(
            planning,
            core.reporting,
            core.leases,
            core.evidence,
            core.contracts,
            core.persistence,
        ),
    )

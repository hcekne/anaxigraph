"""Low-fan-out composition root for explicit semantic application services."""

from __future__ import annotations

from dataclasses import dataclass

from anaxigraph.semantic_agent import SemanticAgentService
from anaxigraph.semantic_index_port import SemanticIndex
from anaxigraph.semantic_pattern_plan import SemanticPatternPlanner
from anaxigraph.semantic_runner import SemanticRunnerService
from anaxigraph.semantic_scope_plan import SemanticPlanningService
from anaxigraph.semantic_service_core import SemanticCoreServices, build_semantic_core
from anaxigraph.semantic_taxonomy_plan import SemanticTaxonomyPlanner


@dataclass(frozen=True, slots=True)
class SemanticServices:
    core: SemanticCoreServices
    planning: SemanticPlanningService
    runner: SemanticRunnerService
    agent: SemanticAgentService

    @property
    def leases(self):
        return self.core.leases

    @property
    def evidence(self):
        return self.core.evidence

    @property
    def contracts(self):
        return self.core.contracts

    @property
    def persistence(self):
        return self.core.persistence

    @property
    def reporting(self):
        return self.core.reporting


def build_semantic_services(database: SemanticIndex) -> SemanticServices:
    core = build_semantic_core(database)
    planning = SemanticPlanningService(
        database,
        core.reporting,
        core.leases,
        SemanticTaxonomyPlanner(),
        SemanticPatternPlanner(),
    )
    return SemanticServices(
        core=core,
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

"""Low-fan-out composition root for explicit semantic application services."""

from __future__ import annotations

from dataclasses import dataclass

from anaxigraph.semantic_index_port import SemanticIndex
from anaxigraph.semantic_service_core import SemanticCoreServices, build_semantic_core
from anaxigraph.semantic_service_workflows import (
    SemanticWorkflowServices,
    build_semantic_workflows,
)


@dataclass(frozen=True, slots=True)
class SemanticServices:
    core: SemanticCoreServices
    workflows: SemanticWorkflowServices

    @property
    def planning(self):
        return self.workflows.planning

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
    def runner(self):
        return self.workflows.runner

    @property
    def reporting(self):
        return self.core.reporting

    @property
    def agent(self):
        return self.workflows.agent


def build_semantic_services(database: SemanticIndex) -> SemanticServices:
    core = build_semantic_core(database)
    return SemanticServices(core, build_semantic_workflows(database, core))

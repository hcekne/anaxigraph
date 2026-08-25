"""Construct database-facing semantic services with explicit dependencies."""

from __future__ import annotations

from dataclasses import dataclass

from anaxigraph.semantic_agent_contracts import SemanticAgentContractService
from anaxigraph.semantic_index_port import SemanticIndex
from anaxigraph.semantic_leases import SemanticLeaseService
from anaxigraph.semantic_reporting import SemanticReportingService
from anaxigraph.semantic_requests import SemanticEvidenceService
from anaxigraph.semantic_results import SemanticPersistenceService


@dataclass(frozen=True, slots=True)
class SemanticCoreServices:
    leases: SemanticLeaseService
    evidence: SemanticEvidenceService
    contracts: SemanticAgentContractService
    persistence: SemanticPersistenceService
    reporting: SemanticReportingService


def build_semantic_core(database: SemanticIndex) -> SemanticCoreServices:
    reporting = SemanticReportingService(database)
    persistence = SemanticPersistenceService(database)
    return SemanticCoreServices(
        leases=SemanticLeaseService(database, persistence),
        evidence=SemanticEvidenceService(database),
        contracts=SemanticAgentContractService(),
        persistence=persistence,
        reporting=reporting,
    )

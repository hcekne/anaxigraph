"""Composition root for explicit semantic application services."""

from __future__ import annotations

from dataclasses import dataclass

from anaxigraph.semantic_agent import SemanticAgentService
from anaxigraph.semantic_fresh_eyes_plan import FreshEyesPlanner
from anaxigraph.semantic_fresh_eyes_review import FreshEyesReviewService
from anaxigraph.semantic_index_port import SemanticIndex
from anaxigraph.semantic_leases import SemanticLeaseService
from anaxigraph.semantic_pattern_plan import SemanticPatternPlanner
from anaxigraph.semantic_reporting import SemanticReportingService
from anaxigraph.semantic_requests import SemanticEvidenceService
from anaxigraph.semantic_results import SemanticPersistenceService
from anaxigraph.semantic_runner import SemanticRunnerService
from anaxigraph.semantic_scope_plan import SemanticPlanningService
from anaxigraph.semantic_taxonomy_plan import SemanticTaxonomyPlanner


@dataclass(frozen=True, slots=True)
class SemanticServices:
    planning: SemanticPlanningService
    leases: SemanticLeaseService
    evidence: SemanticEvidenceService
    persistence: SemanticPersistenceService
    runner: SemanticRunnerService
    reporting: SemanticReportingService
    agent: SemanticAgentService
    fresh_eyes: FreshEyesReviewService


def build_semantic_services(database: SemanticIndex) -> SemanticServices:
    reporting = SemanticReportingService(database)
    persistence = SemanticPersistenceService(database)
    leases = SemanticLeaseService(database, persistence)
    evidence = SemanticEvidenceService(database)
    fresh_eyes_planner = FreshEyesPlanner()
    planning = SemanticPlanningService(
        database,
        reporting,
        leases,
        SemanticTaxonomyPlanner(),
        SemanticPatternPlanner(),
        fresh_eyes_planner,
    )
    return SemanticServices(
        planning=planning,
        leases=leases,
        evidence=evidence,
        persistence=persistence,
        runner=SemanticRunnerService(
            planning,
            reporting,
            leases,
            evidence,
            persistence,
        ),
        reporting=reporting,
        agent=SemanticAgentService(
            planning,
            reporting,
            leases,
            evidence,
            persistence,
        ),
        fresh_eyes=FreshEyesReviewService(
            database,
            fresh_eyes_planner,
            planning,
            reporting,
        ),
    )

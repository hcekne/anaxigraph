"""Public semantic bootstrap, invalidation, and dossier refresh facade."""

from __future__ import annotations

from anaxigraph.semantic_agent import SemanticAgentMixin
from anaxigraph.semantic_module_plan import SemanticModulePlanningMixin
from anaxigraph.semantic_reporting import SemanticReportingMixin
from anaxigraph.semantic_requests import SemanticRequestMixin
from anaxigraph.semantic_results import SemanticResultMixin
from anaxigraph.semantic_runner import SemanticRunnerMixin
from anaxigraph.semantic_scope_plan import SemanticPlan, SemanticScopePlanningMixin
from anaxigraph.storage import AnaxiIndex

__all__ = ["SemanticEngine", "SemanticPlan"]


class SemanticEngine(
    SemanticScopePlanningMixin,
    SemanticModulePlanningMixin,
    SemanticRunnerMixin,
    SemanticRequestMixin,
    SemanticResultMixin,
    SemanticReportingMixin,
    SemanticAgentMixin,
):
    """Plan and execute semantic work without mixing interpretations with parser facts."""

    def __init__(self, database: AnaxiIndex) -> None:
        self.database = database

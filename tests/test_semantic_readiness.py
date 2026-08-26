from __future__ import annotations

from types import SimpleNamespace

from anaxigraph.config import SemanticConfig
from anaxigraph.semantic_status import _coverage


def test_semantic_readiness_waits_for_the_pattern_plan_and_its_jobs():
    base = {
        "counts": {"current": 2},
        "repository_state": {"status": "current"},
        "taxonomy": {"status": "current"},
    }
    unplanned = _coverage(
        SimpleNamespace(**base, scope_counts={"repository": {"current": 1}}),
        SemanticConfig(enabled=True),
    )
    reviewing = _coverage(
        SimpleNamespace(
            **base,
            scope_counts={
                "repository": {"current": 1},
                "pattern_plan": {"current": 1},
                "pattern": {"current": 1, "pending_pattern_review": 1},
            },
        ),
        SemanticConfig(enabled=True),
    )

    assert unplanned.semantically_ready is False
    assert unplanned.baseline_complete is False
    assert reviewing.semantically_ready is False
    assert reviewing.pending_scopes == 1

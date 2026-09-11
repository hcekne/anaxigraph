"""An interface that pushes work onto callers is where complexity actually lands.

The maintenance-task assessment records those obligations so a reader can see the
cost an interface charges. The field is optional: assessments saved before it exist
stay valid, and adding it must not invalidate saved module meaning.
"""

from __future__ import annotations

import pytest
from semantic_support import _agent_dossier

from anaxigraph.semantic_contract import SemanticAnalysisError, validated_result
from anaxigraph.semantic_freshness import semantic_input_hash
from anaxigraph.understandability import (
    UNDERSTANDABILITY_VERSION,
    understandability_advice,
)


def _task(**changes):
    return {
        "key": "change-calculation",
        "task": "Change the calculation while preserving its caller contract.",
        "status": "obstructed",
        "knowledge_sources": ["names", "interfaces"],
        "evidence": ["pkg/core.py::Calculator.calculate"],
        "obstacle": "Every caller must close the session the constructor opened.",
        "smallest_change": "Close the session inside the calculation.",
        "expected_benefit": "A caller stops carrying a rule the interface can enforce.",
        "migration_cost": "low",
        "counter_evidence": ["Two callers reuse one session deliberately."],
        "verification": "Run the calculation tests plus the session lifetime test.",
        "confidence": 0.85,
        **changes,
    }


def _dossier(task):
    value = _agent_dossier({"path": "pkg/core.py", "analysis_kind": "module_intrinsic"})
    value["understandability"] = {
        "contract_version": UNDERSTANDABILITY_VERSION,
        "tasks": [task],
    }
    return value


def _module(task):
    return {
        "path": "pkg/core.py",
        "semantic": {
            "status": "current",
            "understandability": {
                "contract_version": UNDERSTANDABILITY_VERSION,
                "tasks": [task],
            },
        },
    }


def test_an_assessment_saved_without_caller_obligations_stays_valid():
    result = validated_result(_dossier(_task()), input_tokens=0, output_tokens=0)

    assert result.value["understandability"]["tasks"][0].get("caller_obligations") is None


def test_recorded_obligations_reach_the_reader_advice():
    obligations = [
        "The caller must close the session the constructor opened.",
        "The caller must call configure before the first calculation.",
    ]

    advice = understandability_advice([_module(_task(caller_obligations=obligations))])

    assert advice["items"][0]["caller_obligations"] == obligations


def test_a_blank_obligation_is_refused_like_blank_evidence():
    with pytest.raises(SemanticAnalysisError):
        validated_result(
            _dossier(_task(caller_obligations=["  "])), input_tokens=0, output_tokens=0
        )


def test_the_advice_reports_no_aggregate_quality_score():
    advice = understandability_advice([_module(_task(caller_obligations=["Close the session."]))])

    assert "score" not in advice
    assert not any(key.endswith("_score") for key in advice)
    assert advice["basis"].endswith("reader performance has not been measured.")


def test_adding_the_field_does_not_invalidate_saved_module_meaning():
    """The field lives in the response schema, never in the input identity."""

    first = semantic_input_hash("module-intrinsic-v1", "v1", {"path": "pkg/core.py"})
    second = semantic_input_hash("module-intrinsic-v1", "v1", {"path": "pkg/core.py"})

    assert first == second
    assert "caller_obligations" not in first

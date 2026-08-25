from __future__ import annotations

import pytest

from anaxigraph.agent_finding import build_finding_context


class _Database:
    def __init__(self, *, repository=True, finding=True, affected=None, status="planned"):
        self._repository = {"id": 7, "name": "Example"} if repository else None
        self._finding = (
            {
                "id": 4,
                "status": status,
                "summary": "Simplify the service boundary",
                "explanation": "The boundary has too many responsibilities.",
                "recommended_action": "Keep one responsibility here.",
                "affected_artifacts": affected or [],
            }
            if finding
            else None
        )

    def repository(self, repository_id):
        return self._repository

    def finding(self, repository_id, finding_id):
        return self._finding

    def file_details(self, repository_id, path):
        return {"path": path} if path == "src/service.py" else None


def _scope(*args, **kwargs):
    return {
        "recommended_context": ["src/service.py", "src/helper.py"],
        "tests": ["tests/test_scope.py"],
        "protected_files": [{"path": "src/protected.py"}],
        "risk": "medium",
    }


def _impact(*args, **kwargs):
    return {
        "tests_relevant": ["tests/test_impact.py"],
        "critical_paths_affected": ["src/critical.py"],
        "risk": "high",
    }


def test_finding_context_combines_scope_and_impact_without_duplicate_paths():
    result = build_finding_context(
        _Database(affected=["src/service.py"]),
        repository_id=7,
        finding_id=4,
        branch=None,
        config=object(),
        scope_builder=_scope,
        impact_builder=_impact,
    )

    assert result["ready_for_agent"] is True
    assert result["risk"] == "high"
    assert result["recommended_context"] == ["src/service.py", "src/helper.py"]
    assert result["relevant_tests"] == ["tests/test_impact.py", "tests/test_scope.py"]
    assert result["protected_paths"] == ["src/critical.py", "src/protected.py"]
    assert result["primary_impact"]["risk"] == "high"
    assert "Start with src/service.py" in result["goal"]
    assert result["finding"]["plain_language"]["version"] == "plain-language-v2"
    assert "What AnaxiGraph saw:" in result["agent_prompt"]
    assert "Why it matters: The boundary has too many responsibilities." in result["agent_prompt"]
    assert "When no code change may be needed:" in result["agent_prompt"]
    assert "How to check the result:" in result["agent_prompt"]
    assert "ANAXIGRAPH_FINDING_CONTEXT" in result["agent_prompt"]


def test_finding_context_handles_an_unplanned_finding_without_an_attached_file():
    result = build_finding_context(
        _Database(status="active"),
        repository_id=7,
        finding_id=4,
        branch=None,
        config=object(),
        scope_builder=_scope,
        impact_builder=lambda *args, **kwargs: pytest.fail("impact should not run"),
    )

    assert result["ready_for_agent"] is False
    assert result["risk"] == "medium"
    assert result["primary_impact"] is None
    assert "Plan this finding" in result["workflow_note"]
    assert "No file was attached" in result["agent_prompt"]


@pytest.mark.parametrize(
    ("database", "message"),
    [
        (_Database(repository=False), "Repository not found"),
        (_Database(finding=False), "Finding not found: 4"),
    ],
)
def test_finding_context_reports_missing_inputs(database, message):
    with pytest.raises(ValueError, match=message):
        build_finding_context(
            database,
            repository_id=7,
            finding_id=4,
            branch=None,
            config=object(),
            scope_builder=_scope,
            impact_builder=_impact,
        )

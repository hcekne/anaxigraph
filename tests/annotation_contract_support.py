"""Behavioral annotation fixture with one named contract and explicit uncertainty."""

from semantic_support import _agent_dossier


def annotation_case(*obligations):
    request = {
        "analysis_kind": "annotation",
        "path": "pkg/core.py",
        "functions": [{"qualified_name": "pkg.core.calculate"}],
    }
    value = _agent_dossier(request)
    value["detail"] = "Calculates the requested quantity. Runtime retry behavior is unknown."
    value["contracts"] = [
        {
            "name": "calculation-session",
            "statement": "Callers obey the calculation's session lifetime and ordering contract.",
            "functions": ["pkg.core.calculate"],
            "inputs": ["quantity"],
            "outputs": ["total"],
            "errors": ["Invalid quantities are rejected"],
            "side_effects": ["Records audit evidence"],
            "invariants": list(obligations),
            "evidence": ["pkg/core.py::calculate"],
        }
    ]
    return request, value

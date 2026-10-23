"""Dispatch implementation-blind functional requests; legacy reviews remain read-only."""

from __future__ import annotations

from typing import Any

from anaxigraph.semantic_fresh_eyes_functional_requests import functional_request
from anaxigraph.semantic_graph import SupersededSemanticJob


def fresh_eyes_request(database: Any, job: dict[str, Any]) -> dict[str, Any]:
    if not job["metadata"].get("functional_stage"):
        raise SupersededSemanticJob(
            "The legacy source-aware Fresh Eyes recipe is read-only. Start or resume the "
            "functional review; saved legacy analyses remain available."
        )
    return functional_request(database, job)

"""Report which providers and executor families produced the fresh-eyes proposals.

Host workers identify themselves as ``cli:<family>:<pid>`` (``cli:codex:4242``,
``cli:claude:4243``), so the family is the segment after ``cli:``. Any other agent id is an opaque
identity whose family is ``unspecified``. Every agent-funded document records the provider
``agent``, so the family stands in for the provider there; cross-provider agreement is asserted
only when two different known providers or families are recorded, never from opaque identities.
"""

from __future__ import annotations

from typing import Any

UNSPECIFIED = "unspecified"
HOST_EXECUTOR_PREFIX = "cli:"
DIVERSITY_CAVEAT = (
    "Different recorded executors support diversity but cannot prove external model context."
)
_OPAQUE_PROVIDERS = frozenset({"agent", UNSPECIFIED})


def executor_family(executor_id: Any) -> str:
    """Return the host executor family named by a ``cli:<family>:<pid>`` identity."""

    value = str(executor_id or "")
    if not value.startswith(HOST_EXECUTOR_PREFIX):
        return UNSPECIFIED
    family = value[len(HOST_EXECUTOR_PREFIX) :].split(":", 1)[0].strip()
    return family or UNSPECIFIED


def proposal_diversity(documents: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize provider, model, and executor diversity across proposal documents.

    Each document carries the recorded ``provider``, ``model``, ``executor_id``, and
    ``executor_model`` of one fresh-eyes proposal. The review payload and the adjudication packet
    share this block; ``fresh-eyes-review-v1`` key names are kept and ``executor_families``,
    ``distinct_executor_processes``, and ``caveat`` are additive.
    """

    providers = sorted({_provider(item) for item in documents})
    executors = sorted({str(item.get("executor_id") or UNSPECIFIED) for item in documents})
    return {
        "proposal_count": len(documents),
        "providers": providers,
        "models": sorted(
            {
                str(item.get("executor_model") or item.get("model") or UNSPECIFIED)
                for item in documents
            }
        ),
        "executors": executors,
        "executor_families": sorted(
            {executor_family(item.get("executor_id")) for item in documents}
        ),
        "cross_provider": len([item for item in providers if item not in _OPAQUE_PROVIDERS]) > 1,
        "independent_sessions_recorded": bool(documents) and len(executors) == len(documents),
        "distinct_executor_processes": len([item for item in executors if item != UNSPECIFIED]),
        "caveat": DIVERSITY_CAVEAT,
    }


def _provider(document: dict[str, Any]) -> str:
    provider = str(document.get("provider") or UNSPECIFIED)
    family = executor_family(document.get("executor_id"))
    if provider == "agent" and family != UNSPECIFIED:
        return family
    return provider

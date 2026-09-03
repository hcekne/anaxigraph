"""Wire schemas, rehydration, status, and identity for agent-funded semantics."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any

from anaxigraph.architecture_charter_contract import ARCHITECTURE_CHARTER_SCHEMA
from anaxigraph.config import AnaxiGraphConfig, SemanticConfig
from anaxigraph.pattern_evaluation_contract import (
    PATTERN_EVALUATION_SCHEMA,
    PATTERN_REVIEW_SCHEMA,
)
from anaxigraph.semantic_agent_paging import packetize_agent_request as packetize_agent_request
from anaxigraph.semantic_contract import DOSSIER_SCHEMA, SEMANTIC_SCHEMA_VERSION
from anaxigraph.semantic_fresh_eyes_contract import (
    FRESH_EYES_ADJUDICATION_SCHEMA,
    FRESH_EYES_COMPARISON_SCHEMA,
    FRESH_EYES_PROPOSAL_SCHEMA,
    FRESH_EYES_REVIEW_SCHEMA,
)
from anaxigraph.semantic_request_support import (
    INPUT_TERM_MEANINGS,
    PLAIN_LANGUAGE_CONTRACT_VERSION,
    PLAIN_LANGUAGE_REQUIREMENTS,
)
from anaxigraph.semantic_taxonomy_contract import (
    TAXONOMY_REVIEW_SCHEMA,
    TAXONOMY_SCHEMA,
)


def semantic_agent_schema() -> dict[str, Any]:
    return {
        "schema_version": SEMANTIC_SCHEMA_VERSION,
        "dossier_schema": DOSSIER_SCHEMA,
        "architecture_charter_schema": ARCHITECTURE_CHARTER_SCHEMA,
        "taxonomy_schema": TAXONOMY_SCHEMA,
        "taxonomy_review_schema": TAXONOMY_REVIEW_SCHEMA,
        "pattern_evaluation_schema": PATTERN_EVALUATION_SCHEMA,
        "pattern_review_schema": PATTERN_REVIEW_SCHEMA,
        "fresh_eyes_proposal_schema": FRESH_EYES_PROPOSAL_SCHEMA,
        "fresh_eyes_adjudication_schema": FRESH_EYES_ADJUDICATION_SCHEMA,
        "fresh_eyes_comparison_schema": FRESH_EYES_COMPARISON_SCHEMA,
        "fresh_eyes_review_schema": FRESH_EYES_REVIEW_SCHEMA,
        "writing_contract_version": PLAIN_LANGUAGE_CONTRACT_VERSION,
        "writing_requirements": PLAIN_LANGUAGE_REQUIREMENTS,
        "input_term_meanings": INPUT_TERM_MEANINGS,
        "instructions": (
            "Return the complete JSON result named by each work packet's response_contract. The "
            "machine may call it a dossier, architecture charter, taxonomy, taxonomy review, "
            "pattern evaluation, pattern review, or fresh-eyes architecture stage; these mean a "
            "file description, whole-system explanation, code-area map, pattern result, review, "
            "or fixed clean-sheet comparison. Use only supplied source, facts read from code, and prior AI "
            "descriptions. A review must return the full corrected result "
            "without asking a person to approve it. Score how well a pattern fits separately from "
            "how much of it already exists and whether changing code would help. A missing direct "
            "code link does not prove code is unused. Do not change repository files while mapping."
        ),
    }


def agent_semantic(config: AnaxiGraphConfig) -> SemanticConfig:
    semantic = config.semantic
    if not semantic.enabled:
        raise ValueError("Semantic analysis is disabled in .anaxigraph.yml")
    if semantic.provider != "agent":
        raise ValueError(
            "Coding-agent write-back requires semantic.provider: agent in .anaxigraph.yml"
        )
    return semantic


def clean_agent_identity(value: str, field: str, *, required: bool = True) -> str:
    result = value.strip()
    if required and not result:
        raise ValueError(f"{field} is required")
    if len(result) > 160 or any(ord(character) < 32 for character in result):
        raise ValueError(f"{field} must be at most 160 printable characters")
    return result


def agent_worker_fragment(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-")[:48] or "agent"


def agent_token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def rehydrate_agent_request(
    bounded_request: dict[str, Any], evidence_pages: list[dict[str, Any]]
) -> dict[str, Any]:
    """Assemble paged MCP evidence into one provider request on the agent host."""

    request = json.loads(json.dumps(bounded_request))
    source_chunks: list[tuple[int, str]] = []
    for page in evidence_pages:
        payload = page.get("payload") if "payload" in page else page
        if not isinstance(payload, dict):
            raise ValueError("Semantic evidence page payload must be an object")
        if isinstance(payload.get("source"), str):
            source_chunks.append((int(payload.get("start_line") or 0), str(payload["source"])))
            continue
        for field, value in payload.items():
            if isinstance(value, dict) and value.get("kind") in {
                "area",
                "subsystem",
                "memberships",
                "facets",
                "evidence",
            }:
                _merge_taxonomy_fragment(request, field, value)
            else:
                _merge_paged_value(request, field, value)
    if source_chunks:
        source = "".join(value for _, value in sorted(source_chunks))
        reference = request.pop("source_reference", {})
        expected = str(reference.get("text_sha256") or "")
        actual = hashlib.sha256(source.encode("utf-8")).hexdigest()
        if expected and not hmac.compare_digest(expected, actual):
            raise ValueError("Semantic source evidence pages did not match their manifest hash")
        request["source"] = source
    return request


def _merge_paged_value(target: dict[str, Any], field: str, value: Any) -> None:
    current = target.get(field)
    if isinstance(value, list):
        if not isinstance(current, list):
            current = []
            target[field] = current
        current.extend(value)
        return
    if isinstance(value, dict):
        if not isinstance(current, dict):
            current = {}
            target[field] = current
        for child_field, child_value in value.items():
            _merge_paged_value(current, child_field, child_value)
        return
    target[field] = value


def _merge_taxonomy_fragment(request: dict[str, Any], field: str, fragment: dict[str, Any]) -> None:
    taxonomy = request.setdefault(
        field,
        {"summary": "", "areas": [], "facets": [], "confidence": 0, "evidence": []},
    )
    kind = fragment["kind"]
    if kind == "area":
        area = dict(fragment.get("area") or {})
        area["subsystems"] = []
        taxonomy["areas"].append(area)
        return
    if kind == "facets":
        taxonomy["facets"].extend(fragment.get("facets") or [])
        return
    if kind == "evidence":
        taxonomy["evidence"].extend(fragment.get("evidence") or [])
        return
    area = _taxonomy_child(taxonomy["areas"], str(fragment.get("area_key") or ""), "area")
    if kind == "subsystem":
        subsystem = dict(fragment.get("subsystem") or {})
        subsystem["members"] = []
        area["subsystems"].append(subsystem)
        return
    subsystem = _taxonomy_child(
        area["subsystems"], str(fragment.get("subsystem_key") or ""), "subsystem"
    )
    subsystem["members"].extend(fragment.get("members") or [])


def _taxonomy_child(items: list[dict[str, Any]], key: str, label: str) -> dict[str, Any]:
    for item in items:
        if str(item.get("key") or item.get("name") or "") == key:
            return item
    raise ValueError(f"Semantic evidence referenced an unknown taxonomy {label}: {key}")


WAITING_FOR_EXECUTOR = "waiting_for_executor"


def waiting_for_executor_message(repository: Any, waiting: list[dict[str, str]]) -> str:
    """Name the reserved work and the exact command that starts the executor it waits for.

    The state is deliberately not terminal: a host worker keeps polling, because the review
    finishes as soon as the named executor claims its slot.
    """

    families = sorted({str(item["required_executor"]) for item in waiting if item})
    scopes = ", ".join(sorted(str(item["scope_key"]) for item in waiting if item))
    commands = "; ".join(
        f"anaxigraph understand {repository} --executor {family} --until-complete"
        for family in families
    )
    return (
        f"No AI task is ready for this executor. Queued work ({scopes}) is reserved for "
        f"{', '.join(families)}. Start it with: {commands}"
    )


def agent_no_work_status(status: dict[str, Any]) -> str:
    """Name why no work was handed out; live or queued jobs outrank a ready baseline.

    Readiness ignores fresh-eyes scopes, so a peer holding a review stage must read as ``busy``
    and unclaimed queued work as ``waiting`` before the queue may be called ``complete``.
    """

    jobs = status.get("jobs", {})
    if int(jobs.get("running", 0)):
        return "busy"
    if status.get("budget", {}).get("paused"):
        return "paused"
    if int(jobs.get("pending", 0)) or int(jobs.get("retry", 0)):
        return "waiting"
    if status.get("semantically_ready"):
        return "complete"
    if status.get("baseline_complete") and (
        int(status.get("failed", 0)) or int(status.get("failed_scopes", 0))
    ):
        return "complete_with_failures"
    return "waiting"


def agent_no_work_message(status: dict[str, Any]) -> str:
    state = agent_no_work_status(status)
    return {
        "complete": "The AI-created code map and pattern results are up to date. No AI task remains.",
        "busy": "Another coding agent is already working on every AI task that is ready.",
        "paused": "The configured AI-work limit is pausing new tasks.",
        "complete_with_failures": (
            "Some required AI tasks failed too many times. Call again with retry_failed=true to "
            "give those tasks another try."
        ),
        "waiting": (
            "No AI task is ready yet. Call again after active tasks finish or AnaxiGraph finishes "
            "deciding what work remains."
        ),
    }[state]

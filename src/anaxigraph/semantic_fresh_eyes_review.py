"""High-level status and explicit start operation for the fixed architecture review."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from anaxigraph.semantic_fresh_eyes_contract import (
    FRESH_EYES_PROTOCOL_VERSION,
    FRESH_EYES_REVIEW_VERSION,
)
from anaxigraph.semantic_fresh_eyes_plan import (
    FRESH_EYES_PLAN_KEY,
    FRESH_EYES_SCOPE,
    FreshEyesPlanner,
)
from anaxigraph.semantic_index_port import SemanticIndex
from anaxigraph.semantic_ports import (
    AnaxiGraphConfig,
    SemanticConfig,
    SemanticPlanningPort,
    SemanticReportingPort,
)

_STAGES = (
    ("proposal:a", "Independent proposal A"),
    ("proposal:b", "Independent proposal B"),
    ("proposal:c", "Independent proposal C"),
    ("adjudication", "Blind adjudication"),
    ("comparison", "As-built comparison"),
    ("review", "Mission filter and ranked strategy"),
)


class FreshEyesReviewService:
    def __init__(
        self,
        database: SemanticIndex,
        planner: FreshEyesPlanner,
        planning: SemanticPlanningPort,
        reporting: SemanticReportingPort,
    ) -> None:
        self._database = database
        self._planner = planner
        self._planning = planning
        self._reporting = reporting

    def start(
        self,
        repository_id: int,
        repository: str | Path,
        config: AnaxiGraphConfig,
        *,
        proposal_count: int = 2,
        retry_failed: bool = False,
    ) -> dict[str, Any]:
        semantic = config.semantic
        if not semantic.enabled:
            raise ValueError("Build AI understanding before starting a fresh-eyes review")
        if semantic.provider != "agent":
            raise ValueError(
                "Fresh-eyes review uses the connected coding agent's tokens; set semantic.provider: agent"
            )
        snapshot = self._database.latest_snapshot(repository_id)
        if snapshot is None:
            raise ValueError("Repository has not been scanned")
        snapshot_id = int(snapshot["id"])
        with self._database.transaction() as connection:
            created = self._planner.request(
                connection,
                repository_id=repository_id,
                snapshot_id=snapshot_id,
                proposal_count=proposal_count,
            )
        plan = self._planning.plan(
            repository_id,
            repository,
            config,
            retry_failed=retry_failed,
        )
        return {
            "status": "started" if created else "already_started",
            "plan_stage": plan.stage,
            "enqueued": plan.enqueued,
            "review": self.status(repository_id, semantic),
        }

    def status(
        self,
        repository_id: int,
        semantic: SemanticConfig | None = None,
    ) -> dict[str, Any]:
        snapshot = self._database.latest_snapshot(repository_id)
        if snapshot is None:
            return _missing_review(repository_id)
        snapshot_id = int(snapshot["id"])
        semantic_status = self._reporting.status(repository_id, semantic)
        with self._database.connect() as connection:
            plan = connection.execute(
                "SELECT * FROM semantic_scope_states WHERE snapshot_id = ? AND scope_type = ? "
                "AND scope_key = ?",
                (snapshot_id, FRESH_EYES_SCOPE, FRESH_EYES_PLAN_KEY),
            ).fetchone()
            if plan is None:
                return self._not_started(connection, repository_id, snapshot_id, semantic_status)
            plan_value = dict(plan)
            proposal_count = max(1, min(3, int(plan_value.get("interface_hash") or 2)))
            stage_rows = _stage_rows(connection, snapshot_id)
            stages = _stage_payloads(connection, stage_rows, proposal_count)
            review = _document_value(connection, plan_value.get("context_document_id"))
            manifests = _input_manifests(connection, repository_id, stage_rows)
        return _review_payload(
            repository_id,
            snapshot_id,
            plan_value,
            stages,
            review,
            manifests,
            semantic_status,
        )

    def _not_started(
        self,
        connection: Any,
        repository_id: int,
        snapshot_id: int,
        semantic_status: dict[str, Any],
    ) -> dict[str, Any]:
        prior = _prior_review(connection, repository_id)
        return _not_started_payload(repository_id, snapshot_id, semantic_status, prior)


def _prior_review(connection: Any, repository_id: int) -> Any:
    return connection.execute(
        """
        SELECT snapshot_id, id, value_json, created_at FROM semantic_documents
        WHERE repository_id = ? AND scope_type = ? AND document_kind = 'fresh_review'
        ORDER BY id DESC LIMIT 1
        """,
        (repository_id, FRESH_EYES_SCOPE),
    ).fetchone()


def _not_started_payload(
    repository_id: int,
    snapshot_id: int,
    semantic_status: dict[str, Any],
    prior: Any,
) -> dict[str, Any]:
    stale = prior and int(prior["snapshot_id"]) != snapshot_id
    previous = (
        {
            "snapshot_id": int(prior["snapshot_id"]),
            "document_id": int(prior["id"]),
            "created_at": prior["created_at"],
        }
        if prior
        else None
    )
    next_action = (
        "Finish AI understanding first, then start the fresh-eyes review."
        if not semantic_status.get("semantically_ready")
        else "Start a fresh-eyes review with two independent proposals."
    )
    return {
        "contract_version": FRESH_EYES_REVIEW_VERSION,
        "protocol_version": FRESH_EYES_PROTOCOL_VERSION,
        "repository_id": repository_id,
        "snapshot_id": snapshot_id,
        "identity": f"{FRESH_EYES_REVIEW_VERSION}:{repository_id}:{snapshot_id}:none",
        "state": "stale" if stale else "not_started",
        "ready": False,
        "capability_brief": _capability_brief(semantic_status),
        "fingerprints": {"capability": None, "reference": None, "comparison": None},
        "stages": [],
        "proposals": [],
        "adjudication": None,
        "comparison": None,
        "strategy": None,
        "recommendations": [],
        "diversity": _empty_diversity(),
        "input_manifests": [],
        "previous_review": previous,
        "caveats": ["No fresh-eyes review has been requested for the current saved scan."],
        "next_action": next_action,
    }


def _review_payload(
    repository_id: int,
    snapshot_id: int,
    plan: dict[str, Any],
    stages: list[dict[str, Any]],
    review: dict[str, Any] | None,
    manifests: list[dict[str, Any]],
    semantic_status: dict[str, Any],
) -> dict[str, Any]:
    by_key = {item["key"]: item for item in stages}
    proposals = [
        item for key, item in by_key.items() if key.startswith("proposal:") and item["value"]
    ]
    current = plan["status"] == "current" and review is not None
    return {
        "contract_version": FRESH_EYES_REVIEW_VERSION,
        "protocol_version": FRESH_EYES_PROTOCOL_VERSION,
        "repository_id": repository_id,
        "snapshot_id": snapshot_id,
        "identity": _review_identity(repository_id, snapshot_id, plan),
        "state": "current" if current else _active_state(stages, semantic_status),
        "ready": current,
        "capability_brief": _capability_brief(semantic_status),
        "fingerprints": {
            "capability": plan.get("intrinsic_input_hash"),
            "reference": plan.get("context_input_hash"),
            "comparison": plan.get("relationship_hash"),
        },
        "invalidation_reason": (
            plan.get("reason")
            if str(plan.get("reason") or "").startswith("Capability fingerprint")
            else None
        ),
        "stages": [
            {key: value for key, value in item.items() if key != "value"} for item in stages
        ],
        "proposals": proposals,
        "adjudication": (by_key.get("adjudication") or {}).get("value"),
        "comparison": (by_key.get("comparison") or {}).get("value"),
        "strategy": review,
        "recommendations": list((review or {}).get("recommendations") or []),
        "diversity": _proposal_diversity(proposals),
        "input_manifests": manifests,
        "previous_review": None,
        "caveats": _review_caveats(proposals, current),
        "next_action": _next_action(current, stages, semantic_status),
    }


def _stage_rows(connection: Any, snapshot_id: int) -> dict[str, dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM semantic_scope_states WHERE snapshot_id = ? AND scope_type = ? "
        "AND scope_key != ?",
        (snapshot_id, FRESH_EYES_SCOPE, FRESH_EYES_PLAN_KEY),
    ).fetchall()
    return {str(row["scope_key"]): dict(row) for row in rows}


def _stage_payloads(
    connection: Any,
    rows: dict[str, dict[str, Any]],
    proposal_count: int,
) -> list[dict[str, Any]]:
    result = []
    for key, label in _STAGES:
        if key.startswith("proposal:") and ord(key[-1]) - ord("a") >= proposal_count:
            continue
        row = rows.get(key) or {}
        document = _document_record(connection, row.get("context_document_id"))
        result.append(
            {
                "key": key,
                "label": label,
                "state": row.get("status") or "waiting",
                "reason": row.get("reason") or "Waiting for the preceding stage",
                "document_id": document.get("id") if document else None,
                "provenance": _provenance(document),
                "value": document.get("value") if document else None,
            }
        )
    return result


def _document_record(connection: Any, document_id: Any) -> dict[str, Any] | None:
    if not document_id:
        return None
    row = connection.execute(
        "SELECT * FROM semantic_documents WHERE id = ?", (document_id,)
    ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["value"] = json.loads(result.pop("value_json") or "{}")
    return result


def _document_value(connection: Any, document_id: Any) -> dict[str, Any] | None:
    document = _document_record(connection, document_id)
    return document["value"] if document else None


def _input_manifests(
    connection: Any,
    repository_id: int,
    stage_rows: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    result = []
    for scope, _label in _STAGES:
        state = stage_rows.get(scope) or {}
        input_hash = state.get("context_input_hash")
        if not input_hash:
            continue
        row = connection.execute(
            """
            SELECT scope_key, job_kind, status, input_hash, metadata_json FROM semantic_jobs
            WHERE repository_id = ? AND scope_type = ? AND scope_key = ? AND input_hash = ?
            ORDER BY id DESC LIMIT 1
            """,
            (repository_id, FRESH_EYES_SCOPE, state["scope_key"], input_hash),
        ).fetchone()
        if row and (record := _manifest_record(row)) is not None:
            result.append(record)
    return result


def _manifest_record(row: Any) -> dict[str, Any] | None:
    metadata = json.loads(row["metadata_json"] or "{}")
    manifest = metadata.get("input_manifest")
    if not manifest:
        return None
    return {
        "scope": row["scope_key"],
        "job_kind": row["job_kind"],
        "status": row["status"],
        "input_hash": row["input_hash"],
        "manifest": manifest,
        "information_boundary": metadata.get("information_boundary"),
    }


def _capability_brief(status: dict[str, Any]) -> dict[str, Any] | None:
    charter = (status.get("architecture_charter") or {}).get("value") or {}
    return charter.get("capability_brief")


def _provenance(document: dict[str, Any] | None) -> dict[str, Any] | None:
    if not document:
        return None
    return {
        "provider": document.get("provider"),
        "model": document.get("model"),
        "executor_id": document.get("executor_id"),
        "executor_model": document.get("executor_model"),
        "created_at": document.get("created_at"),
    }


def _proposal_diversity(proposals: list[dict[str, Any]]) -> dict[str, Any]:
    provenance = [item.get("provenance") or {} for item in proposals]
    providers = sorted({str(item.get("provider") or "unspecified") for item in provenance})
    models = sorted(
        {
            str(item.get("executor_model") or item.get("model") or "unspecified")
            for item in provenance
        }
    )
    executors = sorted({str(item.get("executor_id") or "unspecified") for item in provenance})
    return {
        "proposal_count": len(proposals),
        "providers": providers,
        "models": models,
        "executors": executors,
        "cross_provider": len(providers) > 1,
        "independent_sessions_recorded": len(executors) == len(proposals),
    }


def _empty_diversity() -> dict[str, Any]:
    return {
        "proposal_count": 0,
        "providers": [],
        "models": [],
        "executors": [],
        "cross_provider": False,
        "independent_sessions_recorded": False,
    }


def _active_state(stages: list[dict[str, Any]], semantic_status: dict[str, Any]) -> str:
    if not semantic_status.get("semantically_ready"):
        return "waiting_for_understanding"
    if any(str(item["state"]).startswith("failed") for item in stages):
        return "failed"
    return "in_progress"


def _next_action(
    current: bool, stages: list[dict[str, Any]], semantic_status: dict[str, Any]
) -> str:
    if current:
        return "Review the ranked suggestions, then use Guide for any change you choose to make."
    if not semantic_status.get("semantically_ready"):
        return "Complete the AI-created repository understanding; review work will then resume."
    failed = next((item for item in stages if str(item["state"]).startswith("failed")), None)
    if failed:
        return f"Retry the failed {failed['label']} task through the semantic executor."
    return "Run the connected semantic executor until the fixed review recipe completes."


def _review_caveats(proposals: list[dict[str, Any]], current: bool) -> list[str]:
    caveats = [
        "AnaxiGraph proves the supplied clean-sheet packet, not the absence of unrelated model context.",
        "Agreement between proposals is evidence of agreement, not proof of correctness.",
    ]
    if proposals and not _proposal_diversity(proposals)["cross_provider"]:
        caveats.append("The proposals do not represent cross-provider agreement.")
    if not current:
        caveats.append("The review is incomplete; do not treat partial stages as a refactor plan.")
    return caveats


def _review_identity(repository_id: int, snapshot_id: int, plan: dict[str, Any]) -> str:
    fingerprint = str(plan.get("context_fingerprint") or "pending")[:16]
    return f"{FRESH_EYES_REVIEW_VERSION}:{repository_id}:{snapshot_id}:{fingerprint}"


def _missing_review(repository_id: int) -> dict[str, Any]:
    return {
        "contract_version": FRESH_EYES_REVIEW_VERSION,
        "protocol_version": FRESH_EYES_PROTOCOL_VERSION,
        "repository_id": repository_id,
        "snapshot_id": None,
        "identity": f"{FRESH_EYES_REVIEW_VERSION}:{repository_id}:missing",
        "state": "not_indexed",
        "ready": False,
        "stages": [],
        "recommendations": [],
        "caveats": ["Scan the repository before requesting a fresh-eyes review."],
        "next_action": "Run a structural scan.",
    }

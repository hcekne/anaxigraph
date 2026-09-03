"""Per-stage wall time, output volume, token counts, and attempts for a fresh-eyes generation.

Every fact here is read from the durable queue: ``semantic_jobs`` supplies the claim and completion
timestamps, the accumulated token counts, the executor identity, and the attempt counter, while
``semantic_documents`` supplies the stored output size. Three limits are reported rather than
hidden. ``started_at`` is the claim time, so a duration includes executor think time and any wait
inside the claimed lease. ``attempts_observed`` is a floor: a released lease decrements the counter
and an explicit retry resets it to zero. Reported token counts are only believed when they are
plausible against the packet size the planner estimated for the same job; an implausible count is
recorded and flagged instead of being summed as real usage.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from anaxigraph.semantic_fresh_eyes_plan import FRESH_EYES_SCOPE

TELEMETRY_VERSION = "fresh-eyes-stage-telemetry-v1"
ATTEMPTS_CAVEAT = (
    "attempts_observed is a floor, not a retry count: a released lease decrements the counter and "
    "an explicit retry resets it to zero."
)
DURATION_CAVEAT = (
    "Stage duration is measured from the claim, so it includes executor think time and lease wait."
)
PLAUSIBLE_INPUT_TOKEN_RATIO = 0.1

_JOB_SQL = """
SELECT id AS job_id, status AS job_status, attempts, started_at, completed_at, input_tokens,
       output_tokens, estimated_input_tokens, executor_id, executor_model, error,
       CAST(ROUND((julianday(completed_at) - julianday(started_at)) * 86400000) AS INTEGER)
           AS duration_ms
FROM semantic_jobs
WHERE repository_id = ? AND scope_type = ? AND scope_key = ? AND input_hash = ?
ORDER BY id DESC LIMIT 1
"""
_DOCUMENT_SQL = """
SELECT id AS document_id, LENGTH(value_json) AS output_bytes, created_at AS recorded_at,
       confidence
FROM semantic_documents WHERE id = ?
"""


def stage_telemetry(
    connection: Any,
    repository_id: int,
    stages: list[tuple[str, Any, Any]],
) -> dict[str, dict[str, Any]]:
    """Return one telemetry record per stage, keyed by fresh-eyes scope key.

    ``stages`` names ``(scope_key, input_hash, document_id)`` for each stage of one generation. A
    stage with neither a job nor a stored document is skipped rather than reported as zero work.
    """

    result: dict[str, dict[str, Any]] = {}
    for scope_key, input_hash, document_id in stages:
        job = (
            connection.execute(
                _JOB_SQL, (repository_id, FRESH_EYES_SCOPE, scope_key, input_hash)
            ).fetchone()
            if input_hash
            else None
        )
        document = (
            connection.execute(_DOCUMENT_SQL, (document_id,)).fetchone() if document_id else None
        )
        if job is None and document is None:
            continue
        result[str(scope_key)] = _stage_record(str(scope_key), job, document)
    return result


def telemetry_totals(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Sum one generation's stage records, believing only plausible reported token counts."""

    reported = [item for item in records if item["token_counts_reported"]]
    plausible = [item for item in reported if item["input_tokens_plausible"]]
    return {
        "contract_version": TELEMETRY_VERSION,
        "stage_count": len(records),
        "wall_clock_ms": _wall_clock_ms(records),
        "stage_duration_ms": sum(int(item["duration_ms"] or 0) for item in records),
        "output_bytes": sum(int(item["output_bytes"] or 0) for item in records),
        "input_tokens": sum(int(item["input_tokens"] or 0) for item in plausible),
        "output_tokens": sum(int(item["output_tokens"] or 0) for item in reported),
        "attempts_observed": sum(int(item["attempts_observed"] or 0) for item in records),
        "stages_reporting_usage": len(reported),
        "stages_with_implausible_input_tokens": len(reported) - len(plausible),
        "caveats": _totals_caveats(records, reported, plausible),
    }


def _stage_record(
    scope_key: str,
    job: Any,
    document: Any,
) -> dict[str, Any]:
    job_row = dict(job) if job is not None else {}
    document_row = dict(document) if document is not None else {}
    input_tokens = int(job_row.get("input_tokens") or 0)
    output_tokens = int(job_row.get("output_tokens") or 0)
    estimated = int(job_row.get("estimated_input_tokens") or 0)
    reported = input_tokens > 0 or output_tokens > 0
    return {
        "key": scope_key,
        "job_id": job_row.get("job_id"),
        "job_status": job_row.get("job_status"),
        "attempts_observed": int(job_row.get("attempts") or 0),
        "started_at": job_row.get("started_at"),
        "completed_at": job_row.get("completed_at"),
        "duration_ms": max(0, int(job_row["duration_ms"])) if job_row.get("duration_ms") else 0,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_input_tokens": estimated,
        "token_counts_reported": reported,
        "input_tokens_plausible": _plausible(input_tokens, estimated),
        "output_bytes": int(document_row.get("output_bytes") or 0),
        "document_id": document_row.get("document_id"),
        "recorded_at": document_row.get("recorded_at"),
        "executor_id": job_row.get("executor_id"),
        "executor_model": job_row.get("executor_model"),
        "error": job_row.get("error"),
    }


def _plausible(input_tokens: int, estimated_input_tokens: int) -> bool:
    """Believe a reported input count only when it is near the estimated packet size."""

    if input_tokens <= 0:
        return False
    if estimated_input_tokens <= 0:
        return True
    return input_tokens >= estimated_input_tokens * PLAUSIBLE_INPUT_TOKEN_RATIO


def _wall_clock_ms(records: list[dict[str, Any]]) -> int:
    started = [_moment(item["started_at"]) for item in records if item.get("started_at")]
    completed = [_moment(item["completed_at"]) for item in records if item.get("completed_at")]
    starts = [item for item in started if item is not None]
    ends = [item for item in completed if item is not None]
    if not starts or not ends:
        return 0
    return max(0, round((max(ends) - min(starts)).total_seconds() * 1000))


def _moment(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _totals_caveats(
    records: list[dict[str, Any]],
    reported: list[dict[str, Any]],
    plausible: list[dict[str, Any]],
) -> list[str]:
    caveats = [ATTEMPTS_CAVEAT, DURATION_CAVEAT]
    silent = [item["key"] for item in records if not item["token_counts_reported"]]
    if silent:
        caveats.append(
            f"{len(silent)} stage(s) reported no token counts and are excluded from the totals: "
            + ", ".join(sorted(silent))
        )
    for item in reported:
        if item in plausible:
            continue
        caveats.append(
            f"Stage {item['key']} reported {item['input_tokens']} input tokens against an "
            f"estimated {item['estimated_input_tokens']}; the count is recorded, not summed."
        )
    return caveats

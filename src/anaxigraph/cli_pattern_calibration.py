"""CLI adapters for local and service-backed pattern calibration reads."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from anaxigraph.pattern_calibration import calibrate_patterns
from anaxigraph.pattern_calibration_models import (
    PatternCalibrationManifest,
    load_pattern_calibration,
)
from anaxigraph.pattern_candidate_query import PatternCandidateQuery
from anaxigraph.pattern_intelligence import PatternIntelligenceService
from anaxigraph.pattern_query import PatternEvaluationQuery
from anaxigraph.semantic_service import (
    discover_semantic_service,
    service_pattern_candidates,
    service_pattern_evaluations,
)


def load_manifest(path: Path | None) -> PatternCalibrationManifest | None:
    return load_pattern_calibration(path) if path is not None else None


def query(args: Any) -> PatternEvaluationQuery | PatternCandidateQuery:
    if args.candidates:
        return PatternCandidateQuery(
            pattern=args.pattern,
            target=args.target,
            level=args.level,
            selection=args.selection,
            limit=args.limit,
            offset=args.offset,
            include_evidence=args.include_evidence,
        )
    return PatternEvaluationQuery(
        target=args.target,
        pattern=args.pattern,
        level=args.level,
        recommendation=args.recommendation,
        presence=args.presence,
        sort_by=args.sort_by,
        minimum_score=args.minimum_score,
        limit=args.limit,
        offset=args.offset,
        include_evidence=args.include_evidence,
    )


def discover_service(repository: Path, explicit_url: str | None) -> Any:
    return discover_semantic_service(repository, explicit_url=explicit_url)


def service_query(
    service: Any,
    request: PatternEvaluationQuery | PatternCandidateQuery,
    snapshot_id: int | None,
) -> dict[str, Any]:
    if isinstance(request, PatternCandidateQuery):
        return service_pattern_candidates(service, request, snapshot_id=snapshot_id)
    return service_pattern_evaluations(service, request, snapshot_id=snapshot_id)


def local_query(
    database: Any,
    repository_id: int,
    request: PatternEvaluationQuery | PatternCandidateQuery,
    snapshot_id: int | None,
) -> dict[str, Any]:
    service = PatternIntelligenceService(database)
    if isinstance(request, PatternCandidateQuery):
        return service.candidates(repository_id, snapshot_id, request=request)
    return service.query(repository_id, snapshot_id, request=request)


def service_result(
    service: Any,
    manifest: PatternCalibrationManifest,
    snapshot_id: int | None,
) -> dict[str, Any]:
    return calibrate_patterns(
        manifest,
        candidates=lambda request: service_pattern_candidates(
            service, request, snapshot_id=snapshot_id
        ),
        evaluations=lambda request: service_pattern_evaluations(
            service, request, snapshot_id=snapshot_id
        ),
    )


def local_result(
    database: Any,
    repository_id: int,
    manifest: PatternCalibrationManifest,
    snapshot_id: int | None,
) -> dict[str, Any]:
    service = PatternIntelligenceService(database)
    return calibrate_patterns(
        manifest,
        candidates=lambda request: service.candidates(repository_id, snapshot_id, request=request),
        evaluations=lambda request: service.query(repository_id, snapshot_id, request=request),
    )

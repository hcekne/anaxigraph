"""Strict, provider-neutral contracts for pattern calibration manifests."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from anaxigraph.pattern_catalog import bundled_pattern_catalog
from anaxigraph.pattern_catalog_models import PatternCatalog
from anaxigraph.pattern_evaluation_contract import (
    PATTERN_REVIEW_CONTRACT_VERSION,
    PATTERN_SCORE_CONTRACT_VERSION,
    PATTERN_SCORE_DIMENSIONS,
)
from anaxigraph.pattern_targets import PATTERN_TARGET_LEVELS

PATTERN_CALIBRATION_VERSION = "pattern-calibration-v1"
PATTERN_CALIBRATION_MAX_BYTES, PATTERN_CALIBRATION_MAX_CASES = 250_000, 1_000

_KEY = re.compile(r"^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$")
_PRESENCE = frozenset({"present", "partial", "absent", "uncertain"})
_RECOMMENDATIONS = frozenset(
    "retain introduce improve_conformance replace avoid no_action insufficient_evidence".split()
)
_VERDICTS = frozenset({"approve", "revise", "retain_competing"})


@dataclass(frozen=True, slots=True)
class ScoreExpectation:
    dimension: str
    minimum: int
    maximum: int

    def __post_init__(self) -> None:
        if self.dimension not in PATTERN_SCORE_DIMENSIONS:
            raise ValueError(f"unknown calibrated pattern score: {self.dimension}")
        if not 0 <= self.minimum <= self.maximum <= 100:
            raise ValueError("calibrated pattern score range must stay between zero and 100")


@dataclass(frozen=True, slots=True)
class PatternCalibrationCase:
    case_id: str
    category: str
    pattern: str
    target: str
    expected_relevant: bool
    presence: tuple[str, ...]
    recommendations: tuple[str, ...]
    scores: tuple[ScoreExpectation, ...]
    review_verdicts: tuple[str, ...]
    false_positive_cause: str = ""

    @property
    def expects_rating(self) -> bool:
        return bool(self.presence or self.recommendations or self.scores or self.review_verdicts)


@dataclass(frozen=True, slots=True)
class PatternCalibrationThresholds:
    candidate_precision: float
    candidate_recall: float
    rating_pass_rate: float
    maximum_confidence_brier: float
    require_complete: bool

    def __post_init__(self) -> None:
        for name, value in (
            ("candidate_precision", self.candidate_precision),
            ("candidate_recall", self.candidate_recall),
            ("rating_pass_rate", self.rating_pass_rate),
            ("maximum_confidence_brier", self.maximum_confidence_brier),
        ):
            if not 0 <= value <= 1:
                raise ValueError(
                    f"pattern calibration threshold {name} must be between zero and one"
                )


@dataclass(frozen=True, slots=True)
class PatternCalibrationManifest:
    name: str
    catalog_version: str
    score_contract_version: str
    review_contract_version: str
    thresholds: PatternCalibrationThresholds
    cases: tuple[PatternCalibrationCase, ...]
    contract_version: str = PATTERN_CALIBRATION_VERSION

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


def load_pattern_calibration(
    path: str | Path,
    *,
    max_bytes: int = PATTERN_CALIBRATION_MAX_BYTES,
    catalog: PatternCatalog | None = None,
) -> PatternCalibrationManifest:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise ValueError(f"pattern calibration manifest does not exist: {target}")
    encoded = target.read_bytes()
    if not 1 <= len(encoded) <= max_bytes:
        raise ValueError(f"pattern calibration manifest must be at most {max_bytes} bytes")
    try:
        value = json.loads(encoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid pattern calibration JSON: {exc}") from exc
    return pattern_calibration_manifest(value, catalog=catalog)


def pattern_calibration_manifest(
    value: Any,
    *,
    catalog: PatternCatalog | None = None,
) -> PatternCalibrationManifest:
    mapping = _mapping(value, "pattern calibration manifest")
    _only_keys(
        mapping,
        {
            "contract_version",
            "name",
            "catalog_version",
            "score_contract_version",
            "review_contract_version",
            "thresholds",
            "cases",
        },
        "pattern calibration manifest",
    )
    selected_catalog = catalog or bundled_pattern_catalog()
    _require_version(mapping, selected_catalog)
    cases = _manifest_cases(mapping.get("cases"), selected_catalog)
    name = _manifest_name(mapping.get("name"))
    return PatternCalibrationManifest(
        name=name,
        catalog_version=selected_catalog.catalog_version,
        score_contract_version=PATTERN_SCORE_CONTRACT_VERSION,
        review_contract_version=PATTERN_REVIEW_CONTRACT_VERSION,
        thresholds=_thresholds(mapping.get("thresholds")),
        cases=cases,
    )


def _manifest_cases(value: Any, catalog: PatternCatalog) -> tuple[PatternCalibrationCase, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= PATTERN_CALIBRATION_MAX_CASES:
        raise ValueError("pattern calibration manifest requires one to 1,000 cases")
    cases = tuple(_case(item, catalog) for item in value)
    identifiers = [item.case_id for item in cases]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("pattern calibration case ids must be unique")
    return cases


def _manifest_name(value: Any) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValueError("pattern calibration manifest requires a name")
    return name


def _require_version(mapping: dict[str, Any], catalog: PatternCatalog) -> None:
    expected = {
        "contract_version": PATTERN_CALIBRATION_VERSION,
        "catalog_version": catalog.catalog_version,
        "score_contract_version": PATTERN_SCORE_CONTRACT_VERSION,
        "review_contract_version": PATTERN_REVIEW_CONTRACT_VERSION,
    }
    for field, value in expected.items():
        if mapping.get(field) != value:
            raise ValueError(f"pattern calibration {field} must be {value}")


def _thresholds(value: Any) -> PatternCalibrationThresholds:
    mapping = _mapping(value, "pattern calibration thresholds")
    fields = {
        "candidate_precision",
        "candidate_recall",
        "rating_pass_rate",
        "maximum_confidence_brier",
        "require_complete",
    }
    _only_keys(mapping, fields, "pattern calibration thresholds")
    if set(mapping) != fields:
        raise ValueError("pattern calibration thresholds require every metric")
    if not isinstance(mapping["require_complete"], bool):
        raise ValueError("pattern calibration require_complete must be boolean")
    return PatternCalibrationThresholds(
        candidate_precision=_ratio_value(mapping["candidate_precision"], "candidate_precision"),
        candidate_recall=_ratio_value(mapping["candidate_recall"], "candidate_recall"),
        rating_pass_rate=_ratio_value(mapping["rating_pass_rate"], "rating_pass_rate"),
        maximum_confidence_brier=_ratio_value(
            mapping["maximum_confidence_brier"], "maximum_confidence_brier"
        ),
        require_complete=mapping["require_complete"],
    )


def _case(value: Any, catalog: PatternCatalog) -> PatternCalibrationCase:
    mapping = _mapping(value, "pattern calibration case")
    _only_keys(
        mapping,
        {"id", "category", "pattern", "target", "expected", "false_positive_cause"},
        "pattern calibration case",
    )
    case_id = _key(mapping.get("id"), "case id")
    category = _key(mapping.get("category"), "case category")
    pattern = str(mapping.get("pattern") or "")
    if catalog.card(pattern) is None:
        raise ValueError(f"unknown calibrated pattern key: {pattern}")
    target = str(mapping.get("target") or "")
    level, separator, identity = target.partition(":")
    valid_repository = level == "repository" and identity == "root"
    valid_scoped = level in PATTERN_TARGET_LEVELS[:-1] and bool(identity)
    if not separator or not (valid_repository or valid_scoped):
        raise ValueError(f"invalid calibrated pattern target: {target}")
    expected = _mapping(mapping.get("expected"), f"calibration case {case_id} expected")
    _only_keys(
        expected,
        {"relevant", "presence", "recommendations", "scores", "review_verdicts"},
        f"calibration case {case_id} expected",
    )
    if not isinstance(expected.get("relevant"), bool):
        raise ValueError(f"calibration case {case_id} relevant must be boolean")
    return PatternCalibrationCase(
        case_id=case_id,
        category=category,
        pattern=pattern,
        target=target,
        expected_relevant=expected["relevant"],
        presence=_choices(expected.get("presence", []), _PRESENCE, "presence"),
        recommendations=_choices(
            expected.get("recommendations", []), _RECOMMENDATIONS, "recommendation"
        ),
        scores=_score_ranges(expected.get("scores", {})),
        review_verdicts=_choices(expected.get("review_verdicts", []), _VERDICTS, "review verdict"),
        false_positive_cause=str(mapping.get("false_positive_cause") or "")[:500],
    )


def _score_ranges(value: Any) -> tuple[ScoreExpectation, ...]:
    mapping = _mapping(value, "calibrated pattern scores")
    result = []
    for dimension in PATTERN_SCORE_DIMENSIONS:
        if dimension not in mapping:
            continue
        bounds = mapping[dimension]
        if not isinstance(bounds, list) or len(bounds) != 2:
            raise ValueError(f"calibrated {dimension} score requires [minimum, maximum]")
        if any(type(item) is not int for item in bounds):
            raise ValueError(f"calibrated {dimension} score bounds must be integers")
        result.append(ScoreExpectation(dimension, bounds[0], bounds[1]))
    unknown = set(mapping) - set(PATTERN_SCORE_DIMENSIONS)
    if unknown:
        raise ValueError(f"unknown calibrated pattern scores: {sorted(unknown)}")
    return tuple(result)


def _choices(value: Any, allowed: frozenset[str], label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"calibrated {label} values must be an array")
    result = tuple(sorted({str(item) for item in value}))
    unknown = set(result) - allowed
    if unknown:
        raise ValueError(f"unknown calibrated {label} values: {sorted(unknown)}")
    return result


def _ratio_value(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"pattern calibration threshold {label} must be numeric")
    return float(value)


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _only_keys(value: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"{label} has unsupported fields: {sorted(unknown)}")


def _key(value: Any, label: str) -> str:
    result = str(value or "")
    if not _KEY.fullmatch(result):
        raise ValueError(f"invalid pattern calibration {label}: {result}")
    return result

"""Architecture finding value object and built-in inspection rules."""

from __future__ import annotations

from dataclasses import dataclass

from anaxigraph.config import RuleConfig


@dataclass(frozen=True, slots=True)
class Finding:
    stable_key: str
    finding_type: str
    severity: str
    confidence: float
    summary: str
    explanation: str
    affected_artifacts: tuple[str, ...]
    evidence: tuple[str, ...]
    recommended_action: str
    source: str = "deterministic"


DEFAULT_RULES = (
    RuleConfig(
        rule_id="module-size",
        rule_type="max_module_loc",
        severity="warning",
        description="Large modules are inspection signals for mixed responsibilities.",
        params={"max": 300},
    ),
    RuleConfig(
        rule_id="function-size",
        rule_type="max_function_lines",
        severity="info",
        description="Long functions are inspection signals, not automatic design failures.",
        params={"max": 25},
    ),
    RuleConfig(
        rule_id="symbol-complexity",
        rule_type="max_symbol_complexity",
        severity="warning",
        description="Complex symbols deserve focused tests and possible simplification.",
        params={"max": 10},
    ),
    RuleConfig(
        rule_id="fan-out",
        rule_type="max_fan_out",
        severity="warning",
        description="High fan-out can indicate an orchestration or boundary problem.",
        params={"max": 12},
    ),
    RuleConfig(
        rule_id="dependency-cycles",
        rule_type="no_cycles",
        severity="warning",
        description="Module dependency cycles make isolated changes harder.",
    ),
    RuleConfig(
        rule_id="stale-unreferenced-source",
        rule_type="dead_code",
        severity="info",
        description="Combine static reachability and change age to identify candidates only.",
        params={"minimum_age_days": 90, "minimum_resolution_rate": 0.95},
    ),
)

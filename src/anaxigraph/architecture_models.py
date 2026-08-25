"""Architecture finding value object and built-in inspection rules."""

from __future__ import annotations

from dataclasses import dataclass

from anaxigraph.config import RuleConfig

DETECTOR_VERSION = "architecture-findings-v1"


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
        description="A very large file may contain jobs that should change separately.",
        params={"max": 300},
    ),
    RuleConfig(
        rule_id="function-size",
        rule_type="max_function_lines",
        severity="info",
        description="A long function may mix steps that would be clearer on their own.",
        params={"max": 25},
    ),
    RuleConfig(
        rule_id="symbol-complexity",
        rule_type="max_symbol_complexity",
        severity="warning",
        description="A function with many decisions has more cases to understand and test.",
        params={"max": 10},
    ),
    RuleConfig(
        rule_id="fan-out",
        rule_type="max_fan_out",
        severity="warning",
        description="A file that uses many modules may be coordinating too many jobs.",
        params={"max": 12},
    ),
    RuleConfig(
        rule_id="dependency-cycles",
        rule_type="no_cycles",
        severity="warning",
        description="Modules that depend on one another in a loop are harder to change separately.",
    ),
    RuleConfig(
        rule_id="stale-unreferenced-source",
        rule_type="dead_code",
        severity="info",
        description="An old file with no known callers may no longer be used, but must be checked.",
        params={"minimum_age_days": 90, "minimum_resolution_rate": 0.95},
    ),
)

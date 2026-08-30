"""Semantic graph evidence, fingerprints, prioritization, and source chunking."""

from __future__ import annotations

from typing import Any

from anaxigraph.config import SemanticConfig
from anaxigraph.semantic_freshness import semantic_digest


class SupersededSemanticJob(RuntimeError):
    pass


def _interface_hash(module: dict[str, Any]) -> str:
    return semantic_digest(
        {
            "public_interfaces": module.get("public_interfaces", []),
            "symbols": [
                {
                    "type": item["symbol_type"],
                    "name": item["name"],
                    "signature": item["signature"],
                }
                for item in module.get("symbols", [])
            ],
        }
    )


def _module_priority(module: dict[str, Any], reason: str) -> int:
    reason_weight = {
        "bootstrap_missing": 80,
        "source_or_semantic_policy_changed": 100,
        "manual_full_review": 90,
        "age_expired": 40,
        "context_missing": 60,
        "architectural_context_changed": 75,
    }.get(reason, 50)
    size = min(20, int(module.get("lines_of_code") or 0) // 100)
    complexity = min(20, int(float(module.get("complexity") or 0) // 10))
    return reason_weight + size + complexity


def _source_chunks(
    source: str, symbols: list[dict[str, Any]], max_chars: int
) -> list[tuple[int, int, str]]:
    lines = source.splitlines(keepends=True)
    symbol_ends = sorted(
        {int(item.get("end_line") or 0) for item in symbols if int(item.get("end_line") or 0) > 0}
    )
    result = []
    start = 0
    while start < len(lines):
        size = 0
        end = start
        while end < len(lines) and (size + len(lines[end]) <= max_chars or end == start):
            size += len(lines[end])
            end += 1
        candidate_ends = [line for line in symbol_ends if start + 1 < line <= end]
        if candidate_ends and end < len(lines):
            end = max(candidate_ends)
        result.append((start + 1, end, "".join(lines[start:end])))
        start = end
    return result or [(1, 1, "")]


def _intent_fingerprint(value: dict[str, Any]) -> str:
    def normalized_terms(key: str) -> list[str]:
        terms = {
            " ".join(str(item).split()).casefold()
            for item in (value.get(key) or [])
            if str(item).strip()
        }
        return sorted(terms)

    return semantic_digest(
        {
            key: normalized_terms(key)
            for key in (
                "responsibilities",
                "inputs",
                "outputs",
                "side_effects",
                "public_contracts",
                "invariants",
                "domain_concepts",
            )
        }
        | {
            "architecture_role": " ".join(
                str(value.get("architecture_role") or "").split()
            ).casefold()
        }
    )


def _cost(input_tokens: int, output_tokens: int, semantic: SemanticConfig) -> float:
    return round(
        input_tokens * semantic.input_cost_per_million / 1_000_000
        + output_tokens * semantic.output_cost_per_million / 1_000_000,
        8,
    )

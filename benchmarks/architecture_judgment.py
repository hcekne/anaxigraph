"""Opt-in model-backed architecture judgments on small, explicit synthetic cases."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from anaxigraph.config import SemanticConfig
from anaxigraph.pattern_catalog import bundled_pattern_catalog
from anaxigraph.pattern_evaluation_contract import PATTERN_SCORE_CONTRACT_VERSION
from anaxigraph.semantic import CodexSemanticProvider
from anaxigraph.semantic_contract import SEMANTIC_SCHEMA_VERSION
from anaxigraph.semantic_evidence_selection import evidence_bytes
from anaxigraph.semantic_freshness import semantic_digest
from anaxigraph.semantic_pattern_requests import _constraints, _contract

FIXTURE = Path(__file__).parent / "fixtures" / "architecture-judgment.json"


def judgment_request(case: dict[str, Any]) -> dict[str, Any]:
    card = next(
        item for item in bundled_pattern_catalog().cards if item.stable_key == case["pattern"]
    )
    identity = semantic_digest(case["sources"])[:12]
    target = {"key": f"{case['level']}:fixture-{identity}", "level": case["level"]}
    return {
        "analysis_kind": "pattern_assessment",
        "contract": _contract("pattern_assessment"),
        "schema_version": SEMANTIC_SCHEMA_VERSION,
        "score_contract_version": PATTERN_SCORE_CONTRACT_VERSION,
        "candidate": {
            "input_fingerprint": semantic_digest(
                {"facts": case["facts"], "sources": case["sources"]}
            ),
            "pattern_key": card.stable_key,
            "target": target,
        },
        "pattern": card.as_dict(),
        "constraints": _constraints(card.kind),
        "target_evidence": {
            "observations": case["facts"],
            "provenance": "controlled synthetic fixture",
        },
        "source_witnesses": [
            {"path": path, "source": source} for path, source in case["sources"].items()
        ],
    }


def judge_case(case: dict[str, Any], provider: Any) -> dict[str, Any]:
    request = judgment_request(case)
    started = time.monotonic()
    stages = []
    result = {
        "id": case["id"],
        "pattern": case["pattern"],
        "level": case["level"],
        "category": case["category"],
        "expected": case["expected"],
    }
    try:
        assessment = run_stage(provider, request, stages)
        review_request = {
            **request,
            "analysis_kind": "pattern_review",
            "contract": _contract("pattern_review"),
            "assessment": assessment.value,
        }
        review = run_stage(provider, review_request, stages)
        evaluation = review.value["evaluation"]
        result.update(
            recommendation=evaluation["recommendation"],
            passed=evaluation["recommendation"] in case["expected"],
            assessment=assessment.value,
            review=review.value,
        )
    except Exception as error:
        result.update(passed=False, error=f"{type(error).__name__}: {error}")
    return {**result, "duration_seconds": round(time.monotonic() - started, 3), "stages": stages}


def run_stage(provider, request, stages):
    started = time.monotonic()
    result = provider.analyze(request)
    stages.append(
        {
            "kind": request["analysis_kind"],
            "request_bytes": evidence_bytes(request),
            "duration_seconds": round(time.monotonic() - started, 3),
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "cache_read_input_tokens": result.cache_read_input_tokens,
            "usage_source": "reported" if result.usage_reported else "unknown",
            "cost_usd": None,
        }
    )
    return result


def judgment_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "cases_completed": len(results),
        "passed": sum(item["passed"] for item in results),
        "known_positive_misses": sum(
            not item["passed"] for item in results if item["category"] == "retain"
        ),
        "unsupported_change_advice": sum(
            item.get("recommendation")
            in {"introduce", "replace", "improve_conformance", "remediate"}
            for item in results
            if item["category"] in {"negative", "uncertain"}
        ),
        "scope_levels": sorted({item["level"] for item in results}),
        "input_tokens": sum(stage["input_tokens"] for item in results for stage in item["stages"]),
        "output_tokens": sum(
            stage["output_tokens"] for item in results for stage in item["stages"]
        ),
        "stages_with_unknown_usage": sum(
            stage["usage_source"] == "unknown" for item in results for stage in item["stages"]
        ),
        "cost_usd": None,
        "cost_caveat": "Executor token reports are retained; subscription or monetary cost was not supplied.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--reasoning-effort", required=True)
    parser.add_argument("--parallel", type=int, choices=(1, 2), default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; use a new report path to preserve prior evidence")
    cases = json.loads(FIXTURE.read_text())["cases"]
    provider = CodexSemanticProvider(
        SemanticConfig(
            enabled=True,
            provider="codex",
            model=args.model,
            reasoning_effort=args.reasoning_effort,
            timeout_seconds=1200,
            max_output_tokens=6000,
        )
    )
    report = {
        "contract": "architecture-judgment-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "provider": "codex",
        "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], text=True)),
        "fixture_fingerprint": semantic_digest(cases),
        "cases_expected": len(cases),
        "results": [],
        "caveat": "Small synthetic judgment check, not exhaustive architectural accuracy or proof of production behavior. No expected answers are supplied to the model.",
    }
    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = [pool.submit(judge_case, case, provider) for case in cases]
        for future in as_completed(futures):
            result = future.result()
            report["results"].append(result)
            report["results"].sort(key=lambda item: item["id"])
            report["summary"] = judgment_summary(report["results"])
            args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
            print(
                json.dumps(
                    {key: result.get(key) for key in ("id", "passed", "recommendation", "error")}
                ),
                flush=True,
            )
    return 0 if all(item["passed"] for item in report["results"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())

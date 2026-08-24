"""Shared fixtures for semantic-understanding tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml


def _semantic_config(repository: Path, provider: Path, log: Path, **overrides) -> None:
    config_path = repository / ".anaxigraph.yml"
    value = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    value["semantic"] = {
        "enabled": True,
        "provider": "command",
        "command": [sys.executable, str(provider), str(log)],
        "prompt_version": "test-v1",
        "max_jobs_per_run": 100,
        "max_parallel_jobs": 2,
        "max_attempts": 1,
        **overrides,
    }
    config_path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def _fake_provider(tmp_path: Path, *, fail_path: str = "") -> Path:
    provider = tmp_path / "semantic_provider.py"
    provider.write_text(
        """from __future__ import annotations
import json
import sys

request = json.load(sys.stdin)
path = str(request.get("path") or request.get("scope_key") or "scope")
kind = str(request.get("analysis_kind") or "unknown")
with open(sys.argv[1], "a", encoding="utf-8") as stream:
    stream.write(json.dumps({"path": path, "kind": kind}) + "\\n")
if FAIL_PATH and path == FAIL_PATH and kind == "intrinsic":
    raise SystemExit(7)
def taxonomy_value():
    modules = request.get("modules") or []
    members = [{
        "path": item["path"],
        "confidence": 0.85,
        "rationale": "Shares the sample repository responsibility.",
        "evidence": [item["path"]],
        "alternatives": [],
    } for item in modules]
    return {
        "summary": "A responsibility-based sample repository map.",
        "areas": [{
            "key": "repository-intelligence",
            "name": "Repository intelligence",
            "description": "Owns the indexed sample application.",
            "responsibility": "Deliver the sample repository behavior.",
            "confidence": 0.85,
            "rationale": "The supplied modules form one small cohesive sample.",
            "evidence": [item["path"] for item in modules[:5]],
            "counter_evidence": [],
            "subsystems": [{
                "key": "sample-runtime",
                "name": "Sample runtime",
                "description": "Implements and verifies sample behavior.",
                "responsibility": "Own implementation, presentation, tests, and docs.",
                "confidence": 0.85,
                "rationale": "The repository is intentionally small.",
                "evidence": [item["path"] for item in modules[:5]],
                "counter_evidence": [],
                "members": members,
            }],
        }] if members else [],
        "facets": [],
        "confidence": 0.85,
        "evidence": [item["path"] for item in modules[:5]],
    }

dossier = {
    "summary": f"{kind} understanding for {path}",
    "detailed_summary": f"Evidence-grounded {kind} dossier for {path}.",
    "responsibilities": [f"Own {path}"],
    "inputs": [],
    "outputs": [],
    "side_effects": [],
    "public_contracts": [],
    "invariants": [],
    "architecture_role": "test role",
    "domain_concepts": [],
    "collaborators": [],
    "overlaps": [],
    "extension_points": [],
    "similar_modules": [],
    "pattern_opportunities": [] if kind == "intrinsic" else [{
        "name": "Repository-local adapter",
        "scope": "module",
        "score": 84,
        "confidence": 0.8,
        "rationale": "The supplied neighboring dossiers share a stable boundary.",
        "evidence": [f"{path}:1"],
        "counter_evidence": [],
        "migration_cost": "low",
        "preconditions": ["Verify the shared contract"],
    }],
    "consolidation_assessment": {
        "recommendation": "insufficient_evidence",
        "score": 0,
        "rationale": "",
        "candidates": [],
        "evidence": [],
        "counter_evidence": [],
    },
    "dead_code_candidates": [],
    "placement_guidance": "",
    "testing_guidance": [],
    "change_summary": "",
    "risks": [],
    "evidence": [f"{path}:1"],
    "confidence": 0.9,
}
if kind == "taxonomy_review":
    value = {
        "verdict": "approve",
        "summary": "The candidate is coherent for this sample.",
        "issues": [],
        "taxonomy": request.get("candidate_taxonomy") or taxonomy_value(),
        "confidence": 0.9,
        "evidence": ["Independent review pass completed"],
    }
elif kind.startswith("taxonomy_"):
    value = taxonomy_value()
else:
    value = dossier
json.dump({"result": value, "usage": {"input_tokens": 100, "output_tokens": 40}}, sys.stdout)
""".replace("FAIL_PATH", repr(fail_path)),
        encoding="utf-8",
    )
    return provider


def _calls(log: Path) -> list[dict[str, str]]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def _agent_dossier(request: dict) -> dict:
    scope = str(request.get("path") or request.get("scope_key") or "repository")
    kind = str(request.get("analysis_kind") or "semantic")
    if kind.startswith("taxonomy_"):
        members = [
            {
                "path": item["path"],
                "confidence": 0.8,
                "rationale": "Grouped from supplied semantic evidence.",
                "evidence": [item["path"]],
                "alternatives": [],
            }
            for item in request.get("modules") or []
        ]
        taxonomy = {
            "summary": "Agent-funded semantic repository map.",
            "areas": [
                {
                    "key": "repository",
                    "name": "Repository",
                    "description": "Repository responsibilities.",
                    "responsibility": "Own the analyzed repository.",
                    "confidence": 0.8,
                    "rationale": "Bounded test evidence supports one area.",
                    "evidence": [item["path"] for item in (request.get("modules") or [])[:5]],
                    "counter_evidence": [],
                    "subsystems": [
                        {
                            "key": "repository-modules",
                            "name": "Repository modules",
                            "description": "Analyzed repository modules.",
                            "responsibility": "Own module behavior.",
                            "confidence": 0.8,
                            "rationale": "Bounded test evidence supports one subsystem.",
                            "evidence": [
                                item["path"] for item in (request.get("modules") or [])[:5]
                            ],
                            "counter_evidence": [],
                            "members": members,
                        }
                    ],
                }
            ]
            if members
            else [],
            "facets": [],
            "confidence": 0.8,
            "evidence": ["Agent-funded taxonomy test"],
        }
        if kind == "taxonomy_review":
            return {
                "verdict": "approve",
                "summary": "Reviewed the candidate taxonomy.",
                "issues": [],
                "taxonomy": request.get("candidate_taxonomy") or taxonomy,
                "confidence": 0.85,
                "evidence": ["Independent agent review"],
            }
        return taxonomy
    return {
        "summary": f"{kind} understanding for {scope}",
        "detailed_summary": f"Evidence-grounded {kind} dossier for {scope}.",
        "responsibilities": [f"Own {scope}"],
        "inputs": [],
        "outputs": [],
        "side_effects": [],
        "public_contracts": [],
        "invariants": [],
        "architecture_role": "agent-funded test role",
        "domain_concepts": [],
        "collaborators": [],
        "overlaps": [],
        "extension_points": [],
        "similar_modules": [],
        "pattern_opportunities": [],
        "consolidation_assessment": {
            "recommendation": "insufficient_evidence",
            "score": 0,
            "rationale": "No consolidation claim without contextual evidence.",
            "candidates": [],
            "evidence": [],
            "counter_evidence": [],
        },
        "dead_code_candidates": [],
        "placement_guidance": "",
        "testing_guidance": [],
        "change_summary": "",
        "risks": [],
        "evidence": [scope],
        "confidence": 0.9,
    }

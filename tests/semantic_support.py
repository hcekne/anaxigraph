"""Shared fixtures for semantic-understanding tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml
from fresh_eyes_support import agent_fresh_eyes

from anaxigraph.semantic import SemanticResult
from anaxigraph.semantic_service import SemanticServiceTarget


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


def _enable_agent_semantics(repository: Path) -> None:
    path = repository / ".anaxigraph.yml"
    policy = yaml.safe_load(path.read_text(encoding="utf-8"))
    policy["semantic"] = {
        "enabled": True,
        "provider": "agent",
        "max_parallel_jobs": 16,
        "agent_lease_seconds": 120,
        "taxonomy": {"enabled": True, "review_passes": 2},
    }
    path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")


def _service_target(base_url: str, repository_id: int, repository: Path) -> SemanticServiceTarget:
    return SemanticServiceTarget(
        base_url,
        repository_id,
        "Large semantic fixture",
        str(repository),
    )


class _DeterministicLifecycleProvider:
    name = "deterministic-lifecycle"

    def analyze(self, request):
        value = _agent_dossier(request)
        return SemanticResult(
            value=value,
            confidence=float(value.get("confidence") or 0.8),
            evidence=tuple(value.get("evidence") or ()),
        )


def _fake_provider(tmp_path: Path, *, fail_path: str = "") -> Path:
    provider = tmp_path / "semantic_provider.py"
    charter_json = json.dumps(_agent_charter(), separators=(",", ":"))
    provider.write_text(
        """from __future__ import annotations
import json
import sys

request = json.load(sys.stdin)
CHARTER_VALUE = json.loads(CHARTER_VALUE_JSON)
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
def pattern_evaluation():
    candidate = request["candidate"]
    target_key = candidate["target"]["key"]
    pattern_key = candidate["pattern_key"]
    values = {
        "applicability": 75, "suitability": 70, "conformance": 20,
        "opportunity": 65, "confidence": 80, "benefit": 70, "urgency": 40,
        "execution_safety": 65, "migration_cost": 35,
    }
    return {
        "score_contract_version": "pattern-scores-v1",
        "candidate_fingerprint": candidate["input_fingerprint"],
        "pattern_key": pattern_key,
        "target_key": target_key,
        "summary": f"{pattern_key} is a plausible repository-local option for {target_key}.",
        "presence": "absent",
        "recommendation": "introduce",
        "scores": {name: {
            "value": value,
            "rationale": f"Supplied evidence supports the {name} score.",
            "evidence": [target_key],
        } for name, value in values.items()},
        "rationale": "The sparse deterministic candidate has enough local evidence to assess.",
        "evidence": [target_key],
        "counter_evidence": list(candidate.get("capability_gaps") or []),
        "affected_targets": [target_key],
        "local_precedents": [],
        "alternatives": list(request["pattern"]["relations"]["alternatives"]),
        "prerequisites": ["Preserve existing behavior."],
        "risks": ["The abstraction could cost more than it saves."],
        "invariants": list(request["pattern"]["verification_invariants"]),
        "invalidation_conditions": ["The supporting evidence no longer applies."],
    }
if kind == "pattern_assessment":
    value = pattern_evaluation()
elif kind == "pattern_review":
    value = {
        "review_contract_version": "pattern-review-v1",
        "candidate_fingerprint": request["candidate"]["input_fingerprint"],
        "verdict": "approve",
        "summary": "The independent critique found the evidence and scores coherent.",
        "issues": [],
        "evaluation": request["assessment"],
        "competing_interpretations": [],
        "confidence": 80,
        "evidence": [request["candidate"]["target"]["key"]],
    }
elif kind == "taxonomy_review":
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
elif kind.startswith("synthesis") and request.get("scope_type") == "repository":
    value = CHARTER_VALUE
else:
    value = dossier
json.dump({"result": value, "usage": {"input_tokens": 100, "output_tokens": 40}}, sys.stdout)
""".replace("FAIL_PATH", repr(fail_path)).replace("CHARTER_VALUE_JSON", repr(charter_json)),
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
    if kind.startswith("fresh_"):
        return agent_fresh_eyes(request, kind)
    if kind.startswith("pattern_"):
        return _agent_pattern_response(request, kind)
    if kind.startswith("taxonomy_"):
        return _agent_taxonomy(request, kind)
    if kind.startswith("synthesis") and request.get("scope_type") == "repository":
        return _agent_charter()
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


def _agent_taxonomy(request: dict, kind: str) -> dict:
    modules = request.get("modules") or []
    members = [
        {
            "path": item["path"],
            "confidence": 0.8,
            "rationale": "Grouped from supplied semantic evidence.",
            "evidence": [item["path"]],
            "alternatives": [],
        }
        for item in modules
    ]
    taxonomy = {
        "summary": "Agent-funded semantic repository map.",
        "areas": [_agent_taxonomy_area(modules, members)] if members else [],
        "facets": [],
        "confidence": 0.8,
        "evidence": ["Agent-funded taxonomy test"],
    }
    if not kind.startswith("taxonomy_review"):
        return taxonomy
    return {
        "verdict": "approve",
        "summary": "Reviewed the candidate taxonomy.",
        "issues": [],
        "taxonomy": request.get("candidate_taxonomy") or taxonomy,
        "confidence": 0.85,
        "evidence": ["Independent agent review"],
    }


def _agent_taxonomy_area(modules: list[dict], members: list[dict]) -> dict:
    evidence = [item["path"] for item in modules[:5]]
    return {
        "key": "repository",
        "name": "Repository",
        "description": "Repository responsibilities.",
        "responsibility": "Own the analyzed repository.",
        "confidence": 0.8,
        "rationale": "Bounded test evidence supports one area.",
        "evidence": evidence,
        "counter_evidence": [],
        "subsystems": [
            {
                "key": "repository-modules",
                "name": "Repository modules",
                "description": "Analyzed repository modules.",
                "responsibility": "Own module behavior.",
                "confidence": 0.8,
                "rationale": "Bounded test evidence supports one subsystem.",
                "evidence": evidence,
                "counter_evidence": [],
                "members": members,
            }
        ],
    }


def _agent_charter() -> dict:
    def claim(statement: str) -> dict:
        return {
            "statement": statement,
            "evidence": ["supplied repository descriptions"],
            "counter_evidence": [],
            "confidence": 0.85,
        }

    def item(key: str, name: str, statement: str) -> dict:
        return {
            "key": key,
            "name": name,
            "statement": statement,
            "related": [],
            "entry_points": [],
            "evidence": ["supplied repository descriptions"],
            "counter_evidence": [],
            "confidence": 0.85,
        }

    return {
        "contract_version": "architecture-charter-v1",
        "purpose": claim("Help people understand and improve a software repository."),
        "actors": [item("developer", "Developer", "Uses the repository map to guide changes.")],
        "capabilities": [item("repository-map", "Repository map", "Explains saved code behavior.")],
        "responsibilities": [
            item("understanding", "Understanding", "Keeps code explanations current.")
        ],
        "execution_flows": [
            item("inspect", "Inspect", "A user requests and receives an explanation.")
        ],
        "public_contracts": [
            item(
                "saved-evidence",
                "Saved evidence",
                "Saved explanations remain tied to indexed evidence.",
            )
        ],
        "invariants": [
            item(
                "read-only-source",
                "Read-only source",
                "Repository source remains read-only during analysis.",
            )
        ],
        "extension_points": [],
        "patterns": [],
        "coherence_concerns": [],
        "unknowns": [],
        "conflicts": [],
        "capability_brief": {
            "contract_version": "capability-brief-v1",
            "purpose": "Help people understand and improve a software repository.",
            "actors": ["A person or coding agent planning a software change."],
            "observable_capabilities": [
                "Explain what the software does and how its parts cooperate."
            ],
            "user_journeys": ["Ask where a change belongs and receive evidence-backed guidance."],
            "external_interfaces": [
                "A dashboard, command line, and agent tool expose the same understanding."
            ],
            "non_functional_requirements": ["Analysis does not modify the inspected repository."],
            "compatibility_obligations": [],
            "non_goals": ["It does not edit source code by itself."],
            "unknowns": [],
            "evidence": ["indexed repository behavior"],
            "confidence": 0.85,
        },
        "confidence": 0.85,
        "evidence": ["supplied repository descriptions"],
    }


def _agent_pattern_response(request: dict, kind: str) -> dict:
    if kind == "pattern_assessment":
        return _pattern_evaluation(request)
    return {
        "review_contract_version": "pattern-review-v1",
        "candidate_fingerprint": request["candidate"]["input_fingerprint"],
        "verdict": "approve",
        "summary": "Independent agent critique found the assessment coherent.",
        "issues": [],
        "evaluation": request["assessment"],
        "competing_interpretations": [],
        "confidence": 80,
        "evidence": [request["candidate"]["target"]["key"]],
    }


def _pattern_evaluation(request: dict) -> dict:
    candidate = request["candidate"]
    target_key = candidate["target"]["key"]
    values = {
        "applicability": 75,
        "suitability": 70,
        "conformance": 20,
        "opportunity": 65,
        "confidence": 80,
        "benefit": 70,
        "urgency": 40,
        "execution_safety": 65,
        "migration_cost": 35,
    }
    return {
        "score_contract_version": "pattern-scores-v1",
        "candidate_fingerprint": candidate["input_fingerprint"],
        "pattern_key": candidate["pattern_key"],
        "target_key": target_key,
        "summary": "The selected pattern is a plausible repository-local option.",
        "presence": "absent",
        "recommendation": "introduce",
        "scores": {
            name: {
                "value": value,
                "rationale": f"Supplied evidence supports the {name} score.",
                "evidence": [target_key],
            }
            for name, value in values.items()
        },
        "rationale": "The sparse deterministic candidate has enough local evidence to assess.",
        "evidence": [target_key],
        "counter_evidence": list(candidate.get("capability_gaps") or []),
        "affected_targets": [target_key],
        "local_precedents": [],
        "alternatives": list(request["pattern"]["relations"]["alternatives"]),
        "prerequisites": ["Preserve existing behavior."],
        "risks": ["The abstraction could cost more than it saves."],
        "invariants": list(request["pattern"]["verification_invariants"]),
        "invalidation_conditions": ["The supporting evidence no longer applies."],
    }

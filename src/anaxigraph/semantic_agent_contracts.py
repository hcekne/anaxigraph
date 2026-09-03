"""Stateless validation and packet contracts for coding-agent semantic work."""

from __future__ import annotations

import json
import secrets
from dataclasses import replace
from typing import Any

from anaxigraph.semantic_agent_protocol import (
    agent_no_work_message,
    agent_no_work_status,
    agent_semantic,
    agent_token_hash,
    agent_worker_fragment,
    clean_agent_identity,
    packetize_agent_request,
)
from anaxigraph.semantic_config_port import AnaxiGraphConfig, SemanticConfig
from anaxigraph.semantic_contract import (
    SEMANTIC_SCHEMA_VERSION,
    SemanticAnalysisError,
    SemanticResult,
)
from anaxigraph.semantic_taxonomy_contract import (
    response_contract_name,
    response_schema,
    validated_agent_semantic_response,
)
from anaxigraph.semantic_usage import ProviderUsage

MAX_SUBMISSION_BYTES = 1_000_000


def agent_reported_usage(
    input_tokens: int | None,
    output_tokens: int | None,
    cache_read_input_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
) -> ProviderUsage:
    """Read the optional token arguments of one agent call as executor-neutral usage."""

    prompt = int(input_tokens or 0)
    completion = int(output_tokens or 0)
    cache_read = int(cache_read_input_tokens or 0)
    cache_creation = int(cache_creation_input_tokens or 0)
    if min(prompt, completion, cache_read, cache_creation) < 0:
        raise ValueError("Reported token counts cannot be negative")
    return ProviderUsage(
        input_tokens=prompt,
        output_tokens=completion,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_creation,
        reported=input_tokens is not None or output_tokens is not None,
    )


class SemanticAgentContractService:
    def semantic(self, config: AnaxiGraphConfig) -> SemanticConfig:
        return agent_semantic(config)

    def identity(
        self, agent_id: str, agent_model: str, agent_effort: str = ""
    ) -> tuple[str, str, str]:
        return (
            clean_agent_identity(agent_id, "agent_id"),
            clean_agent_identity(agent_model, "agent_model", required=False),
            clean_agent_identity(agent_effort, "agent_effort", required=False),
        )

    def lease_identity(self, executor_id: str) -> tuple[str, str, str]:
        token = secrets.token_urlsafe(32)
        token_hash = agent_token_hash(token)
        worker_id = f"mcp:{agent_worker_fragment(executor_id)}:{token_hash[:12]}"
        return token, token_hash, worker_id

    def packetize(
        self, request: dict[str, Any], semantic: SemanticConfig
    ) -> tuple[dict[str, Any], dict[str, Any] | None, list[Any]]:
        return packetize_agent_request(request, semantic)

    def response_contract(self, request: dict[str, Any]) -> dict[str, Any]:
        schema = response_schema(request)
        return {
            "schema_version": SEMANTIC_SCHEMA_VERSION,
            "schema_tool": "ANAXIGRAPH_SEMANTIC_SCHEMA",
            "artifact": response_contract_name(request),
            "required_fields": list(schema["required"]),
        }

    def artifact_name(self, request: dict[str, Any]) -> str:
        return response_contract_name(request)

    def validate_submission(
        self,
        dossier: dict[str, Any],
        request: dict[str, Any],
        *,
        input_tokens: int | None,
        output_tokens: int | None,
        cache_read_input_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
    ) -> SemanticResult:
        """Validate one agent submission and keep whether the agent reported usage at all.

        An omitted count is silence, not zero: a submission that names neither token count is
        recorded as unknown usage, while an explicit zero is a reported zero.
        """

        usage = agent_reported_usage(
            input_tokens,
            output_tokens,
            cache_read_input_tokens,
            cache_creation_input_tokens,
        )
        encoded = json.dumps(dossier, ensure_ascii=False).encode("utf-8")
        if len(encoded) > MAX_SUBMISSION_BYTES:
            raise ValueError(
                f"Semantic dossier exceeds the {MAX_SUBMISSION_BYTES}-byte submission limit"
            )
        try:
            result = validated_agent_semantic_response(
                dossier,
                request,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
            )
        except SemanticAnalysisError as exc:
            raise ValueError(str(exc)) from exc
        return replace(
            result,
            cache_read_input_tokens=usage.cache_read_input_tokens,
            cache_creation_input_tokens=usage.cache_creation_input_tokens,
            usage_reported=usage.reported,
        )

    def no_work(self, status: dict[str, Any]) -> tuple[str, str]:
        return agent_no_work_status(status), agent_no_work_message(status)

    def no_work_response(self, status: dict[str, Any], plan_stage: str) -> dict[str, Any]:
        no_work_status, message = self.no_work(status)
        return {
            "status": no_work_status,
            "message": message,
            "plan_stage": plan_stage,
            "recommended_action": status.get("recommended_action"),
            "semantic": status,
        }

    def waiting_response(self, status: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "waiting",
            "message": "Stale jobs were superseded while work was being claimed; call again.",
            "semantic": status,
        }

    def work_response(
        self,
        job: dict[str, Any],
        token: str,
        analysis_request: dict[str, Any],
        contract_request: dict[str, Any],
        manifest: dict[str, Any] | None,
        semantic: SemanticConfig,
        status: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "status": "work",
            "message": (
                "Analyze this evidence with the coding agent already running in the "
                "repository. Do not modify source as part of semantic mapping."
            ),
            "job": {
                "id": int(job["id"]),
                "kind": job["job_kind"],
                "scope_type": job["scope_type"],
                "scope_key": job["scope_key"],
                "reason": job["reason"],
                "attempt": int(job["attempts"]),
            },
            "lease": {
                "token": token,
                "expires_at": job["lease_expires_at"],
                "seconds": semantic.agent_lease_seconds,
            },
            "analysis_request": analysis_request,
            "evidence_manifest": manifest,
            "response_contract": self.response_contract(contract_request),
            "next_action": (
                "Fetch every evidence page when evidence_manifest is present, produce the "
                f"complete {self.artifact_name(contract_request)}, then call "
                "ANAXIGRAPH_SEMANTIC_SUBMIT with this job id and lease token."
            ),
            "semantic": status,
        }

    def completed_response(
        self,
        job: dict[str, Any],
        plan_stage: str,
        status: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "status": "completed",
            "job_id": int(job["id"]),
            "completed_scope": job["scope_key"],
            "next_plan_stage": plan_stage,
            "next_action": status.get("recommended_action")
            or "Call ANAXIGRAPH_SEMANTIC_WORK again until it returns complete.",
            "semantic": status,
        }

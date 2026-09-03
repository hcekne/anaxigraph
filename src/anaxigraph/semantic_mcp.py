"""Semantic status and durable agent-work tools for AnaxiMCP."""

from __future__ import annotations

from typing import Any

from mcp.types import ToolAnnotations

from anaxigraph.operational_health import served_map_status
from anaxigraph.semantic_agent_protocol import semantic_agent_schema
from anaxigraph.understanding import SemanticEngine


def current_semantic_status(
    database: Any, repository_id: int, semantic_config: Any
) -> dict[str, Any]:
    return SemanticEngine(database).status(repository_id, semantic_config)


def register_semantic_tools(
    server: Any,
    database: Any,
    context: Any,
    config_for: Any,
    config_contract: Any,
    *,
    profile: str = "normal",
) -> None:
    SemanticMcpTools(server, database, context, config_for, config_contract, profile).register()


class SemanticMcpTools:
    def __init__(
        self,
        server: Any,
        database: Any,
        context: Any,
        config_for: Any,
        config_contract: Any,
        profile: str,
    ) -> None:
        self.server = server
        self.database = database
        self.context = context
        self.config_for = config_for
        self.config_contract = config_contract
        self.profile = profile

    def register(self) -> None:
        self._register_status_tool()
        if self.profile in {"analyst", "all"}:
            self._register_taxonomy_tool()
        if self.profile in {"executor", "all"}:
            self._register_executor_read_tools()
            self._register_claim_tools()
            self._register_completion_tools()

    def _register_status_tool(self) -> None:
        self.server.add_tool(
            self.status,
            name="ANAXIGRAPH_SEMANTIC_STATUS",
            description=(
                "Report how much of the AI-created code map is up to date, which tasks are waiting "
                "or failed, whether a worker is actually running, token and cost totals, and the "
                "current whole-repository AI description."
            ),
        )

    def _register_taxonomy_tool(self) -> None:
        self.server.add_tool(
            self.taxonomy,
            name="ANAXIGRAPH_TAXONOMY",
            description=(
                "Return the current inferred responsibility map of broad areas and smaller "
                "groups. A separate AI pass checks the proposal, then AnaxiGraph verifies that "
                "every included file appears exactly once. The result includes evidence strength, "
                "extra cross-area labels, known problems, and who or what created it."
            ),
        )

    def _register_executor_read_tools(self) -> None:
        self.server.add_tool(
            self.schema,
            name="ANAXIGRAPH_SEMANTIC_SCHEMA",
            title="Read the required AI-result shapes",
            description=(
                "Read the exact JSON shapes for file descriptions, the AI-created code-area map, "
                "pattern checks, and their separate AI reviews before processing mapping tasks."
            ),
            annotations=_read_annotations(),
        )

    def _register_claim_tools(self) -> None:
        self.server.add_tool(
            self.work,
            name="ANAXIGRAPH_SEMANTIC_WORK",
            title="Claim one AI-mapping task",
            description=(
                "Give this coding agent the next saved AI-mapping task for a limited lease time. "
                "Claiming changes task state in AnaxiGraph's index but never writes repository source."
            ),
            annotations=_write_annotations(idempotent=False),
        )
        self.server.add_tool(
            self.evidence,
            name="ANAXIGRAPH_SEMANTIC_EVIDENCE",
            title="Read one evidence page for an AI task",
            description=(
                "Read one extra page of source or repository evidence for a claimed task. Fetch "
                "every page named by the task before submitting the completed JSON result."
            ),
            annotations=_read_annotations(),
        )

    def _register_completion_tools(self) -> None:
        self.server.add_tool(
            self.submit,
            name="ANAXIGRAPH_SEMANTIC_SUBMIT",
            title="Store one completed AI-mapping result",
            description=(
                "Check and store one completed file description, code-area map, pattern result, or "
                "separate AI review in AnaxiGraph's external index without changing repository source."
            ),
            annotations=_write_annotations(idempotent=True),
        )
        self.server.add_tool(
            self.release,
            name="ANAXIGRAPH_SEMANTIC_RELEASE",
            title="Return an unfinished AI-mapping task",
            description=(
                "Put an unfinished claimed task back into the saved task list without counting "
                "it as a failed attempt."
            ),
            annotations=_write_annotations(idempotent=False),
        )
        self.server.add_tool(
            self.fail,
            name="ANAXIGRAPH_SEMANTIC_FAIL",
            title="Report one failed AI-mapping attempt",
            description=(
                "Record a model or result failure for one claimed task, including reported token "
                "use, then retry it only while its saved attempt limit allows."
            ),
            annotations=_write_annotations(idempotent=False),
        )

    def status(self, repository: str = "") -> dict[str, Any]:
        row, root = self.context(repository)
        config = self.config_for(row, root)
        result = current_semantic_status(self.database, int(row["id"]), config.semantic)
        result["map_status"] = self._map_status(row, root)
        result.update(self.config_contract(row, root, config))
        return result

    def taxonomy(self, repository: str = "") -> dict[str, Any]:
        row, root = self.context(repository)
        result = self.database.semantic_taxonomy(int(row["id"]))
        value = result or {
            "status": "not_ready",
            "message": "The current saved scan does not have a completed AI-created code-area map.",
        }
        value["map_status"] = self._map_status(row, root)
        return value

    def schema(self) -> dict[str, Any]:
        return semantic_agent_schema()

    def work(
        self,
        agent_id: str,
        agent_model: str = "",
        agent_effort: str = "",
        retry_failed: bool = False,
        repository: str = "",
    ) -> dict[str, Any]:
        row, root = self.context(repository)
        map_status = self._map_status(row, root)
        if map_status["state"] != "current":
            return {
                "status": "scan_required",
                "map_status": map_status,
                "message": "Refresh the structural map before claiming more AI-mapping work.",
            }
        return SemanticEngine(self.database).claim_agent_work(
            int(row["id"]),
            root,
            self.config_for(row, root),
            agent_id=agent_id,
            agent_model=agent_model,
            agent_effort=agent_effort,
            retry_failed=retry_failed,
        )

    def evidence(
        self,
        job_id: int,
        lease_token: str,
        page: int,
        repository: str = "",
    ) -> dict[str, Any]:
        row, root = self.context(repository)
        return SemanticEngine(self.database).agent_evidence_page(
            int(row["id"]),
            root,
            self.config_for(row, root),
            job_id=job_id,
            lease_token=lease_token,
            page=page,
        )

    def submit(
        self,
        job_id: int,
        lease_token: str,
        dossier: dict[str, Any],
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cache_read_input_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
        repository: str = "",
    ) -> dict[str, Any]:
        row, root = self.context(repository)
        return SemanticEngine(self.database).submit_agent_work(
            int(row["id"]),
            root,
            self.config_for(row, root),
            job_id=job_id,
            lease_token=lease_token,
            dossier=dossier,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
            cache_creation_input_tokens=cache_creation_input_tokens,
        )

    def release(
        self,
        job_id: int,
        lease_token: str,
        reason: str,
        repository: str = "",
    ) -> dict[str, Any]:
        row, root = self.context(repository)
        return SemanticEngine(self.database).release_agent_work(
            int(row["id"]),
            self.config_for(row, root),
            job_id=job_id,
            lease_token=lease_token,
            reason=reason,
        )

    def fail(
        self,
        job_id: int,
        lease_token: str,
        reason: str,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cache_read_input_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
        repository: str = "",
    ) -> dict[str, Any]:
        row, root = self.context(repository)
        return SemanticEngine(self.database).fail_agent_work(
            int(row["id"]),
            self.config_for(row, root),
            job_id=job_id,
            lease_token=lease_token,
            reason=reason,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
            cache_creation_input_tokens=cache_creation_input_tokens,
        )

    def _map_status(self, row: dict[str, Any], root: Any) -> dict[str, Any]:
        snapshot = self.database.latest_snapshot(int(row["id"]))
        if snapshot is None:
            return {
                "contract_version": "served-map-status-v1",
                "state": "missing",
                "safe_to_plan": False,
                "scan_recommended": True,
            }
        return served_map_status(root, snapshot)


def _read_annotations() -> ToolAnnotations:
    return ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )


def _write_annotations(*, idempotent: bool) -> ToolAnnotations:
    return ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=idempotent,
        openWorldHint=False,
    )

"""Semantic status and durable agent-work tools for AnaxiMCP."""

from __future__ import annotations

from typing import Any

from mcp.types import ToolAnnotations

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
) -> None:
    SemanticMcpTools(server, database, context, config_for).register()


class SemanticMcpTools:
    def __init__(self, server: Any, database: Any, context: Any, config_for: Any) -> None:
        self.server = server
        self.database = database
        self.context = context
        self.config_for = config_for

    def register(self) -> None:
        self._register_read_tools()
        self._register_claim_tools()
        self._register_completion_tools()

    def _register_read_tools(self) -> None:
        self.server.add_tool(
            self.status,
            name="ANAXIGRAPH_SEMANTIC_STATUS",
            description=(
                "Report semantic and pattern-map coverage, freshness, pending/failed work, "
                "token/cost usage, and the current repository-level dossier."
            ),
        )
        self.server.add_tool(
            self.taxonomy,
            name="ANAXIGRAPH_TAXONOMY",
            description=(
                "Return the current agent-proposed, agent-reviewed, deterministically validated "
                "semantic area/subsystem map with provenance, confidence, facets, and issues."
            ),
        )
        self.server.add_tool(
            self.schema,
            name="ANAXIGRAPH_SEMANTIC_SCHEMA",
            title="Read semantic dossier contract",
            description=(
                "Read strict dossier, taxonomy, pattern-assessment, and independent-review "
                "schemas before executing agent-funded semantic work."
            ),
            annotations=_read_annotations(),
        )

    def _register_claim_tools(self) -> None:
        self.server.add_tool(
            self.work,
            name="ANAXIGRAPH_SEMANTIC_WORK",
            title="Claim semantic mapping work",
            description=(
                "Prepare and lease the next bounded semantic task to this coding agent. This "
                "changes queue state but never writes the target repository."
            ),
            annotations=_write_annotations(idempotent=False),
        )
        self.server.add_tool(
            self.evidence,
            name="ANAXIGRAPH_SEMANTIC_EVIDENCE",
            title="Read a semantic evidence page",
            description=(
                "Read one overflow evidence page for a leased task. Fetch every named page "
                "before submitting its dossier."
            ),
            annotations=_read_annotations(),
        )

    def _register_completion_tools(self) -> None:
        self.server.add_tool(
            self.submit,
            name="ANAXIGRAPH_SEMANTIC_SUBMIT",
            title="Store a semantic mapping result",
            description=(
                "Validate and store one completed dossier, taxonomy, pattern assessment, or "
                "independent review in AnaxiIndex without changing repository source."
            ),
            annotations=_write_annotations(idempotent=True),
        )
        self.server.add_tool(
            self.release,
            name="ANAXIGRAPH_SEMANTIC_RELEASE",
            title="Release semantic mapping work",
            description="Return an unfinished leased task to the queue without consuming an attempt.",
            annotations=_write_annotations(idempotent=False),
        )

    def status(self, repository: str = "") -> dict[str, Any]:
        row, root = self.context(repository)
        return current_semantic_status(
            self.database, int(row["id"]), self.config_for(row, root).semantic
        )

    def taxonomy(self, repository: str = "") -> dict[str, Any]:
        row, _ = self.context(repository)
        result = self.database.semantic_taxonomy(int(row["id"]))
        return result or {
            "status": "not_ready",
            "message": "No finalized semantic taxonomy exists for the current snapshot.",
        }

    def schema(self) -> dict[str, Any]:
        return semantic_agent_schema()

    def work(
        self,
        agent_id: str,
        agent_model: str = "",
        retry_failed: bool = False,
        repository: str = "",
    ) -> dict[str, Any]:
        row, root = self.context(repository)
        return SemanticEngine(self.database).claim_agent_work(
            int(row["id"]),
            root,
            self.config_for(row, root),
            agent_id=agent_id,
            agent_model=agent_model,
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
        input_tokens: int = 0,
        output_tokens: int = 0,
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

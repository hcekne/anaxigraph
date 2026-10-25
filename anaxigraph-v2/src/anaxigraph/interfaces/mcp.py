"""MCP uses exactly the same application answers as the dashboard and CLI."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP


def create_mcp(application: Any) -> FastMCP:
    server = FastMCP(
        "AnaxiGraph V2",
        instructions=(
            "Prepare substantial changes, inspect evidence, assess placement, then scan and validate. "
            "For model analysis, request an explicit packet and submit its result. "
            "Fresh Eyes packets are implementation-blind; do not add source context to that task."
        ),
    )

    @server.tool()
    def status() -> dict:
        """Show the exact checkout and independent map/annotation readiness."""
        return application.status()

    @server.tool()
    def scan() -> dict:
        """Refresh source facts without executing the analyzed code."""
        return application.scan()

    @server.tool()
    def modules(
        sort: str = "path", descending: bool = False, limit: int = 50, offset: int = 0
    ) -> dict:
        """Discover modules in bounded pages, sortable by path, lines or function count."""
        return application.modules(sort, descending, limit, offset)

    @server.tool()
    def inspect(entity_id: str, limit: int = 30) -> dict:
        """Expand a bounded entity neighborhood with evidence and resolution status."""
        return application.inspect(entity_id, limit)

    @server.tool()
    def prepare_change(task: str, limit: int = 12) -> dict:
        """Find existing responsibilities, reuse opportunities and checks before editing."""
        return application.prepare_change(task, limit)

    @server.tool()
    def assess_plan(task: str, files: list[str]) -> dict:
        """Check proposed placement against the shared graph and existing capabilities."""
        return application.assess_plan(task, files)

    @server.tool()
    def validate_change(receipts: list[dict[str, Any]] | None = None) -> dict:
        """Compare saved states; supplied checks only count for their exact fingerprint."""
        return application.validate_change(receipts)

    @server.tool()
    def analysis_request(kind: str, scope: list[str] | None = None) -> dict:
        """Prepare an annotation, catalogue-pattern or blind Fresh Eyes worker packet."""
        return application.analysis_request(kind, scope)

    @server.tool()
    def submit_analysis(request_id: str, result: dict[str, Any]) -> dict:
        """Validate and save a result for the exact requested state and analysis contract."""
        return application.submit_analysis(request_id, result)

    @server.tool()
    def reviews(kind: str | None = None) -> dict:
        """Discover saved review metadata; use inspect('review:<id>') for the full result."""
        return application.reviews(kind)

    return server

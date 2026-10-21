"""Keep planning and shared-record commands on the exact checkout's service authority."""

from __future__ import annotations

import os
from typing import Any

from anaxigraph.semantic_service import _request_json, discover_semantic_service


def planning_service(args: Any) -> Any:
    if args.db is not None and args.service_url:
        raise ValueError("Choose either --db for a local index or --service-url for a service")
    if args.db is not None or os.environ.get("ANAXIGRAPH_DB"):
        return None
    service = discover_semantic_service(args.repository.resolve(), explicit_url=args.service_url)
    if service and args.config:
        raise ValueError("--config cannot override service policy; choose --db for a local index")
    return service


def planning_request(
    service: Any, path: str, body: Any = None, *, details: bool | None = None
) -> dict[str, Any]:
    query = f"repository_id={service.repository_id}"
    if details is not None:
        query += f"&details={str(details).lower()}"
    value = _request_json(
        f"{service.base_url}/api/{path}?{query}",
        method="GET" if body is None else "POST",
        body=body,
        timeout=120,
    )
    return {**value, "index": service.identity()}

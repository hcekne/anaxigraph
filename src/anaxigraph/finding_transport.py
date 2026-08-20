"""Shared finding-query translation for REST, MCP, and command-line clients."""

from __future__ import annotations

from typing import Any

from anaxigraph.persistence.finding_query import FindingPageQuery


def query_findings(
    database: Any,
    repository_id: int,
    config: Any,
    *,
    view: str = "attention",
    cursor: str = "",
    page_size: int | None = None,
    statuses: tuple[str, ...] = (),
    severities: tuple[str, ...] = (),
    finding_types: tuple[str, ...] = (),
    module: str = "",
    architecture_area: str = "",
    minimum_confidence: float = 0.0,
    token_budget: int | None = None,
    compact: bool = False,
) -> dict[str, Any]:
    """Build and execute the same bounded query regardless of transport."""

    query = FindingPageQuery(
        view=view.strip().lower(),
        cursor=cursor,
        page_size=page_size,
        statuses=normalize_statuses(statuses),
        severities=_clean_values(severities),
        finding_types=_clean_values(finding_types),
        module=module.strip(),
        architecture_area=architecture_area.strip(),
        minimum_confidence=float(minimum_confidence),
        payload_budget_bytes=max(1, int(token_budget)) * 4 if token_budget else None,
        compact=compact,
    )
    return database.finding_page(repository_id, query=query, policy=config.findings)


def collect_finding_ledger(
    database: Any,
    repository_id: int,
    config: Any,
) -> dict[str, Any]:
    """Materialize the complete ledger only for an explicit export operation."""

    cursor = ""
    items: list[dict[str, Any]] = []
    while True:
        page = query_findings(
            database,
            repository_id,
            config,
            view="diagnostics",
            cursor=cursor,
            page_size=200,
        )
        items.extend(page["items"])
        cursor = str(page.get("next_cursor") or "")
        if not cursor:
            return {
                **page,
                "items": items,
                "shown": len(items),
                "page_size": len(items),
                "omitted": {
                    "before_cursor": 0,
                    "after_page": 0,
                    "due_to_payload_budget": 0,
                    "diagnostic_groups": 0,
                },
            }


def normalize_statuses(values: tuple[str, ...]) -> tuple[str, ...]:
    cleaned = _clean_values(values)
    if not cleaned or "all" in cleaned:
        return ()
    expanded: list[str] = []
    for value in cleaned:
        candidates = (
            ("new", "acknowledged", "accepted", "planned", "regressed")
            if value == "active"
            else (value,)
        )
        for candidate in candidates:
            if candidate not in expanded:
                expanded.append(candidate)
    return tuple(expanded)


def _clean_values(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value.strip().lower() for value in values if value.strip()))

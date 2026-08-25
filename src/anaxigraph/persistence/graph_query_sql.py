"""SQL fragments shared by bounded graph page and aggregate readers."""

from __future__ import annotations

from typing import Any

from anaxigraph.graph_contract import GraphPageRequest


def eligible_nodes_sql(
    request: GraphPageRequest,
    repository_id: int,
    snapshot_id: int,
) -> tuple[str, list[Any]]:
    conditions: list[str] = []
    parameters: list[Any] = []
    if request.path:
        conditions.append("fv.path LIKE ? ESCAPE '\\'")
        parameters.append(f"%{_escape_like(request.path)}%")
    _add_list_filter(conditions, parameters, "fv.language", request.languages)
    _add_list_filter(conditions, parameters, "ga.area", request.areas)
    _add_list_filter(conditions, parameters, "ga.subsystem", request.subsystems)
    if request.finding_types:
        placeholders = ",".join("?" for _value in request.finding_types)
        conditions.append(
            f"""
            EXISTS (
                SELECT 1 FROM findings f
                JOIN finding_occurrences occurrence ON occurrence.finding_id = f.id
                JOIN json_each(f.affected_artifacts_json) affected
                WHERE f.repository_id = ? AND occurrence.snapshot_id = ?
                  AND f.status NOT IN ('resolved', 'dismissed')
                  AND affected.value = fv.path
                  AND f.finding_type IN ({placeholders})
            )
            """
        )
        parameters.extend((repository_id, snapshot_id, *request.finding_types))
    where = " AND ".join(conditions) if conditions else "1 = 1"
    return (
        f"""
        eligible AS (
            SELECT fv.artifact_id
            FROM projected_file_versions fv
            JOIN graph_architecture ga ON ga.artifact_id = fv.artifact_id
            WHERE {where}
        )
        """,
        parameters,
    )


def relationship_filter_sql(
    request: GraphPageRequest, *, alias: str = "r"
) -> tuple[str, list[Any]]:
    if not request.relationship_types:
        return "1 = 1", []
    placeholders = ",".join("?" for _value in request.relationship_types)
    return f"{alias}.relationship_type IN ({placeholders})", list(request.relationship_types)


def placeholders(values: list[int]) -> str:
    if not values:
        raise ValueError("at least one graph node is required")
    return ",".join("?" for _value in values)


def _add_list_filter(
    conditions: list[str],
    parameters: list[Any],
    column: str,
    values: tuple[str, ...],
) -> None:
    if not values:
        return
    marker = ",".join("?" for _value in values)
    conditions.append(f"{column} IN ({marker})")
    parameters.extend(values)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

"""Read graph properties from their single canonical annotation payload."""

from __future__ import annotations

import json
from typing import Any

from anaxigraph.knowledge_nodes import sentence

_ANNOTATION = """
LEFT JOIN semantic_document_values d ON d.id=g.annotation_id
LEFT JOIN semantic_scope_states s ON s.snapshot_id=g.snapshot_id AND s.scope_type='module' AND s.scope_key=g.path
LEFT JOIN fact_symbols f ON f.id=g.symbol_id
LEFT JOIN file_facts ff ON ff.id=g.file_fact_id
"""
_OVERVIEW = """COALESCE(NULLIF(json_extract(d.value_json,
    g.annotation_selector || '.overview'),''),
    NULLIF(json_extract(d.value_json,g.annotation_selector || '.summary'),''),
    NULLIF(json_extract(d.value_json,g.annotation_selector || '.statement'),''),
    NULLIF(json_extract(d.value_json,g.annotation_selector || '.purpose'),''),
    CASE WHEN json_type(d.value_json,g.annotation_selector)='text' THEN json_extract(d.value_json,g.annotation_selector) END,
    NULLIF(g.overview,''),NULLIF(f.summary,''),
    CASE WHEN f.signature IS NOT NULL THEN 'Declares ' || f.signature ELSE ff.summary END,'')"""
_DETAIL = """COALESCE(json_extract(d.value_json,g.annotation_selector || '.detail'),
    json_extract(d.value_json,g.annotation_selector || '.detailed_summary'),NULLIF(g.detail,''),f.summary,'')"""


def annotation_compatibility(value):
    """Adapt canonical properties for older consumers without another stored representation."""
    if "overview" not in value:
        return value
    return {
        **value,
        "summary": value["overview"],
        "detailed_summary": value.get("detail", ""),
        "responsibilities": [item["purpose"] for item in value.get("capabilities", [])],
        "public_contracts": [item["statement"] for item in value.get("contracts", [])],
    }


def graph_select(*, detail=False, map_layer="current") -> str:
    if map_layer not in {"current", "responsibility", "declared", "path"}:
        raise ValueError("Unsupported graph grouping layer")
    extra = (
        (
            f",{_DETAIL} AS canonical_detail,"
            "json_extract(d.value_json,g.annotation_selector) AS annotation_properties"
        )
        if detail
        else ""
    )
    provenance = ",d.model AS annotation_model,d.confidence AS annotation_confidence,d.created_at AS annotation_created,d.document_kind AS annotation_kind,s.status AS annotation_status,ff.analyzer AS source_analyzer,f.summary AS symbol_summary,CASE WHEN f.id IS NOT NULL THEN json_object('qualified_name',f.qualified_name,'signature',f.signature,'start_line',f.start_line,'end_line',f.end_line,'visibility',f.visibility) END AS symbol_properties"
    missing = "g.area" if map_layer == "current" else "'unconfigured'"
    missing_subsystem = "g.subsystem" if map_layer == "current" else "'unconfigured'"
    grouping = (
        f",COALESCE(json_extract(m.properties_json,'$.architecture_layers.{map_layer}.area'),"
        f"{missing}) AS canonical_area"
        f",COALESCE(json_extract(m.properties_json,'$.architecture_layers.{map_layer}.subsystem'),"
        f"{missing_subsystem}) AS canonical_subsystem"
        ",json_extract(m.properties_json,'$.architecture_layers') AS architecture_layers_json"
    )
    module = "LEFT JOIN graph_entities m ON m.snapshot_id=g.snapshot_id AND m.entity_id='module:'||g.path"
    counts = (
        ",CASE WHEN g.kind='module' THEN (SELECT COUNT(*) FROM graph_entities child "
        "WHERE child.snapshot_id=g.snapshot_id AND child.file_fact_id=g.file_fact_id "
        "AND child.kind='interface') END AS interface_count,"
        "CASE WHEN g.kind='module' THEN CASE WHEN d.document_kind='annotation' "
        "THEN json_array_length(d.value_json,'$.contracts') ELSE 0 END END AS contract_count"
    )
    label = ",COALESCE(NULLIF(g.label,''),f.name,'') AS canonical_label"
    return f"SELECT g.*,{_OVERVIEW} AS canonical_overview{provenance}{extra}{grouping}{counts}{label} FROM graph_entities g {_ANNOTATION} {module}"


def node_value(row: Any, *, detail=False) -> dict[str, Any]:
    value = dict(row)
    properties = json.loads(value["properties_json"])
    properties.pop("unresolved_call_sites", None)
    properties.update(json.loads(value["symbol_properties"] or "{}"))
    result = {
        "id": value["entity_id"],
        "kind": value["kind"],
        "label": value["canonical_label"],
        "path": value["path"],
        "parent_id": value["parent_id"],
        "artifact_id": value["artifact_id"],
        "overview": sentence(value["canonical_overview"]),
        "metrics": {
            key: value[key]
            for key in (
                "lines_of_code",
                "complexity",
                "function_count",
                "interface_count",
                "contract_count",
                "fan_in",
                "fan_out",
                "line_coverage",
                "change_count",
                "first_changed_at",
                "last_commit_at",
            )
        },
        "placement": {"area": value["canonical_area"], "subsystem": value["canonical_subsystem"]},
        "architecture_layers": json.loads(value["architecture_layers_json"] or "{}"),
        "language": value["language"],
        "reference": bool(value["reference"]),
        "readiness": _readiness(value),
        "provenance": json.loads(value["provenance_json"]),
        "properties": properties,
    }
    if detail:
        _details(result, value)
    _uncertainty_metrics(result, value)
    if value["annotation_id"]:
        result["provenance"]["annotation"] = {
            "document_id": value["annotation_id"],
            "model": value["annotation_model"],
            "confidence": value["annotation_confidence"],
            "created_at": value["annotation_created"],
            "verification": "unverified",
        }
    return result


def _uncertainty_metrics(result, value):
    unresolved = int(result["properties"].get("unresolved_target_count", 0))
    result["metrics"]["resolved_fan_out"] = value["fan_out"]
    result["metrics"]["unresolved_target_count"] = unresolved
    result["metrics"]["fan_out"] += unresolved


def _details(result, value):
    result["detail"] = value["canonical_detail"]
    if value["kind"] in {"contract", "capability"}:
        raw = value.get("annotation_properties")
        result["properties"].update(
            json.loads(raw or "{}")
            if value["annotation_kind"] == "annotation"
            else {"statement": raw}
        )


def _readiness(value):
    if not value["annotation_id"]:
        return "structural"
    if value["annotation_status"] != "current":
        return "stale_annotation"
    return "annotated" if value["annotation_kind"] == "annotation" else "legacy_reused"


def edge_value(row: Any) -> dict[str, Any]:
    return {
        "id": row["edge_id"],
        "source": row["source_id"],
        "target": row["target_id"],
        "relationship_type": row["relationship_type"],
        "confidence": row["confidence"],
        "resolution": row["resolution"],
        "evidence": json.loads(row["evidence_json"]),
        "provenance": json.loads(row["provenance_json"]),
    }


EVIDENCE_STATES = {"", "extracted", "inferred", "unresolved", "proposed", "functional"}


def evidence_predicate(alias="", *, edges=False, physical=False):
    """Return a parameter-free evidence classification for indexed graph queries."""
    prefix = alias + "." if alias else ""
    method = prefix + "method" if physical else f"json_extract({prefix}provenance_json,'$.method')"
    resolution = (
        prefix + "resolution"
        if edges
        else f"json_extract({prefix}provenance_json,'$.verification')"
    )
    return (
        f"CASE WHEN {resolution} LIKE 'unresolved%' THEN 'unresolved' "
        f"WHEN {resolution}='proposed' OR {method}='proposed' THEN 'proposed' "
        f"WHEN {resolution}='functional' OR {method}='functional_projection' THEN 'functional' "
        f"WHEN {resolution}='inferred' OR {method} IN ('inferred','legacy_inference') "
        "THEN 'inferred' ELSE 'extracted' END"
    )


def classify_evidence(item):
    method = item.get("provenance", {}).get("method", "")
    resolution = item.get("resolution") or item.get("provenance", {}).get("verification", "")
    if resolution.startswith("unresolved"):
        return "unresolved"
    if resolution == "proposed" or method == "proposed":
        return "proposed"
    if resolution == "functional" or method == "functional_projection":
        return "functional"
    if resolution == "inferred" or method in {"inferred", "legacy_inference"}:
        return "inferred"
    return "extracted"

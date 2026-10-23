"""Stable graph entities built from canonical parser facts and semantic references."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import PurePosixPath
from typing import Any

from anaxigraph.call_graph_contract import CALLABLE_SYMBOL_KINDS


def entity_id(kind: str, path: str, qualified_name: str = "") -> str:
    return f"{kind}:{path}" + (f"#{qualified_name}" if qualified_name else "")


def sentence(value: str) -> str:
    text = " ".join(str(value or "").split())
    first = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text, maxsplit=1)[0]
    return first if not first or first.endswith((".", "!", "?")) else first + "."


def insert_entity(connection: sqlite3.Connection, snapshot_id: int, node: dict[str, Any]) -> None:
    fields = tuple(node)
    columns = ",".join(("snapshot_id", *fields))
    values = (snapshot_id, *node.values())
    placeholders = ",".join("?" for _ in values)
    connection.execute(
        f"INSERT OR REPLACE INTO graph_entities({columns}) VALUES ({placeholders})", values
    )


def module_node(file: dict[str, Any], symbols: list[dict[str, Any]]) -> dict[str, Any]:
    placement = (file.get("architecture_layers") or {}).get("current") or {}
    group = str(
        placement.get("area")
        or file.get("declared_group")
        or file.get("inferred_group")
        or "unassigned"
    )
    path = file["path"]
    return {
        "entity_id": entity_id("module", path),
        "kind": "module",
        "label": PurePosixPath(path).name,
        "path": path,
        "parent_id": entity_id("area", group),
        "artifact_id": file["artifact_id"],
        "file_fact_id": file["file_fact_id"],
        "overview": "",
        "lines_of_code": file["lines_of_code"],
        "complexity": file["complexity"],
        "function_count": len(
            {item["qualified_name"] for item in symbols if symbol_kind(item) == "function"}
        ),
        "area": group,
        "subsystem": placement.get("subsystem", group),
        "language": file["language"],
        "reference": int(file.get("artifact_type") not in {None, "source", "test"}),
        "properties_json": json.dumps(
            {
                "source_fingerprint": file["raw_hash"],
                "architecture_layers": file.get("architecture_layers", {}),
            }
        ),
        "provenance_json": json.dumps({"method": "extracted", "analyzer": file["analyzer"]}),
    }


def symbol_kind(symbol: dict[str, Any]) -> str:
    kind = symbol["symbol_type"]
    return "function" if kind in CALLABLE_SYMBOL_KINDS else "type"


def symbol_node(file: dict[str, Any], symbol: dict[str, Any]) -> dict[str, Any]:
    kind = symbol_kind(symbol)
    path, qualified = file["path"], symbol["qualified_name"]
    return {
        "entity_id": entity_id(kind, path, qualified),
        "kind": kind,
        "label": "",
        "path": path,
        "parent_id": entity_id("module", path),
        "artifact_id": file["artifact_id"],
        "file_fact_id": file["file_fact_id"],
        "symbol_id": symbol["id"],
        "overview": "",
        "lines_of_code": symbol["logical_lines"],
        "complexity": symbol["complexity"],
        "area": ((file.get("architecture_layers") or {}).get("current") or {}).get(
            "area", "unassigned"
        ),
        "subsystem": ((file.get("architecture_layers") or {}).get("current") or {}).get(
            "subsystem", "unassigned"
        ),
        "language": file["language"],
        "properties_json": "{}",
        "provenance_json": '{"method":"extracted"}',
    }


def interface_node(node: dict[str, Any]) -> dict[str, Any]:
    result = dict(node)
    result.update(
        entity_id=node["entity_id"].replace("function:", "interface:", 1),
        kind="interface",
        parent_id=node["entity_id"],
        lines_of_code=None,
        complexity=None,
    )
    return result

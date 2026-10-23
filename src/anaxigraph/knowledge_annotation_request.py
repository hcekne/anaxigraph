"""Build compact source-grounded graph annotation requests."""

from __future__ import annotations

import json

from anaxigraph.call_graph_contract import CALLABLE_SYMBOL_KINDS
from anaxigraph.knowledge_annotation_contract import ANNOTATION_INSTRUCTIONS, ANNOTATION_VERSION
from anaxigraph.persistence.semantic_evidence import module_facts, relationships_for_artifact
from anaxigraph.semantic_target_source import read_mounted_source, require_unchanged_source


def annotation_request(database, job, root):
    path = str(job["scope_key"])
    source = read_mounted_source(root, path, missing="The annotation source no longer exists")
    with database.connect() as connection:
        module, _ = module_facts(connection, int(job["snapshot_id"]), int(job["artifact_id"]))
        require_unchanged_source(source, module, changed="Source changed since annotation planning")
        functions = [
            dict(row)
            for row in connection.execute(
                """SELECT qualified_name,signature,start_line,end_line,summary FROM fact_symbols
            WHERE file_fact_id=? AND symbol_type IN ("""
                + ",".join("?" for _ in CALLABLE_SYMBOL_KINDS)
                + """)
            ORDER BY start_line,id""",
                (module["file_fact_id"], *sorted(CALLABLE_SYMBOL_KINDS)),
            )
        ]
        relationships = relationships_for_artifact(
            connection, int(job["snapshot_id"]), int(job["artifact_id"])
        )
    return {
        "analysis_kind": "annotation",
        "schema_version": ANNOTATION_VERSION,
        "contract": ANNOTATION_INSTRUCTIONS,
        "path": path,
        "functions": functions,
        "language": module["language"],
        "analysis_contract": _analysis_contract(module),
        "source": source.decode("utf-8", errors="replace"),
        "relationships": relationships,
        "writing_requirements": ANNOTATION_INSTRUCTIONS,
    }


def _analysis_contract(module):
    ir = json.loads(module.get("metadata_json") or "{}").get("ir") or {}
    return {
        "analyzer": module.get("analyzer"),
        "analyzer_version": ir.get("analyzer_version"),
        "capability_fingerprint": (ir.get("analyzer_capabilities") or {}).get("fingerprint"),
        "parse_status": ir.get("parse_status"),
    }

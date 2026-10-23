"""Compact group-summary validation and semantic result compatibility exports."""

from __future__ import annotations

from typing import Any

from anaxigraph.semantic_model_contract import SemanticAnalysisError, SemanticResult
from anaxigraph.semantic_model_contract import SemanticProvider as SemanticProvider
from anaxigraph.semantic_model_contract import _validate_schema as _validate_schema
from anaxigraph.semantic_request_support import MAPPING_SCHEMA

SEMANTIC_SCHEMA_VERSION = "repository-understanding-v7"
# Compatibility names now describe the single compact writer. Original saved values are read directly.
DOSSIER_SCHEMA = MAPPING_SCHEMA


def validated_mapping(value: Any, *, input_tokens: int, output_tokens: int) -> SemanticResult:
    _validate_schema(value, MAPPING_SCHEMA, "dossier")
    if not value["summary"].strip() or not 0 <= value["confidence"] <= 1:
        raise SemanticAnalysisError("Mapping requires a summary and finite confidence")
    return SemanticResult(
        value=value,
        confidence=float(value["confidence"]),
        evidence=tuple(value["evidence"]),
        input_tokens=max(0, input_tokens),
        output_tokens=max(0, output_tokens),
    )


validated_result = validated_mapping

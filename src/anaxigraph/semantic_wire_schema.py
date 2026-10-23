"""Nullable strict-output adaptation shared by local semantic workers."""

from __future__ import annotations

from typing import Any


def _codex_schema(value: Any) -> Any:
    """Adapt optional fields for strict output without mutating stored contracts."""
    if isinstance(value, list):
        return [_codex_schema(child) for child in value]
    if not isinstance(value, dict):
        return value
    schema = {key: _codex_schema(child) for key, child in value.items()}
    if value.get("type") == "object":
        schema["required"] = list(schema.get("properties", {}))
        schema["properties"] = {
            key: child if key in value.get("required", []) else {"anyOf": [child, {"type": "null"}]}
            for key, child in schema.get("properties", {}).items()
        }
    return schema


def _without_optional_nulls(value: Any, schema: dict[str, Any]) -> Any:
    """Translate wire-level optional nulls back to omission before validation."""
    if isinstance(value, list):
        return [_without_optional_nulls(child, schema.get("items", {})) for child in value]
    if not isinstance(value, dict):
        return value
    properties = schema.get("properties", {})
    return {
        key: _without_optional_nulls(child, properties.get(key, {}))
        for key, child in value.items()
        if not (child is None and key in properties and key not in schema.get("required", []))
    }

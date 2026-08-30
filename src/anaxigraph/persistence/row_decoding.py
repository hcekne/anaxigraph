"""Shared decoding for JSON-backed persistence rows."""

from __future__ import annotations

import json
from typing import Any


def _decode_json_value(value: Any) -> Any:
    """Decode one JSON-backed column without leaking malformed persistence data."""

    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


def decode_json_columns(value: dict[str, Any]) -> dict[str, Any]:
    for key in list(value):
        if not key.endswith("_json"):
            continue
        decoded_key = key.removesuffix("_json")
        value[decoded_key] = _decode_json_value(value.pop(key) or "null")
    return value

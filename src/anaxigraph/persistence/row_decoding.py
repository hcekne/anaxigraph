"""Shared decoding for JSON-backed persistence rows."""

from __future__ import annotations

import json
from typing import Any


def decode_json_columns(value: dict[str, Any]) -> dict[str, Any]:
    for key in list(value):
        if not key.endswith("_json"):
            continue
        decoded_key = key.removesuffix("_json")
        try:
            value[decoded_key] = json.loads(value.pop(key) or "null")
        except json.JSONDecodeError:
            value[decoded_key] = None
    return value

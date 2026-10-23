"""Exact-text cold semantic values; modern graph annotations stay inspectable JSON."""

from __future__ import annotations

import hashlib
import json
import zlib
from typing import Any

PAYLOAD_MARKER = "$anaxigraph_payload"
MAX_PAYLOAD_BYTES = 16_000_000


def payload_reference(value: str) -> str | None:
    if PAYLOAD_MARKER not in value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict) or set(parsed) != {PAYLOAD_MARKER}:
        return None
    key = parsed[PAYLOAD_MARKER]
    if not isinstance(key, str) or len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
        raise ValueError("Invalid cold semantic payload reference")
    return key


def encode_payload(value: str) -> tuple[str, bytes, int]:
    raw = value.encode()
    if len(raw) > MAX_PAYLOAD_BYTES:
        raise ValueError("Saved semantic result exceeds the cold payload bound")
    return hashlib.sha256(raw).hexdigest(), zlib.compress(raw, level=6), len(raw)


def decode_payload(key: str, data: bytes, size: int) -> str:
    if not 0 <= size <= MAX_PAYLOAD_BYTES:
        raise ValueError("Invalid cold semantic payload decoded size")
    decoder = zlib.decompressobj()
    try:
        raw = decoder.decompress(data, size + 1)
    except zlib.error as error:
        raise ValueError("Invalid cold semantic payload") from error
    if len(raw) != size or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError("Cold semantic payload exceeds its declared decoded size")
    if hashlib.sha256(raw).hexdigest() != key:
        raise ValueError("Cold semantic payload checksum mismatch")
    return raw.decode()


def modern_semantic_value(kind: str, value: str | dict[str, Any]) -> bool:
    if kind in {"annotation", "pattern_manifest"}:
        return True
    parsed: Any = json.loads(value) if isinstance(value, str) else value
    return isinstance(parsed, dict) and (
        parsed.get("score_contract_version") == "pattern-scores-v3"
        or parsed.get("review_contract_version") == "pattern-review-v2"
        or str(parsed.get("contract_version", "")).startswith("functional-")
    )

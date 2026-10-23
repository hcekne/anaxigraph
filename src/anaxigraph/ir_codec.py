"""Bounded, versioned compression for rebuildable parser metadata only."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import zlib
from typing import Any

_MARKER = "$anaxigraph_metadata"
_BINARY = b"ANAXIGRAPH-IR\x00\x01"
MAX_METADATA_BYTES = 16_000_000


def decode_metadata(value: str | bytes | dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, bytes):
        return _decode_binary(value)
    metadata = json.loads(value or "{}") if isinstance(value, str) else dict(value)
    encoding = metadata.get(_MARKER)
    if encoding is None:
        return metadata
    if encoding != "zlib-v1":
        raise ValueError("Unsupported parser cache encoding; rebuild the local source index")
    size = metadata.get("bytes")
    if isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= MAX_METADATA_BYTES:
        raise ValueError("Parser cache decoded size exceeds its supported bound")
    data = metadata.get("data")
    if not isinstance(data, str) or len(data) > MAX_METADATA_BYTES * 2:
        raise ValueError("Invalid compressed parser cache")
    decoded = _decompress(data, size)
    if hashlib.sha256(decoded).hexdigest() != metadata.get("sha256"):
        raise ValueError("Parser cache checksum mismatch; rebuild the local source index")
    result = json.loads(decoded)
    if not isinstance(result, dict):
        raise ValueError("Parser cache must contain an object")
    result.update(
        {
            key: item
            for key, item in metadata.items()
            if key not in {_MARKER, "bytes", "data", "sha256"}
        }
    )
    return result


def storage_metadata(value: dict[str, Any]) -> str | bytes:
    """Keep the deployed JSON codec readable while avoiding base64 in local SQLite."""
    encoded = encode_metadata(value)
    envelope = json.loads(encoded)
    if envelope.get(_MARKER) != "zlib-v1":
        return encoded
    return (
        _BINARY
        + int(envelope["bytes"]).to_bytes(4, "big")
        + bytes.fromhex(envelope["sha256"])
        + base64.b64decode(envelope["data"])
    )


def _decode_binary(value: bytes) -> dict[str, Any]:
    boundary = len(_BINARY)
    if not value.startswith(_BINARY) or not boundary + 36 <= len(value) <= MAX_METADATA_BYTES * 2:
        raise ValueError("Unsupported binary parser cache encoding")
    size = int.from_bytes(value[boundary : boundary + 4], "big")
    if not 0 <= size <= MAX_METADATA_BYTES:
        raise ValueError("Parser cache decoded size exceeds its supported bound")
    raw = _inflate(value[boundary + 36 :], size)
    if hashlib.sha256(raw).digest() != value[boundary + 4 : boundary + 36]:
        raise ValueError("Parser cache checksum mismatch; rebuild the local source index")
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("Parser cache must contain an object")
    return result


def _decompress(data: str, size: int) -> bytes:
    try:
        compressed = base64.b64decode(data, validate=True)
    except (binascii.Error, zlib.error) as error:
        raise ValueError("Invalid compressed parser cache") from error
    return _inflate(compressed, size)


def _inflate(compressed, size):
    decoder = zlib.decompressobj()
    try:
        decoded = decoder.decompress(compressed, size + 1)
    except zlib.error as error:
        raise ValueError("Invalid compressed parser cache") from error
    if len(decoded) != size or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError("Parser cache exceeds its declared decoded size")
    return decoded


def encode_metadata(value: dict[str, Any]) -> str:
    metadata = decode_metadata(value)
    raw = json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode()
    if len(raw) > MAX_METADATA_BYTES:
        raise ValueError("Parser cache exceeds its supported bound")
    if len(raw) < 1_024:
        return raw.decode()
    envelope = {
        _MARKER: "zlib-v1",
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "data": base64.b64encode(zlib.compress(raw, level=6)).decode("ascii"),
    }
    packed = json.dumps(envelope, sort_keys=True, separators=(",", ":"))
    return packed if len(packed) < len(raw) else raw.decode()


def project_evidence_cache(value: dict[str, Any]) -> dict[str, Any]:
    metadata = decode_metadata(value)
    ir = dict(metadata.get("ir") or {})
    declaration = ir.get("analyzer_capabilities") or {}
    builtin = {
        "builtin-python-ast",
        "builtin-javascript-tree-sitter",
        "builtin-typescript-tree-sitter",
        "builtin-text",
    }
    if metadata.get("evidence_cache_evicted") or declaration.get("analyzer") not in builtin:
        return metadata
    docstring = "module_docstring" in metadata
    if not ir.get("evidence_facts") and not docstring:
        return metadata
    # These small facts prevent an evicted optional Pattern cache from turning a
    # registered entry point into a false dead-code candidate.
    wiring = [
        fact
        for fact in ir.get("evidence_facts", [])
        if fact.get("fact") in {"entry_points", "registrations"}
    ]
    ir["evidence_facts"] = wiring
    metadata.pop("module_docstring", None)
    metadata["ir"] = ir
    metadata["evidence_cache_evicted"] = {
        "version": 1,
        "module_docstring": docstring,
        "dynamic_wiring_retained": True,
    }
    return metadata

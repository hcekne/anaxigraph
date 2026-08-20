"""Stable hashes and signatures for immutable temporal facts."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def analysis_signature(metadata_json: str) -> str:
    metadata = json.loads(metadata_json or "{}")
    return str(metadata.get("analysis_signature") or "legacy-unknown")


def resolver_context_hash(metadata_json: str) -> str:
    metadata = json.loads(metadata_json or "{}")
    return digest((metadata.get("ir") or {}).get("resolver_context") or {})


def digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()

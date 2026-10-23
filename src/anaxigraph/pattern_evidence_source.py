"""Restore evicted deterministic Pattern evidence from fingerprint-matching mounted source."""

from __future__ import annotations

import hashlib
import json
import threading
import zlib
from collections import OrderedDict
from dataclasses import asdict
from pathlib import Path

from anaxigraph.analyzers import builtin_registry
from anaxigraph.ir import analyze_with_contract
from anaxigraph.persistence.pattern_evidence_read import (
    empty_pattern_evidence as empty_pattern_evidence,
)
from anaxigraph.persistence.pattern_evidence_read import (
    read_pattern_evidence as _read_evidence,
)

_CACHE: OrderedDict[tuple, bytes] = OrderedDict()
_CACHE_BYTES = 0
_CACHE_LIMIT = 8_000_000
_LOCK = threading.Lock()
_REGISTRY = builtin_registry()


def read_pattern_evidence(connection, repository_id, snapshot_id, *, target=""):
    row = connection.execute(
        "SELECT path FROM repositories WHERE id=?", (repository_id,)
    ).fetchone()
    root = Path(row[0]).resolve()
    return _read_evidence(
        connection,
        repository_id,
        snapshot_id,
        target=target,
        metadata_loader=lambda raw: hydrated_metadata(root, raw),
    )


def hydrated_metadata(root: Path, raw):
    metadata = json.loads(raw["metadata_json"] or "{}")
    marker = metadata.get("evidence_cache_evicted")
    if not marker:
        return raw["metadata_json"]
    analyzer = _REGISTRY.for_language(raw["language"])
    if analyzer is None:
        return _unavailable(metadata, "No compatible source analyzer is mounted")
    key = (str(root), raw["path"], raw["raw_hash"], analyzer.capabilities.fingerprint)
    cached = _cached(key)
    if cached is None:
        try:
            cached = _parse(root, raw, analyzer)
        except (OSError, ValueError, RuntimeError, SyntaxError) as error:
            return _unavailable(metadata, str(error))
        _remember(key, cached)
    value = json.loads(zlib.decompress(cached))
    ir = dict(metadata.get("ir") or {})
    ir.update(
        evidence_facts=value["facts"],
        analyzer_capabilities=value["capabilities"],
        analyzer_version=value["version"],
        parse_status=value["parse_status"],
    )
    metadata["ir"] = ir
    if isinstance(marker, dict) and marker.get("module_docstring"):
        metadata["module_docstring"] = value["module_docstring"]
    metadata.pop("evidence_cache_evicted", None)
    metadata.pop("evidence_cache_unavailable", None)
    return json.dumps(metadata, sort_keys=True, separators=(",", ":"))


def _parse(root, raw, analyzer):
    path = (root / raw["path"]).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Evidence source is outside the mounted checkout")
    if path.stat().st_size > 16_000_000:
        raise ValueError("Evidence source exceeds the bounded parser cache input")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != raw["raw_hash"]:
        raise ValueError("Mounted source differs from this indexed revision")
    analysis = analyze_with_contract(
        analyzer, raw["path"], content.decode("utf-8", errors="replace")
    )
    if analysis.parse_error:
        raise ValueError("The current source analyzer could not reconstruct this evidence")
    value = {
        "facts": [asdict(fact) for fact in analysis.evidence_facts],
        "module_docstring": analysis.metadata.get("module_docstring", ""),
        "capabilities": analysis.analyzer_capabilities.as_dict(),
        "version": analysis.analyzer_version,
        "parse_status": analysis.parse_status,
    }
    encoded = json.dumps(value, separators=(",", ":")).encode()
    if len(encoded) > 16_000_000:
        raise ValueError("Rehydrated evidence exceeds the bounded parser cache input")
    return zlib.compress(encoded)


def _unavailable(metadata, reason):
    metadata["evidence_cache_unavailable"] = reason
    return json.dumps(metadata, sort_keys=True, separators=(",", ":"))


def _cached(key):
    with _LOCK:
        value = _CACHE.get(key)
        if value is not None:
            _CACHE.move_to_end(key)
        return value


def _remember(key, value):
    global _CACHE_BYTES
    if len(value) > _CACHE_LIMIT:
        return
    with _LOCK:
        _CACHE_BYTES -= len(_CACHE.pop(key, b""))
        _CACHE[key] = value
        _CACHE_BYTES += len(value)
        while _CACHE_BYTES > _CACHE_LIMIT or len(_CACHE) > 4096:
            _, removed = _CACHE.popitem(last=False)
            _CACHE_BYTES -= len(removed)

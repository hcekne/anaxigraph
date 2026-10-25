"""Canonical graph-set encoding, stored once inside each SQLite snapshot.

Intern repeated identities before compression. No root or snapshot identity is
repeated per relationship, and no decompressed cache is written to disk.
"""

from __future__ import annotations

import json
import zlib
from typing import Any

from anaxigraph.contracts import Edge


def encode_nodes(nodes: list[dict[str, Any]]) -> tuple[bytes, int]:
    encoded = json.dumps(
        nodes, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False
    ).encode()
    return zlib.compress(encoded), len(encoded)


def _decode(encoded: bytes, maximum: int) -> Any:
    decoder = zlib.decompressobj()
    raw = decoder.decompress(encoded, maximum + 1)
    if len(raw) > maximum or not decoder.eof or decoder.unused_data:
        raise ValueError("Stored graph set exceeds its decoded budget or is incomplete")
    return json.loads(raw)


def decode_nodes(encoded: bytes, *, maximum: int) -> list[dict[str, Any]]:
    return _decode(encoded, maximum)


def encode_edges(edges: tuple[Edge, ...]) -> tuple[bytes, int]:
    symbols = sorted({value for edge in edges for value in (edge.source, edge.target)})
    paths = sorted({edge.path for edge in edges})
    kinds = sorted({edge.kind for edge in edges})
    resolutions = sorted({edge.resolution for edge in edges})
    lookups = [
        {value: index for index, value in enumerate(values)}
        for values in (symbols, paths, kinds, resolutions)
    ]
    symbol, path, kind, resolution = lookups
    data = {
        "symbols": symbols,
        "paths": paths,
        "kinds": kinds,
        "resolutions": resolutions,
        "edges": [
            [
                symbol[edge.source],
                symbol[edge.target],
                kind[edge.kind],
                path[edge.path],
                edge.line,
                resolution[edge.resolution],
            ]
            for edge in edges
        ],
    }
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
    return zlib.compress(encoded), len(encoded)


def decode_edges(encoded: bytes, *, maximum: int) -> tuple[Edge, ...]:
    data = _decode(encoded, maximum)
    symbols, paths = data["symbols"], data["paths"]
    kinds, resolutions = data["kinds"], data["resolutions"]
    return tuple(
        Edge(
            symbols[source],
            symbols[target],
            kinds[kind],
            paths[path],
            line,
            resolutions[resolution],
        )
        for source, target, kind, path, line, resolution in data["edges"]
    )

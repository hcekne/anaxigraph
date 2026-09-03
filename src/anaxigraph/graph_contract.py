"""Versioned request and cursor contracts for bounded graph reads."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import time
from dataclasses import asdict, dataclass
from typing import Any

from anaxigraph.architecture_vocabulary import CURRENT_MAP, MAP_LAYERS

GRAPH_QUERY_VERSION = "graph-query-v2"
DEFAULT_NODE_LIMIT = 250
DEFAULT_EDGE_LIMIT = 500
MAX_NODE_LIMIT = 1_000
MAX_EDGE_LIMIT = 2_000
MAX_GRAPH_CURSOR_LENGTH = 2_000
GRAPH_NEIGHBORHOOD_VERSION = "graph-neighborhood-v1"
DEFAULT_NEIGHBOR_NODE_LIMIT = 100
DEFAULT_NEIGHBOR_EDGE_LIMIT = 250
MAX_NEIGHBOR_NODE_LIMIT = 500
MAX_NEIGHBOR_EDGE_LIMIT = 1_000
MAX_GRAPH_DEPTH = 3
GRAPH_DELTA_VERSION = "graph-delta-v1"
DEFAULT_GRAPH_DELTA_LIMIT = 250
MAX_GRAPH_DELTA_LIMIT = 1_000
# Additive availability labels: an empty graph from a never-scanned repository is a fact,
# not a snapshot that happens to hold nothing. Unknown or foreign ids fail loud instead.
GRAPH_UNSCANNED = "unscanned"
GRAPH_CURRENT = "current"


@dataclass(frozen=True, slots=True)
class GraphPageRequest:
    """One immutable page request; every collection field is normalized for stable cursors."""

    cursor: str = ""
    node_limit: int = DEFAULT_NODE_LIMIT
    edge_limit: int = DEFAULT_EDGE_LIMIT
    include_external: bool = False
    map_layer: str = CURRENT_MAP
    path: str = ""
    languages: tuple[str, ...] = ()
    areas: tuple[str, ...] = ()
    subsystems: tuple[str, ...] = ()
    finding_types: tuple[str, ...] = ()
    relationship_types: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 1 <= self.node_limit <= MAX_NODE_LIMIT:
            raise ValueError(f"node_limit must be between 1 and {MAX_NODE_LIMIT}")
        if not 1 <= self.edge_limit <= MAX_EDGE_LIMIT:
            raise ValueError(f"edge_limit must be between 1 and {MAX_EDGE_LIMIT}")
        if len(self.cursor) > MAX_GRAPH_CURSOR_LENGTH:
            raise ValueError("graph cursor is too long")
        if self.map_layer not in MAP_LAYERS:
            raise ValueError(f"map_layer must be one of: {', '.join(MAP_LAYERS)}")
        object.__setattr__(self, "path", self.path.strip())
        for field in (
            "languages",
            "areas",
            "subsystems",
            "finding_types",
            "relationship_types",
        ):
            object.__setattr__(self, field, _normalized(getattr(self, field)))

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(self.filter_payload(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def filter_payload(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("cursor")
        value["version"] = GRAPH_QUERY_VERSION
        return value


@dataclass(frozen=True, slots=True)
class GraphCursor:
    snapshot_id: int
    query_fingerprint: str
    node_offset: int
    edge_offset: int
    version: str = GRAPH_QUERY_VERSION

    def __post_init__(self) -> None:
        if self.version != GRAPH_QUERY_VERSION:
            raise ValueError("graph cursor version is not supported")
        if self.snapshot_id < 1 or self.node_offset < 0 or self.edge_offset < 0:
            raise ValueError("graph cursor contains an invalid offset or snapshot")
        if len(self.query_fingerprint) != 64:
            raise ValueError("graph cursor query fingerprint is invalid")

    def encode(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(payload).decode().rstrip("=")

    @classmethod
    def decode(cls, value: str) -> GraphCursor:
        if not value or len(value) > MAX_GRAPH_CURSOR_LENGTH:
            raise ValueError("graph cursor is empty or too long")
        try:
            padding = "=" * (-len(value) % 4)
            payload = json.loads(base64.urlsafe_b64decode(value + padding))
            if not isinstance(payload, dict):
                raise TypeError
            return cls(
                snapshot_id=int(payload["snapshot_id"]),
                query_fingerprint=str(payload["query_fingerprint"]),
                node_offset=int(payload["node_offset"]),
                edge_offset=int(payload["edge_offset"]),
                version=str(payload["version"]),
            )
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, binascii.Error) as exc:
            raise ValueError("graph cursor is malformed") from exc


@dataclass(frozen=True, slots=True)
class GraphNeighborhoodRequest:
    node: str
    depth: int = 1
    direction: str = "both"
    node_limit: int = DEFAULT_NEIGHBOR_NODE_LIMIT
    edge_limit: int = DEFAULT_NEIGHBOR_EDGE_LIMIT
    include_external: bool = False
    relationship_types: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "node", self.node.strip())
        object.__setattr__(self, "relationship_types", _normalized(self.relationship_types))
        if not self.node:
            raise ValueError("graph neighborhood requires a node id or exact path")
        if not 1 <= self.depth <= MAX_GRAPH_DEPTH:
            raise ValueError(f"graph depth must be between 1 and {MAX_GRAPH_DEPTH}")
        if self.direction not in {"incoming", "outgoing", "both"}:
            raise ValueError("graph direction must be incoming, outgoing, or both")
        if not 1 <= self.node_limit <= MAX_NEIGHBOR_NODE_LIMIT:
            raise ValueError(
                f"neighborhood node_limit must be between 1 and {MAX_NEIGHBOR_NODE_LIMIT}"
            )
        if not 1 <= self.edge_limit <= MAX_NEIGHBOR_EDGE_LIMIT:
            raise ValueError(
                f"neighborhood edge_limit must be between 1 and {MAX_NEIGHBOR_EDGE_LIMIT}"
            )


def resolve_graph_cursor(
    request: GraphPageRequest,
    snapshot_id: int,
) -> GraphCursor:
    if not request.cursor:
        return GraphCursor(snapshot_id, request.fingerprint, 0, 0)
    cursor = GraphCursor.decode(request.cursor)
    if cursor.snapshot_id != snapshot_id:
        raise ValueError("graph cursor belongs to a different snapshot")
    if cursor.query_fingerprint != request.fingerprint:
        raise ValueError("graph cursor does not match the requested filters or limits")
    return cursor


def next_graph_cursor(
    request: GraphPageRequest,
    snapshot_id: int,
    *,
    node_offset: int,
    edge_offset: int,
) -> str:
    return GraphCursor(
        snapshot_id,
        request.fingerprint,
        node_offset,
        edge_offset,
    ).encode()


def _normalized(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({value.strip() for value in values if value.strip()}))


def with_graph_telemetry(response: dict[str, Any], started: float) -> dict[str, Any]:
    """Attach stable serialized-byte and server-time evidence to a graph response."""

    return _with_response_telemetry(response, started, action="graph_query")


def _with_response_telemetry(
    response: dict[str, Any], started: float, *, action: str
) -> dict[str, Any]:
    """Attach small, stable timing and size evidence to an indexed read response."""

    response["telemetry"] = {
        "contract_version": "action-telemetry-v1",
        "action": action,
        "duration_ms": round((time.perf_counter() - started) * 1_000, 3),
        "payload_bytes": 0,
        "input_tokens": 0,
        "output_tokens": 0,
    }
    for _attempt in range(4):
        size = _response_payload_bytes(response)
        if size == response["telemetry"]["payload_bytes"]:
            break
        response["telemetry"]["payload_bytes"] = size
    return response


def _response_payload_bytes(response: dict[str, Any]) -> int:
    return len(
        json.dumps(response, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    )

"""Shared graph-only entry point to canonical snapshot projection."""

from __future__ import annotations

from typing import Any

from anaxigraph.persistence.snapshot_projection import install_snapshot_projection


def install_graph_projection(connection: Any, snapshot_id: int):
    return install_snapshot_projection(connection, snapshot_id, include_symbols=False)

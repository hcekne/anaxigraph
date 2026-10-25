"""The indexing component accepts a checkout and returns immutable source observations."""

from __future__ import annotations

from pathlib import Path

from anaxigraph.contracts import Graph, Snapshot
from anaxigraph.indexing.discovery import capture_sources, discover
from anaxigraph.indexing.python import Relationships, parse_module
from anaxigraph.indexing.resolution import Resolver


def index(root: Path, *, excluded: tuple[str, ...] = ()) -> Graph:
    """Capture source identity and extract Python facts; never execute repository code.

    Resolution is lexical, not a proof of runtime reachability. External targets, dynamic
    dispatch, parse failures and unsupported languages remain explicit incomplete evidence.
    """
    snapshot, contents, diagnostics = discover(root, excluded)
    nodes = []
    modules = []
    edges = []
    for path, source in contents.items():
        module, observation, error = parse_module(path, source, snapshot.files[path])
        nodes.append(observation)
        if error:
            diagnostics.append(error)
        if module:
            modules.append(module)
            nodes.extend(module.nodes)
    resolver = Resolver(modules)
    external = {}
    for module in modules:
        relationships = Relationships(module, resolver)
        relationships.visit(module.tree)
        edges.extend(relationships.edges)
        external.update(relationships.external)
    nodes.extend(external.values())
    # A syntax visit can find the same relation more than once; facts are set-valued.
    unique_edges = {(e.source, e.target, e.kind, e.path, e.line, e.resolution): e for e in edges}
    return Graph(snapshot, tuple(nodes), tuple(unique_edges.values()), tuple(diagnostics))


def capture_snapshot(root: Path) -> Snapshot:
    """Recheck source bytes and identity without rebuilding the syntax graph."""
    return discover(root, ())[0]


__all__ = ["index", "capture_snapshot", "capture_sources"]

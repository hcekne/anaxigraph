"""The single application owner shared by CLI, MCP and the dashboard."""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from anaxigraph import __version__
from anaxigraph.analysis import build_request, validate_result
from anaxigraph.analysis.changes import change_review
from anaxigraph.analysis.guidance import module_for, neighborhood, prepare
from anaxigraph.contracts import Graph
from anaxigraph.indexing import capture_snapshot, capture_sources, index
from anaxigraph.storage import Store


def context_fingerprints(graph: Graph) -> dict[str, str]:
    owners = {node.id: node.path for node in graph.nodes}
    dependencies = {node.path: {node.path} for node in graph.nodes if node.kind == "module"}
    for edge in graph.edges:
        source, target = owners.get(edge.source), owners.get(edge.target)
        if (
            source in dependencies
            and target in graph.snapshot.files
            and edge.resolution == "resolved"
        ):
            dependencies[source].add(target)
    return {
        path: hashlib.sha256(
            json.dumps({p: graph.snapshot.files[p] for p in paths}, sort_keys=True).encode()
        ).hexdigest()
        for path, paths in dependencies.items()
    }


def _bounds(limit: int, maximum: int = 100) -> int:
    if type(limit) is not int or not 1 <= limit <= maximum:
        raise ValueError(f"limit must be between 1 and {maximum}")
    return limit


class Application:
    """Compose independent components; do not duplicate reasoning in transports."""

    def __init__(self, root: Path, database: Path | None = None) -> None:
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("Repository root must be a directory")
        self.store = Store(database or self.root / ".anaxigraph-v2" / "knowledge.sqlite")
        self._graph_cache: tuple[tuple[int, ...], Graph] | None = None

    def _current(self) -> Graph:
        token = self.store.cache_token()
        if self._graph_cache is not None and self._graph_cache[0] == token:
            return self._graph_cache[1]
        graph = self.store.load_graph(str(self.root))
        if graph is None:
            raise ValueError("No map for this checkout; run scan first")
        contexts = context_fingerprints(graph)
        nodes = []
        for node in graph.nodes:
            data = dict(node.data)
            annotation = data.get("annotation")
            if annotation and annotation.get("context_fingerprint") != contexts.get(node.path):
                data["annotation_status"] = "stale"
            nodes.append(replace(node, data=data))
        current = replace(graph, nodes=tuple(nodes))
        if self.store.cache_token() == token:
            self._graph_cache = (token, current)
        return current

    def _require_live(self, graph: Graph) -> None:
        # Never accept an old job merely because an edit has not been scanned yet.
        if capture_snapshot(self.root).id != graph.snapshot.id:
            raise ValueError(
                "Checkout changed after mapping; scan again before saving or validating"
            )

    def scan(self) -> dict[str, Any]:
        started = time.monotonic()
        graph = index(self.root)
        # Avoid publishing a captured graph after a concurrent edit.
        self._require_live(graph)
        self.store.save_graph(graph)
        return {
            **self.status(),
            "elapsed_seconds": round(time.monotonic() - started, 4),
            "mapped_locally": True,
            "record_exported": False,
            "committed_pushed": False,
        }

    def status(self) -> dict[str, Any]:
        stats = self.store.stats(str(self.root))
        storage = {key: stats[key] for key in ("bytes", "max_bytes", "snapshots", "reviews")}
        if stats["snapshot_id"] is None:
            return {
                "version": __version__,
                "root": str(self.root),
                "snapshot": None,
                "modules": 0,
                "symbols": 0,
                "relationships": 0,
                "annotations": {"current": 0, "stale": 0, "missing": 0},
                "storage": storage,
            }
        graph = self._current()
        modules = [n for n in graph.nodes if n.kind == "module"]
        coverage = Counter(n.data.get("annotation_status", "missing") for n in modules)
        return {
            "version": __version__,
            "root": str(self.root),
            "snapshot": {
                key: value for key, value in asdict(graph.snapshot).items() if key != "files"
            }
            | {"file_count": len(graph.snapshot.files)},
            "modules": len(modules),
            "symbols": sum(n.kind in {"function", "class", "interface"} for n in graph.nodes),
            "relationships": len(graph.edges),
            "unresolved_relationships": sum(e.resolution != "resolved" for e in graph.edges),
            "annotations": {key: coverage[key] for key in ("current", "stale", "missing")},
            "diagnostics": list(graph.diagnostics)[:30],
            "storage": storage,
            "coverage": "Python/PYI syntax and scoped references; dynamic targets may be unresolved",
        }

    def modules(
        self, sort: str = "path", descending: bool = False, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        _bounds(limit)
        if type(offset) is not int or offset < 0:
            raise ValueError("offset must be a nonnegative integer")
        if sort not in {"path", "loc", "functions", "function_count"}:
            raise ValueError("sort must be path, loc or functions")
        nodes = [node for node in self._current().nodes if node.kind == "module"]
        key = "function_count" if sort == "functions" else sort
        nodes.sort(
            key=lambda n: n.path if key == "path" else n.data.get(key, 0), reverse=descending
        )
        items = []
        for node in nodes[offset : offset + limit]:
            data = {
                key: node.data[key]
                for key in ("loc", "function_count", "parse_status", "is_test", "annotation_status")
                if key in node.data
            }
            annotation = node.data.get("annotation")
            if annotation:
                data["annotation"] = {"overview": annotation["overview"]}
            item = asdict(replace(node, data=data))
            if items and len(json.dumps(items + [item]).encode()) > 7600:
                break
            items.append(item)
        next_offset = offset + len(items)
        return {
            "items": items,
            "total": len(nodes),
            "offset": offset,
            "limit": limit,
            "next_offset": next_offset if next_offset < len(nodes) else None,
        }

    def inspect(self, entity_id: str, limit: int = 30) -> dict[str, Any]:
        graph = self._current()
        if entity_id.startswith("review:"):
            row = next(
                (
                    row
                    for row in self.store.reviews(str(self.root))
                    if row["kind"] != "request" and row["id"] == entity_id[7:]
                ),
                None,
            )
            if row is None:
                raise ValueError("Saved review not found")
            row = self._review_state(row, graph)
            return {
                "entity": {
                    "id": entity_id,
                    "kind": "review",
                    "name": row["kind"],
                    "path": "",
                    "line": 1,
                    "data": row,
                },
                "incoming": [],
                "outgoing": [],
                "neighbors": [],
                "snapshot_id": graph.snapshot.id,
            }
        result = neighborhood(graph, entity_id, _bounds(limit))
        result["snapshot_id"] = graph.snapshot.id
        entity = result["entity"]
        if entity["kind"] == "function":
            owner = module_for(graph, entity["path"])
            if owner:
                annotation = owner.data.get("annotation", {})
                entity["data"]["overview"] = next(
                    (
                        item["overview"]
                        for item in annotation.get("functions", [])
                        if item["node_id"] == entity["id"]
                    ),
                    None,
                )
                entity["data"]["annotation_status"] = owner.data.get("annotation_status", "missing")
        return result

    def prepare_change(self, task: str, limit: int = 12) -> dict[str, Any]:
        if not isinstance(task, str) or not task.strip() or len(task) > 4000:
            raise ValueError("task must be nonempty text of at most 4,000 characters")
        graph = self._current()
        matches = self.store.search(str(self.root), task, _bounds(limit, 30))
        statuses = {
            n.path: n.data.get("annotation_status", "missing")
            for n in graph.nodes
            if n.kind == "module"
        }
        for match in matches:
            match["annotation_status"] = statuses.get(match["path"], "missing")
        return prepare(graph, matches, task)

    def assess_plan(self, task: str, files: list[str]) -> dict[str, Any]:
        if not isinstance(files, list) or not files or len(files) > 30:
            raise ValueError("files must name between 1 and 30 relative paths")
        if any(
            not isinstance(p, str) or Path(p).is_absolute() or ".." in Path(p).parts for p in files
        ):
            raise ValueError("Plan files must be repository-relative paths")
        brief = self.prepare_change(task)
        existing = {node["path"] for node in brief["likely_owners"]}
        findings = []
        for path in files:
            if path not in self._current().snapshot.files and existing:
                findings.append(
                    {
                        "path": path,
                        "kind": "reuse-opportunity",
                        "message": "Compare existing responsibility owners before adding a sibling module.",
                        "existing": sorted(existing),
                    }
                )
        return {
            "snapshot_id": brief["snapshot_id"],
            "files": files,
            "findings": findings,
            "brief": brief,
            "status": "advisory",
            "scope": "Placement and lexical reuse evidence; behavioral plan correctness is unresolved.",
        }

    def validate_change(self, receipts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        graph = self._current()
        self._require_live(graph)
        previous_id = self.store.stats(str(self.root)).get("previous_snapshot_id")
        previous = self.store.load_graph(str(self.root), previous_id) if previous_id else None
        return change_review(graph, previous, receipts)

    def analysis_request(self, kind: str, scope: list[str] | None = None) -> dict[str, Any]:
        graph = self._current()
        self._require_live(graph)
        sources = None
        if kind == "annotate":
            modules = [n for n in graph.nodes if n.kind == "module"]
            selected = scope or [modules[0].id] if modules else []
            selected_paths = [n.path for n in modules if n.id in selected or n.path in selected]
            sources = capture_sources(self.root, selected_paths, graph.snapshot.files)
        request = build_request(graph, kind, scope, sources)
        self.store.save_review(
            str(self.root), graph.snapshot.id, request["request_id"], "request", request
        )
        if kind == "fresh-eyes":
            # Do not hand the blind designer a scope envelope containing module IDs.
            return {
                key: request[key] for key in ("request_id", "kind", "packet", "response_schema")
            }
        return {key: value for key, value in request.items() if key != "function_ids"}

    def submit_analysis(self, request_id: str, result: dict[str, Any]) -> dict[str, Any]:
        saved = next(
            (
                row
                for row in self.store.reviews(str(self.root), "request")
                if row["id"] == request_id
            ),
            None,
        )
        if saved is None:
            raise ValueError("Unknown or expired request; request the analysis again")
        request = saved["result"]
        graph = self._current()
        if request["snapshot_id"] != graph.snapshot.id:
            raise ValueError("Request belongs to a stale snapshot; request it again")
        self._require_live(graph)
        validate_result(request, result, graph)
        if request["kind"] == "annotate":
            contexts = context_fingerprints(graph)
            for annotation in result["annotations"]:
                node = next(n for n in graph.nodes if n.id == annotation["node_id"])
                value = dict(annotation) | {
                    "producer": result["producer"],
                    "basis": "agent-reported-interpretation",
                    "source_snapshot": graph.snapshot.id,
                    "context_fingerprint": contexts[node.path],
                    "request_id": request_id,
                }
                prior = next(
                    n["data"].get("annotation")
                    for n in request["packet"]["modules"]
                    if n["id"] == node.id
                )
                expected_digest = hashlib.sha256(
                    json.dumps(
                        prior, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                    ).encode()
                ).hexdigest()
                self.store.annotate(
                    str(self.root),
                    graph.snapshot.id,
                    node.id,
                    value,
                    expected_digest=expected_digest,
                )
        else:
            if build_request(graph, request["kind"], request["scope"])["request_id"] != request_id:
                raise ValueError("Analysis inputs changed; prepare a new review request")
            self.store.save_review(
                str(self.root),
                graph.snapshot.id,
                request_id,
                request["kind"],
                {"basis": "agent-reported-proposal", "scope": request["scope"], "result": result},
            )
        return {
            "request_id": request_id,
            "kind": request["kind"],
            "saved": True,
            "snapshot_id": graph.snapshot.id,
            "validation": "Shape, declared coverage and evidence references checked; semantic quality remains reviewable.",
        }

    def reviews(self, kind: str | None = None) -> dict[str, Any]:
        saved = [
            row for row in self.store.reviews(str(self.root), kind) if row["kind"] != "request"
        ]
        if not saved:
            return {"items": [], "total": 0}
        graph = self._current()
        rows = [self._review_state(row, graph) for row in saved]
        # Results are explicit expansions; keep default lists concise.
        return {
            "items": [
                {key: value for key, value in row.items() if key != "result"}
                | {
                    "producer": row["result"].get("result", {}).get("producer"),
                    "summary": "Three alternatives"
                    if row["kind"] == "fresh-eyes"
                    else "Complete declared catalogue matrix",
                }
                for row in rows
            ],
            "total": len(rows),
        }

    @staticmethod
    def _review_state(row: dict[str, Any], graph: Graph) -> dict[str, Any]:
        if row["status"] != "current":
            return row
        scope = row["result"].get("scope")
        if scope is None:
            return row | {
                "status": "unknown",
                "freshness_reason": "Analysis input identity not recorded",
            }
        try:
            current_id = build_request(graph, row["kind"], scope)["request_id"]
        except ValueError:
            current_id = None
        return (
            row
            if current_id == row["id"]
            else row
            | {
                "status": "stale",
                "freshness_reason": "Source, semantic, catalogue or prompt inputs changed",
            }
        )

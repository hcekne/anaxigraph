"""Knowledge lifecycle tests, including bounded writes and failed publication."""

from __future__ import annotations

import sqlite3
import zlib
from base64 import b64encode
from dataclasses import replace
from pathlib import Path
from random import Random

import pytest

from anaxigraph.contracts import Edge, Graph, Node, Snapshot
from anaxigraph.storage import Store


def graph(root: Path, identity: str = "one", fingerprint: str = "source-a") -> Graph:
    return Graph(
        Snapshot(
            identity,
            str(root.resolve()),
            "base",
            True,
            {"a.py": fingerprint, "b.py": "source-b"},
            "2026-10-25T00:00:00Z",
        ),
        (
            Node("module:a.py", "module", "accounting", "a.py", data={"loc": 12}),
            Node("module:b.py", "module", "storage", "b.py", data={"loc": 4}),
            Node("symbol:a.py:run", "function", "run", "a.py", 3),
        ),
        (Edge("module:a.py", "module:b.py", "imports", "a.py"),),
        ("Dynamic import remains unresolved",),
    )


def annotated(graph: Graph, node_id: str = "module:a.py") -> Node:
    return next(node for node in graph.nodes if node.id == node_id)


def test_round_trip_and_empty_checkout(tmp_path: Path) -> None:
    store = Store(tmp_path / "knowledge.sqlite")
    original = graph(tmp_path / "checkout")
    assert store.load_graph(original.snapshot.root) is None
    store.save_graph(original)
    assert store.load_graph(original.snapshot.root) == original
    stats = store.stats(original.snapshot.root)
    assert stats["nodes"] == 3
    assert stats["edges"] == 1
    assert stats["modules"] == 2
    assert stats["annotations"] == 0
    assert stats["bytes"] <= stats["max_bytes"]


def test_unchanged_cycles_do_not_write_or_grow_storage(tmp_path: Path) -> None:
    store = Store(tmp_path / "knowledge.sqlite")
    current = graph(tmp_path)
    store.save_graph(current)
    body = {
        "overview": "Coordinates invoice creation.",
        "detail": "Keeps currency rules local.",
        "provenance": {"provider": "fixture", "model": "fixture"},
    }
    store.annotate(current.snapshot.root, "one", "module:a.py", body)
    store.save_review(current.snapshot.root, "one", "review-1", "patterns", {"findings": []})
    before = store.path.read_bytes()
    for _ in range(30):
        store.save_graph(replace(current, snapshot=replace(current.snapshot, created_at="later")))
        store.annotate(current.snapshot.root, "one", "module:a.py", body)
        store.save_review(current.snapshot.root, "one", "review-1", "patterns", {"findings": []})
    assert store.path.read_bytes() == before
    assert store.stats(current.snapshot.root)["snapshots"] == 1
    assert store.stats(current.snapshot.root)["reviews"] == 1


def test_new_snapshot_reuses_only_matching_annotations(tmp_path: Path) -> None:
    store = Store(tmp_path / "knowledge.sqlite")
    first = graph(tmp_path)
    store.save_graph(first)
    body = {"overview": "Owns invoice rules.", "context_fingerprint": "context-one"}
    store.annotate(first.snapshot.root, "one", "module:a.py", body)
    second = replace(
        graph(tmp_path, "two"),
        snapshot=replace(
            graph(tmp_path, "two").snapshot, files={"a.py": "source-a", "b.py": "changed-b"}
        ),
    )
    store.save_graph(second)
    loaded = store.load_graph(first.snapshot.root)
    assert loaded is not None
    node = annotated(loaded)
    assert node.data["annotation"] == body
    assert node.data["annotation_status"] == "current"
    # Application-level dependency context is preserved, not silently rewritten.
    assert node.data["annotation"]["context_fingerprint"] == "context-one"


def test_changed_source_keeps_explicit_stale_annotation_and_old_baseline(tmp_path: Path) -> None:
    store = Store(tmp_path / "knowledge.sqlite")
    store.save_graph(graph(tmp_path))
    store.annotate(str(tmp_path), "one", "module:a.py", {"overview": "Old responsibility."})
    store.save_graph(graph(tmp_path, "two", "changed-a"))
    current = store.load_graph(str(tmp_path))
    previous = store.load_graph(str(tmp_path), "one")
    assert current is not None and previous is not None
    assert annotated(current).data["annotation_status"] == "stale"
    assert annotated(previous).data["annotation_status"] == "current"
    assert store.stats(str(tmp_path))["stale_annotations"] == 1
    store.annotate(str(tmp_path), "two", "module:a.py", {"overview": "New responsibility."})
    refreshed = store.load_graph(str(tmp_path))
    assert refreshed is not None
    assert annotated(refreshed).data["annotation_status"] == "current"
    assert annotated(previous).data["annotation"]["overview"] == "Old responsibility."


def test_stale_submissions_and_fingerprint_mismatch_are_rejected(tmp_path: Path) -> None:
    store = Store(tmp_path / "knowledge.sqlite")
    store.save_graph(graph(tmp_path))
    store.save_graph(graph(tmp_path, "two", "changed"))
    with pytest.raises(ValueError, match="stale"):
        store.annotate(str(tmp_path), "one", "module:a.py", {"overview": "Too late."})
    with pytest.raises(ValueError, match="fingerprint"):
        store.annotate(str(tmp_path), "two", "module:a.py", {"fingerprint": "wrong"})
    with pytest.raises(ValueError, match="fingerprint"):
        store.annotate(str(tmp_path), "two", "unknown", {"overview": "Missing target."})
    with pytest.raises(ValueError, match="stale"):
        store.save_review(str(tmp_path), "one", "late", "patterns", {})


def test_snapshot_identity_cannot_change_meaning(tmp_path: Path) -> None:
    store = Store(tmp_path / "knowledge.sqlite")
    original = graph(tmp_path)
    store.save_graph(original)
    with pytest.raises(ValueError, match="identity"):
        store.save_graph(graph(tmp_path, fingerprint="different"))
    assert store.load_graph(str(tmp_path)) == original


def test_only_current_and_previous_snapshots_survive(tmp_path: Path) -> None:
    store = Store(tmp_path / "knowledge.sqlite")
    for number in range(10):
        store.save_graph(graph(tmp_path, str(number), f"source-{number}"))
    assert store.load_graph(str(tmp_path), "7") is None
    assert store.load_graph(str(tmp_path), "8") is not None
    assert store.load_graph(str(tmp_path), "9") is not None
    assert store.stats(str(tmp_path))["snapshots"] == 2
    assert store.stats(str(tmp_path))["snapshot_id"] == "9"
    assert store.stats(str(tmp_path))["previous_snapshot_id"] == "8"


def test_checkout_isolation_and_bounded_semantic_search(tmp_path: Path) -> None:
    store = Store(tmp_path / "knowledge.sqlite")
    for name in ("left", "right"):
        current = graph(tmp_path / name)
        store.save_graph(current)
        store.annotate(
            current.snapshot.root, "one", "module:a.py", {"overview": f"{name} invoices"}
        )
    assert len(store.search(str(tmp_path / "left"), "invoices", 1)) == 1
    assert store.search(str(tmp_path / "left"), "right") == []
    assert store.search(str(tmp_path / "left"), '" OR *') == []
    assert store.search(str(tmp_path / "left"), "") == []
    with pytest.raises(ValueError, match="limit"):
        store.search(str(tmp_path), "anything", 101)
    left = store.load_graph(str(tmp_path / "left"))
    right = store.load_graph(str(tmp_path / "right"))
    assert left is not None and right is not None
    assert annotated(left).data["annotation"]["overview"] == "left invoices"
    assert annotated(right).data["annotation"]["overview"] == "right invoices"


def test_requests_survive_completed_review_retention(tmp_path: Path) -> None:
    store = Store(tmp_path / "knowledge.sqlite")
    store.save_graph(graph(tmp_path))
    for number in range(70):
        store.save_review(str(tmp_path), "one", str(number), "request", {"packet": number})
    for number in range(25):
        store.save_review(str(tmp_path), "one", str(number), "patterns", {"findings": []})
    assert len(store.reviews(str(tmp_path), "request")) == 64
    assert len(store.reviews(str(tmp_path), "patterns")) == 20
    assert store.stats(str(tmp_path))["reviews"] == 84
    assert store.reviews(str(tmp_path), "patterns")[0]["id"] == "24"
    store.save_graph(graph(tmp_path, "two"))
    assert store.reviews(str(tmp_path), "request")[0]["status"] == "stale"


def test_oversized_records_preserve_valid_state(tmp_path: Path) -> None:
    store = Store(tmp_path / "knowledge.sqlite")
    original = graph(tmp_path)
    store.save_graph(original)
    before = store.path.read_bytes()
    with pytest.raises(ValueError, match="limit"):
        store.annotate(str(tmp_path), "one", "module:a.py", {"overview": "x" * 70_000})
    with pytest.raises(ValueError, match="limit"):
        store.save_review(str(tmp_path), "one", "large", "request", {"packet": "x" * 300_000})
    assert store.path.read_bytes() == before


def test_sqlite_capacity_failure_rolls_back_map_and_cleans_journal(tmp_path: Path) -> None:
    store = Store(tmp_path / "knowledge.sqlite", max_bytes=98_304)
    original = graph(tmp_path)
    store.save_graph(original)
    large = graph(tmp_path, "too-large")
    large = replace(
        large,
        nodes=tuple(
            Node(
                f"module:{number}.py",
                "module",
                str(number),
                f"{number}.py",
                data={"note": b64encode(Random(number).randbytes(4500)).decode()},
            )
            for number in range(10)
        ),
    )
    with pytest.raises(ValueError, match="budget"):
        store.save_graph(large)
    assert store.load_graph(str(tmp_path)) == original
    assert not Path(str(store.path) + "-journal").exists()
    assert store.path.stat().st_size <= store.max_bytes


def test_annotations_are_canonical_not_copied_into_node_rows(tmp_path: Path) -> None:
    store = Store(tmp_path / "knowledge.sqlite")
    store.save_graph(graph(tmp_path))
    store.annotate(
        str(tmp_path), "one", "module:a.py", {"overview": "Purpose.", "detail": "Unique narrative."}
    )
    store.save_graph(graph(tmp_path, "two"))
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT count(*) FROM annotations").fetchone()[0] == 1
        assert all(
            "Unique narrative" not in zlib.decompress(row[0]).decode()
            for row in db.execute("SELECT data FROM node_sets")
        )
        assert all(
            "Unique narrative" not in row[0] for row in db.execute("SELECT overview FROM search")
        )


def test_changed_large_map_keeps_two_complete_snapshots_compact(tmp_path: Path) -> None:
    """Long symbol identities must not be repeated for every stored edge."""
    paths = [
        "src/responsibility_boundaries/" + "tenant_invoice_domain_" * 3 + f"feature_{n}/service.py"
        for n in range(300)
    ]
    symbols = [f"symbol:{path}#InvoiceCoordinationService.create_and_validate" for path in paths]
    nodes = tuple(
        node
        for path, symbol in zip(paths, symbols)
        for node in (
            Node(f"module:{path}", "module", "InvoiceCoordinationService", path, data={"loc": 100}),
            Node(symbol, "function", "create_and_validate", path, 10),
        )
    )
    edges = tuple(
        Edge(
            symbols[n % 300],
            symbols[(n * 17 + n // 300 + 1) % 300],
            "calls",
            paths[n % 300],
            n % 100 + 1,
            "resolved" if n % 3 else "ambiguous",
        )
        for n in range(12_000)
    )
    snapshot = Snapshot(
        "a" * 64,
        str(tmp_path),
        "base",
        False,
        {path: "f" * 64 for path in paths},
        "2026-10-25T00:00:00Z",
    )
    first = Graph(snapshot, nodes, edges)
    second = replace(
        first, snapshot=replace(snapshot, id="b" * 64, files=snapshot.files | {paths[0]: "changed"})
    )
    store = Store(tmp_path / "knowledge.sqlite")
    store.save_graph(first)
    store.save_graph(second)
    current = store.load_graph(str(tmp_path))
    previous = store.load_graph(str(tmp_path), first.snapshot.id)
    assert current is not None and previous is not None
    assert current.edges == previous.edges == edges
    assert current.snapshot.files[paths[0]] == "changed"
    assert previous.snapshot.files[paths[0]] == "f" * 64
    assert store.stats(str(tmp_path))["snapshots"] == 2
    assert store.stats(str(tmp_path))["edges"] == 12_000
    assert store.path.stat().st_size < 5_000_000
    before = store.path.read_bytes()
    store.save_graph(second)
    assert store.path.read_bytes() == before


def test_cache_token_is_read_stable_and_changes_for_other_store_writes(tmp_path: Path) -> None:
    store = Store(tmp_path / "knowledge.sqlite")
    store.save_graph(graph(tmp_path))
    before = store.cache_token()
    other = Store(store.path)
    assert other.cache_token() == before
    store.load_graph(str(tmp_path))
    store.stats(str(tmp_path))
    store.reviews(str(tmp_path))
    assert store.cache_token() == before
    other.annotate(str(tmp_path), "one", "module:a.py", {"overview": "Updated elsewhere."})
    assert store.cache_token() != before
    loaded = store.load_graph(str(tmp_path))
    assert loaded is not None
    assert annotated(loaded).data["annotation"]["overview"] == "Updated elsewhere."


def test_graph_materialization_holds_one_consistent_read_transaction(
    tmp_path: Path, monkeypatch
) -> None:
    store = Store(tmp_path / "knowledge.sqlite")
    original = graph(tmp_path)
    store.save_graph(original)
    read_annotations = store._annotation_rows
    blocked = []

    def concurrent_publication(db, root):
        writer = sqlite3.connect(store.path, timeout=0)
        try:
            # A publisher may obtain its reserved lock, but cannot commit/prune
            # underneath an in-progress read of the old snapshot.
            writer.execute(
                "DELETE FROM source_nodes WHERE snapshot_key IN "
                "(SELECT record_id FROM snapshots WHERE root=?)",
                (str(tmp_path),),
            )
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                writer.commit()
            blocked.append(True)
        finally:
            writer.rollback()
            writer.close()
        return read_annotations(db, root)

    monkeypatch.setattr(store, "_annotation_rows", concurrent_publication)
    assert store.load_graph(str(tmp_path)) == original
    assert blocked == [True]

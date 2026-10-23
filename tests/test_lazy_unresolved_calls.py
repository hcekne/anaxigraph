"""Unknown static links retain canonical evidence without one SQL node per call target."""

import json

import anaxigraph.knowledge_edges as edges
from anaxigraph.knowledge_detail import entity_detail, neighborhood
from anaxigraph.knowledge_query import entity_page
from anaxigraph.knowledge_sync import sync_knowledge
from anaxigraph.knowledge_unresolved import (
    all_unresolved_nodes,
    unresolved_connections,
    unresolved_counts,
    unresolved_node,
)
from anaxigraph.scanner import RepositoryScanner


def test_lazy_unknown_links_preserve_each_call_site_without_source_reads_or_writes(
    tmp_path, database
):
    root = tmp_path / "unresolved"
    root.mkdir()
    path = root / "dynamic.py"
    path.write_text("def first(fn):\n    fn()\n    fn()\ndef second(fn):\n    fn()\n")
    stats = RepositoryScanner(database).scan(root)
    first, second = "function:dynamic.py#dynamic.first", "function:dynamic.py#dynamic.second"
    target = "unresolved:dynamic.py#fn"
    path.unlink()
    with database.connect() as connection:
        before = connection.total_changes
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM graph_entities WHERE kind='unresolved'"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM graph_links WHERE resolution='unresolved'"
            ).fetchone()[0]
            == 0
        )
        node = unresolved_node(connection, stats.snapshot_id, target, detail=True)
        assert node["id"] == target and node["properties"]["call_site_count"] == 3
        assert node["properties"]["caller_count"] == node["metrics"]["fan_in"] == 2
        edges = unresolved_connections(connection, stats.snapshot_id, [target], "incoming")
        assert {edge["source_id"] for edge in edges} == {first, second}
        sites = {edge["source_id"]: json.loads(edge["evidence_json"]) for edge in edges}
        assert [site["line"] for site in sites[first]] == [2, 3]
        assert [site["call_site_index"] for site in sites[first]] == [0, 1]
        assert sites[second][0]["call_site_index"] == 2
        assert all(site["binding"] == "dynamic" for values in sites.values() for site in values)
        assert unresolved_counts(connection, stats.snapshot_id) == {
            "nodes": 1,
            "connections": 2,
            "call_sites": 3,
        }
        assert unresolved_counts(connection, stats.snapshot_id, [first], "outgoing") == {
            "nodes": 1,
            "connections": 1,
            "call_sites": 2,
        }
        assert unresolved_connections(connection, stats.snapshot_id, [target], "outgoing") == []
        assert unresolved_connections(connection, stats.snapshot_id, [first], "incoming") == []
        assert unresolved_connections(connection, stats.snapshot_id, [], "both") == []
        assert all_unresolved_nodes(connection, stats.snapshot_id)[0]["id"] == target
        assert unresolved_node(connection, stats.snapshot_id, "unresolved:missing.py#fn") is None
        assert connection.total_changes == before
    page = entity_page(
        database, stats.repository_id, kind="unresolved", evidence_state="unresolved", limit=1
    )
    assert page["total_nodes"] == 1 and page["nodes"][0]["id"] == target
    detail = entity_detail(database, stats.repository_id, target)
    assert detail["node"]["properties"]["call_site_count"] == 3
    assert detail["counts"]["connections_total"] == 2
    focused = neighborhood(database, stats.repository_id, first, evidence_state="unresolved")
    assert {node["id"] for node in focused["nodes"]} == {first, target}
    assert len(focused["edges"]) == 1 and len(focused["edges"][0]["evidence"]) == 2


def test_module_initializer_and_lexical_shadowing_keep_distinct_lazy_owners(tmp_path, database):
    root = tmp_path / "owners"
    root.mkdir()
    (root / "util.py").write_text("def target(): return 1\n")
    (root / "client.py").write_text(
        "from util import target\nexternal()\ndef known(): return target()\n"
        "def shadow(target): return target()\n"
    )
    stats = RepositoryScanner(database).scan(root)
    with database.connect() as connection:
        known = connection.execute(
            "SELECT target_id FROM graph_connections WHERE source_id='function:client.py#client.known' AND relationship_type='calls'"
        ).fetchall()
        assert [row[0] for row in known] == ["function:util.py#util.target"]
        initial = unresolved_connections(
            connection, stats.snapshot_id, ["module:client.py"], "outgoing"
        )
        shadow = unresolved_connections(
            connection, stats.snapshot_id, ["function:client.py#client.shadow"], "outgoing"
        )
        assert [edge["target_id"] for edge in initial] == ["unresolved:client.py#external"]
        assert [edge["target_id"] for edge in shadow] == ["unresolved:client.py#target"]
        assert unresolved_counts(connection, stats.snapshot_id) == {
            "nodes": 2,
            "connections": 2,
            "call_sites": 2,
        }


def test_thousands_of_unknown_targets_do_not_create_thousands_of_graph_rows(tmp_path, database):
    root = tmp_path / "many-unknowns"
    root.mkdir()
    (root / "dynamic.py").write_text(
        "def run(api):\n" + "".join(f"    api.method_{index}()\n" for index in range(2000))
    )
    scanner = RepositoryScanner(database)
    stats = scanner.scan(root)
    with database.connect() as connection:
        rows = connection.execute("SELECT COUNT(*) FROM graph_entities").fetchone()[0]
        links = connection.execute("SELECT COUNT(*) FROM graph_links").fetchone()[0]
        assert rows < 10 and links < 10
        references = json.loads(
            connection.execute(
                "SELECT properties_json FROM graph_entities WHERE entity_id='function:dynamic.py#dynamic.run'"
            ).fetchone()[0]
        )
        assert references["unresolved_call_count"] == references["unresolved_target_count"] == 2000
        assert references["unresolved_call_sites"] == list(range(2000))
        assert unresolved_counts(connection, stats.snapshot_id) == {
            "nodes": 2000,
            "connections": 2000,
            "call_sites": 2000,
        }
    assert scanner.scan(root).snapshot_id == stats.snapshot_id
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM graph_entities").fetchone()[0] == rows
        assert connection.execute("SELECT COUNT(*) FROM graph_links").fetchone()[0] == links


def test_unknown_references_are_complete_on_insert_without_interface_duplication(
    tmp_path, database, monkeypatch
):
    root = tmp_path / "seeded"
    root.mkdir()
    (root / "dynamic.py").write_text(
        "external()\ndef known(): return 1\n"
        "def run(api):\n    api.first()\n    api.first()\n    return known()\n"
    )
    stats = RepositoryScanner(database).scan(root)
    resolved = []
    original = edges.resolve_call

    def resolve_once(file, call, caller, index):
        resolved.append((file["path"], call["line"], call["target"]))
        return original(file, call, caller, index)

    monkeypatch.setattr(edges, "resolve_call", resolve_once)
    with database.transaction() as connection:
        statements = (
            """CREATE TEMP TRIGGER complete_lazy_references BEFORE INSERT ON graph_entities
            WHEN NEW.entity_id IN ('module:dynamic.py','function:dynamic.py#dynamic.run')
            AND json_extract(NEW.properties_json,'$.unresolved_call_count') IS NOT
                CASE NEW.kind WHEN 'module' THEN 1 ELSE 2 END
            BEGIN SELECT RAISE(ABORT,'Lazy references must be complete at insertion'); END""",
            """CREATE TEMP TRIGGER no_lazy_row_growth BEFORE UPDATE OF properties_json ON graph_entities
            WHEN json_extract(NEW.properties_json,'$.unresolved_call_sites') IS NOT
                 json_extract(OLD.properties_json,'$.unresolved_call_sites')
            BEGIN SELECT RAISE(ABORT,'Lazy references cannot grow an inserted row'); END""",
            """CREATE TEMP TRIGGER interfaces_are_not_callers BEFORE INSERT ON graph_entities
            WHEN NEW.kind='interface' AND json_type(NEW.properties_json,'$.unresolved_call_sites') IS NOT NULL
            BEGIN SELECT RAISE(ABORT,'Interfaces must not duplicate implementation call sites'); END""",
        )
        for statement in statements:
            connection.execute(statement)
        sync_knowledge(connection, stats.snapshot_id, force=True)
        assert unresolved_counts(connection, stats.snapshot_id) == {
            "nodes": 2,
            "connections": 2,
            "call_sites": 3,
        }
        assert (
            connection.execute(
                "SELECT target_id FROM graph_connections WHERE "
                "source_id='function:dynamic.py#dynamic.run' AND relationship_type='calls'"
            ).fetchone()[0]
            == "function:dynamic.py#dynamic.known"
        )
    assert len(resolved) == len(set(resolved)) == 4

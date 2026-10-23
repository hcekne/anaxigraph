"""Typed graph calls follow parser bindings without inventing runtime dispatch."""

from anaxigraph.knowledge_unresolved import unresolved_connections
from anaxigraph.scanner import RepositoryScanner


def _scan(tmp_path, database, files):
    root = tmp_path / "calls"
    for path, content in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    stats = RepositoryScanner(database).scan(root)
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT source_id,target_id,resolution,confidence FROM graph_connections "
            "WHERE snapshot_id=? AND relationship_type='calls'",
            (stats.snapshot_id,),
        ).fetchall()
        ids = [
            row[0]
            for row in connection.execute(
                "SELECT entity_id FROM graph_entities WHERE snapshot_id=?", (stats.snapshot_id,)
            )
        ]
        lazy = unresolved_connections(connection, stats.snapshot_id, ids, "outgoing")
    return [dict(row) for row in rows] + lazy


def _target(edges, source):
    return {edge["target_id"] for edge in edges if edge["source_id"] == source}


def test_python_relative_aliases_nested_calls_and_parameter_shadowing(tmp_path, database):
    edges = _scan(
        tmp_path,
        database,
        {
            "pkg/__init__.py": "from .util import target\ntarget()\n",
            "pkg/util.py": "def target(): return 1\n",
            "pkg/core.py": (
                "from .util import target as imported\n"
                "def entry():\n    def nested(): return imported()\n    nested()\n    return imported()\n"
                "def shadow(imported): return imported()\n"
                "def default(value=imported()): return value\n"
            ),
        },
    )
    target = "function:pkg/util.py#pkg.util.target"
    assert target in _target(edges, "function:pkg/core.py#pkg.core.entry.nested")
    assert "function:pkg/core.py#pkg.core.entry.nested" in _target(
        edges, "function:pkg/core.py#pkg.core.entry"
    )
    assert target not in _target(edges, "function:pkg/core.py#pkg.core.shadow")
    assert target in _target(edges, "module:pkg/core.py")
    assert target not in _target(edges, "function:pkg/core.py#pkg.core.default")
    assert target in _target(edges, "module:pkg/__init__.py")


def test_python_receiver_links_are_inferred_and_static_parameters_unresolved(tmp_path, database):
    edges = _scan(
        tmp_path,
        database,
        {
            "service.py": (
                "class Adapter:\n    def impl(self): return 1\n"
                "    def call(self): return self.impl()\n"
                "    @staticmethod\n    def static(impl): return impl()\n"
            )
        },
    )
    edge = next(e for e in edges if e["source_id"] == "function:service.py#service.Adapter.call")
    assert edge["target_id"] == "function:service.py#service.Adapter.impl"
    assert edge["resolution"] == "inferred" and edge["confidence"] < 1
    assert all(
        e["resolution"] == "unresolved"
        for e in edges
        if e["source_id"] == "function:service.py#service.Adapter.static"
    )


def test_python_ambiguous_package_aliases_are_not_guessed(tmp_path, database):
    edges = _scan(
        tmp_path,
        database,
        {
            "pkg/core.py": "from pkg.util import target\ndef run(): return target()\n",
            "pkg/util.py": "def target(): return 1\n",
            "src/pkg/util.py": "def target(): return 2\n",
        },
    )
    calls = [e for e in edges if e["source_id"] == "function:pkg/core.py#pkg.core.run"]
    assert len(calls) == 1 and calls[0]["resolution"] == "unresolved"


def test_typescript_named_default_namespace_and_reexports_resolve(tmp_path, database):
    edges = _scan(
        tmp_path,
        database,
        {
            "web/service.ts": "export function original(){return 1;} export default function main(){return 2;}",
            "web/barrel.ts": 'export { original as renamed } from "./service";',
            "web/client.tsx": (
                'import entry, {original as execute} from "./service"; '
                'import {renamed} from "./barrel"; import * as service from "./service"; '
                "export const App=()=> <div>{execute()}</div>; "
                "export function run(){execute();entry();renamed();service.original();} "
                "export function shadow(execute){return execute();}"
            ),
        },
    )
    original = "function:web/service.ts#web.service.original"
    assert _target(edges, "function:web/client.tsx#web.client.run") == {
        original,
        "function:web/service.ts#web.service.main",
    }
    assert original in _target(edges, "function:web/client.tsx#web.client.App")
    assert original not in _target(edges, "function:web/client.tsx#web.client.shadow")


def test_javascript_same_line_functions_keep_their_own_calls(tmp_path, database):
    edges = _scan(
        tmp_path,
        database,
        {
            "web/local.js": "function one(){return 1;} function two(){return 2;} const a=()=>one(); const b=()=>two();",
        },
    )
    assert _target(edges, "function:web/local.js#web.local.a") == {
        "function:web/local.js#web.local.one"
    }
    assert _target(edges, "function:web/local.js#web.local.b") == {
        "function:web/local.js#web.local.two"
    }


def test_commonjs_bindings_are_lexical_and_dynamic_imports_stay_unresolved(tmp_path, database):
    edges = _scan(
        tmp_path,
        database,
        {
            "web/a.js": "exports.run=()=>1;",
            "web/b.js": "exports.run=()=>2;",
            "web/client.js": (
                'function first(){const provider=require("./a");return provider.run();}'
                'function second(){const provider=require("./b");return provider.run();}'
                'const promise=import("./a"); function unknown(){return promise.run();}'
            ),
        },
    )
    assert "function:web/a.js#web.a.run" in _target(
        edges, "function:web/client.js#web.client.first"
    )
    assert "function:web/b.js#web.b.run" not in _target(
        edges, "function:web/client.js#web.client.first"
    )
    assert "function:web/b.js#web.b.run" in _target(
        edges, "function:web/client.js#web.client.second"
    )
    assert all(
        e["resolution"] == "unresolved"
        for e in edges
        if e["source_id"] == "function:web/client.js#web.client.unknown"
    )


def test_typescript_type_declarations_are_not_invented_runtime_callees(tmp_path, database):
    edges = _scan(
        tmp_path,
        database,
        {
            "web/types.ts": "export interface Contract { value:string; } export type Alias=Contract;",
            "web/client.ts": 'import {Contract,Alias} from "./types"; function uncertain(){Contract();Alias();}',
        },
    )
    calls = [e for e in edges if e["source_id"] == "function:web/client.ts#web.client.uncertain"]
    assert len(calls) == 2 and all(e["resolution"] == "unresolved" for e in calls)

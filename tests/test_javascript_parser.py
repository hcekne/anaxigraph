from __future__ import annotations

import json
from pathlib import Path

from anaxigraph.analyzers.javascript import JavaScriptAnalyzer, TypeScriptAnalyzer
from anaxigraph.analyzers.javascript_parser import parse_source
from anaxigraph.analyzers.javascript_workspace import extract_workspace_config
from anaxigraph.analyzers.text import TextAnalyzer
from anaxigraph.config import SemanticConfig
from anaxigraph.history_discovery import plan_invalidations
from anaxigraph.ir import analysis_metadata
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_module_intrinsic import _module_inputs
from anaxigraph.semantic_requests import SemanticEvidenceService
from anaxigraph.storage import AnaxiIndex


def test_javascript_parser_extracts_module_contracts_and_modern_reference_forms():
    source = """// Browser entry point
import main, { load as fetchLoad } from './api.js';
import * as utils from './utils.js';
import './setup.js';
export { name as renamed } from './names.js';
export * from './extra.js';
const legacy = require('./legacy.cjs');
const lazy = import('./lazy.js');
const computed = import(`./${name}.js`);
export class Service { method(value) { if (value) return utils.run(value); } }
export function helper() { return fetchLoad(); }
export const App = () => <main>{main}</main>;
module.exports.worker = () => legacy.run();
router.get('/items', helper);
"""

    result = JavaScriptAnalyzer().analyze("web/App.jsx", source)
    references = {
        (item.target, item.relationship_type, item.reference_form) for item in result.dependencies
    }
    symbols = {(item.name, item.symbol_type, item.visibility) for item in result.symbols}

    assert result.parse_status == "parsed"
    assert result.analyzer == "builtin-javascript-tree-sitter"
    assert result.metadata["parser"]["engine"] == "tree-sitter"
    assert result.metadata["parser"]["grammar_abi"] > 0
    assert {"renamed", "Service", "helper", "App", "worker"} <= set(result.exports)
    assert ("./names.js", "exports", "static") in references
    assert ("./extra.js", "exports", "static") in references
    assert ("./legacy.cjs", "imports", "commonjs") in references
    assert ("./lazy.js", "imports", "dynamic_literal") in references
    assert any(item.reference_form == "dynamic_expression" for item in result.dependencies)
    assert ("App", "react_component", "public") in symbols
    assert ("GET /items", "api_endpoint", "public") in symbols
    assert all(item.start_line > 0 and item.end_line >= item.start_line for item in result.symbols)


def test_parsed_source_retains_the_tree_that_owns_its_nodes():
    parsed = parse_source("javascript", "export const value = 1;\n")

    assert parsed.tree.root_node == parsed.root
    assert parsed.root.type == "program"


def test_parser_handles_the_real_dashboard_without_native_point_access():
    root = Path(__file__).parents[1]
    path = root / "src/anaxigraph/dashboard/finding-controller.js"

    result = JavaScriptAnalyzer().analyze(
        path.relative_to(root).as_posix(),
        path.read_text(encoding="utf-8"),
    )

    assert result.parse_status == "parsed"
    assert len(result.dependencies) > 20


def test_javascript_structural_hash_ignores_comments_but_retains_literals():
    analyzer = JavaScriptAnalyzer()
    first = analyzer.analyze("module.js", "// first\nexport const value = 'one';\n")
    comment = analyzer.analyze("module.js", "// second\nexport const value = 'one';\n")
    literal = analyzer.analyze("module.js", "// second\nexport const value = 'two';\n")

    assert first.structural_hash == comment.structural_hash
    assert first.structural_hash != literal.structural_hash
    assert first.lines_of_code == 1
    assert first.comment_lines == 1


def test_parser_recovery_keeps_unaffected_facts_and_explicit_diagnostics():
    result = TypeScriptAnalyzer().analyze(
        "module.ts",
        "export function stable() { return 1; }\nexport function broken( {\n",
    )

    assert result.parse_status == "parse_error"
    assert result.parse_error and "Tree-sitter recovered" in result.parse_error
    assert any(item.name == "stable" and item.visibility == "public" for item in result.symbols)
    assert result.metadata["parse_diagnostics"][0]["kind"] == "error"
    assert result.analyzer != "builtin-js-lexer"


def test_typescript_parser_reports_syntax_contracts_without_type_checker_claims():
    source = """import type { Runner } from './runner';
export interface Item extends Base { id: ID }
export type ID<T = string> = T;
export enum Mode { Fast }
export namespace Utils { export const x = 1; }
@sealed
export default class Service<T> implements Runner {
  async run(value: T): Promise<T> { return value; }
}
"""

    result = TypeScriptAnalyzer().analyze("src/service.ts", source)
    symbols = {(item.name, item.symbol_type) for item in result.symbols}
    dependencies = {
        (item.target, item.relationship_type, item.reference_form) for item in result.dependencies
    }
    facts = {item.fact for item in result.evidence_facts}

    assert result.analyzer == "builtin-typescript-tree-sitter"
    assert set(result.exports) == {"Item", "ID", "Mode", "Utils", "default"}
    assert {("Item", "interface"), ("ID", "type_alias"), ("Mode", "enum")} <= symbols
    assert ("Utils", "namespace") in symbols
    assert ("./runner", "imports", "type_only") in dependencies
    assert ("symbol:Base", "extends", "type_only") in dependencies
    assert ("./runner", "extends", "type_only") in dependencies
    assert {"annotations", "decorators", "generics", "inheritance", "types"} <= facts
    assert any(
        "not type-checker results" in item for item in result.analyzer_capabilities.limitations
    )


def test_type_only_reexports_and_anonymous_default_functions_remain_explicit():
    typescript = TypeScriptAnalyzer().analyze(
        "types.ts",
        "export type { Contract } from './contracts';\n"
        "export { type Shape, value as renamed } from './mixed';\n",
    )
    javascript = JavaScriptAnalyzer().analyze("component.jsx", "export default () => <main />;\n")

    references = {
        (item.target, item.reference_form, item.names) for item in typescript.dependencies
    }
    assert ("./contracts", "type_only", ("Contract",)) in references
    assert ("./mixed", "type_only", ("Shape",)) in references
    assert ("./mixed", "static", ("value",)) in references
    assert any(
        item.name == "default" and item.symbol_type == "react_component"
        for item in javascript.symbols
    )


def test_imported_inheritance_and_class_field_methods_link_to_the_imported_module():
    result = TypeScriptAnalyzer().analyze(
        "service.ts",
        "import { Base as FrameworkBase } from './framework';\n"
        "export class Service extends FrameworkBase {\n"
        "  handler = async (value: string): Promise<string> => value;\n"
        "  #secret = () => 1;\n"
        "}\n",
    )

    assert any(
        item.target == "./framework" and item.relationship_type == "extends"
        for item in result.dependencies
    )
    assert any(
        item.name == "handler" and item.symbol_type == "method" and item.visibility == "public"
        for item in result.symbols
    )
    assert any(item.name == "#secret" and item.visibility == "private" for item in result.symbols)


def test_jsonc_workspace_projection_is_bounded_and_deterministic():
    config = extract_workspace_config(
        "tsconfig.app.json",
        """{
          // Compiler-only aliases; AnaxiGraph never runs tsc.
          "compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*",],},},
          "references": [{"path": "../shared"}],
        }""",
    )

    assert config == {
        "kind": "typescript_config",
        "extends": None,
        "base_url": ".",
        "paths": {"@/*": ["src/*"]},
        "references": ["../shared"],
    }


def test_typescript_project_references_are_indexed_without_running_the_build():
    result = TextAnalyzer().analyze(
        "apps/web/tsconfig.json",
        '{"references": [{"path": "../../packages/shared"}]}',
    )

    assert result.metadata["javascript_workspace"]["references"] == ["../../packages/shared"]
    assert [
        (item.target, item.relationship_type, item.evidence) for item in result.dependencies
    ] == [
        (
            "../../packages/shared",
            "references",
            'TypeScript project reference "../../packages/shared"',
        )
    ]


def test_workspace_configuration_change_invalidates_carried_javascript_relationships():
    text = TextAnalyzer()
    typescript = TypeScriptAnalyzer()
    old_config = text.analyze(
        "tsconfig.json",
        '{"compilerOptions": {"paths": {"@/*": ["src/*"]}}}',
    )
    new_config = text.analyze(
        "tsconfig.json",
        '{"compilerOptions": {"paths": {"@/*": ["lib/*"]}}}',
    )
    source = typescript.analyze("src/main.ts", "import api from '@/api';\n")

    def stored(path, analysis):
        return {
            "path": path,
            "metadata_json": json.dumps(
                analysis_metadata(analysis, analysis_version=5, configured_aliases={})
            ),
            "symbols": [],
        }

    plan = plan_invalidations(
        [
            ("tsconfig.json", new_config, "content_changed", True),
            ("src/main.ts", source, "carried_forward", False),
        ],
        {
            "tsconfig.json": stored("tsconfig.json", old_config),
            "src/main.ts": stored("src/main.ts", source),
        },
    )

    assert plan.reasons["tsconfig.json"] == "content_changed"
    assert plan.reasons["src/main.ts"] == "resolver_context_changed"
    assert "src/main.ts" in plan.relationship_sources


def test_semantic_cache_identity_includes_the_analyzer_contract():
    module = {
        "artifact_id": 1,
        "file_fact_id": 2,
        "language": "typescript",
        "analyzer": "builtin-typescript-tree-sitter",
        "structural_hash": "same-source-shape",
        "public_interfaces": ["Service"],
        "symbols": [],
        "analysis_contract": {
            "analyzer_version": "1",
            "capability_fingerprint": "first",
            "parse_status": "parsed",
        },
    }
    changed = {
        **module,
        "analysis_contract": {
            **module["analysis_contract"],
            "analyzer_version": "2",
            "capability_fingerprint": "second",
        },
    }

    first = _module_inputs("service.ts", module, {}, SemanticConfig())
    second = _module_inputs("service.ts", changed, {}, SemanticConfig())

    assert first.input_hash != second.input_hash


def test_scanner_resolves_tsconfig_workspace_ambiguous_and_dynamic_evidence(
    tmp_path: Path,
    database: AnaxiIndex,
):
    root = tmp_path / "workspace"
    (root / "src").mkdir(parents=True)
    (root / "apps" / "web").mkdir(parents=True)
    (root / "shared").mkdir(parents=True)
    (root / "packages" / "core" / "src").mkdir(parents=True)
    (root / "duplicates" / "core" / "src").mkdir(parents=True)
    (root / "src" / "api.ts").write_text("export const api = 1;\n", encoding="utf-8")
    (root / "src" / "choice.ts").write_text("export const choice = 1;\n", encoding="utf-8")
    (root / "src" / "choice.tsx").write_text(
        "export const Choice = () => <p />;\n", encoding="utf-8"
    )
    for directory in (root / "packages" / "core", root / "duplicates" / "core"):
        (directory / "package.json").write_text(
            json.dumps({"name": "@acme/core", "types": "src/index.ts"}), encoding="utf-8"
        )
        (directory / "src" / "index.ts").write_text("export const core = 1;\n", encoding="utf-8")
    (root / "tsconfig.json").write_text(
        json.dumps({"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*"]}}}),
        encoding="utf-8",
    )
    (root / "tsconfig.base.json").write_text(
        json.dumps({"compilerOptions": {"paths": {"~shared/*": ["shared/*"]}}}),
        encoding="utf-8",
    )
    (root / "apps" / "web" / "tsconfig.json").write_text(
        json.dumps({"extends": "../../tsconfig.base.json"}), encoding="utf-8"
    )
    (root / "shared" / "util.ts").write_text("export const shared = 1;\n", encoding="utf-8")
    (root / "apps" / "web" / "feature.ts").write_text(
        "import {shared} from '~shared/util';\nexport const feature = shared;\n",
        encoding="utf-8",
    )
    (root / "src" / "main.ts").write_text(
        "import {api} from '@/api';\n"
        "import choice from './choice';\n"
        "import {core} from '@acme/core';\n"
        "import missing from '@/missing';\n"
        "import express from 'express';\n"
        "const path = './api'; import(path);\n",
        encoding="utf-8",
    )

    stats = RepositoryScanner(database).scan(root)
    detail = database.file_details(stats.repository_id, "src/main.ts")
    assert detail is not None
    rows = detail["relationships"]
    by_original = {
        original: row for row in rows for original in row["metadata"].get("original_targets", [])
    }

    assert by_original["@/api"]["target_path"] == "src/api.ts"
    assert by_original["@/api"]["metadata"]["resolution_provenance"] == [
        "tsconfig_paths:tsconfig.json:@/*"
    ]
    assert by_original["./choice"]["resolution_status"] == "ambiguous_internal"
    assert by_original["./choice"]["candidate_paths"] == ["src/choice.ts", "src/choice.tsx"]
    assert by_original["@acme/core"]["resolution_status"] == "ambiguous_internal"
    assert by_original["@/missing"]["resolution_status"] == "unresolved_internal"
    assert by_original["express"]["resolution_status"] == "external"
    assert next(row for row in rows if row["resolution_status"] == "dynamic")[
        "target_external"
    ].startswith("dynamic:")
    quality = database.overview(stats.repository_id)["graph_quality"]
    assert quality["parser_files"] == 8
    assert quality["dynamic"] == 1
    assert quality["status"] == "partial"

    request = SemanticEvidenceService(database)._intrinsic_request(
        {
            "scope_key": "src/main.ts",
            "snapshot_id": stats.snapshot_id,
            "artifact_id": detail["file"]["artifact_id"],
            "repository_id": stats.repository_id,
            "metadata": {},
        },
        root,
    )
    contract = request["deterministic_facts"]["analysis_contract"]
    assert contract["analyzer"] == "builtin-typescript-tree-sitter"
    assert contract["parse_status"] == "parsed"
    assert contract["capabilities"]["fingerprint"] == TypeScriptAnalyzer.capabilities.fingerprint
    assert any(
        row["resolution_provenance"] == ["tsconfig_paths:tsconfig.json:@/*"]
        for row in request["deterministic_facts"]["relationships"]
    )
    inherited = database.file_details(stats.repository_id, "apps/web/feature.ts")
    assert inherited is not None
    assert inherited["relationships"][0]["target_path"] == "shared/util.ts"
    assert inherited["relationships"][0]["metadata"]["resolution_provenance"] == [
        "tsconfig_paths:tsconfig.base.json:~shared/*"
    ]


def test_scanner_resolves_package_exports_imports_and_project_references(
    tmp_path: Path,
    database: AnaxiIndex,
):
    root = tmp_path / "workspace"
    (root / "app" / "src").mkdir(parents=True)
    (root / "packages" / "shared" / "src").mkdir(parents=True)
    (root / "app" / "package.json").write_text(
        json.dumps({"private": True, "imports": {"#api": "./src/api.ts"}}),
        encoding="utf-8",
    )
    (root / "app" / "src" / "api.ts").write_text("export const api = 1;\n", encoding="utf-8")
    (root / "app" / "src" / "main.ts").write_text(
        "import {api} from '#api';\n"
        "import {feature} from '@acme/shared/feature';\n"
        "export const main = api + feature;\n",
        encoding="utf-8",
    )
    (root / "app" / "tsconfig.json").write_text(
        json.dumps({"references": [{"path": "../packages/shared"}]}), encoding="utf-8"
    )
    (root / "packages" / "shared" / "package.json").write_text(
        json.dumps(
            {
                "name": "@acme/shared",
                "exports": {"./*": "./src/*.ts"},
            }
        ),
        encoding="utf-8",
    )
    (root / "packages" / "shared" / "tsconfig.json").write_text("{}\n", encoding="utf-8")
    (root / "packages" / "shared" / "src" / "feature.ts").write_text(
        "export const feature = 2;\n", encoding="utf-8"
    )

    stats = RepositoryScanner(database).scan(root)
    source = database.file_details(stats.repository_id, "app/src/main.ts")
    project = database.file_details(stats.repository_id, "app/tsconfig.json")
    assert source is not None and project is not None
    source_targets = {
        row["metadata"]["original_targets"][0]: row for row in source["relationships"]
    }

    assert source_targets["#api"]["target_path"] == "app/src/api.ts"
    assert source_targets["#api"]["metadata"]["resolution_provenance"] == [
        "package_imports:app/package.json:#api"
    ]
    assert source_targets["@acme/shared/feature"]["target_path"] == (
        "packages/shared/src/feature.ts"
    )
    assert source_targets["@acme/shared/feature"]["metadata"]["resolution_provenance"] == [
        "workspace_package:packages/shared/package.json:@acme/shared"
    ]
    assert project["relationships"][0]["target_path"] == "packages/shared/tsconfig.json"
    assert project["relationships"][0]["metadata"]["resolution_provenance"] == ["path"]

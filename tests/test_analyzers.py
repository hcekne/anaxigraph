from __future__ import annotations

from dataclasses import replace

from anaxigraph.analyzers.javascript import JavaScriptAnalyzer
from anaxigraph.analyzers.python import PythonAnalyzer
from anaxigraph.analyzers.text import TextAnalyzer
from anaxigraph.ir import IR_SCHEMA_VERSION
from anaxigraph.ir_conformance import validate_analysis


def test_python_ast_extracts_symbols_imports_calls_and_stable_structural_hash():
    analyzer = PythonAnalyzer()
    source = '''"""Module purpose."""
import httpx as client
from .models import User

class Service:
    def fetch(self, user: User) -> str:
        if user.active:
            return client.get(user.url).text
        return ""
'''
    changed_comments = source.replace("Module purpose.", "A better explanation.")

    result = analyzer.analyze("backend/app/service.py", source)
    comment_result = analyzer.analyze("backend/app/service.py", changed_comments)

    assert result.structural_hash == comment_result.structural_hash
    assert [(item.symbol_type, item.name) for item in result.symbols] == [
        ("class", "Service"),
        ("method", "fetch"),
    ]
    assert {(item.relationship_type, item.target) for item in result.dependencies} >= {
        ("imports", "httpx"),
        ("imports", ".models"),
        ("calls", "httpx"),
    }
    assert {item.evidence for item in result.dependencies} >= {
        "import httpx as client",
        "from .models import User",
        "client.get(user.url)",
    }
    assert result.complexity > 1


def test_python_evidence_preserves_multiline_and_unicode_ast_offsets():
    result = PythonAnalyzer().analyze(
        "service.py",
        "LABEL = 'å'\nfrom package import (\n    first,\n    second,\n)\n",
    )

    assert result.dependencies[0].evidence == "from package import (     first,     second, )"


def test_javascript_lexer_extracts_imports_components_and_ignores_comment_changes():
    analyzer = JavaScriptAnalyzer()
    source = """// Screen component
import { load } from './api';
export const Dashboard = () => {
  if (load()) return <main>Ready</main>;
  return null;
};
"""
    result = analyzer.analyze("frontend/Dashboard.tsx", source)
    changed = analyzer.analyze(
        "frontend/Dashboard.tsx", source.replace("Screen component", "New docs")
    )

    assert result.structural_hash == changed.structural_hash
    assert any(item.target == "./api" for item in result.dependencies)
    assert any(
        item.symbol_type == "react_component" and item.name == "Dashboard"
        for item in result.symbols
    )
    assert result.complexity > 1


def test_text_analyzer_accepts_jsonc_and_github_actions_yaml():
    analyzer = TextAnalyzer()
    jsonc = analyzer.analyze(
        "tsconfig.json",
        '{\n  // compiler configuration\n  "compilerOptions": {"strict": true,},\n}\n',
    )
    workflow = analyzer.analyze(
        ".github/workflows/ci.yml",
        "name: CI\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest\n",
    )

    assert jsonc.parse_error is None
    assert workflow.parse_error is None


def test_python_analyzer_is_the_reference_ir_implementation():
    analyzer = PythonAnalyzer()
    result = analyzer.analyze(
        "src/example/service.py",
        "import httpx as client\n\ndef fetch():\n    return client.get('/ready')\n",
    )

    assert validate_analysis(analyzer, "src/example/service.py", result) == ()
    assert result.ir_version == IR_SCHEMA_VERSION
    assert result.module_identity is not None
    assert result.module_identity.canonical_name == "src.example.service"
    assert "example.service" in result.module_identity.aliases
    assert result.resolver_context is not None
    assert ("client", "httpx") in result.resolver_context.import_aliases
    assert result.parse_status == "parsed"
    assert result.exports == ["fetch"]
    assert result.symbols[0].visibility == "public"


def test_every_builtin_analyzer_emits_conforming_ir():
    cases = (
        (PythonAnalyzer(), "module.py", "def value():\n    return 1\n"),
        (JavaScriptAnalyzer(), "module.ts", "export function value() { return 1; }\n"),
        (TextAnalyzer(), "module.go", "package module\n\nfunc Value() int { return 1 }\n"),
    )

    for analyzer, path, source in cases:
        result = analyzer.analyze(path, source)
        assert validate_analysis(analyzer, path, result) == ()


def test_conformance_reports_contract_drift_without_language_guessing():
    analyzer = PythonAnalyzer()
    result = analyzer.analyze("module.py", "import dependency\n")
    result.ir_version = "future-ir"
    result.dependencies[0] = replace(result.dependencies[0], confidence=2.0)

    issues = validate_analysis(analyzer, "module.py", result)

    assert {item.field for item in issues} >= {
        "ir_version",
        "dependencies[0].confidence",
    }

from __future__ import annotations

from codeintel.analyzers.javascript import JavaScriptAnalyzer
from codeintel.analyzers.python import PythonAnalyzer
from codeintel.analyzers.text import TextAnalyzer


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
    assert result.complexity > 1


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

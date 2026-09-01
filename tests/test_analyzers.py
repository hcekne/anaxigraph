from __future__ import annotations

from dataclasses import replace

import pytest

from anaxigraph.analyzer_capabilities import CapabilitySupport, capabilities_from_dict
from anaxigraph.analyzers import builtin_registry
from anaxigraph.analyzers.javascript import JavaScriptAnalyzer, TypeScriptAnalyzer
from anaxigraph.analyzers.python import PythonAnalyzer
from anaxigraph.analyzers.text import TextAnalyzer
from anaxigraph.ir import IR_SCHEMA_VERSION
from anaxigraph.ir_conformance import validate_analysis
from anaxigraph.languages import DETECTED_LANGUAGES


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


def test_typescript_parser_extracts_imports_components_and_ignores_comment_changes():
    analyzer = TypeScriptAnalyzer()
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
        (TypeScriptAnalyzer(), "module.ts", "export function value() { return 1; }\n"),
        (TextAnalyzer(), "module.go", "package module\n\nfunc Value() int { return 1 }\n"),
    )

    for analyzer, path, source in cases:
        result = analyzer.analyze(path, source)
        assert validate_analysis(analyzer, path, result) == ()


def test_every_detected_language_has_exactly_one_builtin_analyzer():
    registry = builtin_registry()
    owned = [language for analyzer in registry.analyzers for language in analyzer.languages]

    assert set(owned) == set(DETECTED_LANGUAGES)
    assert len(owned) == len(set(owned))
    assert all(registry.for_language(language) is not None for language in DETECTED_LANGUAGES)


def test_builtin_analyzers_declare_honest_pattern_evidence_capabilities():
    python = PythonAnalyzer.capabilities
    javascript = JavaScriptAnalyzer.capabilities
    typescript = TypeScriptAnalyzer.capabilities
    text = TextAnalyzer.capabilities

    assert python.support_level("symbols") == "deep"
    assert python.support_level("calls") == "structural"
    assert python.support_level("mutation") == "structural"
    assert python.support_level("data_flow") == "unavailable"
    assert javascript.support_level("symbols") == "structural"
    assert javascript.support_level("types") == "unavailable"
    assert typescript.support_level("symbols") == "structural"
    assert typescript.support_level("types") == "structural"
    assert text.support_level("module_identity") == "deep"
    assert text.support_level("complexity") == "heuristic"
    assert text.support_level("symbols") == "unavailable"
    assert len({item.capabilities.fingerprint for item in builtin_registry().analyzers}) == 4


def test_python_reference_analyzer_emits_pattern_neutral_evidence_families():
    result = PythonAnalyzer().analyze(
        "tests/test_worker.py",
        '''"""Worker tests."""
from typing import Generic, TypeVar
import asyncio
import package.service

T = TypeVar("T")

@registry.register
class Worker(Generic[T]):
    """Runs typed work."""

    def __init__(self, value: T):
        self.value = value

    async def run(self) -> T:
        try:
            await asyncio.sleep(0)
            print(self.value)
            return self.value
        except RuntimeError:
            raise ValueError("failed")

def test_worker():
    if Worker(1):
        pass

if __name__ == "__main__":
    test_worker()
''',
    )

    facts = {item.fact for item in result.evidence_facts}
    assert facts >= {
        "annotations",
        "async_behavior",
        "concurrency",
        "constructors",
        "control_flow",
        "decorators",
        "entry_points",
        "error_handling",
        "generics",
        "inheritance",
        "module_documentation",
        "mutation",
        "registrations",
        "side_effects",
        "symbol_documentation",
        "test_relationships",
    }
    assert all(item.subject and item.evidence for item in result.evidence_facts)
    assert validate_analysis(PythonAnalyzer(), "tests/test_worker.py", result) == ()


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

    result = analyzer.analyze("module.py", "VALUE = 1\n")
    result.analyzer_capabilities = replace(
        analyzer.capabilities,
        limitations=(*analyzer.capabilities.limitations, "Unexpected limitation."),
    )
    issues = validate_analysis(analyzer, "module.py", result)
    assert "analyzer_capabilities" in {item.field for item in issues}


def test_capability_declarations_reject_duplicate_facts():
    capabilities = PythonAnalyzer.capabilities
    duplicate = CapabilitySupport("symbols", "structural")

    with pytest.raises(ValueError, match="unique and sorted"):
        replace(capabilities, facts=(*capabilities.facts, duplicate))


def test_persisted_capability_declaration_verifies_its_fingerprint():
    value = PythonAnalyzer.capabilities.as_dict()
    assert capabilities_from_dict(value) == PythonAnalyzer.capabilities

    value["fingerprint"] = "0" * 64
    with pytest.raises(ValueError, match="fingerprint"):
        capabilities_from_dict(value)


def test_registry_rejects_a_capability_declaration_for_another_analyzer():
    class MismatchedPythonAnalyzer(PythonAnalyzer):
        capabilities = replace(PythonAnalyzer.capabilities, analyzer="different-analyzer")

    with pytest.raises(ValueError, match="capability identity"):
        builtin_registry().register(MismatchedPythonAnalyzer())

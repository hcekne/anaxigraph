"""Built-in analyzer registry."""

from anaxigraph.analyzers.base import AnalyzerRegistry
from anaxigraph.analyzers.javascript import JavaScriptAnalyzer, TypeScriptAnalyzer
from anaxigraph.analyzers.python import PythonAnalyzer
from anaxigraph.analyzers.text import TextAnalyzer


def builtin_registry() -> AnalyzerRegistry:
    registry = AnalyzerRegistry()
    registry.register(PythonAnalyzer())
    registry.register(JavaScriptAnalyzer())
    registry.register(TypeScriptAnalyzer())
    registry.register(TextAnalyzer())
    return registry


__all__ = ["AnalyzerRegistry", "builtin_registry"]

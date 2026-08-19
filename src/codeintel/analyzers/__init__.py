"""Built-in analyzer registry."""

from codeintel.analyzers.base import AnalyzerRegistry
from codeintel.analyzers.javascript import JavaScriptAnalyzer
from codeintel.analyzers.python import PythonAnalyzer
from codeintel.analyzers.text import TextAnalyzer


def builtin_registry() -> AnalyzerRegistry:
    registry = AnalyzerRegistry()
    registry.register(PythonAnalyzer())
    registry.register(JavaScriptAnalyzer())
    registry.register(TextAnalyzer())
    return registry


__all__ = ["AnalyzerRegistry", "builtin_registry"]

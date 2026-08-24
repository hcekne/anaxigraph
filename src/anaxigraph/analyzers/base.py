"""Replaceable extraction interfaces and analyzer selection."""

from __future__ import annotations

from typing import Protocol

from anaxigraph.analyzer_capabilities import AnalyzerCapabilities
from anaxigraph.models import FileAnalysis


class LanguageAnalyzer(Protocol):
    name: str
    version: str
    languages: frozenset[str]
    capabilities: AnalyzerCapabilities

    def analyze(self, path: str, content: str) -> FileAnalysis: ...


class AnalyzerRegistry:
    def __init__(self) -> None:
        self._by_language: dict[str, LanguageAnalyzer] = {}

    def register(self, analyzer: LanguageAnalyzer) -> None:
        if (
            analyzer.capabilities.analyzer != analyzer.name
            or analyzer.capabilities.analyzer_version != analyzer.version
        ):
            raise ValueError("analyzer capability identity must match the registered analyzer")
        for language in analyzer.languages:
            self._by_language[language] = analyzer

    def for_language(self, language: str) -> LanguageAnalyzer | None:
        return self._by_language.get(language)

    @property
    def analyzers(self) -> tuple[LanguageAnalyzer, ...]:
        return tuple(dict.fromkeys(self._by_language.values()))

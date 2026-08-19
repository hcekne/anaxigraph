"""Replaceable extraction interfaces and analyzer selection."""

from __future__ import annotations

from typing import Protocol

from anaxigraph.models import FileAnalysis


class LanguageAnalyzer(Protocol):
    name: str
    languages: frozenset[str]

    def analyze(self, path: str, content: str) -> FileAnalysis: ...


class AnalyzerRegistry:
    def __init__(self) -> None:
        self._by_language: dict[str, LanguageAnalyzer] = {}

    def register(self, analyzer: LanguageAnalyzer) -> None:
        for language in analyzer.languages:
            self._by_language[language] = analyzer

    def for_language(self, language: str) -> LanguageAnalyzer | None:
        return self._by_language.get(language)

    @property
    def analyzers(self) -> tuple[LanguageAnalyzer, ...]:
        return tuple(dict.fromkeys(self._by_language.values()))

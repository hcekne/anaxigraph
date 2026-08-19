# Plugin system

Extraction is replaceable at the package boundary. A language analyzer implements:

```python
class LanguageAnalyzer(Protocol):
    name: str
    languages: frozenset[str]

    def analyze(self, path: str, content: str) -> FileAnalysis: ...
```

Register an adapter with `AnalyzerRegistry.register()` and pass that registry to
`RepositoryScanner`. An adapter returns symbols and unresolved dependencies; it does not write SQL
or know about dashboard/MCP types. The graph resolver owns repository-relative linking.

The built-ins are Python AST, a conservative JavaScript/TypeScript lexer, and a safe text/config
fallback. Graphify or Tree-sitter can be added as an analyzer or graph-extractor adapter without
changing persistence consumers.

Coverage adapters likewise return normalized file coverage before persistence. Semantic analysis
uses a JSON-over-stdin command boundary so the operator can choose an LLM/provider without putting
provider SDK behavior into the scanner. The command receives deterministic facts plus bounded
source and must return the documented JSON contract. Semantic execution is disabled by default and
only runs for new or structurally changed files.

Future adapters should preserve three rules:

1. never execute target code during static extraction;
2. attach source, confidence, and evidence to every inferred relationship;
3. keep provider-specific types out of storage and agent APIs.

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
uses one provider-neutral dossier contract. Built-in executors cover a connected coding agent over
AnaxiMCP, OpenAI and Anthropic APIs, non-interactive Codex and Claude CLIs, and a JSON-over-stdin
custom command. The semantic planner, queue, fingerprints, and storage do not depend on provider
SDK types. Executors receive deterministic facts plus bounded source or stored neighbouring
dossiers and return the strict dossier contract. Execution is disabled by default and runs for
missing, structurally changed, context-invalidated, policy-stale, or explicitly expired scopes.

Future adapters should preserve three rules:

1. never execute target code during static extraction;
2. attach source, confidence, and evidence to every inferred relationship;
3. keep provider-specific types out of storage and agent APIs.

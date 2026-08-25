# Coding patterns

This document is the canonical human-readable architecture policy for AnaxiGraph. The
machine-readable thresholds are in [`.anaxigraph.yml`](../.anaxigraph.yml).

Prefer pure functions for hashing, normalization, rule evaluation, and graph transforms. Use
classes only where identity or lifecycle is real: the database handle, analyzer registry, scanner,
and external provider. Keep filesystem, Git, subprocess, database, and network effects behind
their existing modules.

Language analyzers produce neutral records and never persist. Persistence does not import API or
dashboard code. Interfaces call application services; they do not duplicate graph logic. A new
adapter must remove provider conditionals from the scanner rather than add a second analysis path.

Pattern intelligence uses one shared evidence path. Analyzers declare the facts they support and
their depth, then emit generic IR and `AnalyzerFact` evidence. `pattern-target-v1` identifies
symbols, types, modules, subsystems, areas, and the repository without transient row ids or source
lines. `pattern-evidence-v1` projects those facts with graph, coverage, Git, semantic-dossier, and
architecture-map evidence once; every catalog card reuses that projection. Pattern cards must not
branch on a language name or introduce their own AST query.

The versioned declarative card format, 128-pattern bundled baseline, family coverage, and extension
contract are documented in [Pattern catalog](pattern-catalog.md). The shipped count is a baseline,
not a ceiling.

Only sparse, evidence-supported target/card pairs become semantic work. Each selected pair receives
an independently evidenced assessment followed by a separate agent critique that returns the full
corrected result. Both stages use the existing durable semantic queue and runtime-selected executor;
an unchanged map creates no new pattern work.

Only a completed independent critique appears in the current pattern projection. Use the single
bounded query in either direction:

```text
anaxigraph patterns . --target module:src/service.py --sort-by opportunity --json
ANAXIGRAPH_PATTERNS(target="module:src/service.py", sort_by="opportunity")
ANAXIGRAPH_PATTERNS(pattern="strategy", sort_by="conformance")
GET /api/patterns?target=src/service.py&include_evidence=true
```

The default response returns at most 20 compact evaluations and the hard maximum is 100. Filters
cover target, catalog key, hierarchy level, presence, recommendation, minimum score, score sort,
offset, and limit. Detailed score evidence, contradictions, review issues, and competing
interpretations are opt-in. Every row retains provider, runtime model, executor, prompt/schema,
token, cost, confidence, and creation provenance; model identity is descriptive and is never part
of catalog behavior.

The CLI does not create a fresh scan while reading results. With no `--db`, it first matches a
running loopback service by checkout path or canonical Git identity, then queries that authoritative
index. If no matching service is running, it opens the stable per-checkout local index. Pass
`--service-url` or `--db` to choose explicitly; they are mutually exclusive. The JSON response
always includes `index.authority` and the selected service/repository identity or database path.

Treat 40 logical lines per function and 500 source LOC per module as inspection signals. Prefer a
cohesive module over forwarding layers. Add an abstraction only for multiple real implementations
or a demonstrated bug class. Avoid hidden global state and circular dependencies. Changed behavior
requires focused tests; MCP behavior requires a real SDK protocol test.

The analyzed repository is untrusted input. Never import or execute it, follow its symlinks, write
analysis state into it by default, or interpolate its values into a shell. Semantic mapping,
taxonomy formation, pattern evaluation, and independent agent critique complete without a manual
approval gate. They remain recommendations in AnaxiIndex; the product never mutates target code.

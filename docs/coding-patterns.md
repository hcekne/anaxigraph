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

The dashboard's **Patterns** view uses the same projection. Each result keeps the nine scores
visibly separate, shows the finalized critique and runtime provenance, and can pivot directly from
one target to its competing patterns or from one catalog pattern to other evaluated targets.

The CLI does not create a fresh scan while reading results. With no `--db`, it first matches a
running loopback service by checkout path or canonical Git identity, then queries that authoritative
index. If the port unequivocally refuses a connection or a reachable service indexes no matching
repository, it opens the stable per-checkout local index. A timeout, malformed inventory, or other
ambiguous response fails closed instead of silently selecting another index. Pass `--service-url`
or `--db` to choose explicitly; they are mutually exclusive. The JSON response always includes
`index.authority` and the selected service/repository identity or database path.

Candidate selection is explainable through the same four surfaces. It requires one exact catalog
key and reconstructs only that pattern over eligible targets, then compares the result with the
persisted sparse plan. It does not store or regenerate the dense target-by-pattern product:

```text
anaxigraph patterns . --candidates --pattern=strategy --selection=skipped --include-evidence
ANAXIGRAPH_PATTERNS(mode="candidates", pattern="strategy", selection="skipped")
GET /api/patterns/candidates?pattern=strategy&selection=skipped&include_evidence=true
```

Each result says whether the target was selected, its candidate priority, and one explicit reason:
no positive evidence, counter-evidence, below threshold, displaced by the bounded sparse plan, or
plan not yet ready. Optional details expose matched signals, capability gaps, missing evidence, and
the semantic questions associated with the card. The dashboard switches between finalized ratings
and candidate explanations without mixing candidate priority with the nine independent scores.

Run a repeatable calibration against the already-current map with the same CLI and index-authority
selection:

```text
anaxigraph patterns . --calibrate benchmarks/pattern-calibration/anaxigraph.json --json
```

`pattern-calibration-v1` manifests bind expectations to the catalog, score, and review contract
versions. Each case labels relevance and may define accepted presence, recommendation, score-range,
and critic-verdict outcomes. The report keeps candidate precision/recall, rating pass rate, mean
score-range error, confidence Brier score, false-positive causes, and critic disagreement separate,
then groups them by scenario, runtime provider/model, prompt version, and snapshot. A manifest can
set thresholds and require every expected finalized rating; inspect the report's `passed`, `status`,
and per-case `failures` fields in automation.

Calibration labels are regression evidence, not a human approval stage. Mapping and independent
critique still finish autonomously, and a failed or incomplete calibration report does not mutate
the target repository or rewrite its semantic map. The shipped synthetic and real-repository sets
live under `benchmarks/fixtures/pattern-calibration` and `benchmarks/pattern-calibration`.

The same finalized pattern projection contributes to `architecture-decision-v1` inside the normal
agent scope. Placement guidance distinguishes patterns already worth reusing from genuine change
opportunities and retains critic provenance, contracts, invariants, risks, focused tests, and the
snapshot facts to compare after a rescan. Save the returned
`architecture_decision.verification.post_change_baseline`, then pass it back with the same goal:

```text
ANAXIGRAPH_SCOPE(goal="Add provider fallback")
ANAXIGRAPH_SCAN()
ANAXIGRAPH_SCOPE(
  goal="Add provider fallback",
  verification_baseline=<the earlier post_change_baseline>
)
```

The second response includes `architecture-verification-comparison-v2`. It uses
`rescan_required`, `unchanged`, `changed`, or `incomparable` in ordinary language and lists the
module, finding, and reviewed-pattern facts that differ. It also groups bounded structural effects
as introduced, worsened, improved, resolved, or pre-existing. Those labels describe the indexed
signal: “resolved” does not mean “proved correct,” and a changed score does not by itself mean the
code is better. The focused tests and the intended outcome still decide that.

The CLI accepts either that nested baseline or the whole earlier scope response:

```bash
anaxigraph scope . --goal "Add provider fallback" --json > before.json
anaxigraph update . --json
anaxigraph scope . --goal "Add provider fallback" \
  --verification-baseline before.json --json
```

Consolidation keeps supporting and contrary evidence. Dead-code advice is stricter: a semantic
suggestion needs a same-granularity deterministic candidate, and deterministic module candidates
require trusted graph resolution plus analyzer support for entry points and registrations. A
`dead_code` rule may list repository-relative `entry_points` globs; configured, conventional, or
detected entry points are suppressed. No result is presented as automatic permission to merge,
split, or delete code.

For a selected oversized file, that same scope response may include
`architecture_decision.decomposition`. A concrete split appears only when the current dossier
names separate responsibilities, argues both for and against the split, and those jobs map
unambiguously to real symbols. The packet names callers, contracts, focused tests, destination
evidence, and a bounded extraction order. Size by itself returns no split, and stale, cohesive, or
ambiguous evidence tells the agent to keep the file together or gather better evidence.

Treat 40 logical lines per function and 500 source LOC per module as inspection signals. Prefer a
cohesive module over forwarding layers. Add an abstraction only for multiple real implementations
or a demonstrated bug class. Avoid hidden global state and circular dependencies. Changed behavior
requires focused tests; MCP behavior requires a real SDK protocol test.

The analyzed repository is untrusted input. Never import or execute it, follow its symlinks, write
analysis state into it by default, or interpolate its values into a shell. Semantic mapping,
taxonomy formation, pattern evaluation, and independent agent critique complete without a manual
approval gate. They remain recommendations in AnaxiIndex; the product never mutates target code.

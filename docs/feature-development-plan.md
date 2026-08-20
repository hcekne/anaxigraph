# AnaxiGraph consecutive development plan

**Roadmap version:** 2.5

**Updated:** 20 August 2026

**Execution rule:** one phase is active at a time; the next phase does not begin until the current
phase's exit gate is met.

## Executive decision

The external review is directionally correct, and its priority order is a useful correction to the
previous roadmap. AnaxiGraph now has three credible differentiators:

1. a temporal architecture record rather than only a current-state graph;
2. explicit provenance for resolved, ambiguous, unresolved, and external relationships; and
3. agent-funded semantic understanding, where a connected coding agent uses its own context and
   tokens and writes a validated dossier back to AnaxiIndex.

Those strengths will not matter if a first history import takes an hour, a repository's primary
language falls through to a lexical fallback, or installation feels like a small deployment
project. The near-term roadmap therefore prioritizes first-run performance, signal quality,
distribution, and language depth before adding more visible intelligence features.

The recommendations are adopted with seven important refinements:

- **Delta-driven history comes before batched Git reads.** Profiling says analysis of unchanged
  files is currently the dominant cost. `git cat-file --batch` remains a later optimization for
  reading the changed blobs, not the first intervention.
- **Findings are not deleted to make the UI quiet.** AnaxiIndex should retain the complete evidence
  ledger while the product presents a small ranked attention queue and places low-severity
  diagnostics behind an explicit view.
- **The 500-line rule is a ratchet, not an excuse to freeze the repository or create arbitrary
  499-line fragments.** New oversized modules and growth of existing oversized modules are blocked
  immediately. Existing exceptions are then removed in the phases that touch their responsibilities.
- **Tracked hook configuration and CI are the enforcement mechanism.** Files under `.git/hooks/`
  are local and cannot be versioned. The repository will ship a `.pre-commit-config.yaml`, a
  deterministic size/architecture checker, and the same required CI checks.
- **Tree-sitter support is claimed language by language.** Installing a grammar is not equivalent
  to supporting a language. A language is “parser-backed” only after symbols, imports, exports,
  calls, inheritance, source locations, error behavior, and fixtures meet the support contract.
- **A gate must be failable by one change.** The temporal work is therefore split into Phase 1a
  (delta discovery on the existing schema) and Phase 1b (immutable facts plus snapshot deltas).
  Landing a new algorithm, a new schema, a migration, and a large refactor behind a single gate
  would make a wrong frame impossible to attribute. Two smaller gates are more consecutive, not
  less.
- **P0.1 numbers are now measured and ratified.** The committed schema-6 baseline was recorded on
  revision `cd73765` with a deterministic 3,000-file, eight-frame fixture. Exact correctness/work
  counters and same-runner ratios are binding; the recorded server's absolute timings remain
  reference values rather than universal laptop promises.

This document supersedes the previous phase order. Already shipped capabilities are retained, but
unfinished work is now arranged around explicit dependencies and measurable exit gates.

## Product outcome

AnaxiGraph should be the persistent engineering memory and architecture advisor for a repository.
It should help a person or coding agent answer:

1. **What is this system?** See its areas, modules, contracts, relationships, history, and module
   meanings from a repository view down to a symbol.
2. **What deserves attention?** Rank architecture risks by severity, confidence, churn, complexity,
   coverage, and blast radius instead of presenting a wall of threshold violations.
3. **How could the design improve?** Identify repeated responsibilities, misplaced boundaries,
   consolidation opportunities, dead-code candidates, and suitable patterns with evidence and
   counter-evidence.
4. **Where should new functionality go?** Give an agent local precedents, extension points,
   contracts, protected boundaries, affected tests, and a verification plan before it edits code.
5. **Did the change help?** Rescan, compare the relevant architecture facts, resolve or regress
   findings, and retain the decision in repository history.

The product loop remains:

```text
observe -> explain -> decide -> plan -> implement -> rescan -> verify -> remember
```

The promise is not “draw a pretty code graph.” It is:

> Keep AI-accelerated codebases understandable, auditable, and architecturally sound as they
> evolve—without presenting uncertain static or model-derived evidence as fact.

## Current baseline

The values below are the starting point for this roadmap. Performance figures from the external
review must be reproduced by Phase 0 on a committed benchmark fixture before they become release
regression thresholds.

| Area | Current state | Consequence |
|---|---|---|
| Test health | 79 tests passing, Ruff clean, 81.26% total coverage, and 100% coverage of the Phase 0 closure diff | The executable guardrails are green; critical CLI paths still need stronger targeted coverage as their phases begin |
| Relationship evidence | Resolved, ambiguous, unresolved, and external states are persisted and explained | Strong trust foundation; dynamic wiring must continue to be identified as a blind spot |
| Finding priority | Risk, confidence, churn, complexity, coverage, blast radius, and regression contribute to a versioned score | Good ranking exists, but the complete ledger is still too noisy by default |
| Scope payload | Approximately 21.5 KB in the reviewed Go-analyzer scenario | Improved, but token-budget behavior needs continued regression tests |
| Semantic understanding | Durable `module-dossier-v4` records, fingerprint invalidation, leased agent work, provenance, and budget controls | Differentiating foundation; internal seven-mixin composition needs simplification before expansion |
| Parser depth | Python AST plus a regex-oriented JavaScript/TypeScript analyzer; long-tail languages use text heuristics | The product cannot yet make equally strong graph claims for most repositories |
| History benchmark | Measured 3,000-file/eight-frame import: 69.566 seconds, 23,970 blob reads, 23,970 `file_versions` for 3,217 distinct artifact/raw versions, 47,896 relationship rows, and a 49.56 MB vacuumed index | Unchanged source is repeatedly read and snapshot-heavy facts/edges are repeatedly materialized |
| Graph delivery | `/api/graph` can return the full graph in one response | Fine for small loopback use, unsafe for large/team deployments |
| Authentication | No API or MCP authentication | Acceptable only for loopback sidecar mode |
| Installation | A tested `anaxigraph` 0.1.0 wheel and source distribution are public on PyPI; generated Compose, MCP connection, semantic enablement, and agent bootstrap still require separate actions | The distribution-name and package-availability barriers are removed, but there are still too many steps between curiosity and full value |
| Internal module size | Seven first-party implementation modules exceed 500 physical lines; `storage.py` is now a 398-line facade with no size exception | The Phase 1b storage boundary is clean; scanner decomposition remains part of the Phase 1b exit gate |

The current oversized implementation modules are:

| Module | Physical lines at roadmap creation | Planned decomposition phase |
|---|---:|---|
| `src/anaxigraph/dashboard/app.js` | 2,091 | Phase 3b |
| `src/anaxigraph/storage.py` | 1,809 | Phase 1b |
| `src/anaxigraph/scanner.py` | 1,164 | Phase 1b |
| `src/anaxigraph/agent.py` | 934 | Phase 3b |
| `src/anaxigraph/architecture.py` | 780 | Phase 3b |
| `src/anaxigraph/cli.py` | 653 | Phase 3 |
| `src/anaxigraph/api.py` | 616 | Phase 5 |
| `src/anaxigraph/onboarding.py` | 504 | Phase 3 |

Line counts are baselines, not targets. Every listed module must become smaller through cohesive
responsibility extraction; it must not merely be split at line 500.

## Strategic references

We borrow mechanics with evidence, not product identity:

- [Graphify](https://github.com/Graphify-Labs/graphify) demonstrates the adoption value of a
  skill-first install, broad parser-backed extraction, and inspectable edge origins. AnaxiGraph's
  answer is a similarly easy entry path combined with temporal state, finding lifecycle, and
  agent-funded write-back.
- [CodeScene hotspots](https://codescene.com/product/hotspots) reinforce the value of combining
  change frequency with code health. AnaxiGraph already uses that principle in finding priority
  and should extend it into temporal trends and change coupling.
- [Tree-sitter](https://tree-sitter.github.io/tree-sitter/) provides a fast, error-tolerant parser
  foundation across languages. We will place it behind AnaxiGraph's analyzer contract rather than
  leak grammar-specific nodes throughout the product.
- [pre-commit](https://pre-commit.com/) provides a tracked, cross-platform way to install local Git
  hooks. The same checks will run in CI because local hooks are intentionally bypassable.
- Git's [`diff`](https://git-scm.com/docs/git-diff) and later
  [`cat-file --batch`](https://git-scm.com/docs/git-cat-file) provide the primitives for historical
  change discovery and efficient changed-blob reads.
- [GitHub required status checks](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks)
  provide the remote enforcement layer for contributors who do not install or deliberately skip
  local hooks.

Competitive counts and feature claims change. They are directional context, not acceptance
criteria. AnaxiGraph releases are judged against the measurable product and engineering gates in
this document.

## Non-negotiable engineering principles

### Facts, interpretations, and recommendations remain separate

1. **Facts** are deterministic observations: hashes, syntax, symbols, references, Git changes,
   complexity, imported coverage, and analyzer provenance.
2. **Interpretations** are inferred intent, responsibilities, architecture roles, semantic
   similarity, and pattern classification. They carry model/provider/prompt provenance,
   confidence, and evidence.
3. **Recommendations** are reviewable proposals. They carry suitability, benefit, urgency, safety,
   cost, counter-evidence, and lifecycle state. They are never automatic permission to refactor or
   delete code.

### The target repository remains safe

- Scanning is read-only and never executes target code.
- Container mounts remain read-only by default.
- AnaxiIndex lives outside the target repository unless an operator explicitly chooses otherwise.
- Dynamic behavior that static analysis cannot observe is disclosed, not guessed into certainty.
- Semantic source egress is opt-in, scoped, and auditable.

### Temporal work scales with change

The desired complexity is:

```text
initial frame: O(all eligible files)
later frame:   O(changed files + conservatively invalidated dependants)
stored facts:  O(distinct versions and distinct relationship contexts)
```

Snapshot selection, display, and lightweight references may scale with selected frames. Expensive
source reads, parsing, semantic analysis, symbol rows, and edge bundles must not be multiplied by
every unchanged file in every selected frame.

### AnaxiGraph must pass its own architectural standards

- A 500-line maximum is a safety ceiling, not the design target.
- New modules should normally land between 100 and 350 physical lines and own one explainable
  responsibility.
- Interfaces should be explicit; mixin order and hidden shared state are not acceptable extension
  mechanisms for core workflows.
- Storage, analysis, transport, and presentation must communicate through narrow models rather
  than reach through each other's internals.
- Performance and correctness changes begin with a reproducible characterization test.

## Consecutive execution protocol

Only one numbered phase may be `IN PROGRESS`. Within a phase, work items are completed in the
listed order unless an earlier item explicitly says it may be combined with the next migration.

Each phase follows the same delivery loop:

1. reproduce and record its baseline;
2. write characterization and failure tests;
3. document the relevant schema/API/architecture decision;
4. implement the smallest end-to-end slice;
5. migrate existing data/configuration safely;
6. exercise the dashboard, CLI, REST, and MCP surfaces affected by the change;
7. run performance, quality, and security gates;
8. update onboarding and operator documentation;
9. release or tag the coherent slice;
10. mark the phase complete before opening the next phase.

Emergency security or data-loss fixes may interrupt a phase. Unrelated feature work may not.

### When a phase is not converging

An exit gate says when to move on. It does not say when to stop and reconsider. Because execution is
strictly serial, a phase that is not converging blocks the entire remaining roadmap.

There is no calendar budget here; pace is the owner's call. But a gate that is not being met is not
silently extended either. When the evidence says a phase is not converging — the benchmark is not
moving, the fixtures keep contradicting the design, or the scope keeps growing to keep the gate
reachable — record in this document which of these applies:

1. the gate is correct and the work is simply not finished — continue;
2. the gate is too broad — split it, as Phase 1 was split into 1a and 1b;
3. the approach is wrong — replace it and restate the gate;
4. the phase is not worth its cost now — defer it, re-evaluate every downstream dependency, and
   promote only the nearest phase whose entry assumptions still hold.

The point is that the decision is written down, not that it happens on a schedule.

## Master delivery order

| Order | Phase | Primary outcome | Must be complete before |
|---:|---|---|---|
| 0 | Engineering guardrails and reproducible baselines | New work cannot increase internal architectural debt | Any feature phase |
| 1a | Delta-driven temporal discovery | History import stops re-analyzing unchanged files, on today's schema | Any storage change |
| 1b | Immutable facts and snapshot deltas | Stored facts scale with distinct versions rather than selected frames | More history features or broader parsers |
| 2 | Attention signal | Users see a small, actionable, fully accounted queue | Onboarding promotion |
| 3 | One-command local adoption | One command opens a dashboard; a second or option connects an agent | Ecosystem/language marketing |
| 3b | Dashboard/evaluator decomposition and self-analysis | Frontend and core evaluators become maintainable; AnaxiGraph checks itself in CI | Parser expansion |
| 4 | Core parser-backed language platform | JavaScript/TypeScript, Go, Rust, and Java produce honest structural graphs | Broad core-language claims |
| 5 | Team security and graph-scale APIs | Shared deployment is authenticated, bounded, and repository-scoped | Team-install promotion |
| 6 | Architect-grade semantic and pattern advice | Module understanding becomes evidence-backed consolidation, dead-code, pattern, and build guidance | Autonomous workflow expansion |
| 7 | Temporal architecture intelligence | History becomes an explanatory biography, not just replay | Client-facing temporal positioning |
| 8 | Long-tail languages, non-code context, and extensions | Additional languages and operational context join code without weakening evidence semantics | 1.0 scope freeze |
| 9 | 1.0 hardening and community launch | Stable migrations, public contribution paths, website, and support matrix | 1.0 release |

---

# Phase 0 — engineering guardrails and reproducible baselines

**Status:** COMPLETE on 20 August 2026

**Goal:** prevent AnaxiGraph's implementation from becoming the spaghetti code it warns users
about, while producing trustworthy performance and quality baselines for later phases.

## 0.1 Reproduce the baseline

**Status:** COMPLETE on 20 August 2026

Create committed benchmark fixtures and a machine-readable report for:

- the AnaxiGraph repository itself;
- a deterministic synthetic-repository generator with a committed seed and expected manifest that
  produces approximately 3,000 files in a temporary directory, with controlled change rates,
  renames, deletions, and ambiguous imports;
- a mixed-language fixture with Python, JavaScript, TypeScript, Go, Rust, Java, and fallback text;
- a history fixture with at least eight selected frames and known distinct file versions;
- an agent-scope fixture with a stable goal and expected primary files.

Record:

- current scan wall time and peak memory;
- history time per selected frame;
- files discovered, source blobs read, analyzers invoked, and analyses reused;
- distinct artifact/content/structural versions;
- symbol, relationship, relationship-bundle, snapshot, and finding row counts;
- index size before and after `VACUUM`;
- `/api/graph` payload bytes and dashboard render time;
- scope payload bytes and estimated tokens;
- test count, total coverage, and coverage of CLI, migration, and history paths.

The repository commits the generator, seed, expected manifest, and compact correctness fixtures—not
3,000 generated files. Benchmarks must print environment metadata and may not fail solely because
one developer's laptop is slower. CI regression gates use ratios or a dedicated stable runner;
correctness counters are exact everywhere.

The committed report is
[`benchmarks/results/baseline-schema6.json`](../benchmarks/results/baseline-schema6.json). It was
generated from clean revision `cd73765` on Linux x86-64, Python 3.11.15, SQLite 3.53.1, and 16
reported CPUs. The synthetic history is capped at 5% changed files in any selected transition and
contains modifications, renames, deletions, additions, interface changes, metadata-only changes,
and ambiguous imports.

| Measurement | Ratified schema-6 baseline |
|---|---:|
| Current AnaxiGraph scan | 92 files · 3,176 ms · 76,947,456-byte peak resident set |
| Synthetic history | 3,000 files · 8 frames · 69,566 ms · 8,695.75 ms/frame |
| Historical source reads | 23,970 blobs · 4,167,430 bytes |
| Analysis work | 3,217 analyzer invocations · 23,753 reused analyses |
| File storage | 23,970 heavy rows · 3,217 distinct artifact/raw versions · 3,216 distinct artifact/structural versions |
| Relationship storage | 47,896 edge rows · no reusable relationship-bundle table |
| Index size | 50,290,744 bytes before compaction · 49,561,600 bytes after `VACUUM` |
| Large graph REST response | 3,000 nodes · 5,924 edges · 3,266,988 bytes · 113.27 ms cold · 83.89 ms warm median |
| Browser render | 511 ms to overview · 89 ms to graph · 3,000 visible nodes, measured in the pinned Playwright container |
| Agent scope | 5,757 bytes · approximately 1,440 tokens · all 8 expected primary candidates, no unexpected primary files |
| Quality baseline | 53 tests · 80.636% total · CLI 51.077% · history 92.593% · storage/migrations 82.738% |

These measurements replace the review's extrapolated 24.7-second/76-file reference throughout the
binding temporal gates below. Benchmark code records host/browser availability explicitly and
falls back to the pinned Playwright container when compatible browser libraries are absent on the
host.

## 0.2 Install tracked commit hooks

**Status:** COMPLETE on 20 August 2026

Add:

- `pre-commit` to the development dependency set;
- `.pre-commit-config.yaml` with pinned hook revisions;
- `scripts/check_module_size.py` for staged-file and whole-repository modes;
- `scripts/check_architecture.py` for package dependency and cycle rules;
- a single documented `uv run pre-commit install --install-hooks` setup command;
- an equivalent CI job that runs the checks against the complete checkout.

Fast pre-commit checks:

- trailing whitespace, final newline, YAML/TOML syntax, and merge-marker checks;
- Ruff lint and formatting validation for changed Python files;
- JavaScript syntax checks for changed dashboard modules;
- staged module-size ratchet;
- forbidden generated/index/credential files;
- architecture dependency/cycle check.

Pre-push or CI checks:

- complete Python tests and coverage;
- Playwright dashboard tests;
- Compose configuration validation;
- schema migration tests from every supported schema version;
- the whole-repository size and architecture checks;
- bounded performance smoke benchmarks.

We do **not** commit a script directly under `.git/hooks/`; Git does not version that directory.
The tracked pre-commit configuration installs the local hook, while required CI checks are the
non-bypassable project policy.

## 0.3 Enforce the module-size ratchet

**Status:** COMPLETE on 20 August 2026

The first-party implementation ceiling is **500 physical lines per module** for `.py`, `.js`,
`.jsx`, `.mjs`, `.ts`, and `.tsx` files. A warning begins at 400 lines. CSS and HTML receive
separate asset-bundle warnings, and tests receive a higher temporary split threshold, but neither
category is invisible to the quality report.

Rules:

1. A new implementation module above 500 lines fails the commit and CI.
2. A module at or below 500 lines may not cross the ceiling.
3. A legacy oversized module may shrink, but any net growth fails.
4. A feature change to a legacy oversized module should extract a cohesive responsibility in the
   same change. A narrowly scoped security/data-loss correction may use a reviewed, expiring
   waiver, but still may not grow the module.
5. Baseline exceptions live in a reviewed data file containing path, baseline count, rationale,
   owner, removal phase, and expiry. Adding a new exception is a separate architecture decision,
   not an inline skip.
6. Generated, vendored, and machine-produced files are excluded only by explicit path policy with
   evidence that they are generated. Migrations and fixtures are not silently exempted.
7. `--no-verify` may bypass a local hook but cannot bypass the required CI check.

**Pre-authorized strategy for the temporal rewrite.** Rule 3 forbids net growth in a legacy
oversized module, and rule 4's waiver covers only a narrowly scoped security or data-loss
correction. A transactional, restartable schema migration must support the old and new read paths
at the same time, so a naive implementation would grow `storage.py` before shrinking it and would
fail this gate on its first commit. That collision is resolved here rather than mid-migration:

> Phases 1a and 1b add no lines to `storage.py` or `scanner.py`. All new temporal code lands in new
> modules from the first commit, dual-path compatibility shims live in the new modules rather than
> the legacy ones, and the legacy modules only shrink as call sites migrate.

This is the intended design anyway. Writing it down converts a foreseeable blocker into a stated
constraint and removes any argument for a waiver during the temporal phases.

The checker should report likely extraction boundaries—classes, top-level functions, route groups,
or query families—so the failure teaches the contributor how to improve the design. It must not
encourage deletion of comments, compressed formatting, or meaningless “part1/part2” files.

## 0.4 Add complementary complexity budgets

**Status:** COMPLETE on 20 August 2026

Line count alone does not prevent spaghetti code. Add ratcheted checks and reports for:

- new functions above 50 physical lines or configured cyclomatic complexity 15;
- new package dependency cycles;
- modules with more than one unrelated responsibility in their architecture dossier;
- growing fan-in/fan-out and unstable public interfaces;
- test coverage regressions, with a target of at least 85% changed-code coverage;
- import-layer violations between storage, analysis, application, transport, and dashboard code.

These thresholds begin as warnings where the repository already violates them, become no-growth
ratchets, and become hard gates after the owning module is refactored. The 500-line ceiling for new
modules is hard from the first Phase 0 commit.

The delivered gate records exact legacy function and coupling baselines in
`quality/maintainability-policy.json`. New functions fail above 50 physical lines or cyclomatic
complexity 15; existing exceptions may only shrink. Package fan-in/fan-out above the warning
threshold is ratcheted, while changed public Python surfaces are reported for compatibility
review. `quality/architecture-policy.json` classifies every current package and permits one
explicit legacy sibling-layer edge (`architecture → storage`) without allowing another. CI holds
total line coverage at 80% and changed executable package lines at the 85% target. Semantic dossier
cohesion remains a confidence-gated human-review report: responsibility breadth or a high-scoring
split recommendation is evidence for inspection, never permission to refactor automatically.

## 0.5 Record the intended internal architecture

**Status:** COMPLETE on 20 August 2026

Add a concise ADR and enforce this dependency direction:

```text
domain models and contracts
        ↑
analysis adapters    index repositories
        ↑                 ↑
application services / use cases
        ↑
CLI · REST · MCP · background jobs
        ↑
dashboard client
```

Transport layers may call application services; they may not embed SQL, parser logic, or semantic
state transitions. Index repositories may depend on domain records, but domain records do not
depend on SQLite, FastAPI, MCP, or the dashboard. Analyzer adapters produce one shared intermediate
representation.

### Formalize the existing analyzer intermediate representation here

The current `FileAnalysis`, `Symbol`, `Dependency`, and `LanguageAnalyzer` records already form a
useful proto-IR. Phase 0 must formalize and version that existing contract rather than invent a
parallel abstraction or rewrite working analyzers. Phase 1b designs a relationship-set schema and
Phase 3b reorganizes detector families; if the contract is not explicit before them, both can
accidentally encode Python AST or JavaScript regex implementation details and force a second
migration during Phase 4.

Phase 0 therefore delivers conformance tests and a versioned revision of the existing records,
adding only the concepts needed by later storage and parser work:

- module/package identity and aliases;
- symbols with kind, qualified name, signature, source span, and visibility;
- imports, exports, calls, and inheritance as reference records with evidence and confidence;
- parse status, analyzer identity, and analyzer version;
- the resolver-context inputs that determine unique, ambiguous, or unresolved resolution.

The existing Python analyzer is certified against the contract as the reference implementation,
using compatibility adapters where a staged transition is necessary. This is contract
formalization, not parser work: no grammars, packaging changes, or new languages, and no wholesale
Python analyzer rewrite. Phase 4.1 becomes conformance and extension rather than first definition.

Delivered as [`ADR 0001`](adr/0001-internal-layers-and-analyzer-ir.md), the enforced layer policy,
and the executable `anaxigraph-ir-v1` contract. Analysis version 4 persists the added facts through
a compatibility codec, all built-in analyzers pass the neutral conformance suite, and the Python
AST adapter is the characterized reference. JavaScript/TypeScript remain honestly labeled
lexical; this phase did not claim new parser depth.

## 0.6 Correct today's public claims

**Status:** COMPLETE on 20 August 2026

This subsection began as documentation and release preparation. On 20 August 2026, the narrow
distribution prerequisite was completed early by publishing the first tested package. This is a
recorded exception to the original wording, not the start of Phase 3: it does not authorize work on
the Phase 3 CLI, onboarding, agent connection, or release-automation scope while Phase 0 remains
open.

1. **COMPLETE — Document `init --start` immediately.** The README, onboarding guide, and Docker
   guide now lead with `uvx anaxigraph init . --start` as the one-command sidecar path and retain an
   inspect-before-start alternative.
2. **COMPLETE — Publish the first functional PyPI distribution.** The `anaxigraph` name was
   rechecked at execution time and version 0.1.0 was published as a tested wheel and source
   distribution. This was a functional release, not an empty name-retention placeholder. PyPI's
   [name-retention policy](https://docs.pypi.org/project-management/name-retention/) treats empty or
   non-functional projects as name squatting. Do not publish the near-miss `anaxi-graph`; under the
   [normalization specification](https://packaging.python.org/en/latest/specifications/name-normalization/)
   it is a distinct name, not an alias for `anaxigraph`.
3. **COMPLETE IN SOURCE — Modernize license metadata for the next release.** Package metadata now
   uses the SPDX expression `license = "Apache-2.0"`, declares `license-files = ["LICENSE"]`, and
   requires `setuptools>=77` for PEP 639 support. A clean wheel/source build emits
   `License-Expression: Apache-2.0` and `License-File: LICENSE`, with no prior license-table
   deprecation warning. PyPI artifacts are immutable, so this correction begins with the next
   version rather than altering 0.1.0.
4. **COMPLETE — Soften the shared multi-repository section in the README.** Every public setup
   guide labels it experimental and trusted-operator only, states that REST/MCP have no
   authentication or per-user authorization, and requires loopback/SSH rather than untrusted or
   team exposure until Phase 5.

### PyPI 0.1.0 release evidence

| Check | Recorded result |
|---|---|
| Public distribution | [`anaxigraph` 0.1.0 on PyPI](https://pypi.org/project/anaxigraph/0.1.0/) |
| Source revision | Committed `main` revision `107a306`; unrelated working-tree changes and virtual environments were excluded |
| Repository gates | 49 tests passed and Ruff passed before packaging |
| Package gates | Wheel and source distribution passed `twine check`; archive contents were checked for private environment/configuration and database files |
| Install gates | The wheel installed and executed in a clean local virtual environment; `anaxigraph==0.1.0` then installed and executed from the production PyPI index |
| Publication integrity | The wheel and source-distribution SHA-256 values returned by PyPI matched the locally validated artifacts |
| Remaining release work | Protected trusted publishing, automated release CI, cross-platform clean-machine tests, signed/checksummed containers, SBOM generation, and coordinated version/tag policy remain in Phase 3.1 |

Rule: the repository's public claims may not exceed what the current release actually enforces.

## 0.7 Record the supported platform matrix

**Status:** COMPLETE on 20 August 2026

Windows appears nowhere in this roadmap, yet `uvx` users will try it and the Docker-versus-local
story differs materially there. Phase 0 makes an explicit decision — supported, best-effort, or out
of scope — for Windows, WSL, macOS on Apple silicon and Intel, and Linux, and records it in the
README and onboarding docs.

An explicit "not supported yet" is an acceptable answer. An undecided platform discovered through a
bug report is not.

The published matrix makes Linux x86-64 Docker/local the supported release-gated path. Linux ARM64,
macOS Apple silicon/Intel, and WSL2 are best effort with their untested boundaries stated; Docker
Desktop is the recommended macOS path. Native Windows is not supported yet and Windows containers
are out of scope. Browser and filesystem caveats are explicit, and promotion now requires a
fresh-machine release gate rather than anecdotal success.

## Phase 0 exit gate

- [x] The benchmark command reproduces the current history duplication and timing baseline.
- [x] A deliberately introduced 501-line source module fails locally and in CI.
- [x] Growth of each existing oversized module fails; reducing it succeeds.
- [x] The complete current test suite, Ruff, browser tests, Compose validation, and migration tests run
  through one documented quality command.
- [x] New package cycles and forbidden layer imports fail with an understandable message.
- [x] The baseline exception list contains only the eight known modules and names their removal phases.
- [x] Phase 0 itself introduces no new module above 500 lines.
- [x] The existing analyzer intermediate representation is formalized as a versioned contract, its
  conformance tests pass, and the Python analyzer conforms without a wholesale rewrite.
- [x] The Phase 1a and Phase 1b performance targets have been ratified from the P0.1 report and written
  into this document, replacing the provisional figures carried over from the external review.
- [x] `init --start` is documented; the tested, functional PyPI 0.1.0 release and next-release PEP 639
  metadata are recorded; and the README no longer presents an unauthenticated shared deployment as
  a team installation.
- [x] The supported platform matrix is published, including an explicit decision about Windows.

### Phase 0 closure evidence

The documented command `uv run python scripts/run_quality_gate.py --base HEAD^` passed on the
supported Linux x86-64 runner on 20 August 2026. It is intentionally the same orchestration used by
CI rather than a hand-curated release checklist.

| Gate | Closure result |
|---|---|
| Tracked hooks | Every pre-commit hook passed, including module size, maintainability, architecture, generated-file, formatting, and syntax checks |
| Python suite | 79 tests passed on Python 3.11; migration and analyzer-contract tests are included |
| Coverage | 81.26% total and 100% of the closure diff, above the 80% and 85% floors |
| Deployment contracts | Base Compose and the macOS override both validated |
| Performance smoke | The 120-file/eight-frame deterministic profile completed and wrote evidence to an isolated temporary path |
| Browser contracts | 10/10 Playwright contracts passed in the pinned Linux browser container against a deterministic scanned fixture |
| Release/platform record | PyPI 0.1.0, next-release PEP 639 metadata, one-command start docs, deployment caveats, and the platform matrix are recorded |

---

# Phase 1a — delta-driven temporal discovery

**Status:** COMPLETE on 20 August 2026

**Goal:** stop re-analyzing unchanged files during historical reconstruction, on today's schema, so
the algorithm can be proven correct before storage changes underneath it.

Phase 1a is expected to capture the majority of the wall-time win without changing the temporal
fact schema. That expectation is binding only if Phase 0 confirms that analysis of unchanged files,
rather than Git subprocess overhead, is the dominant cost. If the benchmark contradicts it, the
non-convergence rule applies before implementation begins. Rows continue to be written in the
current shape; only the work required to produce them changes.

## 1a.1 Characterize temporal correctness before changing anything

**Status:** COMPLETE on 20 August 2026

Add tests covering:

- add, modify, delete, rename, copy, and file-type changes between selected revisions;
- a sampled interval containing many unselected commits;
- changed exports that alter another file's import resolution;
- a new same-named module that turns a unique import into an ambiguous import;
- removal of a module that turns an ambiguous import into a unique import;
- documentation-only, metadata-only, interface, relationship, and structural changes;
- branch/working-tree scans after an imported first-parent timeline;
- interruption, retry, and resumption from the last complete frame;

Every fixture records the expected active files, symbols, edges, resolution provenance, groups,
metrics, and finding lifecycle at each selected frame.

These fixtures are written against **today's schema** and must pass before Phase 1a changes any
behavior. They then become the regression net that Phase 1b's migration is measured against, which
is the whole reason the temporal work is split: a wrong frame in Phase 1b can only be caused by the
storage change, because the algorithm was already proven under the same fixtures.

## 1a.2 Discover change before reading source

**Status:** COMPLETE on 20 August 2026

For each selected revision after the initial frame:

1. run `git diff --name-status --find-renames <previous-selected> <revision>`;
2. classify additions, modifications, deletions, renames, copies, and type changes;
3. materialize the unchanged artifact facts required by today's snapshot schema by copying their
   prior rows, without reading or hashing the source blob;
4. read and analyze only changed/added candidate source files;
5. compare their exported module names, symbols, interfaces, and architecture placement;
6. re-resolve relationships only for changed sources and sources whose previous unresolved or
   resolved references intersect an affected namespace/symbol;
7. copy all other unaffected relationship rows into the new snapshot as today's schema requires;
8. recompute snapshot-level aggregates/findings from active indexed facts without reparsing source;
9. commit the complete frame atomically.

The diff spans selected commits, not only adjacent commits, so changes inside skipped history are
still represented in the later selected frame. The first selected revision remains a complete
scan. Working-tree state adds tracked and untracked changes without modifying the repository.
Phase 1a deliberately continues to duplicate required snapshot rows; parent references and reusable
relationship sets do not exist until Phase 1b.

## 1a.3 Make invalidation conservative and visible

**Status:** COMPLETE on 20 August 2026

Skipping unchanged source must never create a falsely stable graph. Persist why a source was
reanalyzed or reused:

- `content_changed`;
- `interface_changed`;
- `namespace_changed`;
- `resolver_context_changed`;
- `analyzer_upgraded`;
- `policy_changed`;
- `carried_forward`.

If the engine cannot prove relationship reuse is safe, it re-resolves the affected source without
rereading unrelated source. Invalidation reasons use existing `metadata_json` fields during Phase
1a rather than introducing the Phase 1b fact schema early. Dashboard and benchmark counters expose
changed, invalidated, reused, and conservatively re-resolved counts.

## 1a.4 Adopt adaptive history defaults

**Status:** COMPLETE on 20 August 2026

New configurations use `history_snapshots: auto`. Initial budgets are:

| Eligible first-party files | Maximum representative frames |
|---:|---:|
| 1–500 | 32 |
| 501–2,000 | 24 |
| 2,001–5,000 | 16 |
| Above 5,000 | 12 |

The selector always preserves the first and latest commit, then prioritizes release tags,
architecture-changing commits, calendar checkpoints, and dense recent history within the budget.
An explicit integer, date range, or `--every-commit` remains available. Existing explicit values
remain explicit during migration; newly generated Compose files stop baking in 64 frames.

Later calibration should use estimated changed-file work, not file count alone. The frame table is
the first safe adaptive policy, not a permanent magic constant.

## 1a.5 Provide progress, cancellation, and immediate usefulness

**Status:** COMPLETE on 20 August 2026

History import becomes a durable job, using the existing `analysis_runs` record and its metadata
where possible rather than introducing the Phase 1b temporal schema early. Its states are:

```text
queued -> enumerating -> importing -> finalizing -> complete
                             |             |
                             +-> failed    +-> cancelled
```

Expose through REST, MCP, CLI, and dashboard:

- selected/total frames and current commit subject/date;
- changed, analyzed, re-resolved, and reused files;
- rows/bytes added;
- elapsed time and a clearly labeled estimated remaining time;
- cancel, retry, and resume controls;
- last complete usable snapshot.

The dashboard server and current-tree scan must become usable independently of background history.
No history spinner may block repository selection, current modules, findings, or agent scope.

Only after changed-file avoidance is proven should changed blobs be read through `git cat-file
--batch`; it is an optional follow-up inside this phase if profiling shows meaningful remaining
subprocess cost.

The completed implementation persists the outer job as `history_import` in `analysis_runs` and
keeps each atomic frame as its own ordinary analysis run. CLI, REST, dashboard, and AnaxiMCP now
share one `HistoryJobService`; none maintains transport-local history state. A process owner claim
prevents a second local service from duplicating an active job. Restart recovery reuses compatible
completed frames, cancellation is polled between atomic frames, and failed/cancelled jobs retain
their last usable snapshot. The dashboard exposes the current commit subject/date, selected and
completed frames, work counters, rows/bytes added, elapsed time, labeled ETA, cancel, and
retry/resume while all current-tree views remain available.

## Phase 1a performance and exit gate

Targets below are binding against the committed P0.1 schema-6 report. Timing and memory gates run
on the same stable runner or compare before/after in the same benchmark job; exact work counters
are machine-independent.

- median history wall time across three runs of the 3,000-file/eight-frame profile is at most 45%
  of the 69,566 ms baseline (31,305 ms on the recorded runner);
- historical source reads are at most 3,250, down from 23,970, covering the first complete frame
  plus changed/added/renamed sources and a small explicit safety margin;
- analyzer invocations are at most the fixture's 3,217 distinct artifact/raw versions unless the
  report identifies a deliberate analyzer/policy invalidation;
- peak resident memory is no more than 125% of baseline (152,494,080 bytes on the recorded runner);
- unchanged, non-invalidated files invoke no source analyzer and have no blob read;
- every add, modify, delete, rename, copy, type-change, and resolver-context correctness fixture
  from 1a.1 passes;
- an interrupted import resumes without repeating completed frames;
- invalidation reasons are persisted and exposed for every analyzed and carried-forward file;
- newly generated Compose files no longer bake in 64 frames, and `history_snapshots: auto` resolves
  through the adaptive table;
- the dashboard, current-tree scan, modules, findings, and agent scope remain usable while a
  history import runs;
- while history imports, the 3,000-node benchmark remains within 125% of the P0.1 browser baseline:
  639 ms to initial overview and 112 ms to graph on the pinned runner;
- `storage.py` and `scanner.py` have not grown.

Row counts and index size are explicitly **not** part of this gate. They belong to Phase 1b.

### Phase 1a closure evidence

The three-run 3,000-file/eight-frame profile and concurrent browser profile were repeated on the
same Linux x86-64 runner on 20 August 2026. The report command remains
`python -m benchmarks.baseline`; the concurrent contract is reproducible with
`python -m benchmarks.history_concurrency`.

| Gate | Closure result |
|---|---|
| Median history wall time | 19,030 ms across 18,925 / 19,030 / 19,160 ms; 27.4% of the 69,566 ms baseline and below the 31,305 ms ceiling |
| Historical source reads | 3,217 in every run, below the 3,250 ceiling and down from 23,970 |
| Analyzer invocations | Exactly 3,217 in every run, matching the fixture's distinct artifact/raw versions |
| Peak resident memory | Maximum 137,170,944 bytes, below the 152,494,080-byte ceiling |
| Materialized Phase 1a facts | Exact legacy-shape totals retained: 23,970 file-version rows and 47,896 relationship rows |
| Concurrent dashboard | While the durable job reported `importing`, the pinned Playwright container measured 632 ms to overview and 94 ms to graph with 3,000 visible nodes, inside the 639/112 ms budgets |
| Correctness and control plane | Add/modify/delete/rename/copy/type/resolver fixtures, durable cancellation, retry, process-restart recovery, cross-service owner claim, and CLI/REST/MCP contracts pass |
| Browser contract | 11/11 pinned Playwright contracts pass, including progress, usable-current-view, cancel, and retry/resume behavior |
| Size ratchet | `scanner.py` remains 822 lines and `storage.py` remains 1,746; API and CLI baselines decreased to 579 and 557 respectively |

The final timing improvement also replaced repeated glob evaluation with bounded result caches and
replaced Python evidence extraction's repeated whole-source splitting with one line index per
analysis. Evidence equivalence, including multiline imports and UTF-8 AST offsets, is covered by
analyzer tests. Cache bounds keep the memory gate explicit rather than trading wall time for an
unbounded process cache.

---


# Phase 1b — immutable facts and snapshot deltas

**Status:** COMPLETE on 20 August 2026

**Goal:** make stored facts scale with distinct versions and relationship contexts rather than with
selected frames multiplied by repository size.

## 1b.1 Introduce immutable facts plus snapshot deltas

Phase 1a has already removed the wasted analysis. This phase removes the wasted *storage*, with the
Phase 1a correctness fixtures green throughout, plus the migration failure-recovery fixtures
deferred from 1a.1:

- transactional failure rollback and backup restoration on a copy of a real version-6 index.

**Migration safety characterization is complete.** The test fixture now creates a real multi-frame
schema-6 index and freezes canonical snapshots, files, symbols, and relationship evidence. Injected
DDL/data/version failure rolls back as one transaction. The SQLite online-backup boundary captures
WAL state, validates integrity and schema version, is idempotent, refuses a mismatched backup, and
restores the exact canonical frame record without consuming the untouched recovery copy. Phase 1b
schema work must use this boundary before destructive compaction.

Replace full snapshot materialization with a versioned schema conceptually shaped as:

```text
snapshots
  id · repository · commit · base_snapshot_id · sequence · analysis signature

file_versions
  immutable analyzed facts keyed by artifact + content/analyzer identity

snapshot_file_changes
  snapshot · artifact · add/change/delete/rename · file_version

relationship_sets
  source file version · resolver-context hash · analysis signature

relationship_edges
  relationship set · target/evidence/provenance

snapshot_relationship_changes
  snapshot · source artifact · relationship set/retract
```

Important invariants:

- A file version is stored once for the same artifact, relevant hashes, analyzer version, and
  analysis signature.
- Symbols belong to the immutable analyzed file version and are not copied into every snapshot.
- Snapshot state is reconstructed from its parent plus deltas. Periodic derived checkpoints may
  accelerate reads, but checkpoints are disposable caches rather than duplicated source facts.
- A relationship set is reusable only when both the source version and resolver context match.
  The resolver-context hash includes the namespace/symbol information that could change unique,
  ambiguous, or unresolved resolution.
- Semantic claims continue to reference the appropriate immutable version and retain their own
  prompt/model/context fingerprints.
- Queries use an index abstraction; REST, MCP, and dashboard code do not learn SQL reconstruction
  details.

The migration must be transactional, idempotent, and restartable. It preserves an untouched backup
until validation succeeds and exposes a `doctor`/compaction report before old duplicate rows are
removed. “Rollback” means aborting a failed transaction or restoring that backup; Phase 1b does not
promise an automatic downgrade after a successful migration.

**Immutable fact schema is complete on 20 August 2026.** Schema 7 now adds immutable `file_facts`
and `fact_symbols`, content-addressed relationship sets/edges, sparse file and relationship change
tables, explicit snapshot bases/sequences, and a persistence-only reconstruction API. New scans
dual-write compatibility frames and canonical facts in the same transaction. A real schema-6 copy
is backed up before an atomic upgrade, and frame-by-frame tests prove identical file facts, symbols,
edge evidence, confidence, and resolution provenance after both direct dual-write and migration
backfill. The compatibility tables intentionally remain until items 19–21 validate semantic and
finding consumers and `doctor` authorizes compaction.

**Migration validation and doctor are complete on 20 August 2026.** Index initialization now
creates the validated schema-6 backup before opening the migration transaction, records its path,
checksum, size, source/target versions, and completion time only when that transaction commits, and
can restart cleanly after an injected post-backfill failure. Reused current snapshots are rebased
onto the selected first-parent history without cycles, including the common scan-before-history
workflow. `anaxigraph doctor` checks integrity, foreign keys, lineage, every frame's file/symbol/edge
digest, and backup recovery metadata. It emits a fail-closed compaction report and explicitly retains
all compatibility rows while legacy product or semantic consumers remain.

## 1b.2 Bound snapshot reconstruction and read amplification

Delta storage must not exchange write amplification for an ever-slower dashboard. Define a
reconstruction budget before choosing the final schema:

- benchmark cold and warm reads for the current snapshot, the oldest selected snapshot, and a
  middle snapshot;
- cap the number of parent deltas any user-facing query may traverse;
- create periodic, disposable materialized checkpoints when that cap would be exceeded;
- index change tables for artifact, source relationship, snapshot sequence, and repository lookup;
- verify that rebuilding or deleting a checkpoint cannot change canonical facts;
- keep checkpoint creation resumable and outside the target repository;
- expose reconstruction depth, checkpoint use, query duration, and returned row count in benchmark
  diagnostics.

The Phase 0 baseline sets the latency ceilings below; the Phase 1b prototype validates the chosen
checkpoint representation against them. Current-snapshot queries remain constant-depth, while
historical queries may traverse at most 16 deltas before using a derived checkpoint.

**Checkpoint foundation is complete on 20 August 2026.** Schema 7 introduced disposable reference
checkpoints; the final bounded policy materializes one before traversal would exceed 16 frames,
invalidates descendant caches when a base frame changes, and reconstructs canonical file and
relationship state from the nearest checkpoint.
Every reconstruction reports traversed deltas, checkpoint identity, duration, and returned rows.
Fresh, migrated, and previously-created schema-7 indexes adopt the versioned checkpoint policy
idempotently; `doctor` verifies cache counts and hashes against canonical reconstruction. A
33-commit regression proves that user reads remain below the 16-delta cap and that deleting and
rebuilding every checkpoint leaves files, edges, and state hashes unchanged.

**Bounded product reads are complete on 20 August 2026.** Snapshot catalog, timeline, overview,
group hierarchy, module ledger, graph, module detail, search, and finding-priority reads now consume
canonical reconstruction through cohesive persistence read models. The compatibility schema moved
out of `storage.py`; its public `AnaxiIndex` facade is 398 lines and its Phase 1b size exception is
removed. A four-entry process-local graph cache is invalidated after every index transaction and is
only an acceleration of immutable snapshot results. On the binding 3,000-file/eight-frame fixture,
current graph delivery measured 98.76 ms cold and 19.38 ms warm median, the middle frame measured
13.70 ms warm, and the oldest frame measured 14.25 ms warm. The current and middle reads traversed
seven and four deltas respectively, while the oldest used its checkpoint directly; all are beneath
the 16-delta and published latency ceilings. The benchmark report now records these read targets,
checkpoint identities, traversal depth, reconstruction duration, returned rows, and checkpoint
storage counts.

**Semantic, finding, and history compatibility is complete on 20 August 2026.** Schema 8 gave
module-scoped claims, dossiers, jobs, and scope states a direct immutable `file_fact_id` while
retaining the compatibility reference for the final compaction window. Migration backfills those
references from exact reconstructed frames. Semantic work planning and evidence, module/detail
claims, deterministic architecture findings, and history invalidation telemetry now consume
canonical facts or durable run records rather than duplicated frame rows. Tests prove identical
semantic evidence and work hashes across checkpoint deletion/rebuild, stable fact identity through
lease retry, exact schema-7-to-8 provenance backfill, and unchanged finding behavior. `doctor`
fails closed when any module-scoped semantic record lacks its canonical fact reference.

**Canonical compaction is complete on 20 August 2026.** Schema 9 makes immutable file facts the
required semantic identity, moves complete symbol detail onto `fact_symbols`, migrates relationship
coverage to canonical edge IDs, and clears the old materialized `file_versions`, `symbols`,
`relationships`, and `group_memberships` rows after exact parity validation. Those empty tables
remain transaction-local scan staging surfaces so the analyzer and detector pipeline can be
decomposed independently; no REST, MCP, dashboard, semantic, finding, or history read consumes
them. File-placement metadata stores only snapshot-specific state, file-fact metadata omits
derivable IR fields and is expanded at the persistence boundary when a consumer needs the full
contract, and equivalent relationship sets are content-deduplicated. A canonical content digest
covering facts, deltas, sets, and edges lets `doctor` detect post-compaction damage without relying
on rows that were intentionally removed.

## 1b.3 Decompose the temporal implementation while changing it

Refactor `storage.py` behind a small `AnaxiIndex` facade into cohesive modules such as schema and
migrations, snapshot/file repositories, relationship repositories, finding repositories, semantic
repositories, and read models. Refactor `scanner.py` into discovery, preparation, resolver,
persistence, invalidation, and orchestration components.

The exact package names follow the ADR, but by the end of this phase:

- `storage.py` and `scanner.py` are each below 500 lines;
- no extracted module exceeds 500 lines;
- transactions remain owned by explicit application operations rather than helper modules opening
  unrelated connections;
- no dashboard, API, or MCP behavior depends on the old table layout.

## Phase 1b performance and exit gate

Targets below are binding against the committed P0.1 schema-6 report:

- immutable heavy file-version rows are at most 3,539, within 10% of the 3,217 distinct analyzed
  artifact/raw versions rather than the baseline 23,970 snapshot copies;
- persisted canonical relationship edges/sets are at most 11,974 (25% of the 47,896-row baseline)
  and are not fully re-materialized for every frame;
- symbols are stored against the immutable analyzed file version and are not copied per snapshot;
- index size scales with changed versions and relationship contexts, and the benchmark report
  demonstrates at least a 5× reduction versus the 49,561,600-byte vacuumed baseline: at most
  9,912,320 bytes on the synthetic fixture capped at 5% changed files per selected transition;
- every Phase 1a correctness fixture still passes unchanged against the new schema;
- current graph reads are at most 136 ms cold and 101 ms warm median (120% of baseline); oldest and
  middle historical reads are at most 168 ms warm median; no user-facing query traverses more than
  16 deltas before using a checkpoint;
- deleting and rebuilding derived checkpoints produces identical canonical graph results;
- version-6 indexes migrate without data loss, retain a restorable backup before compaction, and
  abort cleanly on injected migration failure;
- the migration is transactional, idempotent, and restartable, and `doctor` reports the result
  before duplicate rows are removed;
- `storage.py` and `scanner.py` are below 500 lines and removed from the size-exception baseline;
- no extracted module exceeds 500 lines, and no dashboard, API, or MCP behavior depends on the old
  table layout.

No temporal visualization features begin until this gate passes.

### Phase 1b closure evidence

The binding 3,000-file/eight-frame profile was regenerated on the same Linux x86-64 runner on
20 August 2026 and is committed as
[`benchmarks/results/phase1b-exit-2026-08-20.json`](../benchmarks/results/phase1b-exit-2026-08-20.json).
The report was generated from the dirty implementation tree intentionally, then the complete code,
migration, and browser gate was run before the milestone commit.

| Gate | Closure result |
|---|---|
| Immutable file facts | 3,217 facts for 3,217 distinct artifact/raw versions, below the 3,539 ceiling; 3,225 symbols belong to those facts rather than snapshots |
| Sparse relationships | 3,059 reusable sets plus 6,124 immutable edges (9,183 combined), below 11,974; 3,122 source deltas select/retract them across eight frames |
| Index size | 9,596,928 bytes after vacuum, below 9,912,320 and 5.16× smaller than the 49,561,600-byte schema-6 baseline |
| Read amplification | Current/middle/oldest file reconstruction traversed 8/5/1 deltas; all remain below 16 and no checkpoint is needed for an eight-frame history |
| API latency | Current graph measured 132.09 ms cold and 14.16 ms warm median; middle and oldest measured 13.68/15.22 ms warm, all below their binding ceilings |
| Historical work | 29,181 ms total; exactly 3,217 source reads and analyzer invocations; peak resident memory was 148,254,720 bytes |
| Compaction | Zero rows remain in all four compatibility staging tables; canonical integrity, semantic-fact references, lineage, foreign keys, and reconstruction are doctor-checked |
| Decomposition | `storage.py` is 398 lines and `scanner.py` is 358; both exceptions are removed and no extracted implementation module exceeds 500 lines |
| Agent contract | The Go-analyzer scope retained all eight expected primary files, no unexpected primary files, and a 5,757-byte payload |

---


# Phase 2 — attention signal

**Status:** ACTIVE

**Goal:** turn excellent ranking into an intentionally small action surface without discarding the
complete diagnostic record.

## 2.1 Separate the attention queue from diagnostics

Create two product views:

- **Attention queue:** new, regressed, acknowledged, or planned findings that exceed the configured
  priority/severity threshold. Default page size: 20. The overview continues to show only the top
  10.
- **Diagnostics:** complete low-severity observations, including routine long-function signals,
  with filters by detector, module, architecture area, status, and confidence.

`long_function` remains available as deterministic evidence but information-level instances do not
fill the attention queue by default. Repository policy may disable it, change its threshold, or
promote it for selected production paths. Module-size and complexity gates for AnaxiGraph itself
remain enforced by development tooling whether or not those diagnostics are visible in the
product queue.

## 2.2 Make result limits explicit

- Add cursor pagination and summary counts to the findings REST and MCP surfaces.
- Return `shown`, `total_matching`, `total_by_severity`, `total_by_type`, active filters, and the
  priority version.
- Preserve stable sort order by priority, regression state, first seen, and stable key.
- Let agents request a bounded token budget; return exactly what was omitted.
- Do not silently cap at 500 or imply that a page is the entire ledger.
- Group repeated diagnostics by detector and architecture area before presenting individual rows.

## 2.3 Improve actionability

Every queued finding must answer:

- why it is ranked here;
- what deterministic and semantic evidence supports it;
- what could make it a false positive;
- affected modules, contracts, tests, and blast radius;
- the smallest sensible next action;
- whether the recommended action is investigate, constrain, refactor, test, or remove;
- how a later scan will verify resolution.

Lifecycle remains:

```text
new -> acknowledged -> planned -> resolved by evidence
  \          \              \
   dismissed  accepted risk  regressed if it returns
```

Bulk acknowledgement/dismissal is allowed only after the UI shows the matching filter and count.
Resolution normally comes from a later scan, not a “make green” button.

## Phase 2 exit gate

- A default attention view contains at most 20 findings and accurately reports the complete total.
- Information-level `long_function` results do not dominate the default queue.
- A user can recover and filter every stored diagnostic; no evidence is thrown away for UX reasons.
- MCP finding responses honor their payload budget and pagination contract.
- Finding actions and automatic verification are covered by backend and browser tests.
- Backend and browser tests cover filtering, pagination, totals, lifecycle, and automatic
  verification without requiring unrelated dashboard decomposition.

---

# Phase 3 — one-command local adoption

**Status:** BLOCKED BY PHASE 2

**Goal:** provide a working dashboard in one command and a connected coding agent in at most one
additional explicit action.

## 3.1 Automate and harden the published Python distribution

The tested 0.1.0 wheel and source distribution were published manually during Phase 0.6. Phase 3.1
does not repeat that completed name/publication task. It converts the verified manual path into a
reproducible, protected release system for every subsequent version.

- Publish the next version only after a deliberate version bump and all release gates pass; never
  attempt to replace immutable 0.1.0 artifacts or reuse an already published filename.
- Add build, wheel-install, source-distribution, Python-version, and package-data tests.
- Use PyPI trusted publishing from a protected GitHub release workflow instead of making a
  maintainer's long-lived local upload token the normal release path.
- Verify SPDX license expressions and declared license files in built metadata, so the PEP 639
  correction remains a permanent release gate.
- Publish signed/checksummed container images and align Python and container version tags.
- Generate an SBOM and dependency/license report for releases.
- Test the exact fresh-machine commands in disposable Linux and macOS environments.

Target entry command:

```bash
uvx anaxigraph init . --start
```

Phase 0 documents the already implemented `--start` behavior. This phase makes that path robust
enough to lead onboarding and validates the exact command from a clean supported machine.

## 3.2 Make initialization express the intended workflow

Add idempotent options:

```bash
uvx anaxigraph init . --start --semantic agent --connect codex
uvx anaxigraph init . --start --semantic agent --connect claude
```

- `--semantic agent` writes the enabled agent-funded policy directly.
- `--connect` writes or invokes the selected client's MCP configuration only after the user chose
  that explicit option.
- Client changes are previewable with `--dry-run`, create a backup where appropriate, preserve
  unrelated settings/comments where the format permits, and are safe to repeat.
- Support user-global and project-local connection scopes.
- Print the exact dashboard and MCP URLs and explain Docker-network/remote-host variants.
- Provide `anaxigraph doctor` to test repository mount, database writeability, container/service
  health, MCP reachability, and client configuration.

Do not silently mutate agent configuration during a plain `init`.

## 3.3 Add a no-Docker first-five-minutes path

Provide a convenience command built on the existing scan and serve capabilities:

```bash
uvx anaxigraph up . --open --semantic agent --connect codex
```

It should:

- infer or load policy;
- place AnaxiIndex in an OS-appropriate user state directory rather than pollute the target repo;
- start the dashboard/API/MCP on loopback;
- perform the current scan and queue background adaptive history;
- open the browser when possible;
- show clean shutdown and restart instructions.

Docker remains the recommended durable/isolated sidecar and multi-repository deployment. The local
path optimizes evaluation, workshops, and individual use; it does not replace container hardening.

## 3.4 Ship agent skills/plugins

Package a small AnaxiGraph skill for Claude Code and a standards-compatible agent skill for Codex
and other supported clients. The skill contains:

- connection/health discovery;
- the semantic bootstrap loop (`SCHEMA -> WORK -> EVIDENCE -> SUBMIT/RELEASE`);
- repository selection rules;
- bounded scope/impact/finding workflows;
- instructions never to claim a submitted dossier without a successful MCP response;
- resume and lease-expiry behavior;
- concise commands such as `/anaxigraph` or `$anaxigraph`, following each client's conventions.

The skill is packaging around AnaxiMCP, not a second analysis implementation. Server contracts
remain the source of truth and are versioned.

## 3.5 Collapse onboarding documentation

The first screen and README lead with:

1. one local or Docker start command;
2. the dashboard URL;
3. one agent connection command/option;
4. one sentence asking the agent to bootstrap or resume semantics.

Hosted-key workers, local model workers, multi-repository registries, SSH tunnels, custom coverage,
and manual Compose operations move under **Advanced** sections. The main path explains that the
coding agent uses its own tokens and that AnaxiGraph itself needs no model key in agent mode.

## 3.6 Decompose onboarding code

Split `cli.py` into parser/facade plus command handlers and split `onboarding.py` into repository
detection, policy generation, Compose generation, client connection, and start/doctor services.
Command behavior remains covered at the process boundary, not only through helper unit tests.

## Phase 3 exit gate

- From a clean supported machine, one documented command produces a usable dashboard without a Git
  source URL and without manually writing configuration.
- Full agent-funded value requires no more than a second command or the explicit `--connect` option.
- Re-running initialization is idempotent and does not overwrite unrelated user/client settings.
- Both Docker and no-Docker paths pass end-to-end tests.
- The agent skill completes, resumes, and safely releases a semantic job against a fixture repo.
- Median internal first-user test time is under five minutes to dashboard and under ten minutes to
  the first submitted semantic dossier.
- `cli.py` and `onboarding.py` are removed from the size-exception baseline.
- Shared/team installation is still documented as experimental and loopback/local-first until
  Phase 5 security ships.

---

# Phase 3b — dashboard/evaluator decomposition and self-analysis

**Status:** BLOCKED BY PHASE 3

**Goal:** remove the remaining dashboard and evaluator size exceptions, then prove that
AnaxiGraph's deterministic attention model can act as a stable regression check on its own code.

## 3b.1 Decompose evaluators and the dashboard

Refactor:

- `architecture.py` into rule parsing, detector families, evaluation orchestration, and aggregate
  metrics;
- `agent.py` into scope ranking, graph expansion, impact analysis, collision analysis, and payload
  serialization;
- `dashboard/app.js` into ES modules for API access, application state/navigation, graph layout and
  rendering, module inventory, findings, history, settings, and semantic work.

Preserve the zero-runtime-JavaScript-dependency goal unless a separate ADR demonstrates a clear
maintenance and supply-chain benefit. Update package-data rules and browser tests so nested
dashboard modules ship in wheels and containers.

## 3b.2 Make self-analysis a regression gate, not a zero-backlog gate

Run AnaxiGraph against its own pull-request revision in CI and retain the report as a build
artifact. The required check fails only when a deterministic, policy-enabled condition is newly
introduced or regresses across an explicit threshold relative to the committed baseline.

The gate must:

- pin analyzer, detector, rule, and priority versions;
- compare stable finding keys and evidence rather than queue position alone;
- fail on configured new/regressed severity, architecture boundary, cycle, size, or complexity
  conditions;
- keep information-level diagnostics and model-derived semantic recommendations non-blocking;
- allow accepted existing debt only through a reviewed baseline entry with rationale and removal
  phase, never by dismissing a finding merely to make CI green;
- report when a rule or score-version change requires an explicit baseline review;
- upload the full scan summary even when the required regression check passes.

The human attention queue may remain non-empty. CI proves that a change did not make the governed
architecture worse; it does not pretend all acknowledged or planned work has already been completed.

## Phase 3b exit gate

- `architecture.py`, `agent.py`, and every dashboard JavaScript module are below 500 lines and are
  removed from the size-exception baseline.
- The graph, modules, findings, history, settings, and semantic workflows retain browser and visual
  regression coverage after decomposition.
- Wheels and containers include every nested dashboard module.
- CI self-analysis is deterministic and fails on a fixture that introduces a governed regression.
- An unchanged accepted backlog does not fail CI, and a changed rule/priority version requests a
  reviewed rebaseline rather than silently changing the gate.
- The self-analysis gate needs no LLM call, network model access, or mutable semantic dossier.

---

# Phase 4 — core parser-backed language platform

**Status:** BLOCKED BY PHASE 3b

**Goal:** replace the two-language cliff with a maintainable parser platform and honest per-language
support levels.

## 4.1 Extend and conform to the analyzer intermediate representation

The IR contract was formalized in Phase 0 (§0.5) so that Phase 1b's relationship schema and Phase
3b's detector families could be designed against it rather than against whatever the Python and
JavaScript analyzers happened to emit. This item is therefore conformance and extension, not first
definition: any change to the contract here is a versioned revision with a migration note.

Every parser adapter emits the same versioned records:

- module/package identity and aliases;
- classes, interfaces, functions, methods, constants, and source spans;
- imports, exports, re-exports, includes, calls, constructors, and inheritance/implementation;
- public interfaces/signatures;
- entry-point and framework evidence;
- parse errors and recovered regions;
- complexity inputs;
- extracted doc/comments without allowing prose to become structural fact;
- analyzer name/version, grammar version, confidence, and unsupported constructs.

Resolvers consume this representation rather than grammar-specific tree node names. Grammar query
definitions live in small declarative language adapters; shared traversal and evidence logic is
tested once.

## 4.2 Introduce tree-sitter behind the analyzer contract

- Pin the runtime and grammar packages within compatible version ranges.
- Decide whether grammars are a default dependency, a `languages` extra, or bundled only in the
  container after measuring wheel size and install reliability.
- Cache parser/language objects safely.
- Bound parse time and source size; report timeout/recovery instead of falling through silently.
- Retain Python's standard-library AST where it provides equal or better semantics, while emitting
  the same intermediate representation.
- Keep the lexical fallback as an explicitly labeled `text-heuristic` analyzer, never as “full
  support.”

## 4.3 Wave 1: JavaScript and TypeScript parity

Replace the regex analyzer for `.js`, `.jsx`, `.mjs`, `.cjs`, `.ts`, and `.tsx`. Fixtures include:

- default/named/dynamic imports and re-exports;
- CommonJS require/exports;
- JSX/TSX calls and components;
- decorators, generics, optional chaining, template literals, and arrow functions;
- classes, interfaces, enums, type aliases, inheritance, and method calls;
- malformed but recoverable source.

The new analyzer must match all valid old fixtures, fix documented regex failure cases, and expose
any remaining unsupported dynamic patterns.

## 4.4 Wave 2: Go, Rust, and Java

Implement one language at a time in this order:

1. Go packages, imports, functions, methods, interfaces, receiver relationships, and calls;
2. Rust modules/crates, `use`, structs/enums/traits, implementations, macros as bounded evidence,
   and calls;
3. Java packages/imports, classes/interfaces/records/enums, inheritance/implementation,
   annotations, methods, and calls.

Each language ships only after its fixtures, real-repository sample, resolver metrics, dashboard
support badge, and documentation pass. Work on the next language does not start while the previous
one is still labeled experimental.

## 4.5 Publish an honest support matrix

Support levels:

- **Deep:** parser, symbols, dependency/call relationships, public interfaces, resolution tests,
  and maintained real-repo fixtures;
- **Structural:** parser-backed modules/symbols/imports, but incomplete calls/framework behavior;
- **Heuristic:** text/regex facts only;
- **Inventory:** file metadata and Git history only.

Dashboard, API, MCP, and docs show the level and analyzer version. Repository-level graph trust is
weighted by the actual mix rather than the number of recognized file extensions.

## Phase 4 exit gate

- JavaScript/TypeScript are parser-backed and the regex implementation is removed from normal use.
- Go, Rust, and Java meet the Deep support contract.
- Parser and grammar versions participate in analysis fingerprints and targeted invalidation.
- Malformed syntax produces bounded partial results plus visible parse evidence.
- Mixed-language fixtures verify cross-language import and API boundary behavior where it is
  deterministic.
- No language adapter exceeds 500 lines; shared logic is reused through composition, not a giant
  switch or inheritance lattice.
- Scan performance and memory remain within the Phase 1a and 1b benchmark budgets.

---

# Phase 5 — team security and graph-scale APIs

**Status:** BLOCKED BY PHASE 4

**Goal:** make multi-repository/team deployment safe and keep large graphs bounded from database to
browser.

## 5.1 Define deployment modes

- **Local sidecar:** loopback binding, one operator, optional authentication with clear warning.
- **Trusted LAN/team:** authentication required, explicit repository scopes, TLS terminated by a
  documented reverse proxy or native configuration.
- **Hosted/public:** out of scope until a separate threat model, tenant isolation, rate limiting,
  backup, and operational ownership exist.

AnaxiGraph must fail closed when configured on a non-loopback bind without authentication. README
language may not promote a team installation before this behavior ships.

## 5.2 Authenticate REST, dashboard, and MCP

Implement tokens with:

- hashed-at-rest credentials or injected secrets, never tokens stored in repository YAML;
- scopes for `index:read`, `semantic:write`, `scan:run`, `finding:write`, and `admin`;
- per-token repository allowlists;
- creation, rotation, revocation, expiry, and last-used metadata;
- Docker secret/environment and reverse-proxy examples;
- audit events for scans, semantic leases/submissions, finding lifecycle changes, and admin actions;
- consistent enforcement across REST and MCP.

Browser authentication should use an appropriate short-lived session mechanism and avoid putting
bearer tokens in URLs or durable browser logs. Protect state-changing routes from cross-site
requests and configure CORS narrowly.

## 5.3 Replace unbounded graph responses

Introduce versioned, cursor-based graph queries with:

- repository and snapshot required in the resolved request context;
- node/edge limits with safe server maxima;
- architecture area/subsystem, path, language, finding, and relationship filters;
- overview aggregates first, then region/subgraph expansion;
- “neighbors of selected node” and bounded depth endpoints;
- counts and continuation cursors;
- optional graph deltas between two snapshots;
- payload byte reporting and server timing.

The dashboard should load architecture aggregates and visible regions first rather than download
every node and edge before drawing anything. MCP remains biased toward smallest useful subgraphs.

## 5.4 Bound operational work

- Rate-limit expensive scans/history imports per repository.
- Add job concurrency and cancellation controls.
- Bound request body sizes, evidence pages, graph depth, and export size.
- Add database backup/restore and health/size diagnostics.
- Test repository isolation so an allowed token cannot infer names, counts, or job state from an
  unlisted repository.

## 5.5 Decompose API code

Split `api.py` into thin routers for repositories, graph, findings, history/jobs, semantics, and
authentication backed by application services. The app factory owns dependency wiring; routers do
not execute SQL or semantic state transitions.

## Phase 5 exit gate

- Non-loopback startup without configured auth fails with a direct remediation message.
- REST and MCP authorization tests cover every tool/route and repository scope.
- No graph endpoint can serialize an unbounded repository graph.
- A 50,000-node synthetic graph can open an overview and inspect a region without exhausting the
  browser or returning one monolithic payload.
- Token rotation/revocation and audit events work without restarting the service.
- Backup/restore and schema upgrade are documented and tested.
- `api.py` is removed from the size-exception baseline.
- The legacy exception file is now empty: every first-party implementation module is at or below
  500 physical lines.

---

# Phase 6 — architect-grade semantic and pattern advice

**Status:** BLOCKED BY PHASE 5

**Goal:** turn the existing dossier and agent-funded execution foundation into a dependable
architect and coding partner.

## 6.1 Replace the semantic mixin lattice with explicit services

The current `SemanticEngine` composes seven mixins that share an implicit `database` attribute.
Replace that inheritance with a small facade over injected services, for example:

- `SemanticPlanner` — determines intrinsic/contextual work and priority;
- `LeaseService` — owns claim, heartbeat, release, expiry, and idempotency;
- `EvidenceAssembler` — pages bounded source and graph evidence;
- `DossierContract` — schema validation and canonicalization;
- `DossierRepository` — transactional persistence and provenance;
- `SemanticRunner` — optional hosted/local worker execution;
- `SemanticReporting` — coverage, cost, failure, and stale-state read models.

State transitions become an explicit tested state machine. Services receive narrow protocols
rather than a global engine or SQLite connection. The public CLI/REST/MCP contract remains stable
through a compatibility facade during the refactor.

## 6.2 Make every module meaningfully understood

For every eligible first-party module, the durable dossier should contain:

- concise purpose and detailed summary;
- responsibilities and non-responsibilities;
- inputs, outputs, side effects, public contracts, and runtime role;
- architecture area/subsystem and why it belongs there;
- dependencies/dependants with important relationship evidence;
- local precedents and related responsibilities elsewhere;
- test strategy and observed coverage state;
- lifecycle/Git biography and meaningful intent changes;
- risks, uncertainty, and missing context;
- pattern opportunities, consolidation candidates, dead-code candidates, and placement guidance;
- provider/model/prompt/schema, source/context fingerprints, evidence, confidence, token/cost data,
  and human review state.

Bootstrap remains complete-but-resumable: every eligible module must be current, explicitly
excluded, or visibly failed. Incremental refresh rereads source only when structural, interface,
relationship, analyzer, prompt/model, policy, or age fingerprints require it.

## 6.3 Detect repeated responsibilities and consolidation candidates

Combine independent signals:

- token/AST similarity for repeated implementation;
- similar public interfaces and side effects;
- semantic responsibility similarity from current dossiers;
- common dependants/dependencies;
- historical change coupling;
- shared architecture placement and ownership;
- differences that argue the modules should remain separate.

Produce cluster-level proposals such as merge, extract shared service, introduce adapter, relocate,
or retain separate implementations. A proposal must identify the exact repeated behavior and the
meaningful differences; filename similarity alone is insufficient.

## 6.4 Add conservative symbol and module dead-code analysis

Start deterministic reachability from configured and detected entry points:

- CLI entry points, web routes, workers, scheduled tasks, plugins, framework registrations, public
  packages, tests, and operator-configured roots;
- imports, calls, inheritance, registration, serialization, templates/configuration, and ambiguous
  candidates;
- dynamic/reflection conventions modeled as explicit lower-confidence evidence.

Candidate levels:

1. unreferenced private symbol;
2. unreachable module from known entry points;
3. apparently obsolete feature cluster;
4. removal proposal with impact and verification plan.

Coverage absence, low churn, or no resolved inbound edge is never enough by itself. Deletion advice
is suppressed below a configurable graph-resolution/trust threshold. Every candidate reports
counter-evidence, dynamic blind spots, affected contracts, and tests to run. AnaxiGraph never
deletes target code automatically.

## 6.5 Score pattern and refactor proposals

Evaluate patterns at symbol, module, subsystem, area, and repository levels. Do not force every
design issue into a named Gang-of-Four pattern; consolidation, extraction, relocation, interface
stabilization, and removal are first-class proposal types.

Base suitability components:

```text
fit to repeated problem        0–25
coupling/cohesion improvement  0–20
consistency with local design  0–15
testability/safety benefit     0–15
expected reuse/change value    0–15
migration cost deduction       0–10
```

Also report independent 1–100 scores for expected benefit, urgency, execution safety, and
confidence. “85 suitability, 48 confidence” explicitly means the idea may fit if the inferred
responsibility is correct, but more evidence is required.

Every proposal includes:

- evidence and counter-evidence;
- affected symbols/modules and blast radius;
- local examples to follow or avoid;
- prerequisites and migration steps;
- estimated effort and risk;
- tests and post-change invariants;
- conditions that invalidate the proposal;
- score version and component values.

Lifecycle:

```text
candidate -> reviewed -> approved/rejected -> planned -> implemented -> verified/regressed
```

Human rationale is durable memory. Rejected proposals should not be repeatedly regenerated unless
material evidence changes.

## 6.6 Guide new functionality

Given a coding goal, return:

- the preferred extension point and architecture area;
- existing abstractions and patterns to reuse;
- smallest primary file set and bounded related context;
- contracts, callers, persistence, events, and tests likely to change;
- active findings and known risky boundaries;
- proposed sequence of edits;
- explicit anti-patterns and duplicated paths to avoid;
- verification commands and architecture facts to compare after the change.

After implementation, compare the intended invariants with the new snapshot and explain what
improved, stayed uncertain, or regressed. This closes the loop between dashboard review and the
coding agent operating in the repository.

## 6.7 Calibrate rather than merely generate advice

Build a reviewed corpus of real examples:

- correct and incorrect provider abstractions;
- justified large reference modules versus low-cohesion modules;
- true and false dead-code cases involving dynamic registration;
- merge candidates that share implementation but not responsibility;
- pattern opportunities with different migration costs;
- goals placed correctly and incorrectly in an existing architecture.

Track precision, reviewer acceptance, false-positive reason, score calibration, and repeated
rejection rate by detector/prompt/model version. Default product views favor high precision over
proposal volume.

## Phase 6 exit gate

- The semantic system uses explicit composition; no seven-mixin facade or hidden shared mutable
  service state remains.
- Repeated unchanged reconciliation creates no new source-reading semantic jobs.
- Every eligible fixture module reaches current, excluded, or failed with visible provenance.
- Consolidation and dead-code evaluation expose both supporting and contradicting evidence.
- No deletion proposal appears when relationship trust is below policy or a plausible dynamic root
  remains unexplained.
- Pattern scores are reproducible from stored components and calibrated on the reviewed corpus.
- A coding goal produces placement guidance, a bounded work scope, precedents, risks, tests, and
  post-change verification.
- Semantic and pattern modules comply with the 500-line ceiling and dependency-layer rules.

---

# Phase 7 — temporal architecture intelligence

**Status:** BLOCKED BY PHASE 6

**Goal:** make time an explanatory product advantage rather than only a graph animation.

## 7.1 Persist meaningful graph deltas

For each selected frame, derive:

- modules/symbols/relationships added, removed, renamed, or materially changed;
- architecture area moves and boundary changes;
- cycles introduced/resolved;
- interface, complexity, coverage, and coupling deltas;
- findings introduced, acknowledged, planned, resolved, or regressed;
- semantic intent and pattern proposal changes with provenance.

Store or cache these deltas independently from the renderer so REST, MCP, exports, and dashboard use
the same explanation.

## 7.2 Add behavioral architecture analytics

- File/module change frequency over configurable windows;
- change coupling: files that repeatedly change together even without a static edge;
- churn × complexity hotspots and their trend;
- ownership/knowledge concentration when Git identity data is explicitly enabled;
- unstable interfaces and architecture regions absorbing disproportionate change;
- findings/patterns whose risk is increasing rather than merely present.

Behavioral evidence complements static structure. Co-change is not mislabeled as a runtime
dependency.

## 7.3 Build the visual repository bibliography

The history view includes:

- initial commit, tags/releases, calendar milestones, and architecture-changing commits;
- commit subject/date/author where allowed;
- dominant areas and changed-file counts;
- concise architecture delta and newly actionable findings;
- play/pause, speed, scrub, compare, date range, and milestone filters;
- stable node positions and preserved camera/selection;
- visible add/remove/change animation rather than a complete graph jump;
- exportable, client-safe presentation with optional identity redaction.

## 7.4 Explain “when and why” to agents

MCP queries should answer:

- when a module/responsibility/interface first appeared;
- which change introduced a cycle, hotspot, or proposal;
- whether two modules are statically connected, behaviorally coupled, or both;
- how an architecture area changed over a release/date range;
- whether a current recommendation is new, persistent, improving, or regressed.

## Phase 7 exit gate

- Playback begins at the first selected revision and ends at the current tree without rerunning full
  history analysis.
- Every visual delta matches the shared REST/MCP delta record.
- A user can identify the commit/frame that introduced and resolved a fixture cycle.
- Change coupling and static dependencies remain separately labeled.
- Camera, selected module, and architecture regions remain stable during playback.
- A client-safe export tells a coherent architecture story without leaking excluded paths or
  identities.

---

# Phase 8 — long-tail languages, non-code context, and extension ecosystem

**Status:** BLOCKED BY PHASE 7

**Goal:** expand beyond the core language set and understand the system around source code without
delaying team security or turning AnaxiGraph into an unbounded document-ingestion product.

## 8.1 Add long-tail parser-backed languages

Implement C, C++, C#, Ruby, and PHP one at a time through the Phase 4 analyzer contract. Prioritize
constructs that affect module boundaries and impact analysis before advanced symbol completeness.
C/C++ header/include resolution and build-system ambiguity require explicit provenance;
dynamic Ruby/PHP framework conventions require configurable entry points and lower-confidence
evidence where static certainty is impossible.

Each language must meet at least the Structural support contract and ship its fixtures,
real-repository sample, resolution metrics, dashboard support badge, and documentation before the
next language begins. Moving this wave here keeps it committed in the roadmap without forcing team
authentication to wait for five unrelated language implementations.

## 8.2 Prioritize deterministic operational context

Add adapters in this order:

1. SQL schemas and migrations: tables, views, foreign keys, and code-to-table evidence;
2. OpenAPI/JSON Schema/GraphQL contracts and code endpoints/clients;
3. Docker Compose, Kubernetes, and service/runtime topology;
4. Terraform and selected infrastructure relationships;
5. Markdown architecture/ADR links and explicitly declared module references.

Each adapter uses the same evidence/provenance vocabulary and declares whether a relationship is
extracted, resolved, ambiguous, or inferred.

## 8.3 Keep rich media optional

PDF, image, audio, and video understanding is not on the critical path. If added later, it must be
an optional plugin with explicit egress/privacy policy, bounded cost, separate semantic provenance,
and no effect on deterministic code-graph trust scores.

## 8.4 Stabilize the plugin contract

Publish versioned interfaces for:

- file/language analyzers;
- resolvers;
- architecture detectors and rules;
- semantic providers/agent adapters;
- importers such as coverage or runtime traces;
- exporters and dashboard panels.

Plugins run with declared capabilities and resource bounds. The core can disable a failing plugin,
record its failure, and continue scanning without corrupting a snapshot. First-party plugins follow
the same line, test, provenance, and migration rules as core modules.

## Phase 8 exit gate

- C, C++, C#, Ruby, and PHP each meet at least the Structural support contract and remain honestly
  labeled where calls, framework behavior, macros, or build resolution are incomplete.
- SQL, API schema, and deployment configuration connect to code with inspectable evidence.
- Missing or invalid non-code inputs degrade visibly and do not corrupt code facts.
- A third-party analyzer can be developed from a documented fixture/template without changing core
  scanner or storage code.
- Plugin compatibility and permissions are versioned and tested.
- Optional semantic media processing cannot run without explicit operator policy.

---

# Phase 9 — 1.0 hardening and community launch

**Status:** BLOCKED BY PHASE 8

**Goal:** turn the proven product into a stable, understandable open-source project people can
install, evaluate, operate, and contribute to confidently.

## 9.1 Freeze and document supported contracts

- Stable CLI commands and exit codes;
- versioned REST and MCP contracts;
- documented AnaxiIndex migration/support window;
- configuration schema and upgrade tool;
- language and deployment support matrices;
- backup/restore and disaster-recovery guide;
- security policy, threat model, vulnerability reporting, and release signing.

## 9.2 Build the public project surface

- Product website with the entropy-control, temporal, provenance, and agent-funded semantic story;
- five-minute interactive demo and sanitized example repositories;
- architecture/history screenshots and short replay video;
- contributor guide organized by analyzers, index, dashboard, MCP, and docs;
- issue templates with analyzer evidence and benchmark reproduction fields;
- public roadmap generated from this plan's current phase, not a list of simultaneous promises;
- governance, code of conduct, release cadence, and maintainer expectations.

## 9.3 Run release candidates on real repositories

Use small, medium, and large repositories across supported languages. Record:

- setup completion and abandonment points;
- current scan/history performance and index size;
- relationship resolution and analyzer mix;
- finding/proposal acceptance and false-positive reasons;
- semantic bootstrap coverage, cost, interruption, and reuse;
- dashboard performance and accessibility;
- upgrade/backup/restore success.

Do not call the product 1.0 until published support claims match these results.

## Phase 9 exit gate

- Fresh-install, upgrade, backup/restore, auth, and uninstall paths pass release-candidate tests.
- No first-party implementation module exceeds 500 lines and no time-limited waiver remains.
- Required CI checks protect the release branch.
- Public documentation makes facts, interpretations, recommendations, privacy, and language support
  unambiguous.
- At least one external contributor can follow the documented setup, add a fixture-backed analyzer
  or detector, and pass all gates without maintainer-only knowledge.
- The website and demo accurately represent shipped behavior.

---

# Cross-phase quality gates

Every phase must satisfy all applicable gates below, not only its own feature tests.

## Correctness

- Unit, integration, CLI-process, REST, MCP, migration, and browser tests for affected behavior;
- deterministic fixture outputs where claims should be stable;
- explicit tests for ambiguity, partial parsing, missing inputs, interrupted jobs, and legacy data;
- no target code execution during scans/history import.

## Maintainability

- 500 physical lines maximum for new/cleared first-party implementation modules;
- no growth in temporary legacy exceptions;
- no new package dependency cycles or layer violations;
- 85% or better changed-code coverage and no unexplained total coverage decline;
- an ADR for schema, public API, dependency, or deployment decisions;
- public types/contracts at service boundaries rather than unstructured dictionaries where a
  stable domain record exists.

## Performance

- Updated benchmark report for scanner, history, index size, API payload, scope payload, and browser
  render paths affected by the phase;
- counters that distinguish discovery, reads, analysis, resolution, reuse, persistence, and render;
- explicit memory and payload ceilings for large fixtures;
- no performance claim without fixture, hardware/environment metadata, and before/after result.

## Trust and security

- extracted/inferred/ambiguous/unresolved provenance preserved;
- semantic provider/model/prompt/schema and evidence retained;
- no credential in repository configuration, logs, fixtures, or index exports;
- repository authorization enforced wherever team mode exists;
- state-changing behavior audited and idempotent where retries are expected.

## User experience

- loading, empty, partial, failure, cancellation, retry, and success states;
- clear totals whenever results are filtered, paginated, ranked, or omitted;
- keyboard/accessibility and visual regression checks for changed dashboard flows;
- onboarding and operator docs updated in the same phase, not deferred.

# Metrics that decide whether the roadmap is working

| Product question | Metric |
|---|---|
| Can a new user reach value? | Commands and median minutes to dashboard, MCP connection, and first semantic dossier |
| Can a real repo finish history? | Wall time, source reads, analyzer invocations, reused versions, index bytes per selected frame/change |
| Can users trust the graph? | Analyzer mix, unique/ambiguous/unresolved relationship rate, parse errors, dynamic-wiring caveats |
| Is the attention queue useful? | Queue size, top-20 action rate, dismissal reason, recurrence, time to resolution |
| Is architecture advice useful? | Proposal review/approval rate, false-positive category, score calibration, verified improvement/regression |
| Is semantic cost controlled? | Current/stale/failed/excluded coverage, input/output tokens, cost, reuse rate, jobs per changed module |
| Is AnaxiGraph staying clean? | Modules over 400/500 lines, cycles, layer violations, complexity, changed-code coverage, hotspot trend |
| Can the dashboard scale? | Initial overview bytes/time, expanded-region bytes/time, peak browser memory, dropped frames |
| Is team mode safe? | Unauthorized access tests, scoped-token isolation, audit completeness, rotation/revocation tests |

# Explicitly deferred ideas

These are not started while a numbered phase above is open:

- a Rust scanner rewrite before profiling proves Python/parser libraries are the remaining limit;
- a vector database as a substitute for the versioned graph and canonical dossier contracts;
- automatic code deletion or unreviewed autonomous refactors;
- a hosted multi-tenant service before local/team auth and isolation are proven;
- PDF/media ingestion before deterministic code, schema, and deployment context;
- all-language marketing based only on file-extension recognition;
- batching every Git blob before delta-driven avoidance is implemented;
- new dashboard visualizations that do not answer a decision or workflow question.

# Immediate implementation queue

Development begins with this exact order. Each item cites the section that specifies it, so the
queue and the document cannot drift apart.

| # | Item | Specified in |
|---:|---|---|
| 1 | **COMPLETE** — Add the reproducible history/storage/performance benchmark and capture baseline output | §0.1 |
| 2 | **COMPLETE** — Ratify the Phase 1a and 1b numeric targets from that report and write them into this document | §0.1 |
| 3 | **COMPLETE** — Add the module-size checker, the current eight-file ratchet baseline, and checker tests | §0.3 |
| 4 | **COMPLETE** — Add tracked pre-commit configuration and installation documentation | §0.2 |
| 5 | **COMPLETE** — Run the same size/lint/test checks in CI and make them eligible as required checks | §0.2 |
| 6 | **COMPLETE** — Add the complexity, cycle, coverage, and layer budgets as warnings and no-growth ratchets | §0.4 |
| 7 | **COMPLETE** — Publish the internal architecture ADR, the package-layer policy, and its characterization tests | §0.5 |
| 8 | **COMPLETE** — Formalize and version the existing analyzer IR, add conformance tests, and certify the Python analyzer | §0.5 |
| 9 | **COMPLETE** — Document `init --start`, correct the README's team-install claim, record PyPI 0.1.0, and prepare next-release PEP 639 metadata | §0.6 |
| 10 | **COMPLETE** — Publish the supported platform matrix, including the Windows decision | §0.7 |
| 11 | **COMPLETE** — Close the Phase 0 exit gate and record its reproducible evidence | §0 gate |
| 12 | **COMPLETE** — Build `P1a.1`, the temporal correctness characterization suite on today's schema | §1a.1 |
| 13 | **COMPLETE** — Discover selected-frame changes before reading source and carry unchanged analysis and safe relationship rows forward | §1a.2 |
| 14 | **COMPLETE** — Expose conservative invalidation reasons and work counters in benchmark and product surfaces | §1a.3 |
| 15 | **COMPLETE** — Replace baked-in 64-frame defaults with an explicit adaptive history policy | §1a.4 |
| 16 | **COMPLETE** — Make history import a resumable, cancellable job without blocking current intelligence | §1a.5 |
| 17 | **COMPLETE** — Characterize schema-6 migration rollback/backup behavior and freeze canonical frame reconstruction fixtures | §1b.1 |
| 18 | **COMPLETE** — Introduce immutable file/symbol facts, relationship sets, and snapshot delta tables behind the index abstraction | §1b.1 |
| 19 | **COMPLETE** — Migrate a copied schema-6 index transactionally, validate it, preserve backup recovery, and expose `doctor`/compaction reporting | §1b.1 |
| 20 | **COMPLETE** — Route snapshot reads through bounded reconstruction with disposable checkpoints and measured read amplification | §1b.2 |
| 21 | **COMPLETE** — Prove semantic/finding/history compatibility and unchanged canonical results across migration, retry, and checkpoint rebuild | §1b.1–1b.2 |
| 22 | **IN PROGRESS** — Run and record the complete Phase 1b storage, migration, read-latency, and quality exit gate before onboarding work begins | Phase 1b gate |

Items 9 and 10 are the user-visible Phase 0 changes. The completed 0.1.0 publication is the narrow,
recorded exception described in §0.6; the work that remains in these queue items is restricted to
documentation and release metadata, so it cannot interact with the temporal rewrite that follows.

This order deliberately starts with evidence and guardrails. It ensures the history rewrite does
not expand `storage.py` and `scanner.py` further, and it makes every later feature pay the same
architectural discipline AnaxiGraph asks of the repositories it analyzes.

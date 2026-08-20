# Product development plan

## Outcome

AnaxiGraph should be a persistent engineering memory for a repository, not only a graph viewer. It
must help a person understand the codebase, decide what deserves attention, hand an approved task
to a coding agent, and verify whether the resulting change improved the architecture.

The product loop is:

```text
observe -> explain -> decide -> plan -> implement with an agent -> rescan -> verify -> remember
```

Repository enrollment begins with a complete semantic bootstrap. AnaxiGraph first builds the
deterministic graph, then configured AI workers read every eligible first-party module so the
repository starts with a coherent semantic baseline rather than a patchwork of descriptions.
After that baseline, deterministic scans and hashes make maintenance incremental: only new,
meaningfully changed, context-stale, or explicitly expired understanding is sent back for AI
analysis.

## Product thesis — a temporal architecture advisor

AnaxiGraph's moat is not a prettier dependency diagram. It is the combination of repository
memory, evidence-aware architectural judgment, and a safe handoff to coding agents. The product
should continuously answer four questions:

1. **What does this code mean?** Every module and important symbol has a durable dossier: purpose,
   responsibilities, contracts, side effects, architecture role, history, and provenance.
2. **What deserves attention now?** Findings are ranked by risk, churn, blast radius, confidence,
   and coverage—not dumped as an unprioritized linter feed.
3. **How could the design improve?** The advisor finds repeated responsibilities, duplication,
   misplaced boundaries, dead-code candidates, and pattern opportunities at symbol, module,
   subsystem, area, and repository levels.
4. **How should new work fit?** Before an agent edits code, AnaxiGraph supplies local precedents,
   affected contracts, likely files, protected boundaries, relevant tests, risks, and a verification
   plan. After the edit, the next scan checks the intended outcome.

The core promise is: **keep AI-accelerated codebases understandable and architecturally sound as
they evolve, without pretending uncertain static or model-derived evidence is fact.**

## Product mechanics worth adopting

We should borrow proven mechanics, not product identities:

- From [CodeScene's hotspot model](https://codescene.com/product/hotspots): combine complexity with
  change frequency and blast radius so the first ten recommendations matter more than the next
  hundred threshold breaches.
- From [Graphify's evidence model](https://github.com/ChrisRoyse/Graphify): make extracted,
  inferred, ambiguous, and unresolved relationships inspectable. AnaxiGraph extends this with
  lifecycle state and temporal provenance.
- From [Knip's reachability approach](https://knip.dev/explanations/entry-files): begin unused-code
  analysis at configured entry points and model dynamic/framework conventions before suggesting
  deletion.
- From [PMD CPD](https://pmd.github.io/pmd/pmd_userdocs_cpd.html): use token/structure similarity as
  deterministic evidence for repeated implementation before asking semantic analysis whether the
  responsibilities are actually the same.
- From [ArchUnit](https://www.archunit.org/) and
  [OpenRewrite](https://docs.openrewrite.org/): express architecture expectations as testable
  policy and represent approved refactors as reviewable recipes with explicit preconditions.
- From Git's [`cat-file --batch`](https://git-scm.com/docs/git-cat-file): batch historical object
  reads so temporal reconstruction remains practical on large repositories.

We do not adopt recommendations merely because another tool emits them. Every AnaxiGraph verdict
must expose evidence, counter-evidence, confidence, expected benefit, migration cost, and the
conditions that would invalidate it.

## Immediate trust-and-signal foundation

This slice precedes richer pattern advice because architectural recommendations are only as honest
as their dependency evidence and only as useful as their ranking.

- **Shipped:** persist each extracted reference as `resolved_internal`, `ambiguous_internal`,
  `unresolved_internal`, or `external`, including candidate paths instead of silently losing them.
- **Shipped:** publish relationship-resolution and analyzer-mix metrics through AnaxiIndex,
  REST, AnaxiMCP, and the dashboard.
- **Shipped:** suppress file-deletion advice when graph resolution is below a configured trust
  threshold, and treat ambiguous candidates as possible incoming use.
- **Shipped:** rank task-context findings and enforce a byte budget on MCP scope payloads while
  preserving primary files and policy references.
- **Shipped:** rank the global finding ledger using severity, confidence, churn, complexity,
  fan-in/blast radius, affected breadth, regression state, and imported coverage. The dashboard
  opens on a top-ten queue with the full ranked ledger available on demand, and reference-file
  size is excluded from source refactor triage unless policy explicitly opts in.
- **Next:** batch Git history extraction and deduplicate unchanged temporal facts before increasing
  default history depth.
- **Next:** replace the JavaScript lexer and long-tail fallback with parser-backed analyzers,
  beginning with tree-sitter JavaScript/TypeScript, Go, Rust, Java, and C/C++.

Acceptance criteria for this foundation:

- An unresolved import is visible as unresolved evidence and never mislabeled as a known external.
- The overview explains what fraction of likely internal references resolved uniquely and which
  analyzer class covered each file.
- “Possible dead code” never appears solely because the resolver discarded a plausible inbound
  edge, and no deletion recommendation is emitted when the graph is below the trust threshold.
- A normal agent scope response stays under its configured wire budget, prioritizes findings that
  touch primary task files, and reports exactly what was omitted.
- Backend and browser tests prove the evidence state and its user-visible explanation.

## Implementation status — 20 August 2026

The current shareable slice now includes:

- the AnaxiGraph browser identity, repository-neutral header, and current-repository selector
- the AnaxiIndex name for persistent module, relationship, finding, and history records
- the AnaxiMCP name for the agent-facing protocol surface
- an operator-owned multi-repository YAML registry backed by one durable SQLite database
- per-repository scan/config selection across dashboard, REST, watcher, and MCP tools
- background Git history reconstruction from the initial first-parent commit through HEAD
- evenly sampled lifetime frames for large repositories, with every-commit CLI mode when needed
- a viewport-height graph by default, normal/tall alternatives, and a squarer maximum layout
- color-coded architecture regions behind modules
- history playback that preserves the user's pan, zoom, and selected module across frames
- a sortable, filterable module inventory exposing file purpose, architecture placement, LOC,
  complexity, coupling, imported coverage, Git biography, findings, and deterministic attention
- weighted architecture regions sized by their module populations, with outlined, grid-spaced nodes
- explicit coverage-input diagnostics that distinguish missing reports from unmatched reports and
  measured zero coverage
- an agent-funded semantic executor: a connected coding agent claims bounded work over AnaxiMCP,
  uses its own model/tokens, and writes a strictly validated dossier back to AnaxiIndex under an
  expiring repository-scoped lease

The immediate slice is the trust-and-signal foundation above. The next temporal slice is the commit
bibliography: milestone-aware sampling, commit subjects and architecture deltas in the UI, stable
graph-delta animation, speed controls, compare mode, and client-ready exports. Module dossiers,
intent history, and pattern scoring then become the primary intelligence layer rather than a
distant visualization add-on.

Three kinds of information must remain visibly separate:

1. **Facts** are deterministic observations such as hashes, imports, symbols, complexity, Git
   changes, and imported coverage.
2. **Interpretations** are inferred intent, responsibilities, architecture roles, and pattern
   classifications. They always carry provenance and confidence.
3. **Recommendations** are scored proposals. They are never automatic permission to refactor.

## Product vocabulary

The architecture hierarchy is:

```text
repository -> area -> subsystem/capability -> module (file) -> symbol
```

For MaxOS, `backend` and `frontend` are areas. `backend-api`, `backend-services`,
`backend-models`, and `backend-migrations` are children of the backend area. They are separate
because they have different responsibilities and dependency rules, but the overview should roll
them up under one backend family. A configured group is matched from repository policy; an
inferred group is a lower-confidence fallback derived from path and runtime conventions.

A finding is an observable condition, not a task by itself. Its lifecycle is:

```text
new -> acknowledged -> planned -> automatically verified as resolved
  \                         \
   -> dismissed             -> regressed if the detector sees it again
```

- **Acknowledge** means “I reviewed this; keep monitoring it.”
- **Plan** means “This is approved engineering work and should appear in the agent queue.”
- **Dismiss** means “This is not actionable or is an accepted exception.”
- **Resolved** should normally be assigned by a later scan after the condition disappears.
- **Regressed** means a previously resolved condition has returned.

## Phase 1 — explainable observatory and agent handoff

This is the first implementation slice.

### Dashboard

- Roll subsystem groups into color-coded parent areas while retaining their individual metrics.
- Explain configured versus inferred grouping and give every configured MaxOS group a purpose.
- Add an indexed-repository selector and keep every dashboard query scoped to its repository ID.
- Explain every graph overlay, including what missing coverage means and when “agent safety” has
  enough context to be useful.
- Make the graph viewport tall/focused/fullscreen and provide a reliable “fit graph” action.
- Replace internal terms such as “work envelope” and “reverse traversal” with task-oriented copy.
- Show the recommended action and detector provenance on every finding.
- Replace ambiguous finding buttons with the lifecycle above.
- Let “Plan agent work” build a concrete handoff containing affected files, dependencies,
  relevant tests, protected paths, existing rules, risk, and verification steps.
- Make historical snapshots playable when more than one snapshot has been imported.

### REST and MCP

- Expose the shared product glossary to the dashboard and agents.
- Add a single-finding context endpoint/tool so an agent can retrieve the same handoff shown in
  the dashboard.
- Keep `ANAXIGRAPH_FINDINGS(status="planned")` as the explicit human-approved queue.
- Continue to include active findings and architecture rules inside task scope results.

### Acceptance criteria

- A new user can explain why backend API and backend services are different without reading YAML.
- A user can tell exactly what acknowledge, plan, dismiss, resolved, and regressed mean.
- Planning a finding produces a prompt and structured context usable by Codex through MCP.
- Switching between two already indexed repositories changes all views without data leakage.
- Missing coverage is shown as missing input, not as zero coverage.
- The graph can use the available viewport and can replay imported snapshots.

## Phase 2 — multi-repository runtime and safe container operation (foundation shipped)

Compose now mounts a primary target at `/repo`, a read-only collection root at `/repositories`,
and an explicit registry at `/config/repositories.yml`. The dashboard can refresh only paths in
that registry; selecting a repository never becomes a general host-filesystem browser.

### Design

- **Shipped:** registry keys, read-only container paths, config paths, and history frame budgets.
- **Shipped:** one dashboard/MCP endpoint for multiple repositories, with optional repository
  selectors on MCP tools and `ANAXIGRAPH_REPOSITORIES` discovery.
- **Shipped:** registry-wide scan-on-start and watcher operation.
- **Next:** persist the registry key separately from the checkout path so moving a mount never
  creates a second logical repository.
- **Next:** general scan job progress, cancellation, scheduling, and last-success/error state (Git
  history import already reports background progress).

### Acceptance criteria

- Two repositories remain independently selectable across container rebuilds.
- A dashboard request cannot scan an unregistered path or cross repository IDs.
- Each repository can use its own `.anaxigraph.yml` and schedule.
- The one-repository Compose path remains the simple default.

## Phase 3 — temporal reconstruction and graph playback (baseline shipped)

History must describe the evolution of the repository rather than merely list scan times.

### History import

- **Shipped:** background first-parent history reconstruction, evenly distributed lifetime
  sampling, every-commit CLI mode, and a Git date range.
- Adaptive sampling always includes the first commit, releases/tags, architecture-changing
  commits, regular calendar checkpoints, and dense recent history.
- **Shipped:** the initial and HEAD commits are always retained; historical scans reuse their prior
  sampled frame as the incremental baseline.
- Persist commit subject, author/time, changed files, architecture deltas, and analysis provenance.

### Bibliography and playback

- Render a commit bibliography with milestones, additions/removals, dominant areas, findings
  introduced/resolved, and pattern changes.
- Store graph deltas (node/edge add, remove, move, change) between snapshots.
- **Partly shipped:** module positions derive from stable path hashes, the camera and selection stay
  fixed during replay, and parent architecture regions remain visible. Explicit node/edge delta
  animation remains.
- Provide play/pause, speed, scrub, compare, date range, and exportable client presentation.

### Acceptance criteria

- Playback begins at the first selected revision and ends at the current working tree.
- A user can select any frame and explain the major change represented by it.
- A 1,000-commit repository can use adaptive history without 1,000 full analyses.
- Historical analysis never checks out or executes target code.

## Phase 4 — AnaxiIndex file intelligence and intent ledger

AnaxiIndex's existing `file_versions` table already stores raw/structural hashes, summaries,
responsibilities, inputs, outputs, side effects, interfaces, groups, and change times. This phase
turns that foundation into an explicit semantic ledger.

### Per-file record

Each file version will expose:

- raw content hash and normalized structural hash
- canonical semantic intent document and `intent_fingerprint`
- short purpose and detailed summary
- responsibilities, inputs, outputs, side effects, and public contracts
- declared and inferred architecture role
- dependencies, dependants, coupling, complexity, coverage, and churn
- first seen, last content change, last structural change, and last intent change
- concise “what changed and why it matters” delta from the prior intent version
- provider/model/prompt version, evidence, confidence, and review state
- semantically related modules and an explanation of whether they collaborate, duplicate, or
  contradict one another
- symbol- and module-level reachability, configured/runtime entry-point evidence, and explicit
  reasons a removal candidate may be a false positive
- local implementation precedents to follow when adding adjacent functionality

**Baseline shipped:** the Modules dashboard and `ANAXIGRAPH_MODULES` expose the deterministic
inventory, current intrinsic/contextual summaries, semantic coverage state, Git dates, and a
reproducible 0–100 attention score. The semantic executor records intent fingerprints, provenance,
evidence, token/cost usage, related responsibilities, pattern opportunities,
consolidation/dead-code assessments, and placement guidance. The attention score remains
deterministic triage—not pattern suitability. Model-backed pattern opportunities now carry a
separate 0–100 contextual suitability score, confidence, evidence, counter-evidence, migration
cost, and preconditions. Calibrated component scoring, durable proposal review, and intent-delta
UX remain future work below.

### Repository semantic bootstrap

**Shipped baseline:** the first semantic run is intentionally comprehensive. It is a resumable repository-enrollment
job with three passes:

1. Build the complete deterministic inventory, symbol index, dependency graph, architecture
   placement, Git biography, and all invalidation fingerprints before invoking a model.
2. Have the configured provider-neutral semantic executor read every eligible first-party module and produce
   canonical intrinsic dossiers. Oversized modules are analyzed in symbol-aware chunks and then
   synthesized; exclusions such as generated, vendored, binary, or explicitly private paths are
   recorded rather than silently omitted.
3. Once intrinsic coverage is complete, synthesize contextual module roles plus subsystem, area,
   and repository understanding from the graph and stored dossiers. This second pass primarily
   consumes compact dossiers and interfaces rather than rereading neighbouring source. Large
   scopes are reduced through bounded synthesis batches before their final repository-level pass.

The bootstrap may be processed in bounded batches, but it is not considered semantically ready
until every eligible module is current, explicitly excluded, or visibly failed. It must survive
restart, expose progress and estimated/actual token cost, and prioritize architectural cores and
high-blast-radius modules without treating partial priority coverage as a completed baseline.

Static facts decide what source the executor receives. AI output is a versioned interpretation and
never overwrites parser facts. The operator chooses the provider: a hosted API, a non-interactive
Codex/Claude command adapter, a connected coding agent using its own tokens through AnaxiMCP, an
OpenAI-compatible endpoint, or a local model implementing the same structured contract.

### Incremental pipeline

```text
raw hash unchanged       -> reuse the complete prior record
raw changed, structure same -> update metadata/docs; reuse structural and semantic claims
structure changed        -> reparse and compare the canonical intent document
intent fingerprint changed -> run semantic delta analysis and downstream pattern evaluation
```

Source-bound and context-bound understanding are invalidated separately:

- `raw_hash` detects any byte change.
- `structural_hash` determines whether intrinsic source understanding may be reused.
- `interface_hash` tracks public symbols, signatures, exports, endpoints, and contracts.
- `relationship_hash` tracks resolved imports, calls, callers, and dependency evidence.
- `semantic_input_hash` covers the structured source/facts input plus schema, prompt, and model.
- `intent_fingerprint` hashes normalized canonical intent rather than generated prose.
- `context_fingerprint` tracks the graph neighbourhood and relevant neighbour interfaces/intents.

An interface or relationship change can therefore refresh the contextual role of dependants
without paying to reread their unchanged source. An intent change invalidates affected subsystem
summaries and pattern candidates rather than triggering a repository-wide semantic rerun.

### Refresh policy and semantic work queue

Every deterministic scan performs the inexpensive hash/fingerprint comparison. Repository policy
then controls when stale semantic jobs run: manually, after a scan, continuously through the
watcher, on a periodic schedule, or during a nightly/CI reconciliation. A periodic review checks
the entire module ledger for missing, failed, low-confidence, model/prompt-stale, or age-expired
records; it does not blindly resend unchanged source.

**Shipped:** the durable semantic queue records repository/module/version, invalidation reason, input hash,
priority, provider/model/prompt/schema version, attempts, timestamps, token/cost estimates and
actuals, and result/error state. Priority order begins with missing dossiers, structural changes,
public-interface changes, high-centrality affected modules, contextual invalidations, and finally
routine age-based review. Per-repository budgets, concurrency, cadence, path/egress rules, and
maximum semantic age remain operator controlled. Provider credentials stay outside repository
configuration.

**Shipped:** `semantic.provider: agent` splits planner/persistence from inference. WORK claims one
job with an opaque expiring token; oversized source or dossier evidence is paged; SUBMIT rechecks
the repository snapshot and semantic contract, validates the complete dossier, and writes only
AnaxiIndex. SCHEMA/EVIDENCE are annotated MCP reads, while WORK/SUBMIT/RELEASE are explicit
non-destructive index writes. Executor identity/model are retained as provenance, unreported agent
token use is not fabricated, completed submission retries are idempotent, and interrupted work is
reclaimable in a later coding-agent session.

The dashboard reports semantic coverage as current, pending, context-stale, failed, and explicitly
excluded modules, along with last reconciliation and estimated refresh cost. An initial full
bootstrap and later incremental refreshes use the same queue and canonical dossier contract.

The intent fingerprint is a hash of canonical structured intent, not a hash of prose or source
bytes. LLM-derived intent remains optional and cached. Deterministic summaries provide a lower
confidence fallback, and no semantic claim is presented as parser fact.

### Acceptance criteria

- The inventory answers what a file does, who uses it, what it uses, and when its meaning changed.
- A module dossier answers “what owns this responsibility elsewhere?”, “should these modules
  merge?”, “is any symbol or whole module plausibly unused?”, and “where should adjacent work go?”
  without asserting more than its evidence supports.
- Initial repository enrollment reads every eligible first-party module and reaches an auditable
  terminal state of current, explicitly excluded, or failed; interrupted enrollment resumes.
- An unchanged repository can be reconciled repeatedly without new source-reading model calls.
- A structural, interface, or relationship change invalidates only the appropriate intrinsic,
  contextual, and ancestor records, and the dashboard explains why each refresh was scheduled.
- Users can choose manual, on-scan, watcher, or periodic semantic refresh and enforce per-run or
  per-period cost limits without losing the eventual full-baseline requirement.
- Documentation-only edits do not create false intent changes.
- Model or prompt upgrades do not silently masquerade as code changes.
- Every semantic delta links back to source evidence and its prior version.

## Phase 5 — coding-pattern intelligence and scored proposals

Pattern analysis operates at symbol, module, subsystem, area, and repository levels.

### Pattern catalogue

- Detect existing implementations of patterns such as provider adapters, strategy/registry,
  repository, service boundary, event handling, dependency injection, orchestration, and shared
  contracts.
- Detect repeated change shapes and duplicated responsibilities even when names differ.
- Evaluate new proposals against local precedent, coupling, change frequency, test seams,
  ownership boundaries, migration cost, and expected future variants.
- Link each proposal to supporting and contradicting examples in the repository.
- Distinguish consolidation, extraction, relocation, interface stabilization, pattern adoption,
  and removal proposals; do not force every issue into a named Gang-of-Four pattern.
- Compare proposed new functionality with the current architecture and return a build guide:
  preferred extension point, existing abstraction to reuse, files/contracts likely to change,
  anti-patterns to avoid, tests to extend, and post-change invariants to verify.

### Scoring

Every proposal receives a 1–100 suitability score with visible components:

```text
fit to repeated problem       0-25
coupling/cohesion improvement 0-20
consistency with local design 0-15
testability/safety benefit    0-15
expected reuse/change value   0-15
implementation/migration cost 0-10 deduction
```

Confidence is reported separately from suitability. “82 suitability, 54 confidence” means the
pattern looks valuable if the inferred facts are correct, but more evidence or human review is
needed. The score must never hide its evidence or trade-offs.

Every proposal also reports separate 1–100 dimensions for expected benefit, implementation
urgency, and execution safety. A high-fit abstraction can therefore remain low urgency, while a
high-value but low-safety removal remains a review candidate rather than agent-ready work.

### Review workflow

- Proposal states: candidate, reviewed, approved, rejected, planned, implemented, verified.
- Human decisions and rationale become durable repository memory.
- Approved proposals produce the same bounded agent handoff as findings.
- A rescan verifies whether the intended pattern was introduced without creating new violations.

### Acceptance criteria

- A provider-abstraction proposal identifies the repeated OpenAI/Anthropic/Gemini behavior that
  supports it and counterexamples that weaken it.
- Scores are reproducible from stored components and change when the evidence changes.
- Rejecting a proposal records a rationale and reduces repeated low-value suggestions.

## Phase 6 — continuous review and integrations

- Scheduled deterministic scans plus configurable manual, on-scan, watcher, CI/webhook, and
  periodic semantic reconciliation. Schedules inspect the full ledger but enqueue AI work only
  for missing, changed, context-stale, failed/retryable, or policy-expired records.
- Budgets for LLM calls, concurrency, repository size, and historical depth.
- MCP tools for repository overview, file intent, planned work, finding context, pattern proposals,
  impact, and post-change verification.
- Notifications only for newly actionable or regressed signals, not every metric fluctuation.
- Exportable architecture/history reports suitable for client review while preserving repository
  privacy and provenance.

## Delivery sequence

1. Ship Phase 1 as an explainability and workflow release.
2. Add the repository registry before presenting the selector as an arbitrary filesystem browser.
3. Build background jobs and graph deltas before full-history UI controls.
4. Add the durable semantic queue and complete one resumable full-repository bootstrap into
   canonical intent documents.
5. Add hash-driven invalidation, contextual refresh, configurable reconciliation schedules, and
   semantic coverage/cost reporting.
6. Calibrate pattern scoring on real repositories with reviewed examples.
7. Add broader CI/webhook automation only after review decisions and provenance are durable.

This order keeps each release useful on its own and ensures the expensive semantic and pattern
features rest on understandable, testable repository facts.

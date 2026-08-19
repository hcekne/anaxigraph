# Product development plan

## Outcome

AnaxiGraph should be a persistent engineering memory for a repository, not only a graph viewer. It
must help a person understand the codebase, decide what deserves attention, hand an approved task
to a coding agent, and verify whether the resulting change improved the architecture.

The product loop is:

```text
observe -> explain -> decide -> plan -> implement with an agent -> rescan -> verify -> remember
```

## Implementation status — 19 August 2026

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

The next temporal slice is the commit bibliography: milestone-aware sampling, commit subjects and
architecture deltas in the UI, stable graph-delta animation, speed controls, compare mode, and
client-ready exports. The intent ledger and pattern scoring remain the next major intelligence
layers after that foundation.

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
- Keep `CODEINTEL_FINDINGS(status="planned")` as the explicit human-approved queue.
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
  selectors on MCP tools and `CODEINTEL_REPOSITORIES` discovery.
- **Shipped:** registry-wide scan-on-start and watcher operation.
- **Next:** persist the registry key separately from the checkout path so moving a mount never
  creates a second logical repository.
- **Next:** general scan job progress, cancellation, scheduling, and last-success/error state (Git
  history import already reports background progress).

### Acceptance criteria

- Two repositories remain independently selectable across container rebuilds.
- A dashboard request cannot scan an unregistered path or cross repository IDs.
- Each repository can use its own `.anaxigraph.yml` and schedule; legacy `.codeintel.yml` files
  remain supported.
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

### Incremental pipeline

```text
raw hash unchanged       -> reuse the complete prior record
raw changed, structure same -> update metadata/docs; reuse structural and semantic claims
structure changed        -> reparse and compare the canonical intent document
intent fingerprint changed -> run semantic delta analysis and downstream pattern evaluation
```

The intent fingerprint is a hash of canonical structured intent, not a hash of prose or source
bytes. LLM-derived intent remains optional and cached. Deterministic summaries provide a lower
confidence fallback, and no semantic claim is presented as parser fact.

### Acceptance criteria

- The inventory answers what a file does, who uses it, what it uses, and when its meaning changed.
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

- Scheduled incremental scans, CI checks, webhooks, and nightly semantic/pattern review.
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
4. Migrate the existing file-version data into canonical intent documents.
5. Calibrate pattern scoring on real repositories with reviewed examples.
6. Add scheduled automation only after review decisions and provenance are durable.

This order keeps each release useful on its own and ensures the expensive semantic and pattern
features rest on understandable, testable repository facts.

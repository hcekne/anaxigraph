# AnaxiGraph consecutive development plan

**Roadmap version:** 4.2

**Updated:** 1 September 2026

**Execution rule:** one phase is active at a time; the next phase does not begin until the current
phase's exit gate is met.

## Executive decision

> **AnaxiGraph is the shared architecture intelligence layer for humans and AI agents. It explains
> what a software system does and how its parts work together, while guiding future changes toward
> a cleaner, more coherent design.**

The product has three promises: **understand the system, guide the agent, and keep the architecture
coherent**. That is the admission test for every unfinished feature. Breadth, presentation, and
ecosystem work do not get priority merely because they could make the product look more complete.

The shipped temporal index, relationship provenance, semantic map, pattern catalog, and bounded
agent scope are foundations, not separate products. The dashboard, CLI, and AnaxiMCP are adapters
over one shared architecture model, not separate interpretations of the repository. The principal
using that model may be a person, a coding agent acting for a person, or another authorized system.
No core outcome may depend on a human opening the dashboard, and no core human outcome may require
copying opaque agent payloads by hand.

The central workflow is architecture understanding and guidance, not change management. A principal
asks what the system does, where a requested capability should fit, or how the current design could
be improved. AnaxiGraph answers from current facts, semantic understanding, patterns, and history;
the principal decides whether and how to edit the repository. Formal change contracts, approval
gates, and a decision-management product are deliberately outside the core.

The roadmap follows these refinements:

- **Delta-driven history comes before batched Git reads.** Profiling says analysis of unchanged
  files is currently the dominant cost. `git cat-file --batch` remains a later optimization for
  reading the changed blobs, not the first intervention.
- **Findings are not deleted to make the UI quiet.** AnaxiIndex should retain the complete evidence
  ledger while the product presents a small ranked attention queue and places low-severity
  diagnostics behind an explicit view.
- **Every recommendation must explain itself without a jargon drawer.** Findings, pattern advice,
  consolidation proposals, and possible unused-code reports lead with the observation, consequence,
  sensible action, reasons to leave the code alone, and verification step in ordinary sentences
  that both people and coding agents can act on. Stable detector IDs, machine statuses, and numeric
  ranking inputs remain structured automation fields; moving them to a “technical details” section
  does not count as explaining them.
- **The 500-line rule is a ratchet, not an excuse to freeze the repository or create arbitrary
  499-line fragments.** New oversized modules and growth of existing oversized modules are blocked
  immediately. Existing exceptions are then removed in the phases that touch their responsibilities.
- **Tracked hook configuration and CI are the enforcement mechanism.** Files under `.git/hooks/`
  are local and cannot be versioned. The repository will ship a `.pre-commit-config.yaml`, a
  deterministic size/architecture checker, and the same required CI checks.
- **JavaScript and TypeScript depth is strategic; undirected language breadth is not.** After the
  convergence phase, the regex-oriented JavaScript/TypeScript path is replaced with a parser-backed
  implementation and honest capability reporting. Other languages remain demand-led and cannot
  displace the shared understanding-and-guidance loop merely to increase a supported-language count.
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

### One product, three promises

| Promise | Human outcome | Coding-agent outcome | Existing product surfaces |
|---|---|---|---|
| **Understand the system** | Explain what the software does and move from capabilities and architecture areas to subsystems, files, symbols, relationships, and history. | Reuse a current repository-wide memory instead of rediscovering the system in every task. | Overview, Files, Graph, History, taxonomy, dossiers, file detail |
| **Guide the agent** | Show where a requested change belongs, what already exists, what may be reused, which patterns may fit, and what could be affected. | Receive a bounded working set, extension points, constraints, related tests, evidence, counter-evidence, and verification plan. | Search, scope, impact, pattern evidence, task path |
| **Keep the architecture coherent** | See whether rapid development is introducing sprawl, duplication, weak boundaries, oversized responsibilities, or possible dead code. | Refresh changed facts, compare the same goal after editing, and receive an independent architecture assessment beside test results. | Scan/watch, findings, before/after comparison, history |

AnaxiIndex, extractors, semantic jobs, history jobs, SQLite tables, REST routes, CLI commands, and
MCP queue primitives are enabling machinery. They do not become independent product families,
navigation destinations, or roadmap themes. New work should normally strengthen an existing row
of this map through an existing surface.

AnaxiGraph should help a person or coding agent answer:

1. **What is this system?** See its areas, modules, contracts, relationships, history, and module
   meanings from a repository view down to a symbol.
2. **What deserves attention?** Explain what AnaxiGraph saw and why it may matter, then use measured
   risk, change history, connectivity, test coverage, and affected code to order the work without
   presenting a wall of scores and detector labels.
3. **How could the design improve?** Identify repeated responsibilities, misplaced boundaries,
   consolidation opportunities, dead-code candidates, and suitable patterns with evidence and
   counter-evidence.
4. **What might this system look like with fresh eyes?** Distill behavior without leaking the
   current implementation, obtain independent clean-sheet designs, adjudicate them, and use the
   result as a counterfactual comparator rather than an automatic rewrite target.
5. **Where should new functionality go?** Give an agent local precedents, extension points,
   contracts, protected boundaries, affected tests, and a verification plan before it edits code.
6. **Did the change help?** Rescan, compare the relevant architecture facts, explain improvement or
   regression, and update the shared understanding without requiring a separate change record.

The product loop is:

```text
observe -> understand -> advise -> principal changes code -> reassess
   ^                                                    |
   +----------------------------------------------------+
```

The promise is not “draw a pretty code graph” or “make another AI reviewer.” It is:

> Give people and coding agents one living, inspectable understanding of the software, then use it
> to make the next change fit the system better than an isolated prompt would.

### One model, any principal

“Human-friendly” and “agent-friendly” are presentation requirements over the same use cases, not
two product editions:

- a person may explore the map, read the Architecture Charter, ask for implementation or refactor
  guidance, inspect evidence, add optional context, and refresh the repository through the dashboard;
- a coding agent may install and start AnaxiGraph, create the deterministic map, fund the semantic
  baseline with its own model context, read the same Charter, request the same guidance, inspect the
  same evidence, and reassess after editing through CLI or MCP;
- both receive the same stable identities, confidence, provenance, caveats, and recommendation
  structure, with prose for comprehension and bounded fields for automation;
- human annotations may refine the shared interpretation, but no human-authored setup document,
  approval, comment, or dashboard action is a prerequisite for useful architecture understanding.

Every new core use case therefore begins as an application-level request and response independent
of transport. Dashboard, MCP, and CLI adapters may format or paginate it, but may not invent their
own analysis, vocabulary, lifecycle, or required intermediate object.

### Fresh eyes without architectural amnesia

An agent immersed in an existing repository is good at explaining local constraints but is also
likely to accept accidental structure as inevitable. An agent shown only the required behavior can
design more freely, but may overlook constraints and good decisions already encoded in the running
system. AnaxiGraph should use both perspectives in a controlled sequence:

1. **Distill capability, not implementation.** Derive what the software does, for whom, through
   which workflows, under which externally meaningful constraints and non-goals. Exclude modules,
   packages, tables, frameworks, and current boundaries unless one is itself a public requirement.
2. **Invite independent clean-sheet designs.** Give the same capability-only brief to one or more
   fresh agent contexts. Each proposes a system from first principles without seeing the current
   code architecture or another proposal.
3. **Adjudicate before revealing the legacy.** Compare the independent designs, identify consensus,
   disagreements, assumptions, and trade-offs, and synthesize a reference architecture while the
   adjudicator is still unanchored by the current implementation.
4. **Compare reference and reality.** Only then give a repository-aware agent the synthesized
   reference, current Charter, responsibility map, code evidence, and history. Ask what the current
   design gets right, where it diverges for good reasons, and where accidental complexity remains.
5. **Filter through mission and economics.** Reject ideas that do not advance the product mission or
   that add more complexity, migration risk, or maintenance burden than the expected improvement.
   Preserve useful existing choices even when they differ from the clean-sheet design.
6. **Recommend evolutionary slices.** Produce a small ordered refactor strategy with evidence,
   counter-evidence, expected simplification, protected behavior, and verification—not a wholesale
   rewrite mandate.

The clean-sheet result is a **counterfactual lens**, never architectural truth. Independent agents
can share blind spots, and a beautiful greenfield design may be wrong for a mature repository. The
value comes from deliberately controlling when each reviewer sees implementation detail, preserving
disagreement, and adjudicating every suggestion against the actual mission and constraints.

AnaxiGraph makes this economical because module dossiers and fingerprints already separate changed
understanding from unchanged understanding. If capabilities have not materially changed, the
capability brief and reference architecture can be reused while only the current-architecture
comparison is refreshed. A new clean-sheet review is triggered by a meaningful capability change,
an explicit request, or a deliberately chosen cadence—not by every file edit.

## Feature admission rule

An unfinished feature is **essential** only when it directly improves at least one product question
above. It is **supporting** only when an essential feature cannot remain correct, fast, safe, or
recoverable without it. Everything else is **optional** and does not block the active roadmap.

Before opening implementation, the feature must answer all of these in one short paragraph:

1. Which of the three promises does it strengthen?
2. What concrete human or coding-agent decision becomes easier?
3. Which existing AnaxiIndex fact, interpretation, or recommendation will it reuse?
4. Which existing CLI, MCP, REST, dashboard, graph, semantic, or finding path will deliver it?
5. What can be removed, merged, or replaced as part of the change?
6. What is the smallest end-to-end fixture that can prove the improvement?
7. What new persistent state, provider path, public surface, or abstraction is avoided?

A feature that needs a second analysis platform, another model pipeline, a parallel graph, a broad
plugin framework, or a new primary dashboard screen fails this test unless the existing product
cannot deliver the decision without it. During the convergence phase, an accepted feature must be
production-line neutral or negative unless it fixes security, corruption, or demonstrated
correctness. Optional work is reconsidered only after the core roadmap is complete or concrete user
evidence changes the ranking.

## Current baseline

The values below are the starting point for this roadmap. Performance figures from the external
review must be reproduced by Phase 0 on a committed benchmark fixture before they become release
regression thresholds.

| Area | Current state | Consequence |
|---|---|---|
| Test health | 607 tests passing plus 25 browser contracts; Ruff and every maintainability, size, complexity, coupling, and layer ratchet are clean | The complete local, Docker, normal/executor MCP, packaging, finding, history, rendered first-user, release-identity, pattern-intelligence, actor-neutral guidance, interrupted semantic-resume, fresh-eyes review, post-change comparison, and three-size core-loop paths are regression-tested |
| Relationship evidence | Resolved, ambiguous, unresolved, and external states are persisted and explained | Strong trust foundation; dynamic wiring must continue to be identified as a blind spot |
| Finding priority | A maximum-20 attention queue is separate from the lossless, filterable diagnostic ledger; both retain versioned risk ranking and explicit totals | Routine information-level long-function signals no longer displace actionable work, while no evidence is deleted |
| Scope payload | Approximately 21.5 KB in the reviewed Go-analyzer scenario | Improved, but token-budget behavior needs continued regression tests |
| Semantic understanding | Durable `module-dossier-v4` records, fingerprint invalidation, leased agent work, provenance, budget controls, and explicit composed services | Differentiating foundation; semantic planning, leases, evidence, contracts, persistence, execution, and reporting now evolve behind a stable facade |
| Parser depth | Python AST plus a regex-oriented JavaScript/TypeScript analyzer; other languages use text heuristics | Support claims must disclose those limits; parser-backed JavaScript/TypeScript is committed after convergence, while all further language breadth remains demand-led |
| History benchmark | Measured 3,000-file/eight-frame import: 69.566 seconds, 23,970 blob reads, 23,970 `file_versions` for 3,217 distinct artifact/raw versions, 47,896 relationship rows, and a 49.56 MB vacuumed index | Unchanged source is repeatedly read and snapshot-heavy facts/edges are repeatedly materialized |
| Graph delivery | Versioned overview, page, neighborhood, and delta reads are bounded from SQLite through REST/MCP and the dashboard; a retained 50,000-node fixture stays within time, memory, and payload budgets | Large local indexes can be explored without a monolithic graph response |
| Installation | PyPI and GitHub release 0.3.0 provide one-command local startup, explicit agent connection, the dual-client plugin, generated hardened Compose, and a protected OIDC release workflow; public `uvx --from anaxigraph==0.3.0 anaxigraph` and multi-architecture container artifacts are verified | The first-run distribution barrier is closed and subsequent versions can use the routine short-lived-identity release path |
| Internal module size | Every first-party implementation module is at or below 500 physical lines; the exception list is empty | Phase 3b now locks in the completed dashboard/evaluator decomposition and adds deterministic self-analysis before further feature growth |
| Global implementation size | 77,044 first-party source, dashboard, test, benchmark, and quality-script lines; production contains 47,813 Python lines across 240 modules plus 5,794 dashboard HTML/CSS/JavaScript lines | Phase 10.2 removed complete duplicate paths and is owner-closed; later product work keeps an exact production ratchet and must justify intentional growth without reopening subtraction for its own sake |
| Concentration and warning pressure | Top-level semantic code spans 59 modules/14,247 lines, persistence spans 48 modules/9,526 lines, 18 Python modules plus three dashboard assets are at least 400 lines, and the clean quality gate reports 140 function and 23 coupling warnings | Both near-ceiling packing and small-file fragmentation are visible; Phase 10.2 remains closed, while the hard 500-line and coupling limits continue to prevent unbounded feature growth |
| Public surface | The normal server exposes at most 10 task-level MCP tools, its executor endpoint exposes 7 semantic queue tools, and the dashboard presents five actor-neutral journeys | People and agents now receive the same bounded product workflow while raw lease administration and analyst operations remain deliberately separate |

The modules that were oversized when this roadmap was created were:

| Module | Physical lines at roadmap creation | Planned decomposition phase |
|---|---:|---|
| `src/anaxigraph/dashboard/app.js` | 2,066 | Phase 3b |
| `src/anaxigraph/agent.py` | 898 | Phase 3b |
| `src/anaxigraph/architecture.py` | 731 | Phase 3b |
| `src/anaxigraph/api.py` | 564 | Phase 5A |

All four modules are now within the hard ceiling and the size-exception list is empty. That is a
floor, not a design target: modules approaching 500 lines still need cohesive extraction, and new
implementation modules should normally remain in the 100–350-line range.

## Strategic references

We borrow mechanics with evidence, not product identity:

- [Graphify](https://github.com/Graphify-Labs/graphify) demonstrates the adoption value of a
  skill-first install and inspectable edge origins. AnaxiGraph's answer is a similarly easy entry
  path combined with temporal state, finding lifecycle, and agent-funded write-back.
- [CodeScene hotspots](https://codescene.com/product/hotspots) reinforce the value of combining
  change frequency with code health. AnaxiGraph already uses that principle in finding priority
  and reuses stored changes for task-scoped co-change evidence; that does not require a second
  repository-wide ranking.
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

### The Architecture Charter is inferred first and inspectable always

Every repository receives a living Architecture Charter generated from its code, README files,
documentation, entry points, configuration, extracted relationships, semantic dossiers, reviewed
responsibility map, and relevant history. It is AnaxiGraph's evidence-backed working interpretation
of the system: purpose, capabilities, responsibilities, boundaries, contracts, extension points,
quality concerns, and important unknowns.

The Charter is an **interpretation**, not a deterministic fact and not a form a human must fill in.
Every claim carries evidence, provenance, confidence, and freshness. A human may correct, augment,
or explicitly declare part of it, but inferred and declared statements remain distinguishable and
the absence of human input never prevents generation, refresh, or use. Dashboard, CLI, and MCP read
the same versioned projection. Guidance must identify uncertainty instead of presenting a plausible
summary as certainty.

### Core workflows are actor-neutral

- No architecture understanding, guidance, refresh, reassessment, or semantic-bootstrap capability
  is dashboard-only.
- No normal dashboard task requires a user to understand semantic leases, queue records, transport
  schemas, executor internals, or MCP tool choreography.
- Agent-only operation must be resumable and must not require an interactive human approval in the
  middle of repository-sized semantic work.
- Optional comments, finding lifecycle actions, and saved handoffs may support collaboration. They
  never become a mandatory change contract, approval workflow, or decision ledger.

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
- The quality gate tracks production lines, module count, public surface, dependency direction,
  and per-package cohesion together. Creating a forwarding file or a one-call helper solely to stay
  below 500 lines fails the gate even when every individual file is small.
- Packages that already have high module counts receive non-growth ratchets. An increase requires a
  named responsibility that cannot coherently live in an existing module, removal or consolidation
  elsewhere, and a test at the public boundary.
- Architecture-policy entries must resolve to a current module, path, or declared logical concept;
  stale references to deleted modules fail CI instead of lingering as fictitious structure.
- Interfaces should be explicit; mixin order and hidden shared state are not acceptable extension
  mechanisms for core workflows.
- Storage, analysis, transport, and presentation must communicate through narrow models rather
  than reach through each other's internals.
- Performance and correctness changes begin with a reproducible characterization test.

### Global simplicity matters more than local limit compliance

- Passing a per-file ceiling does not prove the product is lean. Production lines, module count,
  public concepts, default tools, commands, tables, and navigation destinations are tracked too.
- Do not split a cohesive file merely to stay below 500 lines. First remove duplication, obsolete
  compatibility, repeated projections, pass-through layers, and unnecessary branches.
- Tests, evidence fixtures, and migrations that protect real compatibility are not deleted to make
  a line chart look better. The primary reduction target is production machinery and duplicated
  product surface.
- No new primary dashboard destination, default MCP tool, CLI command family, database table,
  provider path, or background coordinator is added during convergence without removing or
  consolidating an equivalent concept.
- A refactor is successful only when behavior remains covered and the resulting responsibility
  map is easier to explain. Fewer lines produced by code golf or larger monoliths are regressions.
- Each pull request records its production-line delta, public-surface delta, and which of the three
  product promises it advances.

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

## Remaining feature re-evaluation

The 25 August self-hosted check found that the served map could lag the checkout and that an agent
worker could stop before its durable queue was complete. Those were core defects. They have now
been fixed and retained as regression gates; they are not reasons to keep expanding lifecycle,
operations, or executor machinery.

The original six coding decisions below are delivered foundations, not a claim that placement and
scope precision can no longer fail. Self-hosted dogfooding remains part of the product loop: a
normal goal that reaches the wrong implementation reopens that decision without reopening the
completed feature families around it.

| Priority | Status | Need-to-have decision | Exit evidence |
|---:|---|---|---|
| 1 | **COMPLETE** | Navigate the responsibility hierarchy | Move from area → subsystem → module → symbol with complete module assignment, an ordinary-language explanation of each group, and no generic catch-all |
| 2 | **COMPLETE** | Place a change in the right code | A real self-hosted goal returns the intended document/module, local precedent, extension point, contracts, and focused tests without unrelated primary files |
| 3 | **COMPLETE** | See the change's likely impact before editing | A real self-hosted module returns its exact direct dependants, bounded transitive impact, and relevant tests with relationship evidence and caveats |
| 4 | **COMPLETE** | Judge pattern fit at the level where the design decision lives | Sparse bounded selection covers genuinely different patterns across repository, area, subsystem, module, type, and symbol levels; obvious candidates are not crowded out by generic patterns; advice includes fit, counter-evidence, and verification |
| 5 | **COMPLETE** | Split a genuinely mixed large file without fragmenting a cohesive one | A controlled mixed-responsibility file gets bounded extraction slices with contracts, callers, tests, and move order, while a self-hosted cohesive near-limit file is explicitly left intact |
| 6 | **COMPLETE** | Verify whether a change improved structure | A real before/after task distinguishes introduced, worsened, improved, resolved, and unchanged or pre-existing effects for boundaries, coupling, cycles, size, complexity, and responsibility placement |

The remaining active list is intentionally short:

| Priority | Status | Core question | Smallest acceptable evidence |
|---:|---|---|---|
| 1 | **COMPLETE on 26 August 2026** | Can a normal concept-level goal find the responsible implementation without already naming its file? | The self-hosted architecture-verification goal selects `agent_decision_verification.py`, its comparison symbols, and a meaningful reviewed hierarchy instead of release, relationship, or generic overflow code |
| 2 | **COMPLETE on 26 August 2026** | Is the returned primary working set small enough that an agent can trust what it should actually read? | The same live goal returned five coherent verification/change-decision files, chose the verification module and comparison symbols, and included no release or unrelated primary file |
| 3 | **COMPLETE on 26 August 2026** | When adding a responsibility, does the map make extend-existing versus create-new clear enough to prevent file sprawl? | A self-hosted goal returns an existing responsibility and extension point when one exists, while a controlled fixture permits a new sibling only when no honest home exists |

Impact traversal, pattern fit, large-file decomposition, and before/after verification remain hard
regression gates. They do not become new feature phases unless a concrete coding task demonstrates
that their current answer is wrong or unusable.

The live pattern run completed 200 bounded reviews across 91 distinct patterns and retained specific
provider-abstraction advice without letting generic patterns occupy the queue. Large-file dogfooding
then exposed a fragmentation defect: a 169-line file could receive a three-part extraction plan.
Large-file decomposition now starts only when a file breaches or reaches 80% of its configured size
limit. The rebuilt MCP response kept the 445-line module reader together, excluded the 169-line file
from this workflow, and retained the controlled 620-line mixed-file extraction contract.

The self-hosted before/after check then exposed a wire-budget defect: the 19.8 KB verification
baseline was removed and the final response used only 5.5 KB of its 20 KB allowance. The existing
decision compactor now removes repeated finding prose while retaining module measurements, finding
identities, pattern facts, repository and goal identity, and enough explanation to rebuild readable
defaults. The same live scope is 17.0 KB with its 11.8 KB baseline intact. Comparing snapshots 263
and 269 then reported the target file's size and branch growth separately from reduced incoming and
outgoing coupling, while stating that those directions are not an overall code-quality verdict.

A code change belongs in the active roadmap only when it closes the current decision, prepares the
next listed decision without implementing it early, or fixes a defect directly demonstrated by the
current decision. One authoritative map, durable bounded semantic execution, the 500-line ceiling,
focused regression tests, and the existing release pipeline are supporting gates. They may be
repaired when they block a core decision, but they do not create feature families of their own.

The following are nice-to-have, not active product work: broader parsers and adapters, more
dashboards or API families, generic operational tooling, provider-specific orchestration,
warning-cleanup campaigns, additional explanatory-language sweeps, ecosystem work, and
release-process expansion. The paused MaxOS run is optional external evidence, not a feature or a
release blocker; it stays untouched until the operator explicitly resumes it. AnaxiGraph
dogfooding remains required because it directly tests the need-to-have decisions.

The concept-level live probe selects the intended five-file verification/change-decision set
and the exact comparison symbols. It also exposed a separate hierarchy defect: when an AI proposal
contained seven useful areas under a six-area limit, deterministic validation deliberately replaced
the smallest areas with `Other responsibilities`. The validator now retains all six allowed
meaningful areas and merges only excess areas into the closest retained responsibility using the
group descriptions and member paths. A focused fixture proves the merge and rejects the generic
overflow area.

The authoritative sidecar recheck completed on snapshot 316 in semantic run
`9c7dbdf7-ffb1-4286-83f3-45c9fd293c3c`, using `gpt-5.6-terra` at medium reasoning with up to 30
parallel calls. The two-pass reviewed map assigns all 470 modules to six meaningful areas and 22
subsystems with no validation issue or repair. The ordinary concept goal selected
`agent_decision_verification.py`, `compare_verification_baselines`, `verification_baseline`, and
`_comparison_status`; its five primary files were all part of change-decision verification. Its
reviewed route is `Prepare change help and AI code reports` →
`Choose files and explain a requested change`, not a path-derived or generic overflow group.

The live extend-existing probe, “Add another saved query for semantic job token telemetry,” selected
`semantic_status_queries.py`. It returned the module's saved-query responsibility, the
`SemanticStatusRows` and `read_semantic_status` contracts, and the existing extension point for
adding one small query and wiring it through `read_semantic_status`. The large-file decomposition
contract already prefers a supplied matching module; a focused paired fixture now proves that it
returns `new_file_candidate` only when no supplied destination matches the separate job, while
retaining the caller-facing responsibility in the original file.

Warning cleanup is also not an automatic queue. Fix a warning when it blocks a hard gate, touches
code already being changed for a core outcome, or describes a demonstrated product defect. A clean
non-regression baseline is sufficient otherwise. In particular, do not create another explanatory
module merely because an adjacent administrative response could be worded more elegantly.

## Historical delivery record

The phases below explain how the current product was built and preserve their acceptance evidence.
Completed phases are not a backlog. Phase 9 is the bounded dogfood-and-release wrapper around the
need-to-have decisions above.

| Order | Phase | Primary outcome | Must be complete before |
|---:|---|---|---|
| 0 | Engineering guardrails and reproducible baselines | New work cannot increase internal architectural debt | Any feature phase |
| 1a | Delta-driven temporal discovery | History import stops re-analyzing unchanged files, on today's schema | Any storage change |
| 1b | Immutable facts and snapshot deltas | Stored facts scale with distinct versions rather than selected frames | More history features or broader parsers |
| 2 | Attention signal | Users see a small, actionable, fully accounted queue | Onboarding promotion |
| 3 | One-command local adoption | One command opens a dashboard; a second or option connects an agent | Agent-workflow promotion |
| 3b | Dashboard/evaluator decomposition and self-analysis | Frontend and core evaluators stay maintainable; AnaxiGraph checks itself in CI | Pattern evidence work |
| 4A | Pattern-ready evidence contract | Analyzers declare comparable capabilities and expose reusable evidence from function to repository scale | Pattern intelligence and any future evidence adapter |
| 5A | Bounded graph and operational APIs | Large local indexes remain bounded from database to browser and the API composition root stays small | Pattern query surfaces |
| 6 | Architect-grade semantic and pattern intelligence | An extensible catalog of at least 120 patterns is evaluated across code hierarchies and independently reviewed by agents | Change-safe architecture guidance |
| 7 | Change-safe architecture loop | Agents and people get placement guidance before a change and a focused entropy comparison afterward | Focused temporal risk signals |
| 8 | Focused history evidence for architecture risk | Co-change and introduction/resolution history improve the current task decision | 1.0 scope freeze |
| 9 | Make the real core loop dependable, then prove it for 1.0 | The current authoritative map reaches a useful autonomous hierarchy and gives bounded architecture decisions through stable agent-facing paths | 1.0 release |

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
cohesion remains a confidence-gated, non-blocking advisory report: responsibility breadth or a high-scoring
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
migration during Phase 4A or 4B.

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
Python analyzer rewrite. Phase 4A becomes conformance and extension rather than first definition.

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
3. **COMPLETE — Modernize license metadata.** Package metadata uses the SPDX expression
   `license = "Apache-2.0"`, declares `license-files = ["LICENSE"]`, and requires `setuptools>=77`
   for PEP 639 support. A clean wheel/source build emits `License-Expression: Apache-2.0` and
   `License-File: LICENSE`, with no prior license-table deprecation warning. PyPI artifacts are
   immutable, so 0.1.0 remains unchanged; the correction shipped in 0.2.0 and remains verified in
   the public 0.4.0 release.
4. **COMPLETE — Make the local operating boundary explicit.** Every public setup guide leads with
   the loopback sidecar and explains the supported local and Docker paths without presenting a
   larger deployment topology as current product scope.

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
  metadata are recorded; and the README presents the supported local operating boundary clearly.
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
- Semantic claims continue to reference the appropriate immutable version, retain prompt/context
  fingerprints, and record provider/model only as execution provenance.
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
| Compaction | All four compatibility tables are absent; SQLite integrity, semantic-fact references, lineage, foreign keys, and reconstruction are doctor-checked |
| Decomposition | `storage.py` is 398 lines and `scanner.py` is 358; both exceptions are removed and no extracted implementation module exceeds 500 lines |
| Agent contract | The Go-analyzer scope retained all eight expected primary files, no unexpected primary files, and a 5,757-byte payload |

---


# Phase 2 — attention signal

**Status:** COMPLETE

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

- what AnaxiGraph actually saw, in a sentence a smart twelve-year-old can understand;
- why that observation could make the code harder to understand, test, or change;
- what could make the current design reasonable as it is;
- affected modules, contracts, tests, and blast radius;
- the smallest sensible next action, including the option to leave clear code alone;
- how focused tests and a later scan will check the result without calling every changed number an
  improvement.

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

**Closure evidence (20 August 2026):**

| Contract | Delivered evidence |
|---|---|
| Bounded attention | The configurable default is 20 results; planned and regressed work remains visible, while information-level `long_function` diagnostics are excluded unless policy explicitly opts in |
| Lossless diagnostics | The dashboard and REST surface filter the complete ledger by detector, module, architecture area, status, severity, and confidence; explicit exports traverse every cursor rather than inheriting a hidden 500-row cap |
| Stable pagination | Opaque query-bound cursors use priority, regression state, first detection, and stable key ordering; every page reports shown, total, per-dimension counts, next cursor, and exact omissions |
| Agent budget | `ANAXIGRAPH_FINDINGS` accepts a token budget, returns a compact actionability record, proves the estimated payload stays inside it, and reports results displaced by that budget |
| Actionability | Each finding now distinguishes deterministic from attached semantic evidence, lists false-positive conditions, affected modules/areas/contracts/tests and blast radius, classifies the action, proposes the smallest next step, and explains scan-based verification |
| Plain-language contract | `plain-language-v2` makes the observation, consequence, action, intentional-design caveats, and verification rule canonical across REST, MCP, the dashboard, scope results, and copied agent prompts. Cards show that reasoning directly; queue scores, confidence, source IDs, and detector keys remain structured automation data rather than a heading or hidden jargon section |
| Lifecycle | The dashboard exposes review, plan, accept-risk, dismiss, reopen, and handoff actions; a characterization test proves a later scan resolves the same stable key and marks it regressed when the condition returns |
| Browser contract | All 12 containerized Playwright scenarios pass, including attention/diagnostics switching, grouped long-function diagnostics, filters, cursor-driven loading, and persisted lifecycle actions |
| Maintainability | The API is 564 lines (down from 579), MCP server 427 (down from 461), CLI 555 (down from 557), and dashboard application 2,066 (down from 2,091); extracted finding modules remain below 500 lines and all ratchets pass |

---

# Phase 3 — one-command local adoption

**Status:** COMPLETE — 0.2.0 PUBLICLY VERIFIED

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

### Phase 3.1 closure evidence

**Completed in source on 20 August 2026.** The 0.2.0 source version became the immutable `v0.2.0`
release on the same date. The release outcome and its one remaining operational hardening action are
recorded below and in `docs/releasing.md`.

| Contract | Delivered evidence |
|---|---|
| One authored version | `project.version` is the authored value; package, CLI, and FastAPI versions derive from installed distribution metadata, and tag validation requires exact `v<version>` parity |
| Reproducible archives | A fixed commit epoch and normalized source archive produce byte-identical wheel and sdist files across two independent builds; the characterization test rebuilds both on every complete suite run |
| Artifact contents | The verifier requires exactly one pure-Python wheel and one sdist, checks the console entry point, every shipped dashboard asset, archive-safe paths, package name/version, Python floor, and absence of retired product paths |
| License contract | Built Metadata 2.4 must contain `License-Expression: Apache-2.0`, exactly one `License-File: LICENSE`, and the actual license under the wheel's `.dist-info/licenses` directory |
| Clean installs | A Linux/macOS × Python 3.11/3.12 CI matrix installs wheel and sdist separately, runs their CLI, resolves packaged dashboard resources, initializes a new Git repository, scans it, and exercises the local `uvx --from <wheel>` path |
| Protected publication | A dedicated GitHub-release workflow rejects mismatched or already-published versions, builds once, and requests the protected `pypi` environment without a stored API token; after the first exchange failed closed, the publisher was registered and a non-publishing probe proved PyPI now accepts the exact workflow identity |
| Supply-chain evidence | Each release produces distribution SHA-256 values, release-contract JSON, SPDX JSON SBOM, installed dependency/license inventory, and GitHub attestations; container tags must match the Python version and their BuildKit SBOM/provenance digest receives a registry attestation |
| Maintainer procedure | `docs/releasing.md` records the trusted-publisher/environment setup, protected tag flow, preflight, artifact verification, digest pinning, and immutable-version recovery policy |
| Local rehearsal | The exact normalized wheel and sdist passed Twine, installed in independent virtual environments, reported `AnaxiGraph 0.2.0`, and the wheel initialized/scanned a fresh fixture; PyPI returned the candidate version as unused |
| Repository gate | All 120 Python tests pass at 85.79% coverage, changed executable coverage is 86.4%, all pre-commit/size/complexity/coupling/layer checks pass, both Compose definitions validate, the bounded benchmark completes, and all 12 Chromium contracts pass |

The `pypi` GitHub environment requires maintainer approval and accepts only `v*` tags. The matching
PyPI publisher is registered and was verified by workflow run
[`32412357679`](https://github.com/hcekne/anaxigraph/actions/runs/32412357679), which minted, masked,
and discarded a short-lived token without building or uploading an artifact. No repository secret
or long-lived release token is required for the routine path.

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

### Phase 3.2 closure evidence

**Completed in source on 20 August 2026.** Initialization now makes the agent-funded path explicit
without turning a plain repository setup into implicit client mutation.

| Contract | Delivered evidence |
|---|---|
| Explicit semantic mode | `--semantic agent` creates or surgically updates the semantic policy block, preserves unrelated YAML and comments, and is a no-op when the requested state already exists |
| Explicit client selection | Repeatable `--connect codex` and `--connect claude` options configure only clients the user named; plain `init` never reads or writes a client configuration |
| Safe scopes | `--connect-scope user` writes the documented private user configuration with mode `0600`; project scope writes `.codex/config.toml` or `.mcp.json` and reports the client trust/approval requirement |
| Loss-minimizing updates | Existing client files receive timestamped backups only when a real change is needed; unrelated TOML/JSON settings are retained, TOML comments are preserved, writes are atomic, credentials/fragments are rejected, and symlinked target files fail closed |
| Preview and repetition | `--dry-run --json` reports every repository and client action without writing; repeated semantic/client setup produces `unchanged` and no additional backup |
| Network clarity | Initialization prints separate loopback dashboard/MCP, Compose-network, and remote-host forms; `--mcp-url` selects the exact endpoint stored for the coding client |
| End-to-end diagnostics | `anaxigraph doctor` retains index integrity/migration evidence and adds repository readability, index-directory writeability, `/healthz`, a real MCP `initialize` exchange, and selected Codex/Claude URL validation |
| Maintainability | Repository discovery, YAML policy editing, template generation, client configuration, initialization CLI, and environment diagnostics are separate modules; `cli.py` and `onboarding.py` are already below 500 lines and their size exceptions have been removed |
| Verification | 21 focused onboarding/doctor tests pass with 90% coverage across the new modules; the complete gate passes 137 tests at 86.82% total coverage, all lint/format/size/complexity/coupling/layer checks, both Compose validations, the bounded benchmark, and all 12 Chromium contracts |

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

### Phase 3.3 closure evidence

**Completed in source on 20 August 2026.** The convenience runtime composes the existing scanner,
API, AnaxiMCP, and durable history service rather than introducing a second analysis path.

| Contract | Delivered evidence |
|---|---|
| One foreground command | `anaxigraph up . --open --semantic agent --connect codex` creates or loads policy, applies only explicit client changes, and runs the dashboard/MCP service; Claude and deterministic-only variants use the same command |
| External state | The default is a stable path-derived per-checkout AnaxiIndex under Linux XDG state or macOS Application Support, with `ANAXIGRAPH_STATE_HOME`, `ANAXIGRAPH_DB`, and `--db` overrides; the private state directory is mode `0700` on POSIX |
| Loopback safety | The convenience server always binds `127.0.0.1`, preflights port conflicts before writes, and enables only index-writing agent refresh |
| Startup ordering | FastAPI readiness waits for the current deterministic scan; adaptive history starts through the existing durable background job after that scan and can resume after interruption |
| Browser and lifecycle | `--open` waits for a successful health response before launching a browser; the startup banner gives dashboard/MCP URLs, state location, Ctrl-C behavior, and an idempotent restart command |
| Safe preview | `--dry-run --json` previews policy, state, semantic, connection, history, endpoint, and restart choices without creating repository/client/state files or starting a listener |
| Process contract | A subprocess test starts the real CLI on an ephemeral port, waits for `/healthz`, confirms the external index, sends SIGINT, and requires a zero exit plus completed application shutdown |
| Maintainability | Runtime assembly uses dependency injection so the new convenience layer does not grow the already-ratcheted API, config, or storage coupling; both new modules are below 200 lines and all size/function/cycle/layer ratchets pass |
| Verification | Seven local-runtime tests pass; the complete gate passes 144 tests at 87.13% total coverage, both Compose validations, the bounded history benchmark, and all 12 Chromium dashboard contracts |

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

### Phase 3.4 closure evidence

**Completed in source on 20 August 2026.** Codex and Claude Code now consume one canonical skill
and one local AnaxiMCP connection from a dual-client plugin package.

| Contract | Delivered evidence |
|---|---|
| One workflow | Both client manifests point to `plugins/anaxigraph/skills/anaxigraph`; the skill routes repository selection, overview, scope, impact, findings, verification, and semantic work through the live AnaxiMCP tools rather than reimplementing analysis |
| Semantic safety | The documented loop follows `SCHEMA -> WORK -> every EVIDENCE page -> SUBMIT`, accepts only `completed`/`already_completed` as stored, releases interrupted work with a reason, discards stale leases, and resumes through a fresh claim |
| Evidence discipline | The skill distinguishes deterministic facts from interpretations, requires dynamic-wiring caveats, and explicitly rejects missing static edges as proof of dead code or findings as automatic edit permission |
| Dual-client packaging | Version-matched Codex and Claude manifests, marketplace catalogs, OpenAI display metadata, the shared SVG, Apache license, and loopback MCP definition are validated together against `project.version` |
| Real client installs | The repository marketplace and plugin installed successfully in isolated Codex and Claude homes without mutating either real user configuration; Claude strict validation and both skill/plugin validators pass |
| Contract test | A real Streamable HTTP MCP session claims work, fetches every evidence page, releases it, reclaims the same job, submits a schema-valid dossier, and verifies durable completion status |
| Reproducible release | `build_agent_plugin.py` creates a byte-identical, normalized seven-file ZIP; release CI includes its SHA-256 value in the attested release checksum bundle |
| Verification | Four focused package/contract tests pass; the complete gate passes 148 tests at 87.46% total coverage, all pre-commit/size/complexity/coupling/layer checks, both Compose validations, the bounded benchmark, and all 12 Chromium contracts |

## 3.5 Collapse onboarding documentation

The first screen and README lead with:

1. one local or Docker start command;
2. the dashboard URL;
3. one agent connection command/option;
4. one sentence asking the agent to bootstrap or resume semantics.

Hosted-key workers, local model workers, multi-repository registries, SSH tunnels, custom coverage,
and manual Compose operations move under **Advanced** sections. The main path explains that the
coding agent uses its own tokens and that AnaxiGraph itself needs no model key in agent mode.

### Phase 3.5 closure evidence

**Completed in source on 20 August 2026.** The public first-run story is now one linear workflow
instead of an operations manual presented before the product can be tried.

| Contract | Delivered evidence |
|---|---|
| Four visible steps | README and onboarding lead with one `uvx anaxigraph up` command, the loopback dashboard URL, the explicit Codex/Claude connection choice, and one sentence asking the agent to build or resume semantic understanding |
| Honest cost model | Both primary documents state before advanced configuration that the connected coding agent uses its own model context and tokens and that agent mode needs no AnaxiGraph model key |
| Local and Docker choices | The local foreground path remains first; one generated, hardened Docker sidecar command follows as the durable alternative without interleaving its manual operations |
| Progressive disclosure | Hosted/local/custom workers, budgets and egress, SSH, coverage, history control, custom state/endpoints, manual Compose, multi-repository operation, integrity, upgrades, and reset behavior moved to `advanced-operations.md` |
| Reduced first-run surface | README is 225 lines and onboarding is 190 lines, down from 437 and 540 respectively; the 264-line advanced guide preserves operational detail without blocking the first success path |
| Agent workflow | The supported Codex/Claude plugin is a clearly labeled optional one-time workflow install; users can still use the one-command `--connect` path without learning plugin packaging first |
| Regression contract | Two documentation tests require the ordered four-step path, dashboard URL, own-token/no-key explanation, resume prompt, and routing of representative advanced topics; all tracked pre-commit checks pass |

## 3.6 Decompose onboarding code

Split `cli.py` into parser/facade plus command handlers and split `onboarding.py` into repository
detection, policy generation, Compose generation, client connection, and start/doctor services.
Command behavior remains covered at the process boundary, not only through helper unit tests.

### Phase 3.6 closure evidence

**Completed in source on 20 August 2026.** The CLI now exposes one stable entry point while each
command family and first-run responsibility has a bounded owner.

| Contract | Delivered evidence |
|---|---|
| Thin facade and parser | `cli.py` is 22 physical lines and owns only error/interrupt handling plus result emission; `cli_parser.py` assembles the versioned command surface from focused registrars |
| Cohesive handlers | Repository/findings, semantic worker, agent scope/impact, and server/operational handlers live in separate modules; no new implementation module exceeds 208 lines |
| Composition root | `cli_services.py` centralizes API/config/scanner/storage/semantic construction, so extraction restores rather than multiplies the existing dependency fan-in ratchets |
| Onboarding responsibilities | Repository discovery, policy editing, policy/Compose templates, safe file application, client configuration, Docker start, local runtime, and doctor checks remain separate services; the coordinating `onboarding.py` is 319 physical lines |
| Removed debt | The legacy `_parser` and `_semantic_worker` function exceptions and the CLI coupling exception are deleted; config, scanner, and storage retain their pre-extraction ratchets, and architecture classification has no gaps or cycles |
| Process boundary | Subprocess contracts prove the installed module exposes every command family, scan/scope/export share one durable index, and validation errors retain exit code 2 and stable diagnostics |
| Handler behavior | Five focused command tests cover repository scans, findings, exports, agent context, semantic planning/status/scheduling/resume, loop interruption, environment defaults, and server assembly through the stable `main` facade |
| Verification | The complete gate passes 158 tests at 88.99% total coverage, all pre-commit/size/function/complexity/coupling/layer checks, both Compose validations, the bounded history benchmark, and all 12 Chromium contracts |

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
- The supported convenience path remains local-first and loopback-bound.

### Phase 3 exit evidence and release blocker

**Completed and publicly verified on 20 August 2026.** All eight product criteria are closed. PyPI
serves 0.2.0, and the exact documented `uvx anaxigraph up` command starts a healthy dashboard from
a fresh repository without a Git source URL or manually authored configuration.

| Contract | Evidence and disposition |
|---|---|
| Clean artifact startup | The Linux/macOS × Python 3.11/3.12 package matrix installs both wheel and sdist; its wheel path now starts the real `anaxigraph up` process in a new Git repository, waits for `/healthz`, verifies policy and external AnaxiIndex creation, and requires a clean SIGINT shutdown |
| One-command local value | Three independent fresh repositories reached a healthy dashboard in a **0.708-second median** with `up --semantic agent --connect codex`; each created only the requested project-scoped connection and external index |
| First semantic dossier | Each timing trial opened a real Streamable HTTP MCP session, validated `module-dossier-v4`, claimed work, traversed every requested evidence page, and stored a validated dossier in a **0.760-second median**, far below the ten-minute ceiling |
| Safe repetition | Focused initialization contracts retain unrelated TOML, JSON, and YAML, create a backup only for a real client change, and prove repeated policy/client setup is unchanged and creates no second backup |
| Local end to end | The process contract and timing gate execute the assembled scanner, API, MCP, semantic queue, storage, and shutdown path rather than mocking the runtime |
| Docker end to end | A fresh generated Compose sidecar builds from the current Dockerfile, scans a three-file repository, becomes healthy in **2.279 seconds**, returns repository and overview data over AnaxiMCP, and tears down its isolated project and volume |
| Container hardening | Inspection of the live generated container proves a read-only root, read-only repository mount, `cap_drop: ALL`, `no-new-privileges`, and a `127.0.0.1`-only published port |
| Skill lifecycle | The dual Codex/Claude plugin contract completes `SCHEMA -> WORK -> EVIDENCE -> RELEASE -> WORK -> SUBMIT`, validates durable completion, and ships one canonical, reproducible workflow package |
| Maintainability | `cli.py` is 22 lines and `onboarding.py` is 319 lines; both legacy exceptions and the CLI coupling exception are removed |
| Exposure boundary | README and onboarding consistently present the convenience runtime as a loopback sidecar |
| Complete quality gate | 159 Python tests pass at **89.02%** line coverage; pre-commit, release, size, function-size, complexity, coupling, cycles, coverage, and architecture-layer checks pass; both Compose definitions validate; the bounded temporal benchmark completes; and all 12 Chromium contracts pass |

The source gate now runs the first-user timing journey and hardened-container inspection in CI and
in `scripts/run_quality_gate.py`, retaining their JSON reports as evidence. The deliberately broad
five- and ten-minute ceilings detect hangs or catastrophic regressions; future releases can tighten
them from accumulated runner data instead of treating this development server's sub-second values
as universal promises.

#### Release outcome and publisher verification

The immutable `v0.2.0` release was built from commit `bf7fc17`. Main CI, the container workflow,
and local preflight passed before tagging. The protected release job then built and attested the
wheel, source distribution, plugin ZIP, SBOM, checksums, dependency inventory, and release contract.

The first OIDC exchange failed closed with `invalid-publisher`: GitHub's claims matched
`hcekne/anaxigraph`, `release.yml`, and environment `pypi`, but PyPI had no corresponding publisher.
Under explicit maintainer authorization, the exact downloaded workflow artifacts were checksum-
and attestation-verified and uploaded through the documented emergency Twine path. PyPI's recorded
SHA-256 values match those artifacts. A clean public install reported `AnaxiGraph 0.2.0`, and the
public `uvx anaxigraph up` path reached `/healthz`, created policy and AnaxiIndex state, and exited
cleanly. The GitHub release retains the verified bundle and publication record.

The versioned multi-architecture image is public at `ghcr.io/hcekne/anaxigraph:0.2.0`; its manifest
digest is `sha256:597fddedb5c1d4cdd3f469ee7dfc30d7d0333dd4c103e26bf2c31524d7ce4230`
and its registry attestation verifies against this repository.

The PyPI project owner subsequently added this exact trusted publisher in the `anaxigraph`
Publishing settings:

| Field | Required value |
|---|---|
| Owner | `hcekne` |
| Repository | `anaxigraph` |
| Workflow | `release.yml` |
| Environment | `pypi` |

Manual workflow run
[`32412357679`](https://github.com/hcekne/anaxigraph/actions/runs/32412357679) then exercised the
exact `release.yml` / `pypi` identity. PyPI minted a short-lived project token, the job masked and
discarded it, and all build and upload jobs were skipped. The temporary `main` deployment allowance
used for that probe was removed, restoring the environment to its `v*` tag-only policy. Do not use
Twine again for a routine release; the next release must complete the OIDC publish and public-
install jobs end to end.

---

# Phase 3b — dashboard/evaluator decomposition and self-analysis

**Status:** COMPLETE on 24 August 2026

**Goal:** keep the completed dashboard and evaluator decomposition protected, then prove that
AnaxiGraph's deterministic attention model can act as a stable regression check on its own code.

## 3b.1 Decompose evaluators and the dashboard

**Status:** COMPLETE on 22 August 2026

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

Delivered: `architecture.py` is 90 physical lines, `agent.py` is 366, `app.js` is 167, and every
extracted dashboard module is below 400. Package contracts and browser workflows cover the nested
modules, and `quality/module-size-policy.json` has no legacy exception.

## 3b.2 Make self-analysis a regression gate, not a zero-backlog gate

**Status:** COMPLETE on 24 August 2026

Run AnaxiGraph against its own pull-request revision in CI and retain the report as a build
artifact. The required check fails only when a deterministic, policy-enabled condition is newly
introduced or regresses across an explicit threshold relative to the committed baseline.

The gate must:

- pin analyzer, detector, rule, and priority versions;
- compare stable finding keys and evidence rather than queue position alone;
- fail on configured new/regressed severity, architecture boundary, cycle, size, or complexity
  conditions;
- keep information-level diagnostics and model-derived semantic recommendations non-blocking;
- allow accepted existing debt only through an explicit baseline entry with rationale and removal
  phase, never by dismissing a finding merely to make CI green;
- report when a rule or score-version change requires an explicit baseline review;
- upload the full scan summary even when the required regression check passes.

The attention queue may remain non-empty. CI proves that a change did not make the governed
architecture worse; it does not pretend all acknowledged or planned work has already been completed.

## Phase 3b exit gate

- `architecture.py`, `agent.py`, and every dashboard JavaScript module are below 500 lines and are
  removed from the size-exception baseline.
- The graph, modules, findings, history, settings, and semantic workflows retain browser and visual
  regression coverage after decomposition.
- Wheels and containers include every nested dashboard module.
- CI self-analysis is deterministic and fails on a fixture that introduces a governed regression.
- An unchanged accepted backlog does not fail CI, and a changed rule/priority version requests an
  explicit baseline update rather than silently changing the gate.
- The self-analysis gate needs no LLM call, network model access, or mutable semantic dossier.

### Phase 3b closure evidence

| Contract | Delivered evidence |
|---|---|
| Cohesive decomposition | `architecture.py` is 90 physical lines, `agent.py` is 366, `app.js` is 167, every dashboard JavaScript module is below 400, and the module-size exception list is empty |
| Exact deterministic ratchet | `scripts/check_self_analysis.py` performs a fresh isolated scan and compares every deterministic warning/error by stable key, affected target, severity, and exact evidence against `quality/self-analysis-baseline.json` |
| Version safety | The baseline pins analysis/IR/detector/priority contracts, every built-in analyzer version, and the effective rule-set digest; a mismatch fails closed and requests an explicit update |
| Improvement preservation | New or worsened evidence fails, while reduced evidence and disappeared findings require the baseline to tighten in the same change rather than silently leaving stale debt |
| Non-blocking diagnostics | The closure scan analyzed 272 artifacts and passed with 50 governed findings, 116 retained information-level diagnostics, and zero regressions; no semantic/model result participates in the decision |
| Regression proof | Six focused tests cover unchanged debt, non-blocking information findings, new findings, evidence regression/improvement/change, stale entries, contract changes, and an actual scanned fixture that introduces new complexity |
| Local and remote enforcement | The tracked pre-push hook and complete local quality runner execute the same command as CI; CI always uploads the full JSON scan report |
| Complete verification | All tracked pre-commit checks pass and 216 Python tests pass at 88.65% total coverage |

---

# Phase 4A — pattern-ready evidence contract

**Status:** COMPLETE on 24 August 2026

**Goal:** give pattern evaluation a small, language-neutral evidence vocabulary that works from a
function or type through module, subsystem, area, and repository scope.

## 4A.1 Extend the analyzer intermediate representation

The `anaxigraph-ir-v1` contract already normalizes modules, symbols, relationships, locations,
signatures, documentation, parse state, complexity inputs, and analyzer provenance. Extend it only
where pattern evaluation needs reusable facts that are absent today, such as symbol kind and
visibility, decorators/annotations, inheritance and implementation roles, entry-point evidence,
mutation and side-effect evidence, error/async behavior, and test relationships.

The IR remains pattern-neutral. An analyzer reports what it observed; it does not contain a
separate detector for Strategy, Adapter, Pipeline, or any other catalog entry.

## 4A.2 Declare analyzer capabilities

Each analyzer publishes a versioned capability record describing which facts it can provide and at
what confidence. Pattern requirements refer to capabilities rather than language names. Missing
capabilities suppress or lower confidence in an evaluation instead of silently treating missing
evidence as absence.

The Python AST analyzer is the reference implementation. Existing JavaScript/TypeScript and
long-tail heuristic analyzers remain honestly labeled while still contributing the evidence they
can support.

## 4A.3 Build reusable evidence projections

Project deterministic IR, graph, dossier, coverage, and history facts into a compact feature
vocabulary shared by every pattern. Feature records carry stable target identity, scope level,
source snapshot, analyzer/capability versions, confidence, and inspectable evidence references.
Features are calculated once per changed target and reused across catalog candidates.

## Phase 4A exit gate

- Function/type, module, subsystem, area, and repository targets have stable identifiers.
- Analyzer capabilities and feature-projection versions participate in targeted invalidation.
- The Python reference fixtures cover every required evidence family without pattern-specific AST
  queries.
- Missing parser capability produces an explicit unavailable or lower-confidence result.
- The contract adds no new parser dependency and no implementation module above 350 lines.

### Phase 4A closure evidence

| Contract | Delivered evidence |
|---|---|
| Honest analyzer depth | Every built-in analyzer publishes a validated `analyzer-capabilities-v1` declaration with per-fact depth, limitations, and a content fingerprint; the full declaration is persisted with immutable file facts and unavailable facts stay explicit |
| Pattern-neutral Python evidence | The Python AST reference emits documentation, decorators, annotations, inheritance, constructors, entry points, mutation, side effects, error/async behavior, control flow, registrations, generics, concurrency, and test relationships through generic `AnalyzerFact` records; conformance rejects undeclared, malformed, or duplicate facts |
| Targeted analyzer invalidation | A capability-only Python contract change reanalyzes exactly the five Python modules in the mixed fixture and reuses the other four modules; analyzer identity, version, capability schema, and fingerprint all participate in reuse |
| Stable six-level identity | `pattern-target-v1` gives symbol, type, module, subsystem, area, and repository targets deterministic repository-scoped keys that exclude database row ids and source lines; methods attach to their owning type where the analyzer can prove it |
| Reusable evidence | `pattern-evidence-v1` projects IR/analyzer facts, graph shape, coverage, Git history, semantic dossiers, and architecture placement once per target with confidence, availability, provenance, and deduplicated capability contracts |
| Incremental parent refresh | A fixture edit changes the function and module fingerprints plus their subsystem/area/repository ancestors while an unrelated module fingerprint remains byte-identical; catalog candidates can reuse every unchanged projection |
| Real-repository scale | A fresh self projection covers 285 modules as 2,247 stable targets: 1,800 symbols, 111 types, 285 modules, 25 subsystems, 25 areas, and one repository, backed by three capability contracts |
| Maintainability and verification | The Python adapter is 268 lines after extracting cohesive syntax/evidence helpers; every new implementation module is at most 350 lines, no parser dependency was added, 228 tests pass at 88.92% coverage, and deterministic self-analysis passes with 50 governed findings and no regression |

---

# Phase 5A — bounded graph and operational APIs

**Status:** COMPLETE on 25 August 2026

**Goal:** keep large local indexes bounded from database to browser and expose a compact query plane
that pattern intelligence can reuse.

## 5A.1 Replace unbounded graph responses

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

## 5A.2 Bound operational work

- Rate-limit expensive scans/history imports per repository.
- Add job concurrency and cancellation controls.
- Bound request body sizes, evidence pages, graph depth, and export size.
- Add database backup/restore and health/size diagnostics.
- Bound concurrent work per repository and expose queue/size pressure in health diagnostics.

## 5A.3 Keep the API composition root small

Split `api.py` into thin routers for repositories, graph, findings, history/jobs, semantics, and
patterns backed by application services. The app factory owns dependency wiring; routers do not
execute SQL or semantic state transitions.

## Phase 5A exit gate

- No graph endpoint can serialize an unbounded repository graph.
- A 50,000-node synthetic graph can open an overview and inspect a region without exhausting the
  browser or returning one monolithic payload.
- Backup/restore and schema upgrade are documented and tested.
- `api.py` is a composition root of at most 300 physical lines and each router/service has one
  bounded responsibility.
- Every first-party implementation module remains below 500 physical lines, with no exception.

### Phase 5A closure evidence

| Contract | Delivered evidence |
|---|---|
| Bounded graph plane | `graph-query-v1`, `graph-overview-v1`, `graph-neighborhood-v1`, and `graph-delta-v1` resolve an explicit repository/snapshot, enforce node/edge/depth maxima, report counts/timing/payload bytes, and use filter-bound opaque cursors; REST and the single `ANAXIGRAPH_GRAPH` MCP tool share those contracts |
| Architecture-first browser | The dashboard fetches area aggregates first, opens the largest region only when a repository exceeds 250 modules, replaces rather than accumulates cursor pages, and preserves the active region across graph controls and history; all 14 browser contracts pass in the pinned Playwright container |
| 50,000-node scale | The retained `graph-scale-v1` fixture represents all 50,000 modules in a 4,216-byte overview, opens a 250-node/500-edge region in 328,773 bytes with a continuation cursor, and reads a five-node neighborhood in 6,472 bytes; every read stays below 15 seconds, 2 MB, and 512 MB peak-resident delta |
| Bounded operations | POST/PUT/PATCH bodies stop at 2 MiB before parsing; per-repository admission prevents concurrent or immediately repeated scan/history/semantic work; bounded module inventory and export contracts cap every collection; operational health reports schema, WAL/index allocation, reclaimable bytes, free disk, active work, and queue pressure |
| Recoverable index | `anaxigraph backup` creates a new integrity/schema-validated online SQLite image and refuses overwrite; local-only `anaxigraph restore --yes` validates before atomic replacement and opens through the supported migration path; round-trip, invalid-source, confirmation, schema-upgrade, and exact migration-recovery tests pass, with local and sidecar runbooks published |
| Small composition roots | `api.py` is 111 physical lines with a 50-line app factory; graph, repository, history, semantic, agent, and operational routers are separate, bounded modules; MCP tool-family registration is behind a focused facade, reducing the deterministic MCP fan-out signal from 18 to 16 |
| Hard size and quality gate | Every first-party implementation and dashboard asset remains at or below the 500-line ceiling with no exception; the complete Python suite passes at 89% coverage, deterministic self-analysis passes with 49 governed findings and no issue, and architecture, maintainability, formatting, Compose, container, benchmark, and browser gates are retained as release checks |

---

# Phase 6 — architect-grade semantic and pattern intelligence

**Status:** COMPLETE on 26 August 2026; self-hosted calibration passed and optional external MaxOS
evidence remains paused.

The deterministic and self-hosted exit gates are met. The paused external run may add independent
evidence later, but it does not block the core roadmap. No parser, provider, or adjacent
plain-language work is opened merely to keep this phase busy.

**Goal:** turn the current semantic map into a compact, evidence-backed pattern intelligence system
that evaluates code at multiple scales, completes its own critique, and remains cheap to extend.

## 6.1 Replace the semantic mixin lattice with explicit services

**Status:** COMPLETE

Replace the current mixin-composed `SemanticEngine` with a small compatibility facade over explicit
planning, lease, evidence, contract, persistence, runner, and reporting services. State transitions
become a tested state machine, services receive narrow protocols, and the CLI/REST/MCP contracts
remain stable during extraction.

The extraction is complete only when no service depends on inheritance order or a hidden shared
database attribute. New implementation modules should normally be 100–300 physical lines.

## 6.2 Preserve complete autonomous semantic mapping

**Status:** COMPLETE

The shipped module dossiers and agent-reviewed architecture taxonomy remain the semantic baseline.
Every eligible scope reaches current, excluded, or visibly failed; interrupted sessions resume from
durable leases; and taxonomy proposals complete their configured independent agent review passes
before becoming the current map. Map completion has no manual edit or approval gate.

Incremental refresh rereads source only when structural, interface, relationship, analyzer,
prompt-contract, enrollment-policy, or age evidence changes. Provider and model are runtime
provenance, never hard-coded catalog behavior, and switching model does not invalidate otherwise
current understanding.

### 6.1–6.2 closure evidence

| Contract | Retained evidence |
|---|---|
| Explicit composition | `SemanticEngine` has no mixin bases or database state; a low-fan-out composition root assembles separately testable planning, lease, evidence, contract, persistence, runner, reporting, and agent services through narrow configuration, index, and workflow ports |
| Durable lifecycle | Pending, retry, running, completed, failed, and superseded jobs move only through the tested semantic-job state machine; claim, release, expiry recovery, retry, completion, failure, reset, and supersession persistence paths use declared transitions |
| Autonomous completion | Existing full-baseline contracts still require intrinsic and contextual dossiers, repository/group synthesis, taxonomy proposal, and all configured independent agent review passes to converge without an operator approval step |
| Stable external protocol | The compatibility facade preserves CLI, REST, MCP work/evidence/submit/release, status, dossier, bootstrap, and provider execution contracts; lease state remains resumable across sessions |
| Incremental/model behavior | Existing characterization proves an unchanged repository creates no semantic work, one local implementation change refreshes only its affected intrinsic scope, and executor/model provenance changes do not invalidate current semantic documents |
| Maintainability | The 241-line/complexity-52 status operation and 151/125-line module planning operations are decomposed; substantive extracted modules are 160–266 lines, all implementation modules remain below 500 lines, and five obsolete deterministic self-analysis exceptions are removed |
| Verification | 54 focused semantic/service/state-machine contracts pass; the current complete 326-test suite passes at 89.79% coverage; deterministic self-analysis passes with 44 governed findings and no issue; formatting, module-size, maintainability, architecture, forbidden-file, and Compose gates pass |

## 6.3 Ship an extensible catalog of at least 120 patterns

**Status:** COMPLETE on 25 August 2026

The first production catalog contains at least 120 canonical entries and has no architectural
ceiling. It spans function/symbol construction, object and interface design, data and state,
module boundaries, composition and workflow, integration and concurrency, reliability and tests,
and subsystem/repository architecture. Both constructive patterns and recognizable failure modes
may be represented, but each entry states which it is.

Pattern cards are validated declarative package data, not one detector class per pattern. A card
contains:

- stable key, version, name, family, kind, intent, and applicable scope levels;
- problem signals, required capabilities, supporting evidence, and counter-evidence;
- semantic questions that an agent must answer when deterministic evidence is insufficient;
- related, complementary, alternative, and conflicting patterns;
- applicability, suitability, conformance, and opportunity scoring guidance;
- benefits, liabilities, migration cautions, verification invariants, and references.

The schema and loader are versioned independently from the bundled catalog. Adding a valid card
requires no schema migration, Python detector, route, or dashboard component. Keep the catalog
compact (target below 300 KB) and the initial pattern engine below roughly 1,500 implementation
lines, with no new model-provider pipeline or vector database.

### 6.3 closure evidence

| Contract | Retained evidence |
|---|---|
| Breadth | The bundled `2026.08.2` catalog contains 128 cards across eight equal families: function construction, object/interface, data/state, module boundary, composition/workflow, integration/concurrency, reliability/testing, and subsystem architecture |
| Multiple scales | Card applicability covers symbol, type, module, subsystem, area, and repository targets; the baseline contains 103 constructive patterns and 25 explicit failure modes |
| Declarative contract | Immutable typed cards validate stable keys, versions, scopes, structured signals, analyzer capability requirements, semantic questions, four relationship categories, four scoring dimensions, benefits, liabilities, cautions, invariants, and references |
| Independent evolution | `pattern-card-v1`, `pattern-catalog-source-v1`, `pattern-catalog-loader-v1`, and the bundled content version are distinct contracts; the expanded sorted content has a deterministic SHA-256 fingerprint |
| Extensibility | A 140-card operator catalog loads without code changes, proving the shipped 128 is not a count ceiling; malformed sources, mixed versions, duplicates, unknown relations, invalid evidence, and unsupported capabilities fail validation |
| Compact delivery | Eight JSON sources occupy 148,143 bytes; the loader and contracts occupy 463 physical Python lines with no module above 280 lines; package and release gates require every source in both wheel and source distribution |
| Verification | 41 focused catalog contracts pass with 96% catalog-code coverage; release artifact tests pass; the complete 326-test suite passes at 89.79% coverage; deterministic self-analysis returns 44 governed findings, 125 non-blocking findings, and no issue |

## 6.4 Generate sparse multi-level candidates

**Status:** COMPLETE on 25 August 2026

Evaluate function/method, type, module, subsystem, area, and repository targets. Deterministic
features first select plausible pattern/target pairs; only those candidates receive semantic work.
Never run or persist the dense product of every pattern and every target.

Candidate generation uses capability requirements, graph shape, responsibility evidence, local
precedents, churn/coverage, and explicit contradictions. It records why a pattern was considered,
why it was skipped, and which missing evidence prevents a confident rating. Changed targets and
their conservatively affected parents/dependants are re-evaluated; unrelated pairs remain current.

The first delivered slice defines `pattern-candidate-v1`, evaluates structured card signals and
capability gaps deterministically, retains explicit supporting/counter/missing evidence, and gives
every candidate a target-input and catalog fingerprint. Default selection keeps at most four cards
per target and 200 repository-wide, while reserving representation across all available hierarchy
levels. Skipped pairs are summarized by reason and can be explained individually without storing
the dense pattern-by-target matrix. Selected pairs enter the durable assessment and critique
lifecycle in §6.6 only after the repository dossier and reviewed taxonomy are current.

Nineteen focused candidate contracts cover all six levels, stable fingerprints, changed-target
isolation, signal aliases and operators, capability gaps, counter-evidence, per-target/global
bounds, per-level reservation, and individual explanations for selected and skipped pairs.

## 6.5 Score presence, fit, and opportunity separately

**Status:** COMPLETE on 25 August 2026

Every completed evaluation reports independent 0–100 values for:

- **applicability** — how strongly the target exhibits the problem/context the pattern addresses;
- **suitability** — how well the pattern fits this target and repository's local design;
- **conformance** — how closely the existing code already implements the pattern;
- **opportunity** — expected value of changing the code, accounting for current conformance;
- **confidence** — strength and completeness of the evidence;
- **benefit, urgency, execution safety, and migration cost** — decision dimensions that must not be
  hidden inside one magic score.

Scores store their component values, score-contract version, evidence, counter-evidence, affected
targets, local precedents, prerequisites, risks, invariants, and conditions that would invalidate
the conclusion. A high suitability with high conformance means “already a good example”; it is not
misreported as a refactor opportunity.

## 6.6 Make independent agent critique part of mapping

**Status:** COMPLETE on 25 August 2026

The normal lifecycle is fully machine-operated:

```text
deterministic candidate -> agent assessment -> independent agent critique -> finalized map result
```

The critique checks scope choice, pattern identity, overlooked alternatives, counter-evidence,
score consistency, and whether the proposal would add more machinery than value. Disagreement
lowers confidence or retains competing interpretations; it does not fabricate consensus. Every
stage is resumable and carries provider/model/reasoning/prompt/schema provenance. Runtime model and
reasoning selection come from the connected agent/session configuration.

Optional operator feedback can annotate or override a finalized result and becomes calibration
evidence, but absence of that feedback never blocks the semantic map or pattern run.

### 6.4–6.6 closure evidence

| Contract | Retained evidence |
|---|---|
| Sparse work | `pattern-candidate-v1` selects at most four cards per target and 200 repository-wide while reserving all represented hierarchy levels; real-repository calibration reduced roughly 188,000 eligible pairs to the 200-work cap without persisting the dense matrix |
| Independent ratings | `pattern-scores-v1` requires nine independently evidenced 0–100 dimensions, explicit presence and recommendation, counter-evidence, precedents, alternatives, prerequisites, risks, invariants, and invalidation conditions; validation rejects high-conformance false opportunities and contradictory introduce recommendations |
| Autonomous critique | Every assessment transaction immediately creates a separate `pattern-review-v1` work item; critique returns a complete corrected evaluation, records scope/pattern/evidence/machinery issues, and can retain competing interpretations without an operator gate |
| Existing durable protocol | Pattern work reuses `semantic_jobs`, `semantic_documents`, `semantic_scope_states`, leases, evidence paging, retries, budget admission, MCP submit/release, and provider execution; no second provider stack, vector store, or model name was added |
| Incremental reuse | The plan is cached against current baseline document identities and catalog/contracts; unchanged reconciliation creates zero jobs, expired work is rebuilt, and a one-module implementation edit refreshes only that target plus conservatively affected hierarchy parents |
| Provenance and handoff | Documents retain provider, model, executor, prompt, schema, token, cost, and evidence provenance; local executor handoff records retain selected reasoning effort, and runtime model/effort changes do not invalidate unchanged semantic or pattern understanding |
| Compact implementation | Operational selection and lifecycle code remains about 1,490 physical lines, split into cohesive modules of 92–370 lines; every first-party implementation module remains below 500 lines and one obsolete complexity exception was removed |
| Verification | 34 focused candidate/rating contracts plus command-provider and MCP-agent end-to-end lifecycle tests pass; the complete 357-test suite passes at 89.90% coverage, and deterministic self-analysis reports 43 governed findings, 133 non-blocking findings, and zero issues |

## 6.7 Add consolidation, dead-code, and placement intelligence

**Status:** COMPLETE on 26 August 2026 — goal-specific placement, consolidation and unused-code
safety, change constraints, post-change comparison, and the human-and-agent-readable main and
expanded evidence contracts are implemented and self-hosted. The paused external calibration is
optional evidence, not unfinished §6.7 product work.

Repeated-responsibility and consolidation analysis combine structural similarity, semantic
responsibility, public contracts, graph neighborhoods, architecture placement, and change coupling,
including differences that argue for keeping implementations separate.

Change coupling is used when the temporal projection exists. Before Phase 7 supplies it, the
decision contract reports that evidence source as unavailable; it never invents co-change from a
static dependency or blocks the otherwise current recommendation.

Dead-code analysis starts from configured and detected entry points and accounts for imports,
calls, inheritance, registration, serialization, templates, configuration, and dynamic/reflection
blind spots. Low coverage, low churn, or no resolved inbound edge is never sufficient alone, and a
removal proposal is suppressed when graph trust is inadequate.

Given a coding goal, placement guidance returns the preferred extension point, patterns and local
precedents to reuse, bounded file/symbol scope, contracts and tests likely to change, risks,
verification commands, and post-change architecture facts to compare.

The first delivered slice adds `architecture-decision-v1` to the existing bounded agent-scope
response. It composes the already-ranked goal scope with current module dossiers and only finalized
independent pattern reviews. Placement, local precedents, contracts, invariants, risks,
consolidation evidence and counter-evidence, dead-code suppression reasons, focused tests, semantic
test guidance, rescan arguments, and the exact snapshot/hash/finding/pattern baseline travel
together. Tight wire budgets compact the details while preserving contract, status, preferred
path, and counts. This adds no table, provider call, queue kind, route, MCP tool, or dashboard state.

The goal-specific packet now preserves the size-limited `pattern-explanation-v2` conclusion,
observations, reason, action, caution, verification, and independent-review summary for every
included pattern. One shared reading guide explains reuse versus opportunity and the four retained
ratings. Agents therefore receive the same meaning as the pattern query and dashboard instead of a
bare score map. Tight payloads may still compact the entire optional decision detail through the
existing explicit omission contract; this adds no semantic work or invalidation.

Consolidation and possible-unused-code advice follow the same rule. The additive
`consolidation-explanation-v1` and `dead-code-explanation-v1` projections state the conclusion,
what AnaxiGraph observed, why it may matter, what to do, what could make the proposal wrong, and
how to check it. Consolidation strength is explicitly evidence for one suggestion, never a grade
or refactoring authorization. Every unused-code candidate starts with “do not delete yet,” explains
static-analysis blind spots, and carries an explicit no-deletion rule. The dashboard uses these
sentences instead of leading with scores and confidence percentages. Existing semantic dossiers
are translated when read, so this change creates no semantic work and invalidates no completed
dossier.

The rest of the goal-specific packet now uses `architecture-handoff-explanation-v2` and
`architecture-verification-explanation-v3` instead of asking an agent to interpret internal status
names and raw deltas. The packet states why its evidence is complete or partial, where to start,
what behavior must remain true, what could go wrong, how to rescan, what changed, and what that
change does not prove. Same-snapshot comparisons explicitly say that no post-change observation was
possible. Under the smallest supported wire budget, optional detail and duplicate context paths are
trimmed while the direct scope and placement conclusions survive. These are read-time projections
over the existing facts and comparison contract, with no semantic work, persistence, endpoint, or
freshness input.

Agent file summaries retain raw semantic pattern, consolidation, and possible-unused-code fields
for compatibility, but `semantic-file-explanation-v4` now labels their freshness and evidence
strength and says explicitly that they are early AI notes rather than instructions to refactor or
delete code. Agents are directed to `architecture_decision`, where the map checks those notes
against repository evidence and explains its recommendation. The dashboard Workbench renders that
same decision as readiness, starting point, constraints, and verification instead of discarding
it, and no longer describes the autonomous map as “human-approved.” This is another bounded read
projection and does not change semantic signatures or queue state.

The v4 file and repository projection also prevents older AI jargon from winning in the main
view. Known legacy phrases such as “contextual synthesis,” “intrinsic dossier,” sampled
dependencies/consumers, and generic ownership boundaries are translated into sentences about the
file descriptions and direct code links that were actually compared. Summary, role, placement,
change, extension-point, and risk sentences from that projection are rendered before the retained
raw compatibility fields. If an older sentence still needs a specialist term such as “adapter,”
“contract,” “persistence,” or “schema,” v4 defines that term immediately in the same explanation;
it never sends the reader to a separate technical-details drawer. The shared AI writing contract
now ends with an explicit self-review,
and independent pattern and map reviewers must rewrite expert labels that do not explain a
concrete fact. None of this claims to change the stored evidence or starts semantic work.

The compact module inventory, repository search, and agent graph now select that same projected
summary as their primary `summary` value. The original AI sentence remains in the nested semantic
record for compatibility and search matching, but it can no longer bypass the readable contract in
the first sentence shown to a person or supplied to an agent.

AI-created repository areas now carry `semantic-taxonomy-explanation-v1` through the existing
hierarchy response. Each area states its concrete job, what belongs there, why its files are grouped,
and what its evidence-strength value means. The overview cards use an ordinary-language group name
and those sentences as the main map, including when an older finalized map stored dense wording or
an invisible partition label such as `Cluster-5`. New proposals and autonomous reviews must write
every explanation for a smart twelve-year-old and another coding agent in the original field; a
technical-details field is explicitly not an acceptable escape hatch. Deterministic validation
flags hidden internal group numbers for the reviewer. File inventory and search records also carry
readable area and smaller-group names plus a direct explanation of why the AI map placed the file
there, so agents do not have to interpret the stored membership note. The extraction also removed
the former `read_semantic_hierarchy` maintainability exception; no extra route, table, provider
call, or semantic job was added.

Graph completeness now follows the same no-jargon-drawer rule. Every overview and bounded graph
response carries `graph-quality-explanation-v1`, which says how many likely links between files were
checked, how many pointed to one file, how many were unclear or missing, what code structure the
analyzers could not read, and exactly which dependency, impact, or deletion advice is limited. Its
action list distinguishes unclear links, plain-text reading, and parsing errors. The dashboard
renders those sentences instead of “graph evidence is partial” and “confidence-gated,” while the
stable counts and resolution states remain available for automation. The underlying caveat fields
are also ordinary sentences, so opening or querying more detail never reveals a second layer of
unexplained shorthand.

Semantic-run status now follows it as well. `semantic-status-explanation-v2` tells both people and
agents whether work is running **now**, whether an idle task list is safely saved but unable to finish
by itself, how many included files have current self-and-repository descriptions, which file or
whole-map work failed or remains, and the exact action that resumes it. Progress is explicitly a
count of current file descriptions rather than a code-quality grade. Agent-backed status says that
the connected coding-agent session chooses model and reasoning effort; neither is hardcoded into
the saved understanding of the code. The API refreshes the explanation after adding live worker
state, and the dashboard and Settings render those same sentences instead of “intrinsic/contextual dossiers,”
“synthesis scopes,” or “durable host executor.” This is a read-time projection only: it changes no
semantic signature, queue item, completed result, or source file. The two semantic browser
contracts now live in a focused 177-line file, reducing the general dashboard contract from 442 to
289 lines. Those contracts also pin the expired-lease case: saved work with zero live leases is
shown as idle, the resume button stays enabled, and polling does not claim that the departed agent
is still running.

Plain-language output is now a product contract rather than a dashboard treatment. New and already
stored architecture findings are read through `plain-language-v2`, so the old message “estimated
complexity 17” becomes an explanation of a branch score: what adds to it, why more possible
outcomes may be harder to test, why the function may still be correct, and the smallest useful
check. The dashboard, CLI, REST, MCP, agent handoff, file detail, impact result, pattern result, and
mapping status use the same ordinary sentences. No second “technical details” view is allowed to
contain unexplained labels. Stable JSON names remain for integrations, but every status, score,
confidence value, and source label has an adjacent meaning that says what it measures and what it
does **not** prove.

That rule now covers AI-written evidence as well as headings. One shared read-time rewriter is
applied to consolidation observations, unused-code cautions, placement guidance, change
constraints, finding summaries and actions, finalized-pattern evidence, score reasons, and the
independent review. Expanded pattern evidence receives the same treatment; opening more detail
cannot reveal the old unexplained wording. Every finalized result also says what its exact pattern
name means in the main result. The bundled 128-pattern catalog defines specialist words beside
that meaning, while the dashboard rewrites older saved responses that predate the current
contract. These are read projections over preserved evidence: they create no job, provider call,
freshness change, or semantic reindex.

AI work requests now carry one shared writing rule and a dictionary for unavoidable machine terms.
The worker must write short, concrete sentences for a smart twelve-year-old and another coding
agent; state the observed fact, consequence, evidence, uncertainty, and useful next action; and
define a necessary design term in the sentence where it appears. Pattern requests separately
define all nine scores, including that a high change-cost score means more work rather than a
better result. Independent AI review checks alternatives, contrary evidence, score consistency,
and needless machinery without adding a human approval step.

This writing-only hardening deliberately does not change the semantic freshness identity. It does
not turn a completed code description stale, drop semantic coverage to zero, or create background
work. New tasks and tasks refreshed because their code or evidence genuinely changed receive the
new writing rules. Older saved AI prose remains evidence with its existing creation details until
such a normal refresh; read-time explanations state its limits instead of pretending an old model
sentence became clearer by moving it elsewhere. No live semantic run was started for this change.

Deterministic dead-code candidates now require trusted relationship resolution, no resolved or
ambiguous inbound path, configured and conventional entry-point exclusion, parser-backed support
for both entry-point and registration evidence, no detected dynamic-wiring fact, and the configured
Git age. Semantic candidates remain suppressed without a same-granularity deterministic finding;
a module finding cannot corroborate a symbol suggestion, and no packet labels source safe to
remove. [`ADR 0002`](adr/0002-goal-specific-architecture-decisions.md) records these boundaries.

The same slice fixes authority under load. Synchronous AnaxiMCP handlers run outside the ASGI event
loop, and discovery retries transient inventory failures. Only an unequivocal refused connection or
a reachable service with no matching repository may select the per-checkout local index; timeouts
and invalid responses fail closed. The former 438-line `mcp_server.py` is now a 40-line composition
root over 64–268-line transport modules, with its function and self-analysis exceptions removed.

Post-change verification now closes the gap between recording a baseline and actually reading it.
`architecture-verification-baseline-v2` binds bounded file measurements, coupling, placement,
semantic responsibilities, readable findings, and finalized-pattern facts to repository and
normalized-goal fingerprints. The same CLI, REST, and `ANAXIGRAPH_SCOPE` surface accepts that
baseline after a rescan and returns `architecture-verification-comparison-v2`. It refuses
cross-repository or cross-goal comparisons, requires a newer snapshot for post-change evidence,
and reads version-1 or unversioned baselines without inventing missing measurements. Its structural
effects are grouped as introduced, worsened, improved, resolved, or pre-existing, with an
observation, consequence, smallest response, counter-case, and check. These are directions in the
indexed evidence: “resolved” is not proof of runtime correctness, and “improved” is not an overall
code-quality verdict without the intended outcome and focused tests.

### 6.7 current evidence

| Contract | Current evidence |
|---|---|
| Goal-specific decision | Existing REST and MCP scope integration returns `architecture-decision-v1`; focused contracts cover readable scope readiness, semantic placement, change constraints, reviewed patterns, consolidation, unused-code advice, before/after interpretation, rating meanings, provenance, exact verification baselines, payload compaction, and deterministic-only fallback |
| Measured post-change handoff | The existing scope request accepts its earlier bounded baseline through CLI, REST, and MCP; same-snapshot, changed, unchanged, cross-goal, cross-repository, legacy, invalid-contract, and wire-budget behavior is versioned and tested without adding state or another product surface |
| Removal safety | Python fixtures prove trusted module candidates, detected registration suppression, heuristic-language suppression, configured entry-point suppression, uncorroborated semantic suppression, and module/symbol granularity separation; `safe_to_remove` remains false |
| Readable evidence at every depth | Main and expanded decision fields translate older AI shorthand in place; every one of the 128 bundled patterns defines specialist words next to “what this pattern means,” and legacy dashboard fallbacks use the same ordinary-language rule rather than exposing a jargon drawer |
| Responsive authority | A blocking synchronous MCP tool no longer blocks the event loop; discovery tests prove connection-refused fallback, transient retry, and timeout refusal, while real SDK MCP and sidecar-preparation tests retain the work protocol |
| Focused orchestration | Scope response assembly now lives behind a bounded payload service, reducing `agent_scope` from its 128-line/complexity-24 ratchet to 91/6; finding handoff and reverse-impact assembly moved out of their former 96/22 and 77/18 functions. All three obsolete self-analysis findings are removed |
| Verification | The complete suite passes 536 tests; all 16 contracts pass in the pinned Playwright container; Ruff, architecture, size, maintainability, and deterministic self-analysis pass, with self-analysis at 26 governed findings, 132 non-blocking findings, and zero issues |

## 6.8 Expose pattern intelligence without multiplying product surfaces

**Status:** COMPLETE on 26 August 2026 — target- and pattern-centric queries, selected and skipped
candidate explanations, all 128 pattern-name meanings, readable main and expanded evidence, and
deterministic same-goal comparison are implemented and self-hosted. Longitudinal outcome
correlation was delivered through Phase 7 and is not a §6.8 closure item.

Reuse the existing semantic queue, leases, evidence paging, provenance, taxonomy, and bounded query
infrastructure. Add one narrow evaluation projection keyed by target, pattern, snapshot, and
contract signatures rather than a parallel analysis platform.

CLI, MCP, REST, and dashboard support both directions:

- target-centric: the best-fitting, already-present, conflicting, and high-opportunity patterns for
  a function, type, module, subsystem, area, or repository;
- pattern-centric: the strongest examples, weak conformers, opportunities, and skipped targets for
  one catalog entry.

Use direct recommendation fixtures covering correct and unnecessary abstractions, justified and
low-cohesion modules, dynamic dead-code traps, consolidation false positives, and different
migration costs. Keep those contracts beside the evaluator rather than shipping a second manifest
and reporting framework to end users.

The first query slice defines `pattern-query-v1` and reads only current `pattern_review` documents,
so an assessment cannot appear as a finalized recommendation before its independent critique.
`ANAXIGRAPH_PATTERNS` and `GET /api/patterns` share one application service and one bounded read
model. Exact target or pattern filtering, all nine score sorts, minimum score, level, presence,
recommendation, offset/limit, compact defaults, and opt-in detailed evidence are supported. The
projection reuses existing semantic documents and scope states; it adds no table, vector store,
provider path, or catalog coupling.

`pattern-candidate-query-v1` explains candidate membership without persisting a dense matrix. An
exact catalog key bounds reconstruction to one pattern over its eligible target levels; the result
is compared with current sparse-plan membership and reports selected, no-positive-evidence,
counter-evidence, below-priority, sparse-plan-bound, or plan-not-ready as the decision reason.
Selection, exact target, level, paging, and opt-in signal/capability evidence are supported by
`anaxigraph patterns --candidates`, `ANAXIGRAPH_PATTERNS(mode="candidates")`, and
`GET /api/patterns/candidates`.

`anaxigraph patterns` exposes that contract without creating a new scan. When `--db` is omitted it
uses the same checkout/Git-identity discovery as semantic execution to select a matching active
sidecar. Refused connections and reachable services without a repository match may select the
stable per-checkout local index; timeouts and invalid inventories fail closed. Explicit database
and service selectors are mutually exclusive, and every response identifies its index authority so
a completed sidecar map cannot be mistaken for an empty host-local index.

Every finalized evaluation now also carries `pattern-explanation-v2`. It turns the existing review
into one explicit conclusion, observed evidence, reason, proposed action, reasons not to change the
code, verification steps, and an ordinary-language account of all nine ratings. The dashboard
shows that complete explanation directly instead of leading with a nine-number grid. REST, MCP,
and CLI receive the same record, while exact scores remain structured for filtering and agent
comparison. The projection is derived from current reviewed documents when they are read, so old
evaluations gain it without a semantic rerun; new assessment and critique requests explicitly ask
for short ordinary sentences that people and coding agents can both understand.

Candidate queries now carry `pattern-candidate-explanation-v1` as well. Selected, rejected,
below-cutoff, bounded-out, and not-yet-final selections each state their reason directly. Matched
and opposing observations, missing feature evidence, analyzer capability gaps, the next machine
step, and the internal queue rank are explained without turning that rank into a pattern rating or
refactoring recommendation. Exact signal/operator/capability records remain available as optional
machine evidence, but they are not a jargon escape hatch: `pattern-candidate-detail-explanation-v2`
now tells both people and agents what each rule checked, what value it found, how the observation
affected selection, how strongly the observation is supported, what analyzer detail was required,
and whether enough information was available. The dashboard presents those sentences under “How
AnaxiGraph checked this evidence” instead of reproducing raw operator names and unexplained ratios.
It also converts the stored zero-to-one observation confidence correctly before showing its
zero-to-100 meaning.

The dashboard adds a dedicated **Patterns** view without growing its 499-line HTML shell or
498-line shared stylesheet. Separate 351-line query/controller, 230-line renderer, and 62-line
responsive stylesheet modules render the complete explanation and grouped exact ratings, critique
and provider/model provenance, bounded filters and pagination, opt-in evidence, candidate decision
reasons, and one-click pivots between finalized evaluations and skipped-target explanations.

Sixty focused candidate/query/calibration/language-contract cases, CLI authority handoff coverage,
completed-semantic projection coverage, REST integration, and a real MCP SDK round trip cover the
read model. The dashboard candidate workflow passes within all 16 browser contracts in the pinned
Playwright container. The complete suite passes 536 tests at 91.39% coverage; architecture, size,
maintainability, formatting, and deterministic self-analysis gates report no errors or regressions,
with self-analysis at 26 governed findings, 132 non-blocking findings, and zero issues.

## 6.9 Make repository-sized semantic bootstrap operational

**Status:** COMPLETE on 26 August 2026; authoritative self-hosted execution is verified and the
paused MaxOS run is optional external evidence.

The repository-sized path now uses a queue-first, stage-boundary lifecycle. Module planning carries
canonical file-fact identities directly, claim atomically reclaims expired leases, and submission
does not re-plan the repository. Semantic runtime, model, concurrency, lease, query, and display
settings no longer participate in structural snapshot identity. The selected service exposes one
non-secret effective semantic policy plus its registry/config provenance and remains authoritative
for service-backed execution.

Structural scan, semantic prepare, and model execution are separate operations. Service prepare
works only against the current snapshot; an absent snapshot returns `scan_required`. The dashboard
starts structural scans asynchronously, reports phase/file progress, and supports cooperative
cancellation without replacing the prior snapshot. The primary repository-sized workflow is the
model-agnostic detached host command, whose durable state now records heartbeat, stage, completed
work, errors, exact index authority, and safe stalled-run recovery.

Deterministic acceptance evidence:

- a 2,000-module fixture plans with zero snapshot reconstructions in the live module path;
- a 200-module lifecycle runs through a real Streamable HTTP MCP server, stops after 100 jobs,
  tears down the service, starts a fresh server on the same index, reclaims an abandoned expired
  lease, and reaches full coverage, ready taxonomy after two reviews, repository synthesis, and
  finalized pattern review with no source writes or duplicate/running work;
- all 16 pinned-container browser contracts pass, including durable-executor guidance;
- complete Python coverage, Ruff, formatting, size, complexity, coupling, architecture,
  self-analysis, Compose, container, first-user, and benchmark gates remain release requirements.

The implementation claim is supported by deterministic scale evidence and the authoritative
self-hosted run recorded in Phase 9.0. The MaxOS run from the P0 handoff can later add independent
external evidence for handoff, interruption/resume, terminal counts, taxonomy, elapsed time,
provenance, token use, failures, and retries. It does not block the core roadmap and must not start
while the explicit semantic-indexing pause remains active.

## Phase 6 exit gate

- The semantic system uses explicit composition and retains durable, session-independent progress.
- The bundled validated catalog contains at least 120 patterns and can grow without code changes.
- All six target levels produce stable, evidence-backed candidate and evaluation records.
- A full run finalizes its own independent agent critique without waiting for manual intervention.
- Unchanged reconciliation creates no source-reading or pattern-review work, and a local change
  invalidates only the target and conservatively affected scopes.
- Applicability, suitability, conformance, opportunity, confidence, benefit, urgency, safety, and
  cost are reproducible and queryable; high conformance never becomes a false refactor proposal.
- Consolidation and dead-code results expose supporting and contradicting evidence, and unsafe
  removal advice is suppressed.
- The engine stays within the stated code/data budget, adds no parallel provider stack, and every
  first-party implementation module remains below 500 lines.

---

# Phase 7 — change-safe architecture loop

**Status:** COMPLETE on 25 August 2026

**Goal:** make the existing map useful during an actual coding change: show where work belongs,
keep the working set small, and say plainly whether the change introduced or worsened structural
problems.

**Feature admission:** this phase directly answers “Where should this go?” and “Did the change
help?” It extends the existing scope, update, finding, graph, pattern, semantic-map, and dashboard
paths. It adds no provider, graph, vector store, approval workflow, or second planning surface. The
smallest proof fixture starts with a healthy module, makes one deliberately harmful change, and
requires AnaxiGraph to identify the new harm without burying it among pre-existing findings.

## 7.1 Make the existing scope handoff the default change loop

One workflow must be enough for both people and coding agents:

1. ask `scope` / `ANAXIGRAPH_SCOPE` about a concrete goal;
2. receive the preferred extension point, smallest useful files, boundaries, contracts, local
   precedents, risks, focused tests, and a bounded before-change baseline;
3. edit the target repository outside AnaxiGraph;
4. run the existing incremental `update` / `ANAXIGRAPH_SCAN` path;
5. ask the same scope question with the saved baseline and receive one focused comparison.

The response gives the next step directly. It does not require a user to understand snapshot IDs,
copy internal detector fields, or visit a second workflow. A stale or incomplete semantic map is
stated plainly; deterministic placement and impact evidence remain usable when safe.

## 7.2 Report architecture change, not a raw diff

Extend the existing bounded verification baseline and comparison so the changed scope reports:

- files that became oversized or grew toward the configured limit;
- functions whose branch or size burden materially increased;
- new or worsened incoming/outgoing coupling;
- dependency cycles introduced or resolved;
- declared or AI-mapped boundaries crossed by new relationships;
- responsibilities, public contracts, architecture placement, and reviewed pattern conclusions
  that changed;
- focused tests and protections that disappeared, appeared, or still need to run.

Classify every result as **introduced**, **worsened**, **improved**, **resolved**, or
**pre-existing**. Lead with the observed change, why it matters for this goal, the smallest sensible
response, reasons the code may be correct as written, and how to verify it. A changed hash or score
is evidence, not a conclusion that the design improved.

This is the first implementation slice. It upgrades the existing derived comparison contract and
stores no duplicate architecture history.

`architecture-verification-baseline-v2` and `architecture-verification-comparison-v2` now deliver
that slice. The baseline retains bounded file measurements, direct coupling, placement, semantic
responsibilities, and readable finding evidence. The comparison classifies at most 20 effects and
keeps the highest-priority guidance when the wider scope packet must be compacted. A real
scope → scan → scope fixture grows a healthy file past its repository rule, adds incoming and
outgoing links, creates a cycle, and crosses a declared boundary; the response separates all four
from an older size finding. Version-1 baselines remain readable and cannot create false metric
changes from fields they never stored. The complete 536-test suite passes at 91.39% coverage, and
all size, complexity, architecture, formatting, and self-analysis gates have zero errors.

## 7.3 Turn a large-file warning into a coherent decomposition map

When a file is over its configured limit or has strong mixed-responsibility evidence, combine its
symbols, semantic responsibilities, public contracts, incoming/outgoing edges, tests, placement,
and finalized pattern reviews. Return at most five proposed responsibility slices with:

- the symbols and job that belong together;
- the contracts and callers that must remain stable;
- the existing module or architecture area each slice belongs in, creating a new file only when no
  honest extension point exists;
- a safe extraction order and focused verification steps;
- coupling or cohesion evidence against the split.

Size alone never fabricates a split. If the file has one cohesive job or the semantic map is not
strong enough, say to keep it together and identify the missing evidence. AnaxiGraph proposes the
map; it does not edit the analyzed repository.

`large-file-decomposition-v1` now adds that map to the existing `architecture-decision-v1`
response. It reuses current dossiers, projected symbols, direct callers/dependencies, focused
tests, size findings, and finalized pattern reviews; it adds no semantic job, provider call,
table, endpoint, or screen. A split candidate requires a current dossier, an explicit split
recommendation of at least 65, supporting and opposing evidence, at least two named
responsibilities, and an unambiguous symbol mapping covering at least 60% of the selected file's
symbols. At most five files, five slices, and 30 symbols per slice are returned. The slice with the
most caller-facing contracts stays in the original file while lower-contract slices are ordered
first. If an existing destination cannot be justified from current similar-module evidence, the
result leaves the path unset and tells the agent to check the map before creating a sibling file.

Cohesive, stale, weak, ambiguous, and unmapped cases return `keep_together` or
`insufficient_evidence`, never a speculative extraction plan. The full and compact scope packets
retain the decision and extraction order, and the existing Agents view explains the recommendation,
counter-evidence, and checks. Focused backend tests and all 16 browser contracts pass; the complete
repository gate passes with 541 tests at 91.47% coverage, 0 self-analysis regressions, and the
container, first-user, Compose, package, formatting, size, complexity, and architecture contracts
all green.

## 7.4 Make hierarchy navigation task-centered

Reuse the current Map, module inspector, search, and scope response so a coding goal can move from
area → subsystem → module → symbol without loading the whole graph. At each level show why the code
is grouped there, its main responsibility, important boundaries, nearby extension points, and the
small set of related code likely to matter for the goal.

Do not add another graph visualization. Improve the existing architecture-first view and the same
bounded read models used by agents. The AI-reviewed taxonomy remains automatic map metadata; no
human approval or edit gate is introduced.

`task-path-v1` now adds one goal-specific route to the existing `architecture-decision-v1`
response: area → subsystem → selected module → matching symbols. It uses the same finalized
semantic taxonomy shown by Map when available, falls back to configured project groups, and labels
file-path guesses as guesses. The route explains each group's responsibility and why its files are
together, then carries the selected file's responsibility, contracts, extension points, direct
callers/dependencies, focused tests, and at most ten nearby files. At most eight symbols are
included, and only when their own name, signature, or summary matches words in the coding goal. A
module-only result is returned instead of inventing a symbol match.

The existing Agents view renders that route while the existing agent overlay highlights the same
working set on Map. CLI, MCP, REST, and dashboard therefore share one bounded contract. Normal
compaction retains responsibilities, grouping reasons, boundaries, tests, and symbol names; the
4 KB emergency packet retains the breadcrumb and matched names while removing duplicate detail.
The implementation adds one 342-line application module but no table, semantic job, model call,
route, dashboard state, or primary screen. It does not alter semantic input fingerprints or make
existing dossiers stale.

The complete Phase 7 gate passes with 545 Python tests at 91.56% coverage and all 16 browser
contracts. The task-path module has 100% statement coverage. The harmful-change scanner fixture
separates new size, coupling, cycle, and boundary problems from existing debt; the improvement
fixture reports smaller size, complexity, and coupling while retaining a pre-existing cycle; the
decomposition fixtures distinguish split, keep-together, stale, ambiguous, and unmapped cases; and
semantic plus configured-policy fixtures both produce an area → subsystem → module → symbol route.
An unchanged semantic reconciliation performs zero new work, while the tight scope fixture keeps
the comparison and route within 4 KB. Self-analysis, size, complexity, architecture, package,
Compose, hardened-container, and first-user gates report zero regressions.

## 7.5 Keep the implementation smaller than the problem

- Extend existing contracts and application services before adding a module or route.
- Add no persistent table unless a derived bounded read is measurably too slow.
- Add no new semantic job kind when current dossiers and pattern reviews contain the evidence.
- Add no policy language for a rule already expressible by current architecture configuration.
- Add no new primary dashboard screen; scope, Map, Modules, and Findings remain the product paths.
- Keep first-party implementation modules below 500 lines and normally between 100 and 350 lines.

## Phase 7 exit gate

- One before/after fixture introduces an oversized file, coupling growth, a boundary crossing, and a
  cycle; the same scope response distinguishes all four from pre-existing debt in ordinary language.
- A second fixture improves or resolves those conditions without calling an unrelated score change
  an improvement.
- A mixed-responsibility large file receives a bounded, evidence-backed extraction map; a cohesive
  large file receives an explicit keep-together result.
- A coding goal can identify an area, subsystem, preferred module/symbol, affected contracts, and
  focused tests through existing bounded CLI/MCP/REST/dashboard paths.
- An unchanged rescan creates no semantic or pattern work and the comparison stays within the
  existing agent payload budget.

---

# Phase 8 — focused history evidence for architecture risk

**Status:** COMPLETE on 25 August 2026

**Goal:** answer only two history questions that the current task loop cannot answer from a static
map: which nearby files repeatedly change with the selected code, and when a selected structural
problem appeared or disappeared. This is not a second history product.

**Feature admission:** this supporting phase improves placement, consolidation, decomposition, and
post-change decisions by showing repeated co-change and the lifetime of a specific structural
problem. It reuses immutable facts, snapshot deltas, findings, graph reads, and the existing history
import. It adds no renderer-specific history model, identity analytics, or general history score.

## 8.1 Add change coupling without inventing static edges

For configurable recent windows of saved commits that touched the task-selected files, identify
modules that repeatedly change in the same commits. Keep co-change separate from imports, calls,
and other static relationships. Scope the calculation to selected modules/areas and store only a
compact reusable projection if measured query cost requires it.

Expose this evidence once in the current architecture decision and attach the relevant subset to
consolidation context instead of duplicating it through every advice surface. Two files changing
together is a clue, not proof they should be merged.

**Status:** COMPLETE on 25 August 2026

`change-coupling-v1` reads the existing `git_changes` ledger on demand for at most eight selected
files. It examines the latest 100 relevant commits by default, clamps the window at 500, requires at
least two shared commits, returns at most 20 pairs by default, and caps output at 50. The query uses
the existing repository/path and repository/commit indexes, then considers only selected-file hits
against files in those commits; it never builds the dense product of every repository file pair.
Only files present in the current snapshot can be returned.

Each pair states how often it changed with the selected file and whether a real static relationship
also exists. A co-change-only result remains a history clue, never a graph edge, dependency claim,
or merge instruction. The evidence appears in the existing architecture-decision response,
file-specific consolidation context, bounded agent packet, and Agents view. It adds no table,
semantic job, model call, route, or primary screen.

Five focused history fixtures cover static versus co-change-only links, one-off changes, deleted
files, missing history, hard bounds, and selected-file work scaling. A 1,000-file fixture produces
1,000 selected pairs instead of 499,500 all-file pairs. The complete gate passes with 552 Python
tests at 91.60% coverage and all 16 browser contracts. Self-analysis reports zero regressions;
architecture, size, complexity, and JavaScript checks pass. Moving the already-cohesive decision
compactor into a 98-line module reduced `agent_payload.py` from 497 to 391 lines.

## 8.2 Answer when a structural problem appeared

For a selected cycle, boundary crossing, oversized module or responsibility, or other current
structural finding, identify the earliest retained frame that exhibits it and the frame that
resolves it when one exists. Agents and people should be able to ask “is this new, persistent,
improving, or regressed?” through existing history, finding, graph, and scope paths.

**Status:** COMPLETE on 25 August 2026

`finding-history-v1` follows only the current snapshot's stored `base_snapshot_id` lineage and
compares one selected stable finding across those retained frames. Historical architecture scans
now save their deterministic occurrences without changing the live attention queue. Reused frames
are refreshed from the already stored immutable facts and relationships; they do not reread source,
create semantic work, change the analysis signature, or invalidate current dossiers. A snapshot
metadata marker distinguishes “not observed” from an older frame that predates this evidence.

The existing `ANAXIGRAPH_FINDING_CONTEXT` / REST finding-context response and Agents handoff now
classify the selected condition as new, persistent, resolved, regressed, not observed, or unknown.
They name the first retained appearance, latest disappearance, and later return, return at most 12
transition records, and state plainly that retained frames may sample Git history. No schema table,
route, MCP tool, semantic job, model call, replay engine, or primary dashboard view was added.

A real four-commit fixture introduces a Python dependency cycle, removes it, and brings it back.
It proves exact introduction, resolution, and regression commit identities, live-ledger safety,
and reuse of previously indexed frames. The complete gate passes with 554 Python tests at 91.60%
coverage and all 17 browser contracts. Container hardening, first-user startup, the bounded history
benchmark, JavaScript, architecture, size, complexity, coupling, and Compose checks pass;
self-analysis reports 26 governed findings, 136 non-blocking findings, and zero regressions. The
change also lowers the `evaluate_architecture` and finding-lifecycle maintainability ratchets.

## Phase 8 exit gate

- A fixture identifies two repeatedly co-changing modules with no static edge and labels that
  distinction correctly.
- A user or agent can identify the retained change that introduced and resolved a fixture cycle or
  boundary regression.
- The calculations scale with changed files and selected history frames, not the dense product of
  all modules and commits.
- No animated playback, ownership-identity model, or new primary dashboard view is required.

---

# Phase 9 — make the real core loop dependable, then prove it for 1.0

**Status:** COMPLETE on 26 August 2026; optional external MaxOS evidence remains paused

**Goal:** prove that the existing AnaxiGraph loop helps a person or coding agent place and change
code without creating sprawl, tangled dependencies, misplaced responsibilities, or giant files.
Phase 9 is a bounded core-defect and acceptance phase, not another feature family.

The re-evaluation removed generic product-maturity work from the active path. Package installation,
schema migration, online backup/restore, platform and analyzer-depth disclosure, semantic-egress
controls, container hardening, artifact attestations, and public-install verification already exist.
Their current tests remain release gates, but they do not justify new subsystems, surfaces, or
documentation projects.

The same re-evaluation stopped the self-analysis backlog from becoming feature work. Phase 9 does
not chase every accepted warning, add plain-language coverage to every administrative response, or
split a cohesive module merely to lower a metric. Internal cleanup is part of a Phase 9 change only
when that change touches the code or cannot pass a hard quality gate without it.

## 9.0 Make the served map authoritative and current

**Status:** COMPLETE on 26 August 2026

The active AnaxiGraph MCP service returned snapshot 221 at commit `80a44a7`, with an empty semantic
hierarchy, while the repository's `main` branch had advanced. The response was internally valid but
could not support the promise that an agent sees the repository it is about to change. Treat this
as a product defect, not an operator footnote.

Fix and accept the existing lifecycle so that:

- CLI, MCP, watcher, and sidecar resolution identify the same repository and authoritative index;
- status names the mapped commit or working-tree fingerprint, the checkout state it was compared
  with, semantic current/stale coverage, and a plain reason for any lag;
- a changed checkout is incrementally scanned or explicitly reported as paused/blocked; an older
  map is never silently presented as current;
- semantic invalidation is scoped to changed evidence or a genuinely incompatible contract, while
  the last known interpretation remains visible as stale instead of disappearing into a misleading
  zero-knowledge state;
- agent-funded execution uses operator-selected provider/model/reasoning settings, safely claims a
  bounded parallel batch, survives interruption through leases and requeueing, and does not report
  success until the durable queue returns `complete`;
- local, service, and container-path identity fixtures reproduce the exact behavior without adding
  another index, provider pipeline, scheduler, or configuration system.

The paused MaxOS semantic run remains paused. Reproduce and fix lifecycle defects against the
self-hosted AnaxiGraph index and deterministic fixtures until the operator explicitly resumes that
run.

Delivered currentness acceptance reuses the existing registry, index, scanner, watcher, REST, and
MCP paths. `served-map-status-v1` compares the saved commit and working-tree fingerprint with the
mounted checkout and labels the map `current`, `stale`, `uncertain`, or `unavailable`; agent scope,
impact, inventory, semantic status, and semantic work all carry that result. A stale map cannot
claim semantic work. The structural watcher now starts by default, while the API/MCP service
becomes healthy before a potentially long first scan and clearly serves the last map as stale until
the replacement transaction commits. Current-schema index startup no longer reruns full migration
and compatibility compaction, and the next lock-owning structural scan closes abandoned `running`
records as `interrupted`.

Live sidecar acceptance rebuilt the runtime at 0.3.0 and refreshed both configured repositories.
Direct MCP reads returned AnaxiGraph snapshot 223 at commit `39254ef`, with the saved and checkout
working-tree fingerprints equal, `safe_to_plan: true`, the service and scanner both at 0.3.0, both
containers healthy/running, and zero phantom active structural runs. MaxOS likewise reached its
exact checkout commit through the default watcher. The retained semantic run was not resumed;
semantic status remained not ready with zero live or expired leases. The complete 565-test suite
passed at 91.56% coverage before the two focused lifecycle follow-ups; 26 startup/onboarding tests,
20 migration/recovery tests, and four scan-lock/storage tests passed afterward with all size,
complexity, coupling, architecture, formatting, and hook gates clean.

Semantic execution acceptance now separates process liveness from stage progress. The detached
wrapper refreshes its own heartbeat while its child is alive, so a valid partitioned taxonomy job
cannot be declared stalled merely because it needs more than one model call. Operator model names
remain free-form, and Codex reasoning effort is passed through instead of being restricted by an
AnaxiGraph-owned list; `gpt-5.6-terra`, `medium`, and a requested parallel limit of 30 are preserved
through the command and durable-run record while repository policy still supplies the ceiling. The
real MCP lifecycle fixture processes 200 modules in bounded 16-call waves, stops after 100 jobs,
restarts the service, reclaims an abandoned expired lease, and reaches an empty durable queue,
complete coverage, repository synthesis, pattern completion, and an independently reviewed
taxonomy without changing source. The gate also caught and fixed a startup fast-path regression:
current indexes still skip full migration/compaction, but restore missing bounded-history checkpoint
metadata. Forty-six focused semantic lifecycle tests and 20 temporal/migration/recovery tests pass.
The complete 568-test suite passed at 91.70% coverage before the final direct progress-sync
assertion raised changed executable coverage for this slice to 100%; formatting, size, complexity,
dependency, package-contract, and deterministic self-analysis gates are clean.

Self-hosted semantic acceptance then completed against authoritative sidecar snapshot 239 at commit
`6318bae`, including the existing dirty-tree fingerprint. Run
`99b08683-9345-40bb-a344-c75c76ca4e1e` used operator-selected `gpt-5.6-terra`, medium reasoning,
30 parallel calls, and exited zero after 417 jobs. All 465 module descriptions, 21 area/subsystem
summaries, and the repository summary are current. Two autonomous reviews produced a valid
hierarchy of five areas and 16 subsystems with all 465 files assigned, zero repairs, and no
unclassified or shared-runtime catch-all. The sparse plan finalized all 200 selected pattern
evaluations with zero pending, failed, expired, or reclaimable work. The durable wrapper ended
`complete`; it did not stop at an intermediate “still running” message.

## 9.1 Protect the smallest agent-facing contract

**Status:** COMPLETE on 25 August 2026

Freeze the names and minimum versioned response fields needed for one workflow:

1. start or scan a repository and read its map;
2. ask where a coding goal belongs and inspect direct/reverse impact;
3. inspect actionable findings, pattern advice, and a large-file decomposition when relevant;
4. run or resume semantic work without model names becoming stored architecture identity;
5. rescan and compare the focused before-change record with the result.

Use characterization tests around the existing CLI, REST, and MCP paths. The contract is a required
subset, not a freeze on every administrative command or every response field. New API versions,
compatibility frameworks, transports, and duplicated workflow endpoints are outside this slice.

`coding-loop-contract-v2` is now returned by the existing REST glossary and
`ANAXIGRAPH_GUIDE(topic="coding_loop")`. It names ten CLI commands, fifteen REST method/path pairs,
nineteen MCP tools, and fourteen versioned result locations as required subsets. It also defines
the development cadence: one persistent structural watcher, scope and impact before editing,
ordinary focused-test work without model calls after every save, one explicit scan and same-goal
comparison at a coherent checkpoint, and one changed-scope semantic refresh afterward when needed.
Parser, generated OpenAPI, live MCP, and implementation-version characterization tests fail on an accidental removal,
rename, or incompatible version change. This added no endpoint, database state, provider path, UI,
or compatibility framework. The complete Python suite passes with 555 tests at 91.60% coverage;
module size, code quality, architecture, Ruff, and focused REST/MCP tests also pass.

## 9.2 Prove architecture decisions at representative sizes

**Status:** COMPLETE on 26 August 2026; external MaxOS evidence is optional and paused

Run the same coding tasks against small, medium, and large Python-first repositories. Record only
measurements that decide whether the map is useful:

- whether the right extension point, affected contracts, tests, and direct neighbors are returned;
- whether a mixed-responsibility large file gets a coherent split while a cohesive one stays
  together;
- whether introduced, worsened, improved, resolved, and pre-existing structural effects are
  classified correctly;
- relationship resolution/ambiguity, unnecessary-file rate, bounded payload size, scan/update
  work, and response time;
- whether interrupted semantic work resumes against the authoritative index and reaches explicit
  completion without rereading unchanged modules.

Deterministic fixtures and the repository's own self-analysis can run now. After §9.0 makes the
self-hosted map current, use it for real AnaxiGraph tasks covering placement, reverse impact,
multi-level pattern fit, mixed-responsibility decomposition, and the before/after architecture
comparison. Record whether the first recommendation was useful, which files were unnecessary, and
whether its explanation was directly actionable. Fix demonstrated defects through existing paths;
do not widen the product to improve a benchmark score.

The live MaxOS semantic run remains paused at the operator's request. Do not resume it or replace it
with adjacent features. It is optional external evidence and does not decide whether this phase's
self-hosted core loop is complete.

`tests/test_core_loop_scale.py` now repeats one coding task at 120, 1,000, and 3,000 files. Every
size returns the same eight expected primary files and no unrelated primary file, chooses
`src/sample/analyzers/base.py` as the task path and `src/sample/languages.py` as the preferred
placement, finds the same two direct dependants, and keeps the exact response within 20 KB. It then
introduces a real dependency cycle by changing one file and resolves it with a second one-file
change; each update analyzes one file and the before/after contract classifies the introduction and
resolution correctly.

The first probe exposed a core-loop defect: compacting a large scope packet discarded its
before-change baseline, so an agent could not perform the promised later comparison. Normal bounded
packets now retain `architecture-verification-baseline-v2`. An explicitly tiny 4 KB policy still
stays inside its configured limit, but reports plainly that the baseline was omitted and tells the
agent to request a larger limit before editing. The fitting logic lives in the existing
architecture-decision compactor; `agent_payload.py` remains below the 500-line hard limit.

| Files | One-frame map | Vacuumed index | Scope | Scope bytes | Expected / unrelated primary files |
|---:|---:|---:|---:|---:|---:|
| 120 | 573 ms | 1,146,880 | 67 ms | 13,182 | 8 / 0 |
| 1,000 | 4,452 ms | 6,414,336 | 192 ms | 13,182 | 8 / 0 |
| 3,000 | 15,189 ms | 18,378,752 | 510 ms | 13,182 | 8 / 0 |

These absolute times describe one 16-core Linux runner; accuracy, bounded payload, baseline
presence, and one-file incremental work are the contracts. The exact environment and results are
retained in `benchmarks/results/core-loop-scale-2026-08-25.json`. Mixed-versus-cohesive large-file
decisions and all five structural-effect classes remain covered by focused bounded fixtures after
scope selection; multiplying irrelevant modules inside those already-local calculations would not
add product evidence. The self-hosted precision task set is complete; the paused MaxOS run is
optional external evidence. The complete Python suite passes with 559 tests at
91.63% coverage; Ruff, module-size, code-quality, architecture, and self-analysis gates also pass.

The first current-map placement task exposed a core defect instead of being counted as a success.
A roadmap-only goal ranked `pattern_evidence_features.py` above the actual development plan because
every repeated generic word in a long semantic description increased its score, and a later symbol
match could displace a more relevant document. Goal terms now contribute at most once per evidence
field, a small alias connects “roadmap” with “plan,” and explicit documentation or test intent gets
a bounded artifact-kind preference. A matching document also survives the later symbol step. On
the same snapshot and goal, the preferred file and task path are now both
`docs/feature-development-plan.md`; focused tests include a deliberately noisy feature module, an
explicit test-edit goal, and the existing 120/1,000/3,000-file precision fixtures.

Reverse impact then passed against `src/anaxigraph/semantic_ports.py`. It returned the exact four
direct dependants, a bounded 64-file transitive set, 30 relevant tests, and no migration paths; the
direct edges were independently checked against source imports. Multi-level pattern fit,
mixed-versus-cohesive large-file decomposition, and a real before/after architecture comparison all
subsequently passed and are recorded in the active re-evaluation above.

A broader self-hosted goal then proved that placement was still too dependent on the user's words
looking like a filename. “Verify whether a code change improved the repository structure without
making files larger or dependencies more tangled” selected `scripts/verify_release_artifacts.py`
and routed the hierarchy through `relationship_builder.py`, even though
`agent_decision_verification.py` owns that behavior. The fix stays inside the existing lexical
ranker: normalize snake-case names, ignore generic goal filler, and expand only a few core product
concepts such as structure/architecture, verify/compare, size/large, and dependency/coupling.

Authoritative snapshot 316 closed the acceptance. The same goal returned a five-file primary set
centered on `agent_decision_verification.py`, selected `compare_verification_baselines`,
`verification_baseline`, and `_comparison_status`, and placed them under the reviewed area “Prepare
change help and AI code reports” and subsystem “Choose files and explain a requested change.” No
release or unrelated file entered the primary set. A separate telemetry-placement goal selected
the existing `semantic_status_queries.py` responsibility and named `SemanticStatusRows`,
`read_semantic_status`, and `_usage` as extension points. The paired controlled fixture permits a
new sibling only when no supplied destination honestly owns the responsibility. Together these
results close both concept-level precision and extend-existing-versus-create-new acceptance without
adding another planning path.

## 9.3 Keep one documented coding loop

**Status:** COMPLETE; CONTINUOUS CADENCE AND TELEMETRY ADDED on 26 August 2026

The primary documentation shows one path: start AnaxiGraph, understand the map, ask where a change
belongs, inspect impact, make the change, update the map, and verify architecture effects. Existing
advanced operations stay available by link. Phase 9 adds no second tutorial, dashboard, planning
surface, or operator product.

README and onboarding now share one concrete scope → impact → change/test → rescan → same-goal
comparison sequence. Both name the saved `post_change_baseline`, the returned
`post_change_comparison`, and the rule that a difference is not automatically an improvement. The
existing agent plugin already executes that sequence. `tests/test_onboarding_docs.py` protects its
order while advanced and operator modes remain linked outside the primary path. The complete Python
suite passes with 560 tests at 91.63% coverage.

The same primary docs, machine-readable guide, and agent skill now state how to use the loop for a
whole coding session. A persistent watcher keeps deterministic source facts current. A full AI map
is a cold-start operation; during normal edits no model-backed work runs on every save. The agent
does one explicit structural verification at a coherent task boundary, then may run one durable
background `understand` command that reuses unchanged semantic scopes. A structural comparison may
finish before that background refresh; only a decision that needs a completely current AI map waits
for `semantically_ready`.

`action-telemetry-v1` uses existing responses and stored run/job rows instead of a new monitoring
system. Scope, impact, and graph reads report server duration, reply bytes, and zero model tokens.
Semantic status groups current-snapshot and lifetime work by action with model names, completions,
failures, task duration, input/output tokens, and cost. Structural scans remain grouped by run type,
and detached semantic records expose elapsed wall time. Summed parallel-job time is explicitly
distinguished from real elapsed time. Successful unchanged scans and completed history jobs count
as finished actions, interrupted offline time is excluded, and missing executor token reports are
shown as unknown usage instead of zero-cost work. Failed model attempts record executor-reported
tokens and retry only their own job; interruption before model work releases a lease without
counting a failed attempt. The Codex executor reads its JSONL completion usage while keeping the
schema-constrained final answer separate. Focused taxonomy, provider,
coding-loop, queue, API/MCP,
documentation, and telemetry tests pass.

Self-hosted calibration used the authoritative sidecar rather than a second host database. A full
Terra/medium run completed 466 current modules and 200 reviewed pattern decisions with 12,527,575
input tokens, 909,458 output/reasoning tokens, 16,885,106 ms of summed parallel task time, and about
45 minutes of real elapsed time. The continuous-loop probes then returned the telemetry-placement
goal in 1.94 seconds wall time (752 ms server time, 16,902 bytes) and the architecture-verification
goal in 1.63 seconds (590 ms server time, 17,403 bytes), down from a profiled 76-second scope path.
Both ordinary CLI calls selected the matching sidecar automatically. The profile showed repeated
decoding of all 200 saved pattern results as the main delay; the read path now filters the requested
module in SQLite before decoding. These measurements are calibration evidence, not fixed performance
promises across machines or repositories.

## Phase 9 exit gate

- CLI, MCP, watcher, and sidecar checks resolve one authoritative index and report whether its
  structural and semantic views match the checkout they claim to describe.
- A bounded parallel agent-funded run uses operator-selected model settings, survives an interrupted
  controller, resumes without losing completed work, and returns `complete` only after the durable
  queue is empty.
- The required CLI, REST, and MCP subset has a versioned characterization test and remains bounded.
- The complete before/after coding loop passes the same decision fixtures at small, medium, and
  large scales within the declared Python-first support boundary, then gives useful placement,
  impact, pattern, decomposition, and verification advice on the current AnaxiGraph map.
- Optional external repository runs use the same authoritative-index and explicit-completion
  contracts when the operator chooses to run them; they do not block the self-hosted core loop.
- Existing install, migration, backup/restore, container, and release-integrity gates remain green.
- No first-party implementation module exceeds 500 lines and no temporary architecture waiver
  remains.
- The main documentation distinguishes deterministic facts, semantic interpretations,
  recommendations, source egress, analyzer depth, and unsupported behavior in ordinary language.

---

# Phase 10 — converge on shared architecture intelligence

**Status:** COMPLETE on 1 September 2026

**Goal:** make AnaxiGraph simpler to understand, operate, and maintain while sharpening the one
thing it exists to do: give people and coding agents the same living understanding of a software
system and use that understanding to guide cleaner changes.

This is a subtraction and convergence phase, not a new feature family. The existing scanner,
AnaxiIndex, semantic dossiers, taxonomy, pattern evidence, history, dashboard, and AnaxiMCP already
contain most of the required capability. The work is to remove competing concepts, organize the
useful parts around the three promises and at most five journeys, and prove the same outcomes with
human-led and agent-only use.

## 10.0 Make the mission an operating rule

**Status:** COMPLETE on 30 August 2026

The README, product brief, architecture description, package metadata, dashboard onboarding, agent
plugin, contributor guidance, and this roadmap use one position:

> **AnaxiGraph is the shared architecture intelligence layer for humans and AI agents. It explains
> what a software system does and how its parts work together, while guiding future changes toward
> a cleaner, more coherent design.**

The concise product language is:

> **Understand the system. Guide the agent. Keep the architecture coherent.**

Pull requests must identify which promise and user decision they advance, what existing surface
they reuse, and what they remove or replace. This turns positioning into an admission gate rather
than a paragraph that implementation can ignore.

## 10.1 Inventory the product surface and write the deletion map

**Status:** COMPLETE on 30 August 2026

Before changing architecture, trace every top-level dashboard journey, default MCP tool, CLI command
family, REST route family, database table family, and major module cluster to one of:

1. a direct **Understand**, **Guide**, or **Keep coherent** user decision;
2. shared enabling infrastructure required by those decisions;
3. an advanced operator or semantic-executor mechanism that should be hidden from normal use;
4. duplicated, legacy, pass-through, or speculative machinery that should be consolidated or
   removed.

Record call sites, stored state, compatibility obligations, tests, and public consumers before
marking anything removable. Give special attention to the 57 semantic files, 51 persistence files
(50 import modules), 25 MCP tools, and repeated language/projection layers. The result is one
ordered deletion map, not another permanent inventory subsystem.

Documentation is part of the same surface. This active roadmap now exceeds 3,000 lines and the
original product brief exceeds 2,000; completed detail should be collapsed into a short delivery
record rather than copied to another tracked archive. Git already preserves the full history.

Acceptance:

- every public surface and major code cluster has one owner and one reason to exist;
- ordinary user journeys are separated from operator/executor primitives;
- removal candidates name the behavior and test that must survive;
- README, product brief, architecture document, and active roadmap have distinct non-repeating jobs;
- no feature implementation, new table, new tool, or new dashboard destination lands during the
  inventory.

### 10.1 delivery record: measured surface

The inventory used the checked-out source, static import graph, test and documentation call sites,
CLI and MCP registrations, dashboard fetches, and the self-hosted AnaxiIndex at commit `676fb4e`.
It records a measured starting point, not a permanent source-of-truth generator:

| Surface | Measured state | Normal owner | Required outcome |
|---|---:|---|---|
| Dashboard | 7 top-level tabs | shared understanding and guidance | converge to at most 5 task journeys; Files and Graph become representations of one selection |
| CLI | 21 top-level commands | local/operator adapter | document a short normal path and move administration, import, worker, and recovery commands under advanced use |
| MCP | 25 registered tools | coding-agent adapter | publish a default profile of at most 10 decision tools; keep executor/operator primitives in named advanced profiles |
| REST | approximately 34 API routes | dashboard and MCP transport | keep route families internal; consolidate only after their shared read models converge |
| SQLite | 34 tables | AnaxiIndex | retain canonical facts and evidence, bound operational history, and remove transaction-only staging after consumers move |
| Python | 245 import modules | implementation | remove forwarding fragments and repeated projections without merging unrelated responsibilities |
| Production source | 53,907 Python/dashboard lines | whole product | add a non-growth ratchet and remove whole duplicate paths; the owner accepted the resulting 49,797-line baseline rather than forcing code golf to reach the original 48,500 directional target |

The apparent `80,000`-line product includes 17,883 lines of tests plus benchmark/tool code. Those
tests are valuable executable contracts and are not the reduction target. The production baseline
is 48,522 Python lines and 5,385 dashboard HTML/CSS/JavaScript lines. Both numbers matter: moving
logic between Python and the browser must not game the combined budget.

### Principal and transport surfaces

The seven dashboard destinations are not seven independent products:

| Current destination | Decision served | Disposition |
|---|---|---|
| Overview | understand purpose, health, and attention | becomes the entry to **Understand** and **Improve** |
| Files | inspect a module and its evidence | becomes a table/detail representation inside **Understand** |
| Graph | inspect relationships and architecture placement | becomes a visual representation inside **Understand**, preserving the same selection as Files |
| Architecture | inspect intended versus observed structure | joins **Understand** for explanation and **Improve** for violations |
| History | understand architectural evolution and current consequences | becomes evidence within **Changes** |
| Agents | turn evidence into bounded architecture guidance | becomes the plain-language **Guide** journey |
| Settings | repository, scan, semantic, and operator controls | remains **Settings**, with advanced controls collapsed by default |

The normal MCP profile will expose no more than these ten existing decisions: repository selection,
overview, search, file evidence, scope/placement, impact, findings, scan/refresh, semantic readiness,
and taxonomy. `GRAPH`, `PATTERNS`, `FINDING_CONTEXT`, the three history controls, and the
six low-level semantic queue/schema controls remain available through advanced operator or executor
profiles until compatibility evidence permits consolidation.
The current `coding-loop-contract-v2` freezes a released 19-tool subset, so the smaller default must
ship as a versioned profile rather than silently changing the old contract. `FINDINGS` may eventually
absorb optional finding detail, and durable docs plus the installed skill may replace `GUIDE`, but
only after old clients receive a deprecation path.

The CLI commands divide into four ordinary outcomes—start/use the service, build understanding,
inspect readiness, and diagnose it—and advanced adapters for scan/update/review/watch/export,
finding lifecycle, semantic workers, patterns/history, server/MCP operation, and scope/impact,
and backup/restore. This phase does not remove a released command merely to improve a count. It first
makes the normal path obvious, observes real use, and then aliases or retires only redundant paths.

REST is principally the dashboard's private adapter. Roughly 22 endpoints have direct browser call
sites, and the remainder serve operation, history, semantic, or compatibility workflows. Route count
therefore is not itself a product metric. Shared query/response services should converge before any
route is merged, so the dashboard and MCP never acquire separate architecture models to achieve a
smaller transport surface.

### Stored-state surface

The 34 SQLite tables have six distinct responsibilities:

| Family | Tables | Decision |
|---|---:|---|
| repository, schema, identity, and time | 8 | retain as canonical identity, configuration, migration, and history state |
| canonical extracted facts, edges, checkpoints, and metrics | 11 | retain as the deterministic foundation shared by every consumer |
| finding lifecycle | 2 | retain; converge queries and ranking rather than creating another advice store |
| semantic documents, claims, queue state, and taxonomy | 8 | retain the evidence model; compact duplicated execution history and repeated projections |
| operational scan history | 1 | retain bounded audit/liveness evidence, not every no-change poll forever |
| transaction-local compatibility projections | 4 | remove after architecture evaluation reads the canonical projection directly |

The four compatibility projection tables are `file_versions`, `symbols`, `relationships`, and
`group_memberships`. At inventory time a scan materialized three of them, translated them into the
canonical temporal model, and cleared all four before commit. Characterization then corrected one
assumption in this map: deterministic architecture evaluation already consumed canonical
`architecture_evidence`; the remaining dependency was the scanner's write/translate/delete path,
not the detector. Migration tests still cover schemas 2, 6, 7, 8, 9, and 10, so released input
readers must survive even after current scans and fresh indexes stop creating the old tables.

The live two-repository sidecar exposed two separate retention problems:

- `analysis_runs` held about 90,100 `watch/unchanged` rows—one durable row per no-op poll—and occupied
  about 18 MB. Explicit scans and changed, failed, cancelled, or interrupted watcher runs are useful
  audit evidence; an unlimited history of identical liveness polls is not.
- `semantic_jobs` occupied about 50 MB, including roughly 12,665 superseded module jobs and repeated
  completed-job metadata. Active leases, failures, cost/provenance summaries, and the documents they
  produced must survive. A call-site audit must prove what completed metadata duplicates before any
  retention or compaction rule is introduced.

The sidecar also demonstrated a coordination cost: a structural scan whose measured work took about
1.2 seconds waited roughly 95 seconds for the database-wide scan lock while the other registered
repository was being watched. Per-repository locking is a candidate only after transaction and
semantic-carry behavior is characterized; it must not be folded casually into the retention fix.

### Major implementation clusters

| Cluster | Files/modules and lines | Product responsibility | Inventory decision |
|---|---:|---|---|
| Semantic | 57 files / 13,038 lines | explain responsibility, compose context, review patterns and taxonomy | keep capability; converge repeated planning, language, projection, execution, and status shapes |
| Persistence | 51 files, 50 import modules / 9,291 lines | make facts, evidence, lifecycle, and time durable | keep canonical model; remove transaction-only projection and one-use forwarding layers in characterized steps |
| Agent | 19 modules / 5,121 lines | turn shared evidence into placement, impact, and verification decisions | keep decisions; converge duplicated payload and response composition |
| Foundation/config/other | 26 modules / 4,468 lines | shared contracts, configuration, Git, and composition | keep explicit boundaries; remove only pass-through compatibility with a real caller map |
| Pattern intelligence | 19 modules / 4,174 lines | evidence-backed pattern, duplication, dead-code, and refactor advice | keep one recommendation model; eliminate semantic/static projection duplication |
| Extraction | 16 modules / 2,720 lines | produce deterministic language facts | keep analyzer boundary; share language identity and capability reporting |
| API | 19 modules / 1,718 lines | adapt shared services to the dashboard | keep thin transport; do not duplicate read models |
| CLI | 12 modules / 1,493 lines | adapt shared services to local workflows | keep composition; separate normal and advanced discovery before removal |
| History | 5 modules / 1,366 lines | provide temporal evidence | keep one time model; avoid turning history into a separate product family |
| Architecture | 6 modules / 1,342 lines | compare intended and observed structure | make it consume canonical projections directly |
| Onboarding | 6 modules / 1,329 lines | get a person and agent to first value | converge generated instructions and durable docs around one ordinary path |
| Scan | 5 modules / 1,266 lines | refresh deterministic facts safely | retain; bound no-op telemetry and later examine repository-scoped coordination |
| Finding | 5 modules / 1,196 lines | prioritize and preserve review lifecycle | retain; join list/detail language where it removes a real duplicate |

Small files are not automatically bloat. `api_models`, `architecture_graph`, and
`semantic_services` express useful transport, algorithm, and composition boundaries. In contrast,
`persistence/finding_facade.py` is a six-line re-export consumed only by `index_facade` and is a
specific later removal candidate once its direct imports are characterized. Near-ceiling modules
such as `storage.py` and `module_read.py` must be simplified before adjacent fragments are merged;
mechanically combining files would merely hide the module count while worsening cohesion.

### Ordered deletion and convergence map

Each item is one independently testable vertical slice. Later items do not begin because an earlier
one looks easy; they begin after its surviving contract and reduction are recorded.

1. **Bound no-op operational history.** Preserve explicit-scan audit rows and all changed, failed,
   cancelled, and interrupted watcher outcomes. Keep only bounded watcher liveness evidence per
   repository, compact existing no-op rows transactionally, and prove telemetry still distinguishes
   completed work from interruption. This immediately stops demonstrated database growth.
2. **Install the combined production-source ratchet.** Count first-party Python plus dashboard
   HTML/CSS/JavaScript, reject growth over 53,907, and lower the exact baseline with every following
   consolidation. Tests and generated/runtime data remain outside this budget.
3. **Compact semantic execution history only after a read-path audit.** Keep current leases, retry
   evidence, failures, token/cost/provenance summaries, and durable semantic documents. Remove or
   summarize superseded and duplicated job payloads only after status, pattern, taxonomy, backup,
   restore, and MCP characterization tests prove the retained contract.
4. **Write scans directly to canonical facts.** Characterize identical architecture findings and
   group evaluation, then stop populating the four empty compatibility projections. Remove their
   current-index schema and runtime materialization while preserving readers for released indexes.
5. **Converge semantic projections and composition.** Establish one internal representation for
   scope identity, language support, evidence references, result provenance, and readiness. Delete
   conversions and one-use service forwarding layers made redundant by that representation; do not
   collapse planning, execution, and validation into a new god object.
6. **Publish bounded public profiles.** Add the versioned ten-tool normal MCP profile and ordinary
   CLI discovery, then deprecate genuinely duplicated guide/detail/raw-query paths with compatibility
   tests. Executor queue primitives remain explicit and fully usable.
7. **Converge the dashboard around shared selection and read models.** Move Files, Graph, and
   Architecture beneath Understand; separate explanation from recommendation; reuse the same backend
   responses as MCP; delete superseded controllers, renderers, and duplicated state only after browser
   task tests pass.
8. **Remove remaining forwarding fragments and collapse completed documentation.** Delete proven
   one-use facades, repeated generated prose, and completed roadmap narrative. Retain cohesive
   algorithm, transport-schema, and composition boundaries even when they are small.

The inventory itself added no runtime surface. Its first implementation slice is deliberately the
bounded watcher history because it is a measured self-hosting failure, has a narrow surviving
contract, and prevents continued growth while deeper semantic and projection work is characterized.

## 10.2 Consolidate the implementation without hiding complexity

**Status:** COMPLETE on 31 August 2026 by owner acceptance of the substantive reduction.

Work through the deletion map one coherent vertical slice at a time. Preserve characterization
tests first, then remove duplicated transformations, obsolete compatibility, one-use forwarding
layers, repeated response language, and unnecessary orchestration. Merge tiny fragments only when
they change for the same reason; shrink near-ceiling modules by simplifying behavior, not by moving
the same lines into another file.

The original package budget is the measured 53,907 production Python/dashboard lines. It was added
to the maintainability ratchet and lowered after every successful consolidation. The initial
directional target was a ten-percent reduction to 48,500 or fewer lines, but that number never
authorized code golf, lost tests, wider modules, generated opacity, or collapsed boundaries. The
owner closed this phase at 49,797 after the remaining work stopped identifying whole duplicate paths
and began selecting code merely to satisfy the number. That explicit revision is preferable to
gaming the gate.

Priority order:

1. semantic planning, execution, taxonomy, status, and repeated language projections;
2. persistence query/projection fragments and compatibility code;
3. agent decision/payload composition and duplicated transport shapes;
4. dashboard controllers and repeated rendering/state handling;
5. CLI/API/MCP adapters after the underlying services converge.

Acceptance:

- production LOC follows a shrinking, tracked package-level ratchet;
- production module and public-surface counts decrease without creating a new oversized module;
- the 500-line, complexity, coupling, layer, changed-coverage, migration, and browser gates remain
  green;
- every retained service has one sentence explaining its responsibility and one obvious caller;
- source compatibility is kept only when a real released consumer or migration requires it.

### 10.2 delivery record: bounded watcher history and source ratchet

The first vertical slice preserves every explicit scan plus changed, failed, cancelled, and
interrupted watcher outcome, while retaining only the latest unchanged watcher poll for each
repository. The cleanup runs transactionally when the next watcher poll starts, so an existing index
with tens of thousands of no-op rows becomes logically compact without a migration, startup pause,
or automatic `VACUUM`. SQLite may keep freed pages in the database file for reuse; physical file
shrinking remains an explicit operator maintenance decision.

Characterization proves that a changed watcher run and the latest no-op remain, an older no-op is
removed, explicit unchanged scans are not removed, and abandoned running work is still marked
interrupted. The implementation introduced no table, migration, module, command, route, or public
tool. Replacing its long list of persistence symbol imports with the existing facade namespace also
made that dependency explicit and reduced `storage.py` from 498 to 488 physical lines without
removing the released `initialize()` method or `SCHEMA_VERSION` export.

The existing maintainability pre-commit gate now counts all first-party `.py`, dashboard
JavaScript/TypeScript, CSS, and HTML beneath `src/anaxigraph`. Its exact shrinking baseline is
**53,897 lines** after the watcher slice. Growth fails with removal/simplification guidance; a lower
count also fails until the contributor lowers the recorded baseline in the same change. Tests and
tooling do not count toward that production budget and cannot be used to offset production growth.
The next consolidation slice follows the semantic-job read-path audit recorded in §10.1.

### 10.2 delivery record: terminal semantic payload compaction

The read-path audit found that deleting terminal `semantic_jobs` rows would break useful contracts.
Completed rows support idempotent coding-agent retries and lifetime duration/cost telemetry; failed
rows retain the packet required to retry; current pattern evaluation reads candidate-selection fields
from its completed assessment job. The durable lifecycle row is therefore retained.

The duplicated work packet is now compacted instead. Pending, retrying, running, and failed work
keeps its full metadata. A completed pattern assessment keeps a versioned
`pattern-evaluation-v1` payload containing its candidate; all other completed and superseded jobs
clear metadata that is already represented by `semantic_documents`, scope state, taxonomy, pattern,
or error/provenance columns. Completion and supersession compact new rows in their existing
transactions. Index initialization safely compacts valid legacy JSON once and leaves malformed
legacy payloads untouched rather than destroying uncertain evidence.

On the pre-change self-hosted index this policy identifies **37,146,976 duplicated metadata bytes**:
about 24.3 MB from non-pattern terminal packets and 12.9 MB from pattern evidence not needed by the
current UI. Rows, job ids, lease-token hashes, status, attempts, timestamps, errors, models, token
counts, and costs remain unchanged. As with watcher cleanup, SQLite may reuse freed pages without an
automatic `VACUUM`.

The deployed self-hosted index reduced total semantic-job metadata to 2,024,883 bytes and increased
reclaimable database space from about 47.3 MB to 76.9 MB. `PRAGMA quick_check` remained clean, all
1,872 actionable packets remained non-empty, all 812 completed assessments retained the versioned
pattern payload, and a saved 200-item pattern map still returned its target and candidate evidence
through the normal REST projection.

The same slice removes two one-use persistence forwarding modules, inlines module-ledger
orchestration into `AnaxiIndex`, and removes an `__all__` list that duplicated the facade imports
without changing its names. Existing finding-query imports preserve the facade's coupling ceiling
without retaining a forwarding file. The Python module count falls from 245 to 243 and the exact
production source ratchet falls from 53,897 to **53,885 lines**. Storage, semantic lifecycle, pattern query,
migration, and recovery characterization tests cover the surviving behavior. The next slice is the
canonical architecture-evaluation cutover in item 4 of the ordered map.

### 10.2 delivery record: direct canonical scan persistence

Characterization showed that architecture rules, coverage, findings, semantic carry-forward, graph
reads, and history already consume reconstructed `file_facts`, `fact_symbols`,
`relationship_sets`/`relationship_edges`, and sparse snapshot deltas. The obsolete detour was the
scanner itself: it wrote complete `file_versions`, `symbols`, and `relationships` frames, converted
them to canonical facts, computed a parity digest, and immediately deleted the staging rows.

Current scans now serialize prepared analysis directly into immutable file and symbol facts, persist
file placement deltas, resolve dependencies directly into reusable relationship sets, and persist
only changed source selections. Architecture evaluation runs after that canonical write and a
characterization test observes that no legacy staging table exists at the evaluation boundary.
Connection-local `projected_*` tables remain disposable read adapters; they are reconstructed from
canonical facts and are not persistent compatibility storage.

A fresh AnaxiIndex now creates **30 product tables instead of 34** and never creates
`file_versions`, `symbols`, `relationships`, or `group_memberships`. Migration-only readers and
parity checks still accept released old indexes. An upgraded database may retain the four empty
tables as compatibility tombstones because older semantic foreign-key declarations name them; they
are no longer populated by a scan. The schema-2 and schema-6 migration fixtures, transactional
failure/restart, exact backup/restore, canonical reconstruction, checkpoint, history, benchmark,
architecture, and scanner tests all remain green.

The exact production source ratchet falls from 53,885 to **53,878 lines**. The small net line
reduction is not the primary measurement for this slice: four current-index tables and an entire
full-frame write/translate/delete path disappear without hiding equivalent source in another
runtime projection. The full suite passes with **605 tests**, and every pre-commit quality gate is
green.

The exact self-hosted Docker image scanned 471 AnaxiGraph modules in 1.339 seconds while reusing all
471 analyses, produced snapshot 364 with 4,439 relationships and 152 findings, and left all four
legacy tables at zero rows. `PRAGMA quick_check` returned `ok`, foreign-key violations remained zero,
the canonical digest was exact, reconstruction stayed within the 16-delta budget, the REST health
endpoint stayed healthy, and `anaxigraph doctor` reported no blockers. The next ordered slice is
item 5: converge semantic projections and composition without creating another semantic model.

### 10.2 delivery record: one semantic planner and one freshness rule

The first item-5 slice removes two small but real parallel representations. First,
`SemanticModulePlanner` was a stateless 56-line class whose only behavior was forwarding intrinsic
and contextual calls to their existing planning functions. Its only production consumer now calls
those two cohesive planners directly; the extraction algorithms remain separate, while the extra
facade, constructor field, composition-root allocation, and Python module disappear.

Second, semantic age was evaluated by two byte-for-byte equivalent functions in
`semantic_graph.py` and `semantic_freshness.py`. Module, group, repository, pattern-plan, and
pattern-cache decisions now share `semantic_freshness.is_expired`. Provider/model-independent input
identity and age policy therefore have one owner, while graph evidence no longer owns a competing
readiness rule.

The Python module count falls from 243 to **242**, and the exact production source ratchet falls
from 53,878 to **53,815 lines**. Existing intrinsic/context planning, age-expiry rebuild, semantic
identity, taxonomy, queue, pattern, and end-to-end understanding contracts characterize the
surviving behavior. Item 5 remains in progress; the next slice must find another measured duplicate
projection or one-use composition boundary rather than expanding the semantic subsystem.

The exact self-hosted image then scanned the 470-module tree and exercised the ordinary semantic
prepare endpoint against snapshot 372. The shared planner preserved 313 current module dossiers,
identified 103 reusable intrinsic descriptions, enqueued exactly 54 missing intrinsic jobs, reported
zero failures, and returned the expected durable `intrinsic` stage with 54 active jobs. This is a
live composition-path check, not an AI execution claim; no model tokens were spent by preparation.

### 10.2 delivery record: one semantic identity and workflow composition root

The second item-5 slice removes two more representations without merging the semantic algorithms.
Stable JSON identity had separate implementations in `semantic_graph.py` and
`semantic_pattern_identity.py`, even though module, taxonomy, and pattern freshness all depend on
the same deterministic serialization rule. `semantic_freshness.semantic_digest` now owns that rule.
Module interface and intent fingerprints, intrinsic relationship fingerprints, legacy identity
checks, and pattern-review assessment fingerprints all use it. This changes neither the serialized
shape nor any stored hash; identity tests characterize legacy reuse across executor and model
changes.

`SemanticWorkflowServices` was also a one-use three-field container constructed by a dedicated
51-line module and immediately projected back into `SemanticServices`. The existing composition
root now owns those three explicit workflow fields and constructs them once. Database-facing core
services remain behind `SemanticCoreServices`, and planning, runner, agent, taxonomy, and pattern
implementations remain separate cohesive services. The change therefore removes an indirection and
one Python module without turning the composition root into an algorithm or a high-coupling god
object.

The Python module count falls from 242 to **241**, and the exact production source ratchet falls
from 53,815 to **53,774 lines**. Semantic identity, service construction, intrinsic/context
planning, pattern evaluation, and end-to-end understanding tests characterize the surviving path.
Item 5 remains in progress: the next slice must characterize duplicated evidence/readiness
projections before choosing a deletion, rather than combining differently scoped semantic facts.

The full suite remains green with **605 tests**, every pre-commit gate passes, and the exact rebuilt
Docker image remains healthy. That image scanned the 469-module working tree in 1.333 seconds while
reusing every analysis, returned 4,419 relationships and 154 findings, and then exercised semantic
preparation through the normal REST route. The unified identity/composition path preserved 309
current contextual dossiers and 104 current intrinsic descriptions, enqueued 56 missing intrinsic
jobs, reported zero failures, and spent no model tokens during preparation.

### 10.2 delivery record: one semantic work-state vocabulary

The third item-5 slice makes durable job state and visible readiness use the same vocabulary. The
seven semantic job kinds previously had separate pending/failed translations in job creation,
coding-agent release, worker failure/retry, pattern retry, and status aggregation. That allowed a
new job kind or renamed state to be accepted by one path while another path could silently report
different readiness.

`semantic_job_state.py` now owns the job-kind-to-scope-state rule alongside the already canonical
job transition machine. `_ensure_job` returns the correct scope state to every intrinsic, context,
group, repository, taxonomy, and pattern planner. Agent release, retry/failure persistence, failed
pattern recovery, and readiness aggregation use the same rule and failure set. Unknown job kinds
fail explicitly. A table-driven characterization covers every supported kind, both outcomes, and
the rejection case; queue, agent, taxonomy, pattern, usage, and complete understanding tests cover
the transactional callers.

The change also removes an unused `semantic_ports.__all__` inventory. Its explicit `SemanticIndex`
re-export remains intact and no wildcard consumer existed. The Python module count remains **241**,
the exact production source ratchet falls from 53,774 to **53,768 lines**, and warning-level
complexity falls from 13 to 12 in group planning, 11 to 10 in repository planning, and 6 to 5 in
taxonomy-review planning. The total maintainability warning count falls from 146 to **145** without
adding a coupling exception. Item 5 remains in progress; result provenance and duplicated read
projections still require characterization before the next deletion.

The full suite passes with **613 tests**, every pre-commit gate is green, and the exact rebuilt
Docker image is healthy. Its normal self-scan reused all 469 analyses in 1.358 seconds, produced
snapshot 389 with 4,420 relationships and 153 findings, and semantic preparation exercised the
shared creation/status vocabulary without model work. It preserved 302 current contextual dossiers
and 105 current intrinsic descriptions, created 62 `pending_intrinsic` jobs, and reported zero
failed module or aggregate scopes.

### 10.2 delivery record: one semantic composition root

The fourth item-5 slice first characterized the semantic read projections instead of forcing them
through a new universal response model. File detail deliberately returns the complete saved dossier
and its 27 provenance/evidence fields; the module ledger returns a rich contextual browsing row;
search returns a minimal current-identity result; repository status returns aggregate completion and
repository-dossier provenance; pattern and taxonomy reads return review-specific evidence. Those
five shapes answer different bounded questions. They remain separate because normalizing them to
the largest document would widen routine payloads and couple unrelated screens and tools.

The audit did expose a redundant composition shape. `SemanticCoreServices` was a one-use five-field
container built in its own module and immediately unwrapped through five forwarding properties on
`SemanticServices`. The real composition root now creates each concrete service once and directly
owns planning, leases, evidence, persistence, runner, reporting, and agent services. The agent owns
its private stateless packet-contract helper. Planning, execution, evidence construction,
validation, persistence, reporting, taxonomy, and pattern algorithms remain separate classes; no
stored schema, result document, public route, tool payload, or readiness rule changes.

The Python module count falls from 241 to **240**, and the exact production source ratchet falls
from 53,768 to **53,725 lines**. Making the actual root visible raises its reported fan-out from a
hidden nested shape to 10, below the hard cap of 12, and increases the warning count from 145 to
146. No coupling exception is added: this is an intentional, reviewable signal at the only module
whose responsibility is construction, not a reason to recreate an indirection. The focused
composition/queue/MCP suite passes with 50 tests, the full suite passes with **613 tests**, and all
hard quality gates remain green.

The exact rebuilt Docker image is healthy. Its self-scan reused all 468 analyses in 1.335 seconds,
kept snapshot 395 current with 4,413 relationships and 154 findings, and semantic preparation
exercised the flattened construction path without model work. It preserved 301 current contextual
dossiers and 104 current intrinsic descriptions, created 63 `pending_intrinsic` jobs, and reported
zero failed scopes. Item 5 remains in progress; its next slice must remove another characterized
conversion or forwarding boundary, not merge the deliberately different read projections above.

### 10.2 delivery record: one semantic scope, language, and pattern vocabulary

The final item-5 slice used both the self-hosted module assessments and a deterministic duplicate
scan. The saved AI assessments correctly supported keeping small cohesive taxonomy, packet-paging,
parallel-execution, and graph-reading helpers separate. The deterministic scan then identified the
parallel representations that could be removed safely: intrinsic and contextual planning repeated
the same five module-scope identity fields four times; analyzer ownership repeated the complete
fallback-language inventory; and pattern validation, work prompts, query filters, and human
explanations repeated the same score dimensions and allowed outcomes.

`semantic_graph._module_scope` now supplies one current-fact identity for module work. Language
detection owns the complete detected-language set and its disjoint Python, JavaScript-family, and
text-fallback analyzer partitions; a characterization proves every detected language has exactly
one built-in analyzer. The strict pattern-response contract owns score dimensions, presence values,
and recommendations, while prompts, queries, and explanation code consume that vocabulary. Adding
a language or pattern dimension can no longer make one surface silently disagree with another.

Together with the earlier freshness, digest, work-state, composition, and read-projection audits,
this completes ordered deletion-map item 5. Evidence and provenance projections remain deliberately
bounded to the question each caller asks; they do not become one maximal response object. The
Python module count remains **240**, the exact production source ratchet falls from 53,725 to
**53,667 lines**, and the maintainability warning count remains 146 with no new exception. Focused
language, pattern, semantic identity, planning, and complete-understanding coverage passes with 86
tests; the full suite passes with **616 tests** and every hard quality gate remains green.

The exact rebuilt Docker image is healthy. Its self-scan reused all 468 analyses in 1.370 seconds,
produced snapshot 403 with 4,418 relationships and 154 findings, and semantic preparation exercised
the shared vocabularies without model work. It preserved 274 current contextual dossiers and 121
current intrinsic descriptions, created 73 `pending_intrinsic` jobs, and reported zero failed
module or aggregate scopes. Section 10.2 remains in progress against its reduction gate; the next
slice moves to characterized persistence query/projection duplication rather than extending the
semantic subsystem.

### 10.2 delivery record: one canonical persistence vocabulary

The first persistence slice characterized repeated schema and lifecycle lists before moving any
query implementation. The same nine temporal tables were separately named by schema clearing,
fact counts, canonical digesting, and index diagnostics. Relationship parity and compatibility
coverage backfill separately named the same ten edge fields. Finding query validation, the public
index update, and CLI choices separately named the same seven lifecycle states even though the
human guidance already owned their meanings and allowed transitions.

`temporal_schema.py` now owns content, checkpoint, and complete temporal table inventories. Clearing
uses their foreign-key-safe reverse order; counts, digests, and doctor output consume the same
names. `index_parity.EDGE_FIELDS` now defines exact relationship equality for both parity and
coverage migration. The guidance lifecycle now drives bounded-query validation, CLI choices, and
AnaxiIndex status updates through its existing narrow facade. The schema-9 semantic-claim table text
remains duplicated intentionally: it is a frozen migration input whose exact historical shape must
not change when the current schema evolves.

The Python module count remains **240**, the exact production source ratchet falls from 53,667 to
**53,606 lines**, and the maintainability warning count remains 146 with no coupling exception.
Focused temporal, checkpoint, migration, parity, doctor, finding, CLI, and API coverage passes with
42 tests; the full suite passes with **616 tests** and every hard quality gate remains green.

The exact rebuilt Docker image is healthy. Its self-scan reused all 468 analyses in 1.398 seconds,
produced snapshot 406 with 4,424 relationships and 154 findings, and the live index doctor reported
schema 10, `integrity=ok`, canonical-only parity, valid lineage, bounded reconstruction, an exact
canonical digest, and no blocker. Semantic preparation spent no model tokens, preserved 265 current
contextual dossiers and 128 current intrinsic descriptions, created 75 `pending_intrinsic` jobs,
and reported zero failed scopes. The next persistence slice targets duplicated read/projection
orchestration, not versioned migration contracts.

### 10.2 delivery record: one artifact and pattern-detail projection

The second persistence slice separated accidental duplication from explicit compatibility. Both
architecture evaluation and semantic planning independently queried artifact classifications for
the same already-reconstructed files. They now consume one temporal-read projection, which reuses
the canonical 800-row batching policy instead of building an unbounded SQLite placeholder list.
This is both a deletion and a scale correction: a 1,001-module characterization proves that the
shared projection crosses SQLite parameter batches without changing architecture or semantic
inventory results.

Pattern validation and the public reviewed-pattern projection also repeated the same seven
explanation-list field names. The strict evaluation contract now owns the complete ordered list
vocabulary and the bounded detail reader consumes its explanation subset. A future addition can no
longer be accepted and stored by the agent contract while silently disappearing from the human or
MCP detail response.

The audit deliberately retains three superficially similar shapes. Historical schema DDL remains
frozen migration input; changing it to follow current schema constants would make old-version tests
lie. Empty graph overview and neighborhood responses remain explicit public contracts because they
have different paging and exploration semantics. The tiny graph projection boundary also remains:
inlining it would push the canonical snapshot projection above the coupling ceiling merely to
remove a wrapper. These are recorded constraints, not unexamined duplication.

The Python module count remains **240**, the exact production source ratchet falls from 53,606 to
**53,587 lines**, and the maintainability warning count remains 146 with no new exception. Focused
scanner, temporal, semantic-identity, complete-understanding, pattern-contract, and pattern-query
coverage passes with 55 tests; the full suite passes with **617 tests**. The next persistence slice
must characterize duplicated query composition or a one-use persistence facade before deletion;
it must not invent a maximal read model that widens every caller.

The exact rebuilt Docker sidecar is healthy. Its normal self-scan reused all 468 analyses in 1.366
seconds, kept snapshot 414 current with 4,426 relationships and 154 findings, and exercised the
shared artifact projection through architecture evaluation. Semantic preparation used the same
projection to preserve 264 current contextual dossiers and 125 current intrinsic descriptions,
queue 79 missing intrinsic jobs, and report zero failures without spending model tokens. The live
index doctor reports schema 10, `integrity=ok`, canonical-only parity, valid lineage, bounded
reconstruction, an exact canonical digest, and no blocker.

### 10.2 delivery record: one bounded agent normalization vocabulary

The final persistence audit found no remaining accidental block-level duplicate. Its only detected
clone is the frozen schema-9 semantic-claim DDL already retained as migration evidence. The
one-consumer architecture-evidence, pattern-plan-state, graph-query, graph-projection, and index
facade modules remain because each owns a coherent database boundary or keeps the public index
facade below its coupling ceiling. Merging them would move the same logic into a less cohesive or
near-ceiling module, not simplify the system. Phase 10.2 therefore advances to agent composition
instead of deleting files by size.

The first agent slice found smaller parallel input rules that could make the same saved evidence
appear differently across scope, decision, decomposition, task-path, and verification responses.
Semantic graph attachment and scope findings now use the existing persistence-row decoder for one
fail-closed malformed-JSON rule. Decision, safety, handoff, decomposition, and task-path projections
now share one bounded non-empty text rule. Blank AI evidence is removed before the item limit is
applied, so empty values no longer consume scarce coding-agent context. Before/after comparison
also consumes the verification contract's existing bounded-text rule instead of defining another.

These are internal normalizers, not a new universal agent model. Full architecture decisions,
compact scope responses, task paths, decomposition guidance, verification baselines, and readable
handoff explanations remain different contracts because they answer different questions. The
shared helpers follow dependency edges those callers already needed; no new public Python surface,
module, API route, MCP tool, stored schema, or maintainability warning is introduced.

The Python module count remains **240**, the exact production source ratchet falls from 53,587 to
**53,556 lines**, and the maintainability warning count remains 146 with no new exception. Focused
agent, decision, decomposition, task-path, verification transport, scanner, and temporal coverage
passes with 65 tests. Two new characterizations prove malformed JSON fails closed and blank values
do not consume a bounded response slot; the full suite passes with **619 tests**. The next agent
slice should characterize decision/payload assembly or repeated response telemetry before deleting
another layer; it must not flatten evidence, recommendation, execution, and verification into one
god response.

The exact rebuilt Docker sidecar is healthy. Its normal self-scan reused all 468 analyses in 1.344
seconds, kept snapshot 428 current with 4,434 relationships and 154 findings, and the live index
doctor again reports exact canonical integrity with no blocker. The ordinary agent-scope route then
mapped the goal “consolidate duplicate agent payload normalization without widening architecture
boundaries” to `agent_decision_payload.py`, returned a bounded 16,358-byte work packet under the
20,000-byte limit in 607 ms, and spent no model tokens. Semantic preparation preserved 240 current
contextual dossiers and 138 current intrinsic descriptions, queued 90 missing intrinsic jobs, and
reported zero failures without executing AI work.

### 10.2 delivery record: one agent map state and wire-size rule

The next agent audit retained the large scope orchestration and its small assembly helpers. The
scope builder coordinates ranking, bounded graph expansion, tests, protected paths, rules,
findings, symbols, branch conflicts, architecture decisions, verification, and final byte-budget
compaction. Inlining its one-use helpers would grow the already ratcheted 91-line entry point and
erase the names of those stages; merging the full and compact decision modules would couple normal
reasoning to transport pressure. They remain explicit boundaries.

Two smaller parallel facts were removed. Scope and impact previously looked up the same repository
and latest snapshot independently, while only scope attached the current-map explanation later in
payload assembly. `agent_graph` now resolves one repository id, snapshot id, and served-map status
for both workflows, with the same missing-repository and unscanned-repository failures. Graph and
impact telemetry also measured JSON using ASCII escaping while scope budgets measured UTF-8. One
internal serializer now measures the actual UTF-8 response bytes for graph, scope, and impact; the
scope budget and action telemetry therefore cannot disagree merely because a human-readable label
contains non-ASCII text.

The Python module count remains **240**, the exact production source ratchet falls from 53,556 to
**53,553 lines**, and the maintainability warning count remains 146. No public Python surface,
coupling warning, API route, MCP tool, or response field changes. Focused scope, impact, graph,
decision, and verification transport coverage passes with 31 tests; a new Unicode contract proves
the recorded byte count equals the real UTF-8 serialization, and the full suite passes with **620
tests**. The next agent slice should target a measured duplicate decision projection; if none
remains, Phase 10.2 should advance to dashboard state/rendering rather than manufacture a generic
agent response model.

The exact rebuilt Docker sidecar is healthy. Scope and impact answered against the same current
snapshot 437 and the same current map-status contract. Scope returned a 16,840-byte packet under
its 20,000-byte budget in 615 ms; its budget estimate and telemetry byte count were identical.
Impact resolved `agent_payload.py`, found 52 transitive dependants, and returned a 7,546-byte packet
in 299 ms. Both used zero model tokens. A following self-scan reused all 468 analyses in 1.393
seconds, retained 4,430 relationships and 154 findings, and the live index doctor reported exact
canonical integrity with no blocker.

### 10.2 delivery record: one dashboard explanation-markup vocabulary

The dashboard audit traced the seven destinations through their controllers, renderers, shared
selection state, API reads, and browser contracts before changing presentation code. The first
bounded duplicate was not navigation state: Findings and Patterns independently constructed the
same escaped prose section and escaped list markup, while Findings also carried private copies of
the dashboard's canonical HTML escaping and label-humanizing rules. These copies could make the
same evidence render or normalize differently depending on which journey displayed it.

`dashboard-format.js` now owns the two explanation-markup primitives, and both Findings and
Patterns consume them together with the existing core escaping and humanizing vocabulary. Finding
actions, pattern scoring, selection state, routes, payloads, headings, and primary journeys remain
unchanged. This is deliberately not a generic component framework: the helpers own only the exact
safe prose shapes already shared by two evidence views.

The Python module count remains **240**, the exact production source ratchet falls from 53,553 to
**53,534 lines**, and the maintainability warning count remains 146 with no exception. JavaScript
syntax checks and API coverage pass, and all **17 browser contracts** pass in the pinned Playwright
container, including finding explanations, pattern stories, lifecycle actions, graph selection,
history, semantic state, and first-run onboarding. Phase 10.2 continues with a measured dashboard
controller or selection-state duplicate; it must not rearrange the primary journey before §10.6.

The exact rebuilt Docker sidecar serves the shared formatter and both importing views. Its normal
self-scan reused all 468 analyses in 1.385 seconds, kept snapshot 441 current with 4,436
relationships and 154 findings, and spent no model tokens. The live index doctor reports schema
10, exact canonical integrity, no compatibility rows, valid lineage, bounded reconstruction, zero
foreign-key violations, and no blocker.

### 10.2 delivery record: remove the hosted-model product path

The earlier dashboard slices established safe characterization but reduced only 375 of the 5,407
production lines required by this phase. That pace did not satisfy the consolidation goal. The next
slice therefore removes a complete secondary product path rather than another presentation helper.

AnaxiGraph previously both prepared semantic work for the coding agent already authenticated in a
repository and acted as a separate OpenAI/Anthropic HTTP client with API-key configuration, a
periodic `semantic-worker` command, and an optional `ai` Compose service. The second path duplicated
credential ownership, provider transports, scheduling, errors, documentation, and operations while
writing the same dossier contract to the same queue. ADR 0004 makes the product boundary explicit:
AnaxiGraph owns evidence, bounded work, validation, leases, provenance, and AnaxiIndex; the user's
connected agent or authenticated host Codex/Claude executor owns inference.

The two hosted API clients, their key/base-URL policy fields, periodic refresh policy and scheduler,
CLI command, generated and repository Compose services, dashboard instruction, provider tests, and
operator documentation are removed. The advanced local JSON command adapter remains for
operator-owned runtimes and deterministic tests. Existing dossiers and provider/model provenance
remain readable; only creation through an AnaxiGraph-hosted API credential is retired. Policies
using `openai`, `anthropic`, or `periodic` now fail with a migration-oriented message instead of
silently selecting another authority.

The Python module count remains **240**, but the exact production source ratchet falls by 298 lines,
from 53,534 to **53,236 lines**. Runtime, tests, and current documentation delete 608 obsolete lines
while adding 107 migration and replacement-contract lines, plus this decision record and ADR.
Semantic configuration, local Codex/Claude execution, durable background execution, sidecar
write-back, agent-funded completion, CLI routing, onboarding, and Compose characterization pass
together. The full suite passes with **618 tests**, all **17 browser contracts** pass in the pinned
Playwright container, and every hard maintainability gate remains green. Phase 10.2 must continue
at whole-path scale; cosmetic or single-digit consolidation no longer counts as an implementation
milestone.

The exact rebuilt Compose project now has only the main service and read-only watcher; no hidden
`ai` profile or semantic-worker command remains. The deployed service reports both registered
repositories with `provider: agent`, completes a real MCP initialization as AnaxiMCP protocol
2025-03-26, and passes service/MCP doctor checks. Its self-scan reused all 469 analyses in 1.413
seconds, kept snapshot 462 current with 4,420 relationships and 153 findings, and spent no model
tokens. The live index doctor reports schema 10, exact canonical integrity, canonical-only parity,
bounded reconstruction, zero foreign-key violations, and no blocker.

### 10.2 delivery record: remove the duplicate before/after verification protocol

The live-sidekick mission does not require a second temporal model inside every scope response.
AnaxiIndex already retains snapshots, graph deltas, finding lifecycle, history, current module
facts, and reviewed semantic evidence. The former scope workflow copied a bounded subset of those
facts into a client-owned packet, validated two historical packet versions, accepted that packet
through CLI, REST, and MCP, compared it with another scope response, classified effects, and then
compacted the duplicate packet to fit the wire budget. That machinery made an ordinary agent save
and return opaque JSON before it could finish a coding loop.

The saved-baseline validator, comparison engine, structural-effect classifier, transport argument,
CLI file loader, comparison prose, and special payload compaction are removed. Scope still returns
placement, constraints, patterns, decomposition, dead-code caveats, focused tests, semantic test
guidance, and the exact rescan command. After a coherent change the agent refreshes the shared map,
repeats scope or impact only when responsibilities or dependencies may have moved, and reads
History, findings, or graph deltas when temporal evidence matters. One durable AnaxiIndex remains
the authority; the agent no longer carries a parallel mini-index in its prompt.

This deletes three production modules and lowers the exact production-source ratchet by **1,092
lines**, from 53,236 to **52,144**. The complete change removes more than 1,800 lines while adding
fewer than 150 replacement, migration, and decision-record lines. Scale fixtures at 120, 1,000,
and 3,000 files still prove bounded scope, precise placement, impact traversal, incremental scans,
current finding evidence, and refresh guidance. The versioned ordinary coding loop advances to
`coding-loop-contract-v3`; the pre-1.0 saved-baseline wire argument is intentionally retired rather
than preserved as an invisible compatibility subsystem. The complete Python suite passes with
**603 tests at 91.95% coverage**, all **17 browser contracts** pass in the pinned Playwright
container, and every hard architecture, size, complexity, coupling, formatting, and package gate
remains green.

### 10.2 delivery record: remove duplicate standalone agent guidance

Branch overlap remains useful only when it changes a coding decision. Scope and Impact already
measure active-branch overlap for the exact files they return, incorporate it into risk, and explain
which file conflicts. The separate `collisions` CLI command, REST route, and MCP tool reran the same
Git traversal without a coding goal or selected file. They are removed while the contextual evidence
inside Scope and Impact remains unchanged.

The dashboard glossary remains the human interface's single vocabulary for measurements, finding
states, and overlays. The installed Codex/Claude skill remains the agent's executable workflow.
`ANAXIGRAPH_GUIDE` and the glossary's embedded coding-loop/agent-operation manifest duplicated those
durable instructions but were not consumed by the dashboard or part of the released
`coding-loop-contract-v3` tool subset. They are removed instead of preserving three documentation
authorities and sending unused workflow manifests on every dashboard load. Together these removals
delete one CLI command, one REST route, two MCP tools, their remote adapter, and **231 production
lines**, lowering the exact source ratchet from 52,144 to **51,913**. That slice initially retained
branch-overlap fields inside Scope and Impact so their complete caller map could be characterized;
the following slice records their final disposition.

### 10.2 delivery record: retire Git-overlap analysis and reuse legacy migration facts

The remaining branch-overlap code was a small merge-conflict analyzer embedded in an architecture
tool. It enumerated every local and origin branch, calculated merge-base diffs, threaded an optional
branch argument through CLI, REST, MCP, finding handoff, Scope, and Impact, changed risk scores, and
maintained a third graph-overlay state. Git and coding harnesses already own that decision. The
feature is removed end to end; protected-path rules and architecture blast radius remain the
extra-care signals AnaxiGraph is uniquely positioned to explain.

Live startup against the retained pre-canonical index exposed the opposite kind of waste: the
schema-6 migration processed 313 snapshots, 198,602 materialized file rows, and 1,471,557 materialized
relationships in one transaction. Identical file facts repeatedly reloaded symbols, and identical
relationship sets repeated insert/select checks. Migration-local fact, symbol, and relationship-set
caches now reuse those immutable identities across frames while the existing exact-parity,
transaction rollback, backup, restore, and restart tests remain authoritative. A new migration
contract proves every distinct file fact is symbolized exactly once.

The useful migration acceleration adds no schema or public surface. Removing Git-overlap analysis
more than pays for it: the exact production-source ratchet falls another **118 lines**, from 51,913
to **51,795**, while one MCP/REST/CLI argument family, three response fields, Git traversal helpers,
and dashboard conflict state disappear. The complete suite passes with **603 tests**, all **17
browser contracts** pass against a freshly scanned fixture, and the deterministic maintainability
report falls to 138 warnings with no hard error.

### 10.2 delivery record: retire redundant pattern grading and make legacy migration real-world safe

This slice removes two complete side paths. `ANAXIGRAPH_MODULES` returned an independently filtered
dump of as many as 1,000 files even though agents already have bounded Overview, Search, File, Scope,
Impact, and Graph queries; the human Files table continues to use its purpose-built REST read model.
The `patterns --calibrate` path was a second mini-product that graded saved pattern results against a
private benchmark manifest but did not produce, improve, or validate a recommendation at runtime.
Its four production modules, CLI mode, benchmark manifests, fixtures, documentation, and tests are
deleted. Normal pattern suggestions remain available through CLI, REST, MCP, and the dashboard and
retain their direct candidate/evidence tests.

The released schema-6 upgrade was then exercised against the retained **1.4 GB** index rather than
accepted on fixture performance. That index contains 313 materialized snapshots, 198,602 file
versions, 861,861 symbols, and 1,471,557 relationships. Migration now:

- reuses one immutable file fact and symbol set across frames whose raw hash, structural hash,
  analyzer, and analysis signature are identical;
- fingerprints the exact ordered edge content for each source and reuses any matching relationship
  set already seen for that repository, source artifact, analysis signature, and resolver context;
- installs and removes migration-only indexes for legacy symbol and per-source relationship reads;
- constructs new canonical frames once instead of immediately rereading the entire result through
  parity and duplicate-set passes that are still retained for pre-existing canonical projections;
- removes the global canonical-table self-hash that scanned every row after every scan. Recording a
  freshly calculated hash as its own expected value did not prove legacy-to-canonical parity; atomic
  rollback, SQLite integrity, foreign-key validation, bounded reconstruction, exact semantic
  references, and the checksummed restorable backup remain the actual safety gates;
- retires the four legacy tables after conversion instead of retaining empty compatibility schema.
  Automatic FK actions and secure page overwrites are suspended inside the exclusive migration
  transaction, an explicit full `foreign_key_check` must pass before commit, and both settings are
  restored on every exit path;
- clears checkpoint children explicitly before rebuilding their disposable parent records, so the
  operation remains correct even while automatic FK actions are suspended.

The live gate found and fixed two failures that the small fixture could not reveal: secure deletion
first exhausted temporary disk while retiring 2.5 million duplicate rows, and checkpoint cleanup
then relied on disabled cascades. Each failed attempt rolled back to schema 6, the backup remained
valid, and the corrected migration completed. The dashboard and MCP server were available by
**4 minutes 18 seconds** and Docker reported healthy at **4 minutes 40 seconds**; the former path was
still unavailable after eight minutes. The resulting schema-10 index has 23,554 distinct file facts,
154,210 fact symbols, 16,909 relationship sets, 214,615 relationship edges, 18 checkpoints, no
legacy tables, no foreign-key violation, and a valid unchanged schema-6 backup. REST answers,
AnaxiMCP initializes with protocol `2025-03-26`, and the read-only watcher runs against the migrated
index.

The first real watcher write then found one final compatibility dependency: the released coverage
table still named the dropped `relationships` table in a foreign key even after every legacy value
had been moved to canonical relationship-edge IDs. Fresh schema no longer creates that column, and
schema-10 startup atomically removes it from already migrated indexes before any scan. A regression
recreates the dangling foreign key, reopens the index, and proves a following scan can write static
relationship coverage. The plain-language finding reader also no longer carries a separate
366-line regular-expression translator for detector copy written by unreleased and pre-0.3 builds.
Current detectors are the one wording authority; rescanning refreshes persisted findings.

This is a net product reduction despite the migration hardening. The exact production-source
ratchet falls **1,173 lines**, from 51,795 to **50,622**. Phase 10 has now removed 3,285 production
lines from its 53,907-line starting point; 2,122 lines remain before the 48,500 exit target. Public
surface falls by one MCP tool and one CLI mode, and five production modules disappear. The complete
suite passes with **573 tests**, and every formatting, architecture, module-size, production-size,
credential, JavaScript, package, and agent-package pre-commit gate passes.

### 10.2 delivery record: keep one current hierarchy vocabulary

The history and graph correction exposed a generality defect in the AI taxonomy presentation.
`semantic_taxonomy_language.py` had grown to 453 lines largely by recognizing and rewriting prose
previously generated while AnaxiGraph analyzed itself: benchmark names, dashboard labels, release
roles, persistence phrases, and other repository-specific sentences were embedded in production as
if they were a general language model. Current taxonomy prompts and validation already require
ordinary language, while `semantic_file_language.explain_specialist_terms` already owns the small
generic vocabulary that explains unavoidable architecture terms.

The taxonomy projection now uses that shared vocabulary plus twelve stable label substitutions.
Its contract advances to `semantic-taxonomy-explanation-v2`; it still explains group purpose,
membership, rationale, evidence strength, and configured versus AI placement, but the module falls
from 453 to **156 physical lines**. Obsolete project-specific file-summary rewrites are removed at
the same boundary. Legacy saved prose remains readable through generic term definitions rather than
an ever-growing collection of phrases copied from one repository.

The same hierarchy slice hides declared groups that have no files in the selected snapshot, so
retired names no longer appear beside the active current map. The watcher also compares the Git head
with its durable completed-history result after restart instead of scheduling the same history
import again, and the `review` CLI reuses the canonical scan handler without changing its response.
Focused hierarchy, watcher, review, taxonomy-language, and full semantic-bootstrap contracts pass.

The exact production-source ratchet first fell from 50,611 to 50,606 in the hierarchy/watcher
commit, then to **50,287 lines** after removing the repository-specific language path. Phase 10 has
now removed 3,620 production lines from its 53,907-line starting point; **1,787 lines remain** before
the 48,500 convergence target. This is still Phase 10.2: the next slice must remove another whole
duplicate path before the single-service runtime work in §10.3 and five-journey convergence in §10.6.

### 10.2 delivery record: remove the unused raw-graph agent surface

The shipped Codex/Claude workflow and ordinary coding loop never call `ANAXIGRAPH_GRAPH`. Overview
already gives agents the architecture hierarchy; Search and File give bounded source evidence;
Scope and Impact turn graph traversal into the placement, dependency, risk, and test decisions an
agent can act on. The dashboard uses the bounded REST graph directly. The standalone MCP adapter
therefore exposed four low-level query modes and eighteen arguments without owning a distinct user
decision or a documented normal consumer.

The 263-line `graph_mcp.py` adapter, its registration, architecture-policy entry, and transport-only
tests are removed. Graph overview, paging, neighborhoods, deltas, current-frame projection, history
replay, REST routes, persistence queries, and dashboard rendering remain unchanged. The focused MCP
contract passes and still verifies every retained core, finding, history, pattern, taxonomy, and
semantic-executor tool.

The exact production-source ratchet falls another 265 lines, from 50,287 to **50,022 lines**. Phase
10 has now removed 3,885 production lines; **1,522 lines remain** before the 48,500 target, and one
flat low-level tool no longer competes with the goal-oriented agent workflow.

### 10.2 delivery record: keep operator controls out of the coding-agent menu

The installed agent workflow does not start or cancel Git-history imports and does not issue raw
pattern-result queries. History import is an operator action already owned by the dashboard and
CLI; agents only need its read-only status when answering a history question. Relevant pattern
recommendations are already composed into Scope, while the complete expert result browser remains
available through the dashboard, REST API, and `anaxigraph patterns`.

`ANAXIGRAPH_HISTORY_IMPORT`, `ANAXIGRAPH_HISTORY_CANCEL`, and `ANAXIGRAPH_PATTERNS` are removed from
the flat MCP menu without removing history import/cancellation or pattern intelligence. Their
198-line adapters and registration paths disappear. The now-empty 26-line `mcp_tools` forwarding
facade also disappears; the MCP composition root calls the retained history and finding tool
families directly. Focused MCP, history, CLI-pattern, and pattern-query contracts pass.

The exact production-source ratchet falls from 50,022 to **49,800 lines**. Phase 10 has now removed
4,107 production lines; **1,300 lines remain** before the 48,500 target. This slice also removes
three more low-level choices from the tool list seen by an ordinary coding agent.

### 10.2 delivery record: make live history append instead of reshuffle

The repository watcher previously treated every new Git head as a reason to run the complete
representative-history plan again. Adding four commits to a repository with a 32-frame budget
therefore revisited all 32 positions. Because tag, architecture-change, calendar, and recent-commit
weighting chose different older commits whenever the lifetime changed, repeated updates accumulated
retired samples, consumed CPU for minutes, and made replay appear to jump between incompatible
historical selections.

Automatic history updates now begin after the newest **completed** durable import head. The selected
tail reuses that compatible commit frame as its structural and relationship baseline, preserves the
former clean current frame as a visible commit, and appends only later first-parent commits. A
partial or cancelled retry cannot displace the last completed head. If Git history was rewritten or
the saved analysis signature is incompatible, the importer deliberately falls back to a complete
safe plan instead of carrying facts across an unverified boundary.

The initial bounded import now uses one predictable evenly spaced lifetime sample that always keeps
the first and current commits. Later watcher updates preserve those choices and append the new tail;
they do not continually reinterpret which old commits were important. This removes the tag and
repository-filename weighting path, its Git adapter, and duplicate frame-progress builders. Focused
watcher, durable-job, history, temporal-fact, migration, CLI, and MCP contracts pass with **54 tests**.

The exact production-source ratchet falls from 49,800 to **49,797 lines** despite adding durable
incremental-extension behavior. Phase 10 has now removed 4,110 production lines; **1,297 lines
remain** before the 48,500 convergence target.

### 10.2 closure record: accept the substantive reduction

On 31 August 2026 the owner directed the roadmap to stop spending time on further Phase 10.2
subtraction. The phase removed **4,110 production lines (7.6%)**, eliminated complete duplicate
provider, projection, verification, MCP, taxonomy, and history-planning paths, retained all hard
quality gates, and left no module above 500 lines. The remaining difference from the original
ten-percent target was not backed by another confidently removable product path.

The binding production ratchet is therefore **49,797 lines**, not 48,500. Later phases still prefer
line-neutral or line-negative changes and must ratify intentional growth, but they do not reopen this
phase or manufacture fragments/deletions merely to reach the retired target.

## 10.3 Put the watcher inside one service and establish one write authority

**Status:** COMPLETE on 31 August 2026.

The normal deployment currently describes one product but runs the HTTP/MCP service and repository
watcher as separate AnaxiGraph processes against the same SQLite index. That creates lifecycle,
locking, restart, configuration, and support behavior that the product does not need. The default
runtime becomes:

```text
one AnaxiGraph service process
  ├─ dashboard, REST, and MCP adapters
  ├─ repository registry
  ├─ scan/update coordinator
  ├─ supervised repository watchers
  └─ one AnaxiIndex write authority
```

“One writer” means one owner coordinates write transactions, migrations, scans, semantic
submissions, and lifecycle updates for an index. It does not mean one global database for every
repository or a long transaction that blocks all reads. Read-only queries remain concurrent and
bounded; multi-repository service remains supported.

Delivery order:

1. Characterize current local, generated-Compose, multi-repository, watcher, semantic-submission,
   cancellation, crash-recovery, and shutdown behavior before moving ownership.
2. Start and supervise repository watchers inside the service lifecycle after registry and index
   initialization. Stop them before closing write coordinators and database handles.
3. Route every in-process mutation through one repository-scoped write authority. Preserve short
   transactions and the existing durable semantic lease model.
4. Generate one normal AnaxiGraph Compose service. Remove the second watcher service, duplicate
   environment/configuration, cross-process lock workarounds, and associated onboarding prose.
5. Keep a standalone `watch` command only as a temporary advanced compatibility adapter when a real
   consumer requires it. It must refuse unsafe concurrent ownership of an index; otherwise deprecate
   and remove it through the existing release policy.

Acceptance:

- generated Compose contains one AnaxiGraph service and one health/lifecycle story;
- a two-repository fixture watches, scans, accepts semantic write-back, and serves reads without a
  database lock stall or wrong-repository response;
- SIGTERM, SIGINT, failed scans, and expired semantic leases recover without an abandoned writer;
- an unchanged watcher cycle adds no unbounded durable noise;
- dashboard, MCP, local `up`, backup/restore, and migration contracts remain green;
- the change removes more production/process/configuration surface than it adds.

### 10.3 delivery record: one supervised service and one index writer

The HTTP/MCP service now owns repository watching as part of the same application lifespan that
owns its registry, scan coordination, semantic refresh, and history jobs. One
`RepositoryWatchService` polls every registered target, skips targets with active history work,
scans through the existing canonical scanner, appends history only when the Git head changes, and
optionally prepares semantic work under the target's own policy. A failed target is isolated from
the others, and status for every target is exposed through operational health.

`IndexWriteAuthority` claims a file lock beside the AnaxiIndex for the complete service lifespan.
A second server using the same index now fails immediately with a direct explanation instead of
starting another partially functional writer. Shutdown first cancels and joins the supervised
watcher, its history workers, semantic refresh workers, and scan coordination, then releases the
write authority. A live container restart demonstrated a clean Uvicorn shutdown, released the
lock, reclaimed it on startup, and returned healthy without an abandoned worker.

The normal `serve` and `mcp` commands supervise watching by default at the configurable
`ANAXIGRAPH_WATCH_INTERVAL`; `--no-watch` gives an explicit frozen service. No real consumer of the
standalone `watch` command remained, so the command and its competing ownership path were removed
rather than retained as hypothetical compatibility. Generated Compose and the maintained example
now contain exactly one AnaxiGraph service. The companion watcher service, duplicate configuration,
unused hosted-model API-key environment, and the separate `start_with_watch` onboarding branch are
gone.

Characterization covers one-start lifecycle behavior, rescan after an edit, history cancellation,
bounded worker shutdown, exclusive authority and release, generated single-service Compose, and a
two-repository service whose responses and watcher results remain repository-scoped. The complete
suite passes with **588 tests**, every pre-commit and Compose validation passes, and the rebuilt
self-hosted deployment removed its orphan watcher container. Its single healthy process supervised
both the 1,882-file MaxOS target and 453-file AnaxiGraph target, reported the service-owned write
claim through `/api/health`, rejected a live second writer, and recovered cleanly through a Docker
restart.

This phase deliberately adds **198 production lines** for explicit lifecycle and ownership while
removing an entire process, CLI path, Compose service, duplicate environment, and split shutdown
story. The exact production-source ratchet is therefore ratified from 49,797 to **49,995 lines**;
the increase is accepted phase evidence, not an untracked relaxation. Making application wiring
more explicit also lowers the recorded `anaxigraph.api` coupling baseline from 1/11 to **1/9**. The
next work is §10.4; Phase 10.2 remains closed and is not reopened to offset this intentional growth.

## 10.4 Establish one responsibility-map vocabulary and one search substrate

**Status:** COMPLETE on 31 August 2026.

The graph, history, semantic taxonomy, configured architecture groups, and file browser must stop
using overlapping group names as if they were equivalent truths. Use four precise terms:

| Term | Meaning | Authority |
|---|---|---|
| **Declared map** | Optional repository policy supplied or corrected by a person/team | Explicit intent; never required for first value |
| **Path map** | Deterministic package/directory grouping inferred without a model | Reliable fallback, not semantic meaning |
| **Inferred responsibility map** | AI-reviewed capabilities, areas, subsystems, and responsibilities supported by dossiers and relationships | Default semantic explanation with confidence and evidence |
| **Current view** | A presentation projection choosing declared intent where present, then inferred responsibility, then path fallback | Convenience only; not a fourth source of truth |

Stable group identities are separate from display labels so a renamed area does not look like a new
architecture. The default historical replay shows earlier files through today's current
responsibility map, allowing a viewer to see stable regions fill and connect over time. An explicit
“as understood then” lens may show the historical classification when that question matters. A
generic bucket such as `code`, `other`, or a one-file top-level region must expose why it is a
fallback and should normally be folded into a meaningful parent once semantic evidence exists.

Search and goal scoping currently maintain separate whole-repository lexical ranking paths. Replace
both with one repository- and snapshot-scoped SQLite FTS5 projection over paths, names, symbols,
summaries, responsibilities, contracts, and approved aliases. Exact path/name matches receive
deterministic boosts; semantic evidence remains provenance-tagged; graph expansion occurs only after
the shared seed query. FTS is a rebuildable read model, not a new source of architectural truth.

Delivery order:

1. Pin current search and scope fixtures, including exact symbol/path lookup, similar-responsibility
   discovery, repository isolation, stale semantic evidence, and bounded payload behavior.
2. Add an incrementally maintained FTS5 projection with explicit schema/analyzer identity and a
   deterministic rebuild path.
3. Make dashboard search, MCP search, CLI search, goal scope, Charter evidence lookup, and pattern
   candidate seeding call one query service.
4. Delete the duplicate lexical corpora, tokenizers, ranking loops, and repeated result projection.
5. Migrate graph/history grouping to the vocabulary above without rewriting extracted facts or
   pretending an inferred label was declared policy.

Acceptance:

- the same query against dashboard, CLI, MCP, and guidance returns the same ranked identities before
  transport-specific pagination;
- no query scans every dossier or source file in Python after the FTS projection is current;
- current-view graph counts do not change when a user merely focuses or filters a region;
- history retains stable group identities and defaults to the present-day responsibility lens;
- ambiguous placement, generic fallbacks, and missing semantic evidence remain visible;
- the old independent lexical rankers are removed and the production ratchet falls.

### 10.4 delivery record: one vocabulary and one bounded module search

AnaxiGraph now uses four explicit architecture projections everywhere: `declared`, `path`,
`responsibility`, and `current`. `architecture_vocabulary.py` owns the names and current-view
precedence: declared repository intent first, then an evidence-backed responsibility assignment,
then deterministic path placement. Group keys remain stable machine identities while labels remain
presentation. Every hierarchy includes its source, and path/missing fallbacks explain why richer
placement was unavailable instead of pretending to be semantic truth.

The canonical overview returns all four hierarchies. Graph reads use `graph-query-v2`, bind the
selected map layer into pagination cursors, and project nodes for that layer on the server. The
dashboard map selector therefore changes the actual backend projection rather than recoloring a
stale client-side graph. Current history continues to place earlier files through today's stable
map, while historical placement remains available as evidence. Region focus changes the bounded
page, not repository-wide counts or identities.

`module-search-fts-v1` is now the single repository- and snapshot-scoped discovery substrate. Its
disposable SQLite FTS5 projection indexes paths, names, symbols, deterministic summaries,
responsibilities, public contracts, semantic dossier text, taxonomy identities, and normalized
aliases. Exact path, filename, and symbol matches receive deterministic boosts. Every result
identifies the projection contract, snapshot, and semantic/taxonomy provenance. A new snapshot
refreshes it during commit; completed semantic work updates affected rows; same-snapshot semantic
replanning invalidates it once so stale evidence cannot survive policy or fingerprint changes.

Dashboard module search, REST, MCP, CLI `anaxigraph search`, and agent goal scoping now consume the
same ranked artifact identities. Hydration occurs only after the bounded FTS query. The former
Python TF-IDF corpus, whole-module browser filter, and repeated lexical ranking loop are gone.
Future Charter lookup and pattern seeding must reuse this service; they do not receive another
search implementation.

The obsolete graph-overview read model and route, the duplicate groups route/facade, redundant
overview group payload, and browser-side lexical corpus were removed during the convergence. The
complete Python suite passes with **592 tests**, the browser suite passes **21/21** contracts, Ruff
and JavaScript syntax checks pass, and the maintainability checker reports zero errors. Even after
adding the shared FTS projection and four-layer contracts, production source falls from 49,995 to
**49,991 lines**. That lower number is the new hard ratchet. Extracting the module-table sort
strategies also removed one previously accepted dashboard complexity finding from self-governance.
A live upgrade against the retained 1.3 GB index additionally proved that search projections must
be backfilled before request serving: startup now fills missing current projections under the sole
writer, and semantic planning refreshes stale rows in its own transaction, so a GET never becomes
the first competing writer.

## 10.5 Generate and maintain the Living Architecture Charter

**Status:** COMPLETE on 31 August 2026.

AnaxiGraph must be able to read a repository and state what it believes the system is for without
waiting for a person to author an architecture document. Introduce `architecture-charter-v1` as a
versioned projection in the existing semantic-document model, not a new configuration product or a
mandatory checked-in file.

The Charter contains:

- system purpose, users/actors, and externally visible capabilities;
- major responsibilities and how they map to areas, subsystems, modules, and entry points;
- important execution/data flows and relationships between responsibilities;
- public contracts, invariants, protected boundaries, and natural extension points;
- recurring implementation patterns and meaningful exceptions;
- current coherence concerns, duplication/dead-code hypotheses, and quality priorities;
- unknowns, contradictions, weak evidence, confidence, provenance, and freshness.

The Charter also exposes a generated **Capability Brief** projection for fresh-context review. It
contains purpose, actors, observable behavior, user journeys, external interfaces, non-functional
requirements, compatibility obligations, and genuine non-goals. It deliberately omits internal
module/package names, storage choices, frameworks, current boundaries, findings, and historical
design decisions unless one is itself an externally required constraint. The full Charter explains
the system as built; the Capability Brief describes the problem the system must solve.

Initial and refresh behavior:

1. A deterministic scan immediately produces a **provisional** Charter containing only supportable
   facts, documentation claims, and explicit unknowns.
2. The connected coding agent can start one resumable **build understanding** task and use its own
   tokens to complete module dossiers, responsibility synthesis, taxonomy review, and repository
   synthesis. The official client workflow owns paging, leases, retries, and continuation; a normal
   agent is not asked to manually administer thousands of jobs.
3. The complete Charter is synthesized from code plus README/documentation evidence rather than
   treating prose as automatically correct. Conflicts are recorded instead of silently resolved.
4. Structural, interface, relationship, intent, prompt, and model fingerprints invalidate only the
   affected claims and aggregates. Unchanged Charter sections keep stable identities and wording
   where the evidence has not materially changed.
5. Human additions and corrections are optional overlays with author, time, and rationale. They may
   override the current presentation but never erase the inferred statement or masquerade as an
   extracted fact.

The same Charter read model is returned through dashboard, CLI, and MCP. It leads with a concise
ordinary-language explanation, then permits progressive disclosure:

```text
purpose -> capability -> responsibility area -> subsystem -> module -> symbol -> evidence
```

Acceptance:

- a repository with no `.anaxigraph.yml` architecture section and no human response receives a
  useful provisional Charter after static scan and a complete Charter after agent-funded synthesis;
- every material statement can be traced to file/document/relationship evidence and its inference
  provenance;
- a misleading README fixture is represented as conflicting evidence rather than unquestioned truth;
- the Capability Brief remains behaviorally complete while a leakage fixture proves that current
  module, framework, storage, and boundary names are absent unless marked as public constraints;
- interruption, expired leases, agent restart, and service restart resume the same understanding task;
- dashboard, CLI, and MCP return the same Charter identity, readiness, claims, and caveats;
- optional human correction is visible as declared context and is never a completion prerequisite;
- the feature reuses semantic documents, jobs, claims, and taxonomy rather than adding a parallel
  architecture database or provider path.

### 10.5 delivery record: one evidence-backed Charter on every product surface

`architecture-charter-v1` is now the repository-synthesis contract used by the existing semantic
pipeline. A static scan immediately projects an honest `provisional` Charter from repository
identity, snapshot facts, and the current responsibility map. Agent-funded repository synthesis
replaces that projection with a strictly validated Charter only after the existing module dossiers,
taxonomy, evidence, and freshness checks are satisfied. A saved Charter is reported as `current`
only while its indexed semantic scope is current; changed evidence makes it `stale` rather than
allowing old prose to masquerade as present understanding. Older generic repository dossiers are
also treated as stale input instead of being silently relabelled as the new contract.

The contract covers purpose, actors, observable capabilities, responsibilities, execution flows,
public contracts, invariants, extension points, recurring patterns, coherence concerns, unknowns,
and conflicts. Material claims require evidence and confidence. Documentation is presented to the
agent as evidence to test against code, not as architecture truth. The embedded
`capability-brief-v1` projection is separately validated to reject internal filenames, module paths,
framework identities, and storage choices outside an explicitly declared compatibility obligation.
This makes the brief suitable for the fresh-context workflow in §10.7 without building another
semantic product.

One actor-neutral projection supplies the dashboard Overview, `anaxigraph charter`, the repository
Overview API, and `ANAXIGRAPH_OVERVIEW`. Those surfaces return the same Charter identity, state,
readiness, claims, provenance, and caveats; the browser does not infer its own currentness. Optional
human or agent corrections are append-only `charter_correction` semantic documents. They may add
declared wording to the current presentation, including author and rationale, while preserving the
original inferred statement and evidence. Corrections survive subsequent scans, can be superseded
or withdrawn, and are never required to make a repository semantically ready. This reuses the
existing semantic-document store and write authority; it adds no architecture table, model provider,
approval workflow, or dashboard-only truth.

The acceptance suite covers a no-policy/no-human provisional Charter, strict evidence and conflict
validation, Capability Brief leakage, current-to-stale invalidation, legacy dossier handling,
correction persistence and withdrawal, API/MCP parity, CLI behavior, semantic chunk reduction, and
rendered dashboard disclosure. The complete Python suite passes with **601 tests** and **92% total
coverage**. The exact browser contract runner passes **21/21**, including the Charter projection.
Pre-commit, Ruff, JavaScript syntax, Compose validation, architecture cycles, container hardening,
first-user latency, and deterministic self-analysis all pass; self-analysis reports zero governed
issues. A rebuilt retained-index deployment serves both registered repositories with the same
repository-scoped Charter contract and no selection bleed.

This phase adds **704 intentional production lines** for the strict contract, projection, correction
overlay, and adapters. The exact production-source ratchet moves from 49,991 to **50,695 lines**.
Every new module remains below 500 lines and the maintainability warning count does not increase.
The increase is accepted evidence-backed product work and does not reopen the owner-closed Phase
10.2 subtraction target. The next work is §10.6.

## 10.6 Deliver one actor-neutral understanding and guidance workflow

**Status:** COMPLETE on 1 September 2026.

The principal should be able to ask either of the two questions that define the product:

1. **“How should I build this capability in this repository?”**
2. **“How should this repository or selected area be refactored to become cleaner?”**

Both dashboard prompts and coding-agent calls invoke the same application service. A goal and
optional scope/context are sufficient input. The response composes existing evidence into:

- its understanding of the goal and any important ambiguity;
- where the work belongs and why;
- what already performs the same or adjacent responsibility;
- whether to extend, reuse, consolidate, split, move, delete, or create code;
- suitable patterns, local precedents, counter-evidence, trade-offs, and migration cost;
- direct and bounded transitive impact, callers, dependencies, contracts, and focused tests;
- the smallest coherent working set and a concrete verification plan;
- confidence, unknowns, reasons to leave the design alone, and evidence links.

This is guidance, not a Change Contract. Do **not** introduce a mandatory plan record, approval gate,
decision ledger, workflow state machine, or project-management lifecycle. A response may be cached,
linked to a finding, or shared as an optional handoff, but the principal can act on it immediately
and can ask again after changing the repository.

The normal dashboard converges to at most five actor-neutral journeys:

1. **Understand** — Charter, capabilities, responsibility map, files, graph, and evidence;
2. **Guide** — goal-driven placement and implementation advice;
3. **Improve** — refactor, pattern, duplication, boundary, size, and possible dead-code advice;
4. **Changes** — current deltas, reassessment, and supporting history;
5. **Settings** — repositories, readiness, refresh, and progressively disclosed operations.

Files and Graph are representations of one selection inside Understand, not competing semantic
models. The normal MCP profile contains no more than ten high-level use cases covering repository,
understanding/Charter, search/explanation, guidance, improvement, impact, refresh, reassessment, and
readiness. Raw graph/history and semantic lease/evidence/submit operations remain in explicit
analyst/executor profiles or behind the official client workflow.

Actor-neutral acceptance has two independent paths:

- **agent-only:** on a clean machine, an ordinary medium-capability Codex or Claude configuration
  installs/starts AnaxiGraph, scans a repository, completes and resumes agent-funded understanding,
  reads the Charter, requests implementation and refactor guidance, follows evidence, refreshes, and
  reassesses without opening a browser or receiving mid-run human help;
- **human-led:** a professional developer and a person who does not read code use the dashboard to
  explain the system, trace a capability, inspect a module, distinguish fact from interpretation and
  recommendation, request the same two forms of guidance, and hand an optional link/prompt to their
  coding agent without copying raw payloads.

Both paths must produce the same recommendation identity and core contents for the same repository,
snapshot, goal, policy, and completed semantic state. Browser layout and MCP token budgets may
change presentation, never the architectural conclusion.

### 10.6 delivery record: one adviser, five journeys, and a bounded normal agent surface

`architecture-guidance-v1` is now the single actor-neutral answer to the product's two defining
questions. It accepts a `build` or `refactor` intent plus an optional focus and composes the current
Charter, responsibility map, module descriptions, static links, findings, reviewed pattern
evidence, history clues, protected paths, and focused tests. Its stable identity includes the
repository, saved snapshot, goal, intent, focus, and core evidence-backed conclusion. The response
states what AnaxiGraph understood, recommends one of reuse, extend, create, move, split,
consolidate, delete-as-candidate, refactor, or retain, and preserves counter-reasons, expected
migration effort, bounded impact, confidence, unknowns, caveats, and direct evidence references.
It remains advice that can be acted on immediately; no Change Contract, approval gate, decision
ledger, or project-management state was introduced.

The dashboard, CLI, REST API, and normal MCP profile all call that same application service.
`anaxigraph guide`, `POST /api/guidance`, and `ANAXIGRAPH_GUIDE` therefore return the same identity
and architectural conclusion for the same saved state. The dashboard submits the same goal, intent,
and focus contract and only changes presentation. Finding handoffs reuse the refactor guidance
service instead of constructing another recommendation. Tight MCP budgets preserve the guidance
conclusion and bounded impact before compacting older diagnostic detail.

The dashboard now exposes exactly five top-level journeys: **Understand**, **Guide**, **Improve**,
**Changes**, and **Settings**. Files and Graph are views inside Understand; Findings and Patterns
are views inside Improve. Their navigation is generated from one definition so the visible tabs and
view routing cannot drift independently. The normal MCP profile contains nine read tools when scan
permission is disabled and exactly ten in the generated sidecar: repositories, overview/Charter,
semantic readiness, search, file explanation, guidance, impact, findings, finding context, and
read-only-source refresh. History/taxonomy diagnostics remain in the analyst profile. The seven
lease/schema/evidence/submission tools now live only at `/executor/mcp`, which the official durable
semantic worker uses; they no longer overwhelm an ordinary coding agent's tool menu.

The agent-only acceptance path covers a real Streamable HTTP executor lifecycle over a 200-module
repository, including partial completion, an abandoned lease, process replacement, automatic
reclamation, completed taxonomy/pattern work, and `semantically_ready: true`. The normal profile
then proves the exact ten-tool coding loop, implementation/refactor guidance, evidence follow-up,
refresh, and API/MCP conclusion parity without a browser. The human-led path uses the rendered
dashboard form against the same REST service and proves five-journey navigation, readable
recommendations and counter-reasons, module/graph exploration, and the prior white-canvas and
repository-selection regressions. The complete suite passes with **603 tests at 91.98% coverage**;
the pinned browser runner passes **23/23** contracts.

The generated Compose service and this repository's deployment enable the safe scan tool while
keeping source mounted read-only; only AnaxiIndex changes. First-user measurement now connects its
semantic bootstrap to the internal executor endpoint. Ruff, JavaScript syntax, agent-package,
module-size, architecture, Compose, and production-quality ratchets remain green. This phase adds
**631 intentional production lines** for the guidance contract and projection, profile boundary,
five-journey navigation, and their adapters. The exact production-source ratchet moves from 50,695
to **51,326 lines**. No implementation asset exceeds 500 lines. Phase 10.2 remains closed; the next
work is §10.7.

## 10.7 Add the fixed fresh-eyes architecture review

**Status:** COMPLETE on 1 September 2026.

Turn the method in “Fresh eyes without architectural amnesia” into one resumable, agent-funded
review recipe beneath **Improve**. This is not a generic agent framework. It is a fixed sequence with
versioned inputs, explicit information boundaries, existing semantic-job execution, and one composed
result: `fresh-eyes-review-v1`.

The stages are:

```text
                             ┌─> independent proposal A ─┐
repository -> Capability Brief                           ├─> blind adjudication
                             └─> independent proposal B ─┘          |
                                                                    v
current Charter + map + history --------------------------> as-built comparison
                                                                    |
mission + constraints + engineering economics ---------------------+
                                                                    v
                                                   ranked refactor strategy
```

One proposal is a supported low-cost mode. Two independent proposals are the recommended default
when the connected principal has the capacity; a third is optional. Diversity may come from Claude,
Codex, Gemini, or independent sessions of one capable model. AnaxiGraph records actual provider,
model, prompt/protocol version, and input manifest and never labels same-model sessions as
cross-provider agreement.

### Stage A — capability distillation

Use the Charter's Capability Brief rather than asking every reviewer to reread the repository.
Require evidence coverage for every capability and identify contradictions or unknown requirements.
A reviewer may request bounded supporting evidence when a behavior is unclear, but implementation
details do not enter the clean-sheet packet.

### Stage B — isolated clean-sheet proposals

Each proposal receives the same versioned Capability Brief, externally required constraints,
quality priorities, and output schema—nothing from the current responsibility map, file paths,
frameworks, findings, history, or another proposal. It describes component responsibilities,
boundaries, information flows, extension strategy, operating model, and important patterns at a
useful architectural level. It must explain trade-offs and avoid speculative infrastructure that
the stated scale and mission do not require.

AnaxiGraph can guarantee and hash only the packet it supplies. It cannot prove that an external
model has no unrelated prior context, so the result records the requested isolation mode and this
caveat. The official Codex/Claude workflow should create a fresh subagent or session where the host
supports it; otherwise it must report that isolation is unverified.

### Stage C — blind adjudication

The adjudicator receives the Capability Brief and proposals, still without the current repository
architecture. It preserves meaningful disagreement, calls out shared assumptions and likely common
blind spots, and synthesizes a reference design from the strongest compatible ideas. Consensus is
evidence of agreement, not proof of correctness.

### Stage D — comparison with the as-built system

A repository-aware reviewer receives the adjudicated reference plus the current Charter,
responsibility map, module dossiers, graph evidence, patterns, findings, and relevant history. It
maps reference responsibilities to current responsibilities and classifies each difference as:

- current design already satisfies the intent;
- current design differs for a documented or evidence-backed good reason;
- potentially useful simplification or consolidation;
- missing capability or architectural weakness;
- greenfield idea whose migration cost or risk outweighs its likely value;
- unresolved because evidence is insufficient.

The reviewer must search for strengths in the current system as deliberately as it searches for
debt. Absence from the clean-sheet proposal is not evidence that existing code should be deleted.

### Stage E — mission filter and refactor strategy

Adjudicate candidate changes against the current mission, user value, architectural coherence,
expected production-code reduction, operational simplicity, compatibility, migration risk,
reversibility, and verification cost. The output keeps only suggestions that make the existing
product materially better. Each retained suggestion contains:

- the mission/capability it advances;
- current evidence and the reference-architecture insight;
- the smallest coherent change, expected benefit, and expected deletions/consolidations;
- protected behavior, affected contracts/tests, risk, counter-evidence, and reasons not to proceed;
- dependencies and a safe sequence relative to other retained suggestions;
- a verification method and a confidence statement.

This ordered result is refactor guidance, not a mandatory roadmap, Change Contract, or permission to
rewrite code. A principal may request deeper evidence, ignore it, or use selected slices as input to
the ordinary Guide workflow.

### Reuse, recurrence, and storage

Reuse the existing semantic document/job/lease/provenance machinery and recommendation language.
Persist one versioned review bundle plus bounded stage artifacts; do not create a new database,
provider client, scheduler, recommendation ledger, or configurable workflow DAG.

Fingerprint three boundaries independently:

1. **capability fingerprint** — behavior, public contracts, mission, non-functional constraints, and
   Capability Brief protocol;
2. **reference fingerprint** — capability fingerprint plus proposal/adjudication protocol and actual
   reviewer identities;
3. **comparison fingerprint** — reference fingerprint plus current Charter, responsibility,
   relationship, pattern, finding, and relevant history identities.

When implementation changes but capabilities do not, reuse proposals/adjudication and rerun only
the as-built comparison and mission filter. When capabilities change materially, mark the reference
stale and offer a new review. A watcher may mark stages stale but never launches model work by
itself; the connected agent or human-triggered agent workflow owns tokens and execution. Support
manual review at any time and an optional release/milestone reminder, not an always-on AI schedule.

The dashboard shows this inside **Improve** as Capability Brief, independent proposals,
adjudication, as-built comparison, and ranked strategy. MCP/CLI expose the same high-level review
operation and result through the bounded normal Improve use case; low-level work packets remain in
the executor profile. This adds no sixth dashboard journey or flat family of stage-specific tools.

Acceptance:

- a fresh agent can complete the whole review using its own tokens without reading source files or
  receiving manual human orchestration after the task starts;
- exact stage input manifests prove current module/path/framework labels are withheld from proposal
  and blind-adjudication packets;
- interrupted work, expired leases, service restart, and a different connected agent resume safely;
- a two-proposal fixture preserves real disagreement and reports model/provider diversity honestly;
- a legacy-anchoring fixture discovers a simpler responsibility split that repository-local review
  misses, while a compatibility fixture keeps an existing design that the greenfield proposal would
  wrongly replace;
- a mission-filter fixture rejects attractive but unnecessary infrastructure and retains a smaller,
  evidence-backed refactor slice;
- an implementation-only change reuses the reference stages, while a capability change invalidates
  them with an explicit reason;
- dashboard and MCP/CLI return the same review identity, stage readiness, recommendations, evidence,
  and caveats;
- no workflow engine, provider integration, table family, top-level navigation item, mandatory
  approval state, or automatic refactor is introduced.

### 10.7 delivery record: fresh eyes without a second architecture system

`fresh-eyes-recipe-v1` now runs as one explicit, resumable consumer of the existing agent-funded
semantic queue. `FreshEyesPlanner` schedules one to three `fresh_proposal` jobs, then
`fresh_adjudication`, `fresh_comparison`, and `fresh_review` in a fixed order. It reuses the current
Living Architecture Charter and its behavior-only Capability Brief; it does not add a workflow
DAG, scheduler, model provider, database table family, approval ledger, or source-editing path.
The normal semantic baseline remains ready while this optional review is pending.

Every stage has a strict versioned result schema and a retained exact input manifest. Proposal
packets contain the Capability Brief, public constraints, quality priorities, and an explicit list
of withheld implementation evidence. Blind adjudication sees only those proposals and the same
brief. Current paths, responsibility map, dossiers, relationships, patterns, findings, and bounded
history enter only for the as-built comparison. Submission recomputes the manifest identity and
rejects superseded packets. The result states the requested isolation boundary honestly: it can
prove what AnaxiGraph supplied, but not that an external model had no unrelated context.

Capability, reference, and comparison fingerprints are stored independently in existing semantic
scope-state fields. A fixture proves that an implementation-only snapshot reuses the exact proposal
and adjudication documents and queues only comparison work; changing the Capability Brief queues
new proposals and returns an explicit invalidation reason. Existing lease reconciliation, retry,
provider/model/executor provenance, paging, strict validation, and saved documents provide restart
and different-agent resume behavior.

One `FreshEyesReviewService` now supplies the same identity, readiness, fingerprints,
recommendations, manifests, diversity, and caveats to `GET/POST /api/fresh-eyes`,
`anaxigraph fresh-eyes`, **Improve → Fresh eyes**, and the fresh-eyes mode of the existing
`ANAXIGRAPH_GUIDE`. The normal MCP profile therefore remains within ten tools and the dashboard
remains within five top-level journeys. The dashboard exposes stage progress and provenance but
presents only the final mission-filtered recommendations as actionable advice; disagreement,
current strengths, rejected overengineering, counter-evidence, and reasons not to proceed remain
visible.

The full Python suite passes with **607 tests**. The pinned browser runner passes the complete
dashboard contract set, including the new stage/provenance/final-advice fixture; Ruff, JavaScript
syntax, module-size, architecture, agent-package, Compose, and deterministic self-analysis gates
remain required by the final phase commit. Five cohesive core modules keep every implementation
asset within 500 lines rather than extending the already crowded semantic orchestrators. This
phase adds **2,281 intentional production lines** for strict contracts, bounded evidence,
fingerprint/reuse planning, the shared review projection, dashboard, and four transport adapters.
The exact production-source ratchet moves from 51,326 to **53,607 lines**. Phase 10.2 remains
closed; this ratification is feature growth, not a reopened subtraction campaign.

## 10.8 Close the continuous architecture-sidekick loop

**Status:** COMPLETE on 1 September 2026.

After a coherent edit or commit, hashes and deterministic analysis identify changed modules. Only
stale semantic scopes, affected responsibility aggregates, and Charter sections are refreshed. The
same application response then explains to either principal what changed in responsibility,
placement, dependencies, complexity, duplication, pattern fit, boundary coherence, and possible
unused code.

The response separates:

- observed change;
- architectural consequence;
- recommendation and confidence;
- counter-evidence and reasons to leave the code alone;
- smallest safe follow-up and verification.

Reassessment uses the last compatible durable snapshot and current evidence. It does not require a
pre-created Change Contract, saved plan, or human approval. An optional earlier snapshot or goal may
narrow the comparison, but ordinary watch/refresh is enough to keep the shared model current.

AnaxiGraph can surface proactive, ranked opportunities—duplicate responsibilities, merge/split
candidates, missing abstractions, misplaced modules, suitable patterns, boundary erosion, and
possible dead symbols/modules—but never deletes or rewrites target code automatically. History
supports the advice with churn, co-change, introduction, and recurrence evidence; it is not a
separate product center.

Acceptance:

- a one-module edit reanalyzes that module plus only conservatively affected dependants/aggregates;
- the Charter and both principal surfaces become current without a repository-wide semantic rerun;
- known pattern, duplication, boundary, dead-code, and coherent-no-change fixtures yield calibrated
  advice with false-positive caveats;
- asking again after a good refactor explains the improvement; asking after a harmful edit explains
  the regression;
- no mandatory decision/change-management state is created along the path.

### 10.8 delivery record: one shared bounded reassessment

One `architecture-reassessment-v1` application response now compares the current durable snapshot
with the last changed snapshot in the same lineage that uses a compatible analyzer contract. An
explicit compatible earlier snapshot remains optional. The comparison reads immutable file and
relationship facts, finding occurrences, current semantic scope states, the Living Architecture
Charter, independently reviewed pattern evaluations, and existing change-coupling history. It
creates no table, model request, semantic job kind, decision record, approval state, or target-code
write. A bounded lineage walk skips up to eight compatible commit-only or otherwise architecturally
unchanged frames, so routine rescans cannot hide the most recent real code change.

The response identifies changed modules and their conservative direct context, while the existing
semantic planner continues to decide which of those scopes are genuinely stale from content,
interface, relationship, dossier, aggregate, pattern, taxonomy, and Charter fingerprints. A
one-module fixture first exposes the pending changed/affected scope, then becomes current after one
intrinsic reread plus the affected pattern assessment and independent review. Its unchanged
dependant descriptions, taxonomy, group synthesis, and repository synthesis are reused rather than
rerun. If new module meaning changes an aggregate input hash, the existing group and repository
planner queues only those affected aggregates. The response never claims that the whole repository
needs another semantic pass.

Every returned effect shares one calibrated shape: observed change, architectural consequence,
recommendation, structured confidence, counter-evidence, reasons to leave the code alone, smallest
safe follow-up, verification, and evidence. Deterministic and semantic fixtures cover complexity
regression and improvement, stable-text-only changes, relationship source-line churn, placement,
dependency changes, boundary violations, reviewed pattern fit, consolidation/duplication, and
possible unused code. Relationship comparison deliberately ignores changed source locations when
the architectural source/target/type/provenance link is unchanged.

The same saved identity and content is exposed through `GET /api/reassessment`, `anaxigraph
reassess`, the `reassess=true` mode of the existing `ANAXIGRAPH_GUIDE`, and the existing **Changes**
journey. No eleventh normal MCP tool or sixth dashboard journey was added. Repository loading also
treats reassessment as a degradable panel, so a temporarily unavailable comparison cannot leave
the rest of the current repository dashboard stuck in a loading state.

The ratified acceptance evidence is **615 Python tests** and **26 pinned-browser contracts**, plus
Ruff, JavaScript syntax, module-size, architecture, agent-package, Compose, deterministic
self-analysis, coverage, changed-coverage, first-user, container, and benchmark gates. On the
self-hosted 479-module AnaxiGraph map, the read-only response compared two saved frames, bounded two
changed modules to six context modules, returned about 26 KB, and completed in about 847 ms. Five
cohesive Python modules and two dashboard assets keep every implementation file below 500 lines.
They add **1,864 intentional production lines** for temporal/semantic evidence, calibrated advice,
the shared application projection, transport adapters, and the human rendering. The exact
production-source ratchet moves from 53,607 to **55,471 lines**. Phase 10.2 remains closed; this is
measured core product capability, not a reopened subtraction campaign.

## Phase 10 exit gate

- The three product promises and the actor-neutral rule are visible in onboarding, navigation,
  agent guidance, contribution review, and roadmap admission.
- Normal generated Compose runs one AnaxiGraph service process with supervised watchers and one
  repository-scoped AnaxiIndex write authority.
- One vocabulary distinguishes declared, path-derived, inferred-responsibility, and current-view
  maps; dashboard, history, CLI, and MCP preserve stable identities and use it consistently.
- One FTS5-backed query service seeds search, scope, guidance, Charter evidence, and pattern discovery;
  the duplicate whole-repository lexical rankers are gone.
- A no-human-input repository receives an evidence-backed Charter, and optional human corrections
  remain visibly distinct from inferred understanding.
- One current AnaxiIndex produces the hierarchy, Charter, explanations, and recommendations consumed
  by dashboard and coding-agent workflows; neither maintains a competing semantic model.
- The normal dashboard has at most five task-centered journeys and the normal MCP profile has at
  most ten tools; advanced operations remain intentionally accessible.
- Both the agent-only and human-led acceptance paths in §10.6 pass, including interrupted semantic
  bootstrap and medium-capability agent configurations.
- The §10.7 fresh-eyes review proves implementation-blind proposal packets, honest independent-agent
  provenance, blind adjudication, as-built comparison, mission filtering, and incremental reuse
  without adding another provider or workflow platform.
- The latest phase-ratified **55,471-line** production ratchet remains enforced unless a later phase
  explicitly ratifies necessary growth; production module count, high-fragmentation package counts,
  and public surface are governed alongside LOC rather than traded against it.
- No Change Contract, mandatory approval/decision workflow, new product family, database, provider
  pipeline, or parallel architecture model was introduced to achieve the phase.

---

# Phase 11 — parser-backed JavaScript and TypeScript understanding

**Status:** COMPLETE AND PUBLICLY VERIFIED on 1 September 2026 in AnaxiGraph `0.4.0`. Phase 10 is
closed and Phase 10.2 remains frozen.

**Goal:** make AnaxiGraph genuinely useful on modern JavaScript/TypeScript repositories without
turning language count into a vanity metric. Python remains the reference analyzer. JavaScript,
JSX, TypeScript, and TSX become the second deeply supported family through the existing IR and
analyzer contract.

## 11.0 Ratify the parser and capability contract

**Status:** COMPLETE on 1 September 2026.

Benchmark tree-sitter as the preferred implementation against representative browser, Node,
monorepo, decorator, JSX/TSX, CommonJS, and ECMAScript-module fixtures. Record an ADR covering wheel
availability, grammar/version pinning, security/update policy, parse recovery, memory, speed, license,
and packaging. If tree-sitter fails a binding constraint, select an equivalent concrete parser; the
regex analyzer is not accepted as the deep-analysis fallback.

Publish an honest capability matrix for each syntax family. Extension recognition alone never means
symbol, call, type, or dependency support.

### 11.0 delivery record

ADR 0005 selects the official Tree-sitter Python binding (`0.26.0`), JavaScript grammar (`0.25.0`),
and TypeScript/TSX grammar (`0.23.2`) as exact runtime pins. The decision records license, wheel and
container constraints, parse recovery, the two-megabyte input bound, update/security policy, cache
invalidation, and the prohibition on a hidden regex fallback. `docs/language-support.md` publishes
the binding per-family evidence contract and distinguishes syntax facts, repository resolution,
type-checker certainty, and runtime behavior.

The retained `parser-selection-v1` benchmark covers browser JSX, Node CommonJS, monorepo ESM,
decorators/generics, TSX, and malformed recovery. On the recorded Linux x86-64 / Python 3.11 runner,
all classifications passed; small samples parsed in 0.010–0.023 ms median and a 955,000-byte
TypeScript sample in about 134 ms median. These numbers establish feasibility, not a universal
latency promise. A focused regression contract executes the same syntax/recovery matrix in tests.

## 11.1 Produce parser-backed JavaScript/JSX facts

**Status:** COMPLETE on 1 September 2026.

Extract stable modules, imports, exports/re-exports, CommonJS references, declarations, classes,
methods, functions, selected calls, and source locations. Preserve ambiguous, unresolved, external,
and dynamic relationships explicitly. Parse recovery returns partial facts plus diagnostics rather
than silently falling through to high-confidence regex results.

### 11.1 delivery record

The `builtin-javascript-tree-sitter` analyzer now parses JavaScript and JSX through the pinned
grammar. It emits versioned IR v2 facts for ESM imports and exports, re-exports, CommonJS
`require`/`module.exports`, literal dynamic imports, computed dynamic expressions, functions,
classes, methods, class-field arrow methods, React components, selected API endpoints, calls,
inheritance, visibility, source spans, comments, complexity, and structural hashes. Literal,
CommonJS, computed, and ordinary static references retain distinct reference forms.

Recovery diagnostics remain attached to partial parser facts. A malformed file never silently
falls back to the retired regex analyzer, and a computed import is stored as dynamic evidence with
no invented target. A regression built from the real dashboard also protects against the pinned
Python binding's unsafe native `Point` access: source positions are derived from stable byte offsets
while the owning parse tree remains alive.

## 11.2 Add TypeScript/TSX contracts without inventing precision

**Status:** COMPLETE on 1 September 2026.

Add interfaces, type aliases, enums, namespaces, typed declarations, decorators, and type-only
imports/exports where the syntax supports them. Distinguish syntax-level reference evidence from
compiler/type-checker resolution. Project references, aliases, and workspace/package resolution are
reported with provenance and honest ambiguity; AnaxiGraph still does not execute the target build.

### 11.2 delivery record

The separate `builtin-typescript-tree-sitter` capability contract adds TypeScript and TSX syntax
facts for interfaces, type aliases, enums, namespaces, annotations, generics, decorators,
implements/extends clauses, and type-only imports and re-exports. These remain syntax claims: the
capability declaration expressly excludes type-checker and runtime certainty.

Repository resolution uses only indexed evidence from `.anaxigraph.yml`, `package.json`, and bounded
JSON/JSONC projections of `tsconfig`/`jsconfig`. It handles relative and repository paths, configured
aliases, `baseUrl`, `paths`, bounded relative `extends` chains, TypeScript project references,
workspace package names/subpaths, package `exports`, package `imports`, and entry points. Every
resolved edge carries its provenance; duplicate candidates stay ambiguous, missing internal aliases
stay unresolved, unknown packages stay external, and target repository tooling is never executed.
Changing resolver configuration invalidates carried JavaScript-family relationships without forcing
unchanged source files through semantic analysis again.

## 11.3 Migrate consumers and remove the regex path

**Status:** COMPLETE on 1 September 2026.

Version analyzer identity and invalidate affected cached facts. Make responsibility synthesis,
patterns, scope/guidance, impact, dead-code caveats, graph resolution, and Charter generation consume
the same IR capabilities used for Python. Delete the regex-oriented import/symbol analyzer after
fixture parity and migration tests pass; retain only bounded text heuristics for explicitly shallow,
unsupported languages.

### 11.3 delivery record

Analysis version 5 and IR `anaxigraph-ir-v2` make parser identity, capability fingerprint, parse
status, source evidence, reference form, and resolution provenance explicit. Stored v1 facts remain
readable with safe defaults, while changed analyzer contracts invalidate only affected semantic
dossiers. Agent scope, public-interface selection, semantic requests, pattern evidence, graph
quality, impact analysis, and dead-code safeguards now consume this shared evidence. Dynamic or
insufficiently resolved references suppress unsafe deletion advice.

The old `builtin-js-lexer` implementation and its comment-stripping/regex projections are gone from
current scans. The name remains readable only as legacy-index telemetry. Candidate wheel and sdist
metadata require the three exact parser pins, the clean-wheel smoke parses TSX, the hardened sidecar
container exposes parser-backed graph quality through MCP, and dependency inventory records both
license metadata and classifiers.

## Phase 11 exit gate

- JavaScript, JSX, TypeScript, and TSX fixtures expose versioned parser-backed capability truth;
- modern syntax, parse errors, aliases, monorepos, ambiguous resolution, dynamic imports, and
  CommonJS have explicit tests and provenance;
- mixed Python/TypeScript guidance finds correct responsibilities, extension points, contracts, and
  focused tests without pretending syntax extraction is runtime certainty;
- scan/history/incremental-reuse performance is benchmarked on small, medium, and large fixtures;
- supported wheels, containers, SBOMs, licensing, and release artifacts include the pinned parser
  safely;
- the regex analyzer and its duplicate projections are removed, all size/cohesion gates pass, and
  production growth is offset by deleted shallow-analysis code or explicitly ratified.

### Phase 11 acceptance record

The source exit gate passed on 1 September 2026:

- **634 Python tests passed** with **92% aggregate coverage**, including modern syntax, recovery,
  workspace ambiguity, project aliases/references, dynamic evidence, IR v1 compatibility, semantic
  invalidation, real-dashboard parsing, release metadata, and container contracts;
- the retained parser scale benchmark passed at 120, 1,000, and 3,000 source files. The 3,000-file
  case completed a cold scan in **4.825 seconds**, an unchanged scan in **1.827 seconds**, a one-file
  incremental scan in **4.338 seconds**, and three historical frames in **22.945 seconds**. Each
  later history frame read and analyzed exactly one changed file while carrying 3,001 unchanged
  files;
- deterministic self-analysis passed with six exact governed findings and no regression. The three
  newly accepted dashboard warnings were existing complexity made visible by deeper JavaScript
  parsing, not new Phase 11 complexity; Phase 10.2 was not reopened;
- all parser implementation modules remain below the 500-line hard ceiling, the architecture and
  module-size hard gates pass, and the prospective wheel, sdist, clean-wheel TSX smoke, dependency
  inventory, and hardened sidecar-container smoke pass;
- the production-source ratchet moves from **55,471** to **57,439 lines**. This explicit 1,968-line
  increase replaces the 443-line shallow regex path with a capability-honest parser, syntax-fact
  extractors, deterministic workspace resolver, provenance, compatibility, safety, and scale
  evidence. It is accepted Phase 11 product depth rather than Phase 10.2 cleanup debt.

The public release gate passed on 1 September 2026:

- annotated tag `v0.4.0` resolves to exact source commit `6fdf7e6`; that commit passed all seven
  jobs in [main CI run 33468529239](https://github.com/hcekne/anaxigraph/actions/runs/33468529239),
  including the complete quality gate, Python 3.12, four wheel/sdist matrices, and browser contracts;
- [GitHub release 0.4.0](https://github.com/hcekne/anaxigraph/releases/tag/v0.4.0) was published only
  after [container run 33469214981](https://github.com/hcekne/anaxigraph/actions/runs/33469214981)
  passed its release-tag verification and produced a public `linux/amd64` plus `linux/arm64` image;
- the `0.4.0`, `0.4`, and `latest` image tags resolve to manifest digest
  `sha256:3f7f3f2ed5f4bbe0b58996fe75d8fa14b7d032fe6d6d72c67133643ed1b45c3b`.
  GitHub provenance verification passes for that exact digest, and a clean pull by digest reports
  `AnaxiGraph 0.4.0`;
- [release run 33470550275](https://github.com/hcekne/anaxigraph/actions/runs/33470550275)
  built and attested the bundle once, attached the wheel, source distribution, dual-client plugin,
  SPDX SBOM, dependency-license inventory, checksums, and release contract to GitHub, published to
  the protected PyPI environment with short-lived OIDC identity, and passed its public-install job;
- [PyPI 0.4.0](https://pypi.org/project/anaxigraph/0.4.0/) publishes wheel digest
  `64776780d7a3d8d8aaa8b716f4335ff0250f7cf84a2fd54ae26e7ba88cb33ed6` and source-distribution
  digest `c402bddd04fb1643528d255de506802653b101674668ba9d575e0444b7d87d3f`, exactly matching the
  GitHub release assets. The published `SHA256SUMS` validates the wheel, source distribution, and
  plugin, and GitHub attestations verify all three against the release workflow and `v0.4.0` ref;
- an independent no-cache install from public PyPI reports `0.4.0`, installs the three exact parser
  pins, and parses a TSX component as `builtin-typescript-tree-sitter` with status `parsed`;
- a pre-publication evidence check caught that the container workflow's digest text used the Git
  ref spelling `:v0.4.0` instead of the published semver image tag `:0.4.0`. The release asset was
  corrected before publication, and commit `b8acd28` fixes and regression-tests future generation.

The previously published `0.3.0` artifact remains immutable and lexical. Public `0.4.0` closes
Phase 11 and the complete roadmap 4.2 without reopening Phase 10.2.

---

# Nice-to-have ideas — not an implementation queue

These are recorded only so they are not repeatedly rediscovered and mistaken for active work. They
do not block 1.0 and are not implementation tasks. The owner must explicitly reopen one after
concrete user evidence shows that it materially improves the core navigation-and-structure mission:

- parser-backed Go, Rust, Java, C, C++, C#, Ruby, or PHP support, delivered one language at a time
  through the existing analyzer contract after the committed JavaScript/TypeScript phase;
- SQL, API-schema, deployment, Terraform, Markdown/ADR, or other non-code adapters;
- a general third-party plugin SDK;
- PDF, image, audio, or video understanding;
- animated architecture playback, a visual repository bibliography, or identity/ownership analytics;
- a standalone historical hotspot score or ranking beside the existing attention queue and
  before/after structural comparison;
- a separate website, interactive demo, replay video, or ecosystem-growth program.
- extra disaster-recovery automation beyond the tested backup/restore path;
- new release-governance infrastructure beyond the existing protected, attested pipeline;
- guarantees for administrative/export endpoints that are not part of the coding loop;
- uninstall automation or a second operations interface.
- additional plain-language coverage outside the navigation and coding-decision outputs;
- a generic warning-cleanup or self-analysis-debt campaign;
- another provider, executor, scheduler, or orchestration framework beyond the existing bounded
  resumable semantic path.

Optional work still obeys provenance, safety, bounded-resource, module-size, test, and honest-support
rules. Installing a parser or recognizing an extension never counts as supporting a language.

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
- production LOC, module count, exported surface, and high-fragmentation package counts use ratchets
  together; passing the file-size ceiling by adding a forwarding fragment is not a valid reduction;
- architecture-policy references resolve to current modules, paths, or declared logical concepts;
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
- declared, path-derived, inferred-responsibility, and presentation projections remain distinguishable;
- semantic provider/model/prompt/schema and evidence retained;
- no credential in repository configuration, logs, fixtures, or index exports;
- state-changing behavior audited and idempotent where retries are expected.

## User experience

- loading, empty, partial, failure, cancellation, retry, and success states;
- clear totals whenever results are filtered, paginated, ranked, or omitted;
- keyboard/accessibility and visual regression checks for changed dashboard flows;
- every changed core use case has dashboard and CLI/MCP parity tests unless a surface is explicitly
  classified as advanced operator or semantic-executor behavior;
- onboarding and operator docs updated in the same phase, not deferred.

# Metrics that decide whether the roadmap is working

| Product question | Metric |
|---|---|
| Can a new user reach value? | Commands and median minutes to static map, agent connection, resumable semantic understanding, and first useful guidance—with and without opening the dashboard |
| Does AnaxiGraph understand the repository? | Charter claim evidence coverage, unknown/conflict rate, confidence calibration, freshness, independent-agent agreement, and optional human correction rate |
| Does fresh-eyes review escape legacy anchoring? | Capability coverage versus implementation leakage, proposal diversity, preserved disagreement, useful novel simplifications, rejected overengineering, retained good existing decisions, and reference-stage reuse |
| Can someone navigate a large codebase? | Steps and bounded payload from a coding goal to area, subsystem, module, symbol, contracts, and related files |
| Are human and agent views equivalent? | Same-snapshot Charter/guidance identity and content parity across dashboard, CLI, and MCP plus completion rate for human-led and agent-only fixtures |
| Can an agent choose where code belongs? | Placement-fixture accuracy, useful local precedents, affected-contract recall, focused-test recall, and unnecessary-file rate |
| Does the change loop prevent entropy? | Introduced/worsened/improved/resolved classification accuracy for size, complexity, coupling, cycles, boundaries, and responsibilities |
| Can a large file be split coherently? | Mixed-versus-cohesive decision accuracy, bounded extraction slices, preserved-contract coverage, and focused-test coverage |
| Can users trust the graph? | Analyzer capability mix, stable responsibility-map identities, unique/ambiguous/unresolved relationship rate, parse errors, and dynamic-wiring caveats |
| Is the attention queue useful? | Queue size, top-20 action rate, dismissal reason, recurrence, time to resolution |
| Is architecture advice useful? | Independent-agent agreement, optional operator correction rate, false-positive category, score calibration, verified improvement/regression |
| Is semantic cost controlled? | Current/stale/failed/excluded coverage plus per-action task time, input/output tokens, cost, model, reuse rate, jobs per changed module, and detached-run wall time |
| Does history improve today's decision? | Co-change precision, introduction/resolution lookup time, and incremental work per changed file |
| Is AnaxiGraph staying clean? | Production LOC, per-package LOC/module count, public surface, modules over 400/500 lines, stale architecture policy, cycles, layer violations, complexity, changed-code coverage, and finding recurrence |
| Is the runtime simple? | Normal AnaxiGraph process count, writer ownership violations, lock-wait time, clean-shutdown rate, and restart/recovery success |
| Is JavaScript/TypeScript support real? | Parser-backed capability coverage, fixture precision/recall, partial-parse honesty, edge-resolution provenance, and mixed-repository guidance accuracy |
| Do product surfaces stay bounded? | Charter, guidance, scope, overview, expanded-region, comparison, and evidence payload bytes/time plus peak browser memory |

# Complexity exclusions

These are not introduced to deliver the active core roadmap:

- a second graph, vector database, or provider pipeline beside the existing contracts;
- a second planning or verification product beside scope, update, findings, patterns, and Map;
- a Change Contract, mandatory approval gate, decision ledger, or project-management workflow;
- a dashboard-only core action or separate agent-only interpretation of the repository;
- a configurable multi-agent workflow engine, provider broker, autonomous review scheduler, or
  stage-specific public tool family for the fixed fresh-eyes recipe;
- automatic code deletion or unreviewed autonomous refactors;
- a general policy language for rules current configuration can express;
- a new primary dashboard view for information that fits the existing task-centered views;
- framework or ecosystem work without a concrete core-use fixture.

# Immediate implementation queue

Completed work stays documented in its phase and is intentionally absent here. This is the entire
remaining queue; a warning, idea, or adjacent polish task does not enter it without passing the
feature-admission rule.

| # | Status | Outcome and acceptance | Specified in |
|---:|---|---|---|
| 1 | **COMPLETE** | Inventory every public surface and major code cluster against Understand, Guide, Keep coherent, enabling infrastructure, advanced operations, or removal; produce the ordered deletion map without implementing features | §10.1 |
| 2 | **COMPLETE** | Close substantive consolidation at the owner-accepted 49,797-line ratchet after removing 4,110 lines and multiple complete duplicate paths without code golf | §10.2 |
| 3 | **COMPLETE** | Fold watchers into one service lifecycle, establish one repository-scoped write authority, and reduce normal generated Compose to one AnaxiGraph service | §10.3 |
| 4 | **COMPLETE** | Adopt the declared/path/inferred/current responsibility vocabulary and replace duplicate lexical ranking with one bounded FTS5 query substrate | §10.4 |
| 5 | **COMPLETE** | Generate the evidence-backed Living Architecture Charter without human input, support optional visible corrections, and prove resumable agent-funded completion | §10.5 |
| 6 | **COMPLETE** | Deliver the same implementation/refactor guidance through five dashboard journeys and at most ten normal MCP tools; pass independent agent-only and human-led workflows | §10.6 |
| 7 | **COMPLETE** | Run the fixed capability brief → independent clean-sheet proposals → blind adjudication → as-built comparison → mission filter sequence through one resumable agent-funded Improve workflow | §10.7 |
| 8 | **COMPLETE** | Refresh only changed semantic scope and return shared architecture reassessment without a Change Contract or approval workflow | §10.8 |
| 9 | **COMPLETE — PUBLICLY VERIFIED** | Replace regex-oriented JavaScript/TypeScript analysis with a parser-backed, capability-honest implementation and remove the shallow path; public 0.4.0 wheel, source distribution, plugin, SBOM, attestations, clean install, and multi-architecture container pass the release gate | Phase 11 |

All admitted roadmap 4.2 work is complete. There is no active implementation phase or hidden
continuation queue. The retained MaxOS run and public `0.4.0` acceptance record are evidence for the
completed product, not independent product features. Any further parser expansion, adapter family,
plugin framework, website, media support, generic operations work, warning-cleanup campaign, or
dashboard family requires a separately admitted roadmap item under the feature-admission rule.

Roadmap 4.2 is therefore closed on 1 September 2026. A later roadmap may build on it, but may not
silently reopen Phase 10.2, reinterpret a nice-to-have as unfinished 4.2 work, or weaken the public
acceptance evidence recorded above.

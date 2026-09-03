# Architecture

AnaxiGraph is the shared architecture intelligence layer for humans and AI agents. Its dashboard
and agent interfaces expose the same living model of what a software system does, how its parts
work together, and how a proposed or completed change affects that design.

The implementation is one process with deliberately boring boundaries. The CLI, REST API,
dashboard, and AnaxiMCP call the same application functions. Extraction adapters return
provider-neutral records; the scanner resolves those records into AnaxiIndex, a temporal SQLite
graph; architecture and agent services query that index.

```text
target Git repository (read-only)
             │
             ▼
  language / coverage / Git adapters
             │ deterministic facts + evidence
             ▼
      incremental scanner ───────── semantic planner / durable queue
             │                         │                    │
             │                         ▼                    ▼
             │               local Codex/Claude      connected coding agent
             │                   executor              through AnaxiMCP
             │                         │ dossiers + provenance │
             └──────────────┬──────────┴──────────────────────┘
                            ▼
                  AnaxiIndex (SQLite)
                       │          │
                       ▼          ▼
             architecture rules  guidance/impact
                       │          │
                       └────┬─────┘
                            ▼
              CLI / REST / dashboard / AnaxiMCP
```

Dependency direction inside the package is:

```text
dashboard → CLI / REST / MCP → application services
                                  ├→ analysis adapters → foundation contracts
                                  └→ index persistence → foundation contracts
```

Analysis and persistence are sibling layers and may not import each other. One shrinking legacy
edge from architecture evaluation to storage is recorded explicitly. The complete rationale,
module classification, and versioned analyzer contract are in
[`ADR 0001`](adr/0001-internal-layers-and-analyzer-ir.md); the corresponding import policy runs in
every commit and CI gate.

Goal-specific placement, reviewed-pattern, consolidation, dead-code, and verification evidence is
composed into the actor-neutral bounded guidance response. [`ADR 0002`](adr/0002-goal-specific-architecture-decisions.md)
defines the additive contract and the safety rules that keep facts, interpretations, and
recommendations distinct without creating another provider, persistence, or transport surface.
Its recommendation projections lead with ordinary-language conclusions, evidence, action,
cautions, and checks for both people and coding agents. Machine statuses and exact scores remain
queryable fields, but never substitute for that explanation or move into a jargon-only drawer.
That rule continues inside expandable evidence panels: opening a detail view must reveal a clearer
account of what was checked, what was found, how it affected the result, and what the number means.
Pattern-candidate signal and analyzer-coverage records therefore carry their own `plain_language`
projection beside the stable machine fields, so REST, MCP, CLI, and dashboard readers receive the
same explanation.
The same rule covers overall evidence readiness, preferred placement, change constraints, and
before/after verification. Even the smallest bounded guidance packet keeps the recommendation and placement
conclusions while compacting optional evidence and duplicate paths.
Raw semantic advisory fields remain in agent file summaries for compatibility, but a companion
explanation calls them early AI notes rather than instructions. It directs action to the
architecture packet, where the map checks those notes against repository evidence and explains its
recommendation. The dashboard Guide journey renders that packet directly; it does not add a human
approval stage.

The CLI has the same boundary discipline. `cli.py` is a stable facade, `cli_parser.py` assembles
command families, and focused modules own repository, semantic, agent-context, and server
handlers. `cli_services.py` is their dependency-composition root, so extracting handlers does not
multiply imports into config, scanner, storage, or API internals. First-run policy detection,
rendering, safe file application, client configuration, Docker start, local runtime, and doctor
checks likewise live in separate onboarding/application services rather than one initializer.

In multi-repository mode, an operator-owned YAML registry maps stable keys to read-only container
paths, per-repository policy files, and Git history sample budgets. One service and one SQLite
database hold all repositories, while every dashboard, REST, and MCP query remains repository
scoped. The web process can refresh registered targets but cannot add arbitrary filesystem paths.

The target repository is never imported or executed. Working-tree scanning reads regular,
non-symlink files; historical scanning uses `git ls-tree` and `git show` without checkout. The
SQLite database is external by default under the user's state directory.

Deterministic parser facts and probabilistic semantic claims never share a provenance record.
Relationship rows name their evidence source and confidence. Semantic rows name provider, model,
prompt version, time, confidence, and supporting evidence.

Current built-in analyzers emit `anaxigraph-ir-v2`. That contract records module identity and aliases,
symbol kind/signature/span/visibility, extracted references with evidence and confidence, explicit
exports, parse depth, analyzer version, resolver inputs, and the source form of each reference.
Python is AST-backed; JavaScript, JSX, TypeScript, and TSX are Tree-sitter-backed; other recognized
languages are explicitly fallback analysis today. Resolution outcomes remain separate relationship
facts: resolved, ambiguous, unresolved, external, or dynamic. Historical v1 facts remain readable
without being relabeled as v2 evidence.

Architecture placement exposes four precise views. The **declared map** is optional repository
intent, the **path map** is deterministic directory/package grouping, and the **inferred
responsibility map** is an AI-reviewed interpretation backed by current dossiers and relationships.
The default **current view** chooses declared placement per file, then inferred responsibility,
then path fallback. Stable group keys remain separate from display labels so a wording change does
not masquerade as a new architecture. Historical replay uses today's current-view frame by default
and preserves each file's original historical placement as separate evidence.

The path fallback has a small set of areas—application, testing, documentation, infrastructure, and developer tooling—and
places build metadata, containers, quality gates, agent integrations, scripts, tests, and examples
into narrower subsystems. It never promotes a root filename such as `pyproject.toml` or
`package.json` into an architecture area. Dependency lockfiles are ignored as generated resolution
records rather than presented as application modules. This keeps maps comparable across
repositories without pretending that a path heuristic is semantic understanding.

Module discovery has one query substrate. A rebuildable SQLite FTS5 projection indexes paths,
filenames, symbols, summaries, responsibilities, contracts, and normalized aliases for exactly one
repository snapshot. Dashboard, REST, CLI, AnaxiMCP, and architecture guidance call the same ranked query;
guidance expands through graph links only after those shared seeds are selected. Search provenance
states whether current semantic and responsibility evidence contributed. The projection is a
disposable read model over AnaxiIndex, not an architectural fact or a second database.

Every overview and graph response also carries `graph-quality-explanation-v1`. It translates those
machine states into the number of links checked, what failed to point to one file, which dependency,
impact, or deletion advice becomes incomplete, and what to do next. Plain-text and parsing limits
are described as missing code structure rather than “fallback analysis,” and runtime-only
connections remain an explicit blind spot. The dashboard renders this same response instead of a
separate technical warning.

Semantic enrollment has four phases: intrinsic module dossiers, contextual module dossiers, an
autonomous responsibility-taxonomy proposal plus independent AI critic/revision passes, then
taxonomy-shaped group synthesis and an `architecture-charter-v1` repository synthesis. The Living
Architecture Charter is the shared actor-neutral read model for purpose, actors, capabilities,
responsibilities, flows, public contracts, invariants, extension points, patterns, coherence
concerns, conflicts, unknowns, evidence, confidence, provenance, and freshness. Its embedded
Capability Brief deliberately describes behavior rather than the current module, framework,
storage, or internal-boundary shape. A static scan supplies a provisional Charter; a complete
agent-funded synthesis supplies the current one. Context carry-forward is per module: unaffected scopes
remain fully current while changed modules and their semantic neighbours wait. A deterministic
validator repairs duplicate, unknown, missing, and over-limit membership before the map becomes
current; it also matches nodes to the prior snapshot so unchanged responsibilities retain stable
identity. Structural hashes invalidate source-bound understanding; interface, relationship,
neighbour-intent, prompt, stage-contract, and taxonomy fingerprints invalidate only their
downstream work. Provider and model are execution provenance and never freshness inputs. SQLite
jobs carry priorities, attempts, token/cost estimates, and renewable worker leases, making the
pipeline resumable across process and coding-agent restarts.
Optional principal corrections are immutable `charter_correction` semantic documents. The shared
projection may present their declared wording, but retains the original inferred statement plus
author, time, and rationale. A correction is never a semantic-completion prerequisite and does not
create another architecture database, provider, or approval workflow.

Fresh-eyes review is a fixed consumer of that same semantic lifecycle, not another orchestration
platform. An explicit request creates `fresh_eyes` scope states and four existing-queue job kinds:
one to three implementation-blind proposals, blind adjudication, as-built comparison, and the final
mission filter. Stage packets and outputs use strict `fresh-eyes-*-v1` contracts. Proposal packets
contain the Capability Brief, public constraints, and a hashed information-boundary manifest; the
as-built system is introduced only after adjudication. Exact manifests remain attached to saved
jobs so the service can reject a packet whose evidence identity changed before submission. The two
repository-aware stages also carry the active corrections as bounded `declared_context`, each beside
the inferred claim it targets and marked `correct` or `refute`; a fingerprinted manifest entry makes
saving or withdrawing one re-run only comparison and mission filtering, and the review payload
reports which declared keys the saved review actually saw. Implementation-blind stages never
receive them.

Capability, reference, and comparison fingerprints are independent. An implementation-only change
may reuse proposal and adjudication documents across snapshots while rebuilding comparison and
mission filtering; a capability change invalidates the reference stages explicitly. The existing
lease, retry, provenance, token, document, and scope-state machinery owns interruption and resume.
There is no fresh-eyes table family, provider client, scheduler, configurable workflow DAG, or
automatic refactor path. `FreshEyesReviewService` is the shared read/start boundary used by REST,
CLI, dashboard, and the fresh-eyes mode of `ANAXIGRAPH_GUIDE`.

The status response adds `semantic-status-explanation-v1` over those machine states. It says
whether a worker is running now, whether saved work can finish by itself, how many included files
have current descriptions, which whole-map work or failures remain, and what action will resume it.
The API route recomputes that explanation after attaching the live worker state, so REST, MCP,
settings, and the dashboard cannot mistake a saved queue for an active process. For a connected
coding agent it also states that runtime model and reasoning effort are session choices, not
hardcoded parts of the saved understanding. Dashboard controls and polling use live leases, not the
raw count of rows formerly marked running, so an expired agent session remains resumable without
pretending that a worker still exists.

Historical reconstruction has a separate application-level job coordinator. Its outer
`history_import` record uses `analysis_runs` metadata for queued, enumerating, importing,
finalizing, complete, failed, and cancelled state; individual atomic frame scans remain ordinary
analysis runs. Progress and cancellation therefore survive browser sessions and process restarts,
while completed commit snapshots remain queryable throughout the import. CLI, REST, and dashboard
controls all delegate to this coordinator instead of maintaining transport-local job state.

The target-code boundary remains read-only. The normal `/mcp` profile exposes at most ten
architecture use cases: repository selection, Overview/Charter, readiness, search, file
explanation, guidance, impact, findings, selected-finding context, and optional refresh. Raw
history and semantic queue administration are not mixed into that menu.

A repository may explicitly select `semantic.provider: agent` to enable an index-only write path.
The official host executor uses the separate `/executor/mcp` transport to lease prepared work,
reason with the user's authenticated model and tokens, and store schema-validated interpretations
in AnaxiIndex. Opaque expiring lease tokens, repository/snapshot checks, strict validation, MCP
write annotations, and the repository allowlist bound that internal transport. An authenticated
local Codex or Claude CLI drives the queue in the background; AnaxiGraph itself holds no model API
key. Dashboard, CLI, REST, and normal MCP never implement their own queue semantics.

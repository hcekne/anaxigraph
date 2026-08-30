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
             │               provider-neutral       connected coding agent
             │                model adapters          through AnaxiMCP
             │                         │ dossiers + provenance │
             └──────────────┬──────────┴──────────────────────┘
                            ▼
                  AnaxiIndex (SQLite)
                       │          │
                       ▼          ▼
             architecture rules  agent scope/impact
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
composed into the existing bounded scope response. [`ADR 0002`](adr/0002-goal-specific-architecture-decisions.md)
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
before/after verification. Even the smallest bounded scope keeps the direct scope and placement
conclusions while compacting optional evidence and duplicate paths.
Raw semantic advisory fields remain in agent file summaries for compatibility, but a companion
explanation calls them early AI notes rather than instructions. It directs action to the
architecture packet, where the map checks those notes against repository evidence and explains its
recommendation. The dashboard Workbench renders that packet directly; it does not add a human
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

All built-in analyzers emit `anaxigraph-ir-v1`. That contract records module identity and aliases,
symbol kind/signature/span/visibility, extracted references with evidence and confidence, explicit
exports, parse depth, analyzer version, and resolver inputs. Python is AST-backed, JavaScript and
TypeScript are lexical, and other recognized languages are explicitly fallback analysis today.
Resolution outcomes remain separate relationship facts: resolved, ambiguous, unresolved, or
external.
Every overview and graph response also carries `graph-quality-explanation-v1`. It translates those
machine states into the number of links checked, what failed to point to one file, which dependency,
impact, or deletion advice becomes incomplete, and what to do next. Plain-text and parsing limits
are described as missing code structure rather than “fallback analysis,” and runtime-only
connections remain an explicit blind spot. The dashboard renders this same response instead of a
separate technical warning.

Semantic enrollment has four phases: intrinsic module dossiers, contextual module dossiers, an
autonomous responsibility-taxonomy proposal plus independent AI critic/revision passes, then
taxonomy-shaped group/repository synthesis. Context carry-forward is per module: unaffected scopes
remain fully current while changed modules and their semantic neighbours wait. A deterministic
validator repairs duplicate, unknown, missing, and over-limit membership before the map becomes
current; it also matches nodes to the prior snapshot so unchanged responsibilities retain stable
identity. Structural hashes invalidate source-bound understanding; interface, relationship,
neighbour-intent, prompt, stage-contract, and taxonomy fingerprints invalidate only their
downstream work. Provider and model are execution provenance and never freshness inputs. SQLite
jobs carry priorities, attempts, token/cost estimates, and renewable worker leases, making the
pipeline resumable across process and coding-agent restarts.
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
while completed commit snapshots remain queryable throughout the import. CLI, REST, dashboard, and
MCP controls all delegate to this coordinator instead of maintaining transport-local job state.

The target-code boundary remains read-only. Most AnaxiMCP tools only retrieve current dossiers and
use them in task-file ranking. A repository may explicitly select `semantic.provider: agent` to
enable an index-only write path: AnaxiMCP leases a prepared job, the connected coding agent reasons
with its own model and tokens, and SUBMIT writes a schema-validated interpretation to AnaxiIndex.
Opaque expiring lease tokens, repository/snapshot checks, strict dossier validation, MCP write
annotations, and the repository allowlist bound that path. Hosted and CLI providers remain a
separate executor option for unattended work.

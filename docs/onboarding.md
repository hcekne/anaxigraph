# Get started with AnaxiGraph

AnaxiGraph reads a repository without executing its code and builds a semantic graph of modules,
functions, interfaces, contracts and capabilities. The dashboard and AnaxiMCP read the same saved
graph. A local AnaxiIndex holds rebuildable indexes; the root `anaxigraph/` folder carries current
understanding and selected reviews through Git between machines.

```text
repository (read-only) ──→ facts read from code ──→ AnaxiIndex
                                                    ├── dashboard
                                                    └── AnaxiMCP ──→ coding agent
```

Run the service on the host with **uv** under the same account as your authenticated Codex or
Claude Code CLI. This is the recommended setup for dashboard workers and coding-agent integration.
The recommended AI-mapping mode needs no model key in AnaxiGraph. Codex or Claude Code uses its own
model context and token allowance to read a limited amount of evidence for each file and write a
checked, structured code description back to AnaxiIndex.

## Four steps to a working architecture partner

### 1. Start it

Install [`uv`](https://docs.astral.sh/uv/), open a shell in the repository you want to understand,
and run:

```bash
uvx anaxigraph up . --open --semantic agent --connect codex
```

Use `--connect claude` for Claude Code. For a code-only map without AI descriptions, omit
`--semantic agent --connect codex`.

For regular use, `uv tool install anaxigraph` installs the `anaxigraph` command in an isolated
environment. You can then use `anaxigraph up` and the CLI commands below directly. Otherwise,
prefix those commands with `uvx`. Update an installed tool with `uv tool upgrade anaxigraph`;
update a `uvx` run with `uvx --refresh anaxigraph up . --open --semantic agent --connect codex`.
Restart the service after updating. Install and authenticate the selected agent CLI before AI work.

The command creates an idempotent `.anaxigraph.yml`, stores AnaxiIndex outside the target
repository, scans the current checkout, and starts the loopback dashboard and MCP server. It loads
a compatible portable record when present. Detailed Git-history mapping is opt-in; ordinary scans
keep a bounded current map and comparison checkpoints. Stop it with Ctrl-C; completed work remains
available for the next run.

### 2. Open the dashboard

Visit <http://127.0.0.1:8765>. The current architecture is usable as soon as the first scan
completes. An explicitly requested history import can continue without blocking the other views.
Understand retains the sortable module table, including lines of code and function counts; expand
an entity to traverse callers, dependencies, interfaces, contracts and relevant tests. Read a module's
one-sentence overview first, then its short paragraph and individual function sentences as needed.

The first-run tour explains the main loop:

1. inspect the repository areas and file list;
2. review the short list of findings worth checking first rather than every saved observation;
3. plan only the findings you deliberately want an agent to act on; and
4. rescan after a change so measured findings can resolve or regress.

### Explore and run repository workflows

**Workflows**, the opening page, shows four interactive diagrams for the selected repository:

- **Mapping:** scan → compact graph annotations → contracts → responsibility proposal → map reviews →
  group summaries → Charter → exploration.
- **Pattern analysis:** saved graph and code evidence → whole-catalogue coverage → assessments →
  independent critiques → saved evaluations → exploration.
- **Fresh eyes:** functional brief → product/capability/subsystem hierarchy → three alternatives
  per scope → scoped trade-offs → review across levels → exploration. Every model pass remains
  blind to source and the existing implementation.
- **Architecture planning:** optional direction → Mapping and available reviews → architecture
  options → agent-selected target → current/target diagrams → migration milestones → agent work.
  Blank direction uses suggested defaults. A person can steer or select another option, but no
  human approval is required. Targets remain available across edits; milestone reports identify
  their scan and actual verification evidence.

Select any card to see its inputs, outputs, recorded models, usage and result links. File coverage
counts current saved annotations, including reuse. Model-job totals can include repeated work;
Pattern coverage counts catalogue cards, with separate considered, rated, reviewed and unresolved
totals. The shipped catalogue currently has 133 cards; every loaded card is considered rather than
only a preselected shortlist. Optional flows remain **Not run** until requested, and queued work is distinguished
from a live worker or an expired lease. Progress refreshes while this view is open.

With the `agent` provider, every model card shows **Next run** choices separately from saved
provenance. **Configure** lets you choose OpenAI/Codex or Anthropic/Claude, a model, reasoning effort
and workers. **Use suggested** restores the suggested rows; **Save settings** persists them for
this repository. Saving alone makes no model calls. **Save & run step** applies the choices and
runs that card; **Try 2 jobs** bounds a file or pattern sample to two jobs. A completed job is reused
even if you later change models. Start a new fresh-eyes generation to obtain new review results.

Graph annotations and pattern assessments distribute distinct jobs across the selected model
pools. Their worker counts add together, up to the repository limit. Map reviews run successive
passes in the displayed order, repeating the model list if more passes are required. Fresh eyes
assigns its three rows to three retained alternatives at each functional scope, with concurrency
capped by repository policy. The CLI also supports five alternatives. A single synthesis result
uses one worker. Cards also show live worker counts
by model when a lease is active. Suggested choices are starting points, not benchmark results.

Mapping step 5 saves each independent review batch as it finishes. Batches within a pass run in
parallel; configured OpenAI and Claude passes remain ordered. Progress shows completed/total
batches, active workers, elapsed time and a final reconciliation phase. An interrupted run reuses
successful batches and retries failed work. The worker queue refills available slots continuously.

Card settings take precedence over repository stage-model defaults for these dashboard runs;
usage limits, leases and saved provenance remain enforced. The CLI must be installed and logged in
as the user running the service. A configured non-agent provider retains the existing workflow
panel for mapping and patterns. Fresh eyes requires the agent provider.

The Docker image does not bundle coding-agent CLIs or credentials. Its diagrams remain readable,
and the run panel explains when no local executor is available; installing a CLI only on the
host does not make it available inside that container. Existing host-worker and MCP execution
still work as described below. A [persistent uv host service](advanced-operations.md#persistent-host-dashboard-with-uv)
can use the host's CLI logins directly. It starts separate noninteractive sessions; it does not send
commands into an existing chat. No task is reported as running merely because it was prepared.

Complete Mapping before starting pattern analysis or fresh eyes. Pattern analysis rates and
independently reviews the loaded catalogue against that graph. It does not change the compact
annotation contract. Fresh Eyes does not wait for Pattern review, and it never receives Pattern
judgments. Its passes run in separate sessions; the recorded
provenance shows whether different models or providers actually participated. You can start a
new review generation explicitly, or resume an unfinished one. A changed proposal count or pinned
provider assignment needs a new generation. **Run this step** completes missing prerequisites
and stops at the selected step. The main **Run full…** action completes the selected sequence
while reusing current results. Runs leave application source unchanged, save the shared
`anaxigraph/` record when writable, and retain completed results across page
reloads. Resume unfinished work after restarting the server. Settings live beside the index in
`<database filename>.workflows/`; include that directory in backups.

### 3. Start your coding agent in the same repository

The explicit `--connect codex` or `--connect claude` option writes the local MCP connection for the
selected client. Restart that client after first-time setup, then launch it from the repository it
will edit:

```bash
cd /path/to/your/repository
codex
```

AnaxiGraph itself remains a read-only observer of repository source. Most MCP tools only read
AnaxiIndex; semantic work and an explicitly enabled scan can update the external index, never the
target code.

### 4. Ask the agent to build or resume understanding

Use this sentence in the coding-agent chat:

> Use AnaxiGraph to build or resume the AI-created code map for this repository. Choose an
> explicit economical worker model, start or reuse the background run, and return its run ID.
> Let the worker manage the queue. Check compact progress when I ask; do not supervise it in an
> LLM loop or edit source while mapping.

Codex processes the saved AI task list from one background host command:

```bash
anaxigraph understand . --executor codex --model '<worker-model>' --parallel-jobs 4 --background --json
anaxigraph semantic-status . --compact --json
```

Replace `<worker-model>` with your chosen Codex model; for Claude Haiku workers, use
`--executor claude --model haiku`. Choose the worker model explicitly to avoid inheriting an
expensive CLI default. The caller's conversation is not sent to workers. The repository's
`max_parallel_jobs` must allow the requested concurrency; all executors share that total ceiling.
Inside a Codex session the default `--executor auto` selects the authenticated Codex CLI.
Both executors also accept an explicit `--reasoning-effort` for this run.
`--background` starts a host
worker that continues after the invoking coding-agent session exits; `semantic-status` reports its
run ID, log, heartbeat, index authority, progress, and terminal state; full status also includes
process and configuration details. `already_running` means reuse the existing run. Return its
handle and let ordinary software manage scheduling and retries. Read compact status on request or
no more often than every five minutes; never infer failure from a missing `anaxigraph understand`
process or create an LLM supervision loop. A `stalled` run
can be relaunched with the same command and resumes saved completed work. Use direct MCP work only
as a one-task-at-a-time fallback when no authenticated host worker exists;
`agent_action_required` means the connected agent must keep working and is not completion.

Each worker claims one task for a limited time and reads bounded evidence. Module annotation
returns one overview sentence, a short detail paragraph (normally 40–80 words), one behavior sentence
per supplied function, named caller contracts, capabilities, evidence and confidence. Contracts
record obligations once and link the functions they govern; there are no paired intrinsic/context
essays. Confirmed output truncation can receive one configured retry with more room, with both calls
counted. Pattern and Fresh Eyes reviews are optional workflows. Mapping continues through an
inferred responsibility grouping of
files, separate AI checks and revisions, and the whole-repository Living Architecture Charter. The
Charter explains purpose, observable capabilities, responsibilities, flows, contracts, invariants,
extension points, patterns, coherence concerns, conflicts, and unknowns. Its Capability Brief
describes required behavior without leaking the current implementation shape. Code checks give every
included file exactly one main smaller group. No person has to approve this metadata map. Unchanged
code, direct links, instructions, and intended job reuse current records; worker and model names
record who created the result but do not decide whether it is stale.

If a matching loopback dashboard/sidecar is live, the command verifies the exact checkout and uses
its saved MCP task list and persistent AnaxiIndex. Container path aliases must also match Git and
working tree identity; the same remote alone is insufficient. Linked worktrees remain distinct.
Container paths therefore do not create a second host-local baseline. A refused connection or a reachable service with no matching
repository selects the same per-checkout user-state database as `anaxigraph up`; a timeout or
invalid inventory fails closed because the sidecar may be busy. Use `--service-url` or
`ANAXIGRAPH_SERVICE_URL` for a non-default endpoint; use `--db` only when you intentionally want a
standalone local index. The JSON response always names the selected index authority.

When `ANAXIGRAPH_SEMANTIC_STATUS` reports ready, read the responsibility map in
`ANAXIGRAPH_OVERVIEW` or select **Responsibility map** in the dashboard. **Current view** uses declared project intent first, then
that inferred responsibility map, then deterministic path fallback. **Declared map** and **Path
map** remain available for honest comparison.

`anaxigraph charter .` returns the same current Charter that Overview and
`ANAXIGRAPH_OVERVIEW` expose. Before AI mapping finishes it is explicitly provisional; after code
changes an older AI result is explicitly stale. A person may add optional declared context without
making it a prerequisite or deleting the inferred claim:

```bash
anaxigraph charter . --correct-section purpose \
  --statement "The intended product outcome in ordinary language." \
  --author "repository owner" \
  --rationale "The outcome is not fully inferable from code."
```

Use the same target with `--withdraw` to stop presenting that overlay. Add `--refute` instead of a
`--statement` to declare an inferred claim a known non-issue: the claim stays visible and keeps its
evidence, marked as a declared non-issue with the rationale beside it. Only the newest declared
context per section and key applies, so a refutation and a reworded statement never coexist on one
claim. Corrections live only in the external AnaxiIndex and retain author, time, rationale, and the
original inference. Behavioral purpose/capability corrections can inform the sanitized functional
brief. Source-specific declared context belongs to Architecture Planning and source-aware guidance;
it is never passed into Fresh Eyes as implementation detail. Compatible blind alternatives remain
reusable until their functional requirements change.

## Recommended: install the agent workflow

The repository ships one shared skill for Codex and Claude Code. It teaches the client repository
selection, AI-task resume/release behavior, focused file and affected-caller analysis, finding handoff,
and post-change verification.

For Codex:

```bash
codex plugin marketplace add hcekne/anaxigraph && \
  codex plugin add anaxigraph@anaxigraph
```

Invoke `$anaxigraph` after restarting Codex. For Claude Code:

```bash
claude plugin marketplace add hcekne/anaxigraph && \
  claude plugin install anaxigraph@anaxigraph --scope user
```

Invoke `/anaxigraph:anaxigraph`. The plugin already includes the default loopback MCP definition,
so a plugin user may start AnaxiGraph with `uvx anaxigraph up . --semantic agent` and omit the
`--connect` option. See the [agent plugin guide](agent-plugin.md) for custom endpoints and the exact
safety contract.

## Prefer Docker?

Use the durable, isolated sidecar path from the target repository:

```bash
uvx anaxigraph init . --start --semantic agent --connect codex
```

Use `--connect claude` for Claude Code. This generates `.anaxigraph.yml` and
`compose.anaxigraph.yml`, mounts the repository read-only, persists AnaxiIndex in a named volume,
and publishes the service only on loopback by default. Repeating the initializer does not replace
unrelated policy or client settings.

To inspect all changes before writing or starting anything:

```bash
uvx anaxigraph init . --start --semantic agent --connect codex --dry-run --json
```

See [Docker operation](docker.md) for container lifecycle and the generated security controls.

## Use one coding loop

Keep one persistent AnaxiGraph service running for the whole coding session. It supervises the
structural watcher in the same lifecycle, so no companion container is required. Build the complete
AI map once when no current baseline exists. Saving a file refreshes cheap source facts; it does not
start another model-backed repository pass.

Give the connected agent one concrete goal:

> Use AnaxiGraph to guide “add saved prompt exports.” Find the smallest relevant file set, tell me
> where the code belongs, inspect what depends on shared files, identify focused checks, and refresh
> the shared map after implementation.

The agent should follow this sequence for a feature, fix, or refactor:

1. **Guide.** Call `ANAXIGRAPH_GUIDE` with `intent="build"` or `intent="improve"`. Use
   `intent="understand"` when you first need the system map. Read its one
   recommendation, evidence strength, counter-reasons, small file list, placement, bounded impact,
   likely tests, relevant findings, and reviewed patterns.
2. **Impact.** Call `ANAXIGRAPH_IMPACT` for shared files that may change. Inspect direct dependants
   and tests; a missing static edge is not proof that code is unused because dynamic wiring may be
   invisible.
3. **Change.** Edit source and run focused tests through the normal coding workflow. AnaxiGraph
   observes repository source and updates its external index; it does not edit the target code.
4. **Refresh and reassess.** Request `ANAXIGRAPH_SCAN(refresh_semantics=true)`, finish any prepared
   semantic work, then call `ANAXIGRAPH_GUIDE(intent="reassess")`. It compares the latest compatible
   saved maps and returns the
   observed change, consequence, calibrated recommendation, counter-evidence, reasons to leave the
   code alone, and the smallest safe follow-up and verification. It does not create an approval,
   plan, or change-management record. A person sees the same result under **Changes**; the CLI form
   is `anaxigraph reassess .`.
   Use History when the decision needs wider introduction, recurrence, churn, or co-change context.

At the end of a coherent task or commit, run
`anaxigraph understand . --executor codex --background` if the changed AI descriptions matter.
It refreshes only stale changed and affected scopes and reuses unchanged descriptions. Structural
reassessment is available first; ask for reassessment again after `semantically_ready` when the
next decision needs current responsibility, duplication, pattern, or possible-unused-code evidence.

Use the returned telemetry to tune the loop: guidance and impact replies report server time, payload
size, and model-token use; semantic status groups AI work by action with current-snapshot and
lifetime time/token totals; scan results and detached semantic runs report wall-clock duration.
Successful and failed attempts contribute tokens when the executor reports them. Missing reports
still mean unknown usage, not a free call.

A changed metric or finding is not automatically an improvement. Expected behavior, focused tests,
and architecture evidence must agree.

The comparison says what changed in the bounded file, finding, and reviewed-pattern evidence. It
does not call a difference an improvement unless the expected outcome and tests support that
conclusion. Findings and pattern evaluations below explain optional evidence inside this same loop;
they are not separate planning products.

Each reviewed pattern inside the decision packet retains its concise conclusion, observations,
reason, proposed action, caution, verification, and independent-review summary. A shared reading
guide explains suitability, conformance, opportunity, and confidence once, so an agent can use the
ratings without treating them as code-quality grades or permission to refactor.

## Run a fresh-eyes architecture review

Use this optional workflow when you want to challenge the current architecture from first
principles, not for every feature or ordinary refactor. It requires `semantic.provider: agent` and
a current or resumable AI-created repository understanding.

```bash
anaxigraph fresh-eyes . --start --proposals 3
anaxigraph understand . --executor codex --background
anaxigraph semantic-status . --compact --json
anaxigraph fresh-eyes .
```

Use `--executor claude` when that is the authenticated host agent. The background executor first
finishes any missing baseline understanding and then advances the durable review stages. It can be
stopped and resumed without discarding completed alternatives. Three alternatives per reviewed
functional scope are the default; `--proposals 5` explores five. Keep all options and read their
trade-offs rather than reducing the result to one reference design.

With a running service, `--start` and `--restart` wait up to 120 seconds for the service to accept
the request, longer than the index's busy window; pass `--timeout-seconds` to wait longer. A start
that times out reports that the service may still be planning; read `anaxigraph fresh-eyes .`
before requesting it again instead of repeating `--restart`.

### Two providers in one review

Cross-provider review means two host worker processes on the same durable review. Name the executor
family for each proposal slot when you start the review, then start one background worker per
executor; a repository owns one background run slot per executor, so both survive the session:

```bash
anaxigraph fresh-eyes . --start --proposals 3 --proposal-executors codex,claude,any
anaxigraph understand . --executor codex --background
anaxigraph understand . --executor claude --background
anaxigraph semantic-status . --compact --json
```

`semantic-status` lists one `execution_runs` entry per executor; full status also keeps
`execution_run` as the most relevant single record. Both workers only claim at the same time when
`semantic.max_parallel_jobs` is 2 or more; with a limit of 1 they take the pinned slots one after
the other. Use `any` for a slot any executor may take, for example
`--proposal-executors codex,any,any`.

The Fresh Eyes workflow's saved model rows control proposal executor assignments. The CLI, REST
body and `ANAXIGRAPH_GUIDE` also accept explicit assignments.

A pinned slot is handed only to the executor family that the plan names, derived from the worker's
`cli:<family>:<pid>` identity; a connected agent that is not a host worker can name its family with
`executor_family` on `ANAXIGRAPH_SEMANTIC_WORK`. A worker that finds only the other executor's slot
is told `waiting_for_executor`, with the reserved scope keys and the exact command that starts the
missing executor, and keeps polling instead of reporting the queue complete. Assignments are
recorded when the review is planned, so they apply to a new review or to a `--restart` generation
and never rewrite a review already under way.

If the second executor is never started, release the assignments rather than leaving the review
half-pinned: `anaxigraph fresh-eyes . --unpin`, `POST /api/fresh-eyes {"unpin": true}`, or
`ANAXIGRAPH_GUIDE(intent="redesign", unpin=true)` drops every pin from the plan and from the queued
proposal jobs, so any executor can finish the review. `--restart` stays refused while a review is
unfinished.

The review reports `diversity.cross_provider: true` only when two different executor families
actually produced the proposals. Two sessions of one provider report `false` and keep the caveat
that different recorded executors support diversity but cannot prove external model context.

The fixed sequence is:

1. project the Charter's purpose and observable capabilities into a sanitized functional brief;
2. describe product, capability and functional-subsystem scopes without guessing existing modules;
3. retain three alternatives for each scope, including proposed interfaces, control flow, data
   ownership, failure boundaries, pros, cons and parent-option compatibility;
4. compare every retained option for that scope and report convergence or unexplored directions
   honestly; and
5. review composition across levels while preserving the alternatives.

Every model-backed phase is implementation-blind: no source, paths, current topology,
frameworks, Pattern judgments, repository tools or inherited conversation. Native workers request
fresh restricted contexts; external execution isolation remains labelled **unverified**. Different
graph shapes or provider names alone do not prove novel or independent ideas.

Read the shared result in **Improve → Fresh eyes**, from `anaxigraph fresh-eyes .`, or through
`ANAXIGRAPH_GUIDE` with `intent="redesign"`. Set `start=true` and `proposal_count=3` to request it.
Expand a selected scope using `anaxigraph fresh-eyes . --scope <scope-id>`,
`GET /api/fresh-eyes?scope_id=<scope-id>&details=true`, or
`ANAXIGRAPH_GUIDE(intent="redesign", scope_id="<scope-id>", details=true)`.
Default replies summarize other scopes. Use **Architecture Planning** afterward for the separate
source-aware comparison, target choice and migration plan. Direction can be blank: the agent
provides useful defaults and selects a target without requiring a user decision. Saved slots,
proposal agreement and missing proposed components are never permission to delete code.

Every review and Charter also names the checkout it was read from: the commit, the branch, whether
that checkout was dirty, and a `working_tree_fingerprint` over the uncommitted content. A result
produced from a dirty checkout leads with a provenance caveat because its mapping cannot be
reproduced from that commit alone. Fresh Eyes separately records the immutable functional-brief
revision that its workers actually received. An implementation-only change can reuse compatible
functional alternatives; different functional requirements need a new generation.

To repeat all five stages with a deliberately selected model, use `fresh-eyes --restart`, or
`ANAXIGRAPH_GUIDE(intent="redesign", start=true, restart=true)` from a connected agent, and then
start the semantic executor with explicit `--model` and `--reasoning-effort` values. This creates a
new auditable review generation without rereading unchanged module annotations. Merely changing the
runtime model does not make saved understanding stale.

Every review reply lists the recorded generations under `generations`, each with its snapshot,
state, executor models, retained alternative counts, and a per-stage telemetry block:
`duration_ms` measured from the claim, `output_bytes` of the stored document, reported token counts
with a plausibility check against the packet the planner estimated, and `attempts_observed`. Treat
`attempts_observed` as a floor rather than a retry count: a released lease decrements the counter
and an explicit retry resets it to zero. The same telemetry appears on the stage cards in
**Improve → Fresh eyes**.

To read an earlier generation in full, add `--generation 2` to `anaxigraph fresh-eyes .`, request
`GET /api/fresh-eyes?generation=2`, or call `ANAXIGRAPH_GUIDE(intent="redesign", generation=2)`; the
dashboard offers the same choice as a selector beside the review heading. A recorded generation
reports `state: superseded` with `ready: false` and cannot be started, retried, or restarted. An
unrecorded number is refused with the list of generations that exist.

## Understand findings

The **Improve → Findings** view opens on at most 20 findings worth checking first. It suppresses routine
long-function notes unless repository policy opts in. **Complete record** keeps every observation
and supports filters and pagination.

- **Mark reviewed** records that someone inspected an active condition.
- **Plan agent work** selects the finding and prepares a coding handoff.
- **Accept risk** retains monitoring without occupying normal attention.
- **Not actionable** dismisses the current condition.
- **Resolved** and **regressed** are normally determined by later scans, not by a button.

Every finding directly explains what AnaxiGraph saw, why it may matter, what to do, when the code
may be fine as it is, and how to check the result. The exact detector and ranking fields remain
available to tools, but they are not a substitute for that explanation. The coding handoff also
uses retained code maps to say when the condition first appears, disappears, or returns. It says
when older frames lack that evidence and never pretends that sampled frames cover every commit.

## Understand pattern evaluations

The **Patterns** page contains only evaluations that completed an independent agent critique. Each
result states its conclusion, what AnaxiGraph saw, why the pattern may matter, the smallest sensible
action, reasons not to change the code, and how to verify any change. The API, MCP tool, CLI, and
dashboard share the same `pattern-explanation-v2` record.

The nine ratings are still separate and queryable, but the page groups them into five questions:
does the problem exist and does the pattern fit, how much of the pattern already exists, would a
change help now, how difficult would the change be, and how strong is the evidence? The exact
0–100 values remain beside those explanations for tools and comparisons; they are not grades for
the code.

The catalogue contains 133 cards today and expands when patterns are added. Every loaded card
receives contextual consideration, ratings, pros, cons and an independent review; a concrete defect
is not required before an architectural opportunity can be explored. Candidate ranking can guide
where to inspect or apply a card, but cannot silently remove cards from whole-catalogue coverage.
Considered, rated, reviewed and unresolved counts are separate, and filtered pages retain global
totals. An unresolved evidence gap is visible rather than being reported as no useful pattern.

## Check the setup

Run the end-to-end environment check when the dashboard or agent connection is unclear:

```bash
anaxigraph doctor /path/to/your/repository \
  --service-url http://127.0.0.1:8765 \
  --client codex \
  --mcp-url http://127.0.0.1:8765/mcp \
  --json
```

Change `--client` to `claude` where appropriate. The report checks repository readability, state
writeability, index integrity, service health, a real MCP initialization exchange, and the
selected client entry.

## Platform and security boundary

Linux x86-64 is release-gated. Linux ARM64, macOS, and WSL2 are best effort; Docker Desktop is the
recommended macOS path. Native Windows is not supported—use WSL2. See the
[platform matrix](platform-support.md) for exact support levels.

The current service is a local sidecar. Keep it on loopback or behind a trusted SSH tunnel. Do not
publish port 8765 to an untrusted network.

## Advanced operation

The first path above is intentionally narrow. Continue with
[Advanced operation](advanced-operations.md) for:

- local Codex/Claude/custom executors and durable background runs;
- semantic privacy, budget, scheduling, and invalidation controls;
- manual Compose review, custom state paths, ports, and endpoints;
- remote servers and SSH forwarding;
- optional coverage reports;
- history jobs, watchers, upgrades, backup diagnostics, and resets; and
- isolated sidecars or the experimental multi-repository registry.

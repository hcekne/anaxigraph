# Get started with AnaxiGraph

AnaxiGraph runs beside a repository, scans it without executing its code, and stores architecture
facts in an external AnaxiIndex. The dashboard gives you the human view; AnaxiMCP gives your coding
agent the same evidence.

```text
repository (read-only) ──→ facts read from code ──→ AnaxiIndex
                                                    ├── dashboard
                                                    └── AnaxiMCP ──→ coding agent
```

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

The command creates an idempotent `.anaxigraph.yml`, stores AnaxiIndex outside the target
repository, scans the current checkout, starts the loopback dashboard and MCP server, and imports
representative Git history in the background. Stop it with Ctrl-C; the index and completed history
frames remain available for the next run.

### 2. Open the dashboard

Visit <http://127.0.0.1:8765>. The current architecture is usable as soon as the first scan
completes; history can continue building without blocking the Understand, Guide, Improve, Changes,
or Settings journeys.

The first-run tour explains the main loop:

1. inspect the repository areas and file list;
2. review the short list of findings worth checking first rather than every saved observation;
3. plan only the findings you deliberately want an agent to act on; and
4. rescan after a change so measured findings can resolve or regress.

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

> Use AnaxiGraph to build or resume the AI-created code map for this repository, using your own
> model context and tokens. Start the background coding-agent worker, do not edit source while
> mapping, and monitor it until the status says the map is up to date.

Codex processes the saved AI task list from one background host command:

```bash
anaxigraph understand . --executor codex --background
anaxigraph semantic-status .
```

Inside a Codex session the default `--executor auto` selects the authenticated Codex CLI. The
command deliberately omits a model so Codex can use its currently supported configured default.
Use `--model` and `--reasoning-effort` only when you explicitly select them for this run; both the
Codex and Claude executors accept the effort value.
`--background` starts a host
worker that continues after the invoking coding-agent session exits; `semantic-status` reports its
PID, log, heartbeat, exact index/config authority, progress, and terminal state. A `stalled` run
can be relaunched with the same command and resumes saved completed work. Use direct MCP work only
as a one-task-at-a-time fallback when no authenticated host worker exists;
`agent_action_required` means the connected agent must keep working and is not completion.

Each worker claims one task for a limited time, reads its evidence, and submits a result that must
match the required JSON shape. It continues through file descriptions, an inferred responsibility grouping of
files, separate AI checks and revisions, and the whole-repository Living Architecture Charter. The
Charter explains purpose, observable capabilities, responsibilities, flows, contracts, invariants,
extension points, patterns, coherence concerns, conflicts, and unknowns. Its Capability Brief
describes required behavior without leaking the current implementation shape. Code checks give every
included file exactly one main smaller group. No person has to approve this metadata map. Unchanged
code, direct links, instructions, and intended job reuse current records; worker and model names
record who created the result but do not decide whether it is stale.

If a matching loopback dashboard/sidecar is live, the command identifies it from the checkout's
Git remote and uses its saved MCP task list and persistent AnaxiIndex. Container paths therefore do not
create a second host-local baseline. A refused connection or a reachable service with no matching
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

Use the same target with `--withdraw` to stop presenting that overlay. Corrections live only in the
external AnaxiIndex and retain author, time, rationale, and the original inference.

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
anaxigraph fresh-eyes . --start --proposals 2
anaxigraph understand . --executor codex --background
anaxigraph semantic-status .
anaxigraph fresh-eyes .
```

Use `--executor claude` when that is the authenticated host agent. The background executor first
finishes any missing baseline understanding and then advances the durable review stages. It can be
stopped and resumed without discarding completed proposals. `--proposals 1` reduces cost;
`--proposals 2` is the recommended default; `--proposals 3` adds another independent view.

With a running service, `--start` and `--restart` wait up to 120 seconds for the service to accept
the request, longer than the index's busy window; pass `--timeout-seconds` to wait longer. A start
that times out reports that the service may still be planning; read `anaxigraph fresh-eyes .`
before requesting it again instead of repeating `--restart`.

One repository owns one background run, so a second `--background` launch with a different executor
is refused and names the foreground alternative,
`anaxigraph understand . --executor claude --until-complete`. Cross-provider review therefore means
two host worker processes, and both only claim work when `semantic.max_parallel_jobs` is 2 or more.

The fixed sequence is:

1. reuse the Charter's implementation-blind Capability Brief;
2. produce isolated clean-sheet proposals without current paths, frameworks, map, findings, or
   history;
3. adjudicate those proposals without seeing the current implementation;
4. compare the reference design with the current Charter, map, dossiers, graph, patterns,
   findings, and history; and
5. filter the differences against mission, compatibility, operational simplicity, migration cost,
   reversibility, and verification cost.

Read the shared result in **Improve → Fresh eyes**, from `anaxigraph fresh-eyes .`, or through
`ANAXIGRAPH_GUIDE` with `intent="redesign"`. Set `start=true` and `proposal_count=2` in that MCP call
to request the review. Only the final mission-filtered recommendations are advice; partial stages,
proposal agreement, and absent clean-sheet components are never permission to rewrite or delete
code. AnaxiGraph records the actual provider/model/executor identity and says explicitly when two
proposals are independent sessions of one provider rather than cross-provider agreement.

To repeat all five stages with a deliberately selected model, use `fresh-eyes --restart`, or
`ANAXIGRAPH_GUIDE(intent="redesign", start=true, restart=true)` from a connected agent, and then
start the semantic executor with explicit `--model` and `--reasoning-effort` values. This creates a
new auditable review generation without rereading unchanged module dossiers. Merely changing the
runtime model does not make saved understanding stale.

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

Candidate explanations use the same rule. They say why AnaxiGraph considered one pattern/target
pair, why it was or was not selected for the limited set of AI checks, what evidence matched, what
the code readers could not check, and what happens next. The internal selection order only limits agent work;
it is not a pattern rating or advice to refactor.

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

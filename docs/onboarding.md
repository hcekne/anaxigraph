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
completes; history can continue building without blocking the Overview, Modules, Graph, or
Architecture pages.

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
Use `--model` and `--reasoning-effort` only when you explicitly select them for this run.
`--background` starts a host
worker that continues after the invoking coding-agent session exits; `semantic-status` reports its
PID, log, heartbeat, exact index/config authority, progress, and terminal state. A `stalled` run
can be relaunched with the same command and resumes saved completed work. Use direct MCP work only
as a one-task-at-a-time fallback when no authenticated host worker exists;
`agent_action_required` means the connected agent must keep working and is not completion.

Each worker claims one task for a limited time, reads its evidence, and submits a result that must
match the required JSON shape. It continues through file descriptions, an inferred responsibility grouping of
files, separate AI checks and revisions, and a whole-repository summary. Code checks give every
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

When `ANAXIGRAPH_SEMANTIC_STATUS` reports ready, call `ANAXIGRAPH_TAXONOMY` or select
**Responsibility map** in the dashboard. **Current view** uses declared project intent first, then
that inferred responsibility map, then deterministic path fallback. **Declared map** and **Path
map** remain available for honest comparison.

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

1. **Scope.** Call `ANAXIGRAPH_SCOPE`. Read the small file list and its
   `architecture-decision-v1` placement, boundaries, likely tests, relevant findings, and reviewed
   patterns.
2. **Impact.** Call `ANAXIGRAPH_IMPACT` for shared files that may change. Inspect direct dependants
   and tests; a missing static edge is not proof that code is unused because dynamic wiring may be
   invisible.
3. **Change.** Edit source and run focused tests through the normal coding workflow. AnaxiGraph
   observes repository source and updates its external index; it does not edit the target code.
4. **Refresh.** Request `ANAXIGRAPH_SCAN`. Repeat scope or impact when responsibilities or
   dependencies may have moved, and use History and findings when you need change evidence.

At the end of a coherent task or commit, run
`anaxigraph understand . --executor codex --background` if the changed AI descriptions matter.
It refreshes stale scopes and reuses unchanged descriptions. Structural facts are available first;
wait for `semantically_ready` only when the next decision needs a completely current AI map.

Use the returned telemetry to tune the loop: scope and impact replies report server time, payload
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

## Understand findings

The Architecture page opens on at most 20 findings worth checking first. It suppresses routine
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

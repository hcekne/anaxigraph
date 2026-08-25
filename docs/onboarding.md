# Get started with AnaxiGraph

AnaxiGraph runs beside a repository, scans it without executing its code, and stores architecture
facts in an external AnaxiIndex. The dashboard gives you the human view; AnaxiMCP gives your coding
agent the same evidence.

```text
repository (read-only) ──→ deterministic scan ──→ AnaxiIndex
                                                    ├── dashboard
                                                    └── AnaxiMCP ──→ coding agent
```

The recommended semantic mode needs no model key in AnaxiGraph. Codex or Claude Code uses its own
model context and token allowance to read bounded module evidence and write validated semantic
dossiers back to AnaxiIndex.

## Four steps to a working architecture partner

### 1. Start it

Install [`uv`](https://docs.astral.sh/uv/), open a shell in the repository you want to understand,
and run:

```bash
uvx anaxigraph up . --open --semantic agent --connect codex
```

Use `--connect claude` for Claude Code. For a deterministic map without AI understanding, omit
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

1. inspect the architecture and module ledger;
2. review the bounded attention queue rather than every diagnostic at once;
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

> Use AnaxiGraph to build or resume the semantic baseline for this repository, using your own
> model context and tokens. Launch the durable host executor, do not edit source while mapping,
> and monitor it until semantic status reports ready.

Codex drives the durable queue from one detached host command:

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
can be relaunched with the same command and resumes durable completed work. Use direct MCP work only
as a bounded fallback when no authenticated host executor exists; MCP mode returns
`agent_action_required` and is not completion.

Each worker leases bounded evidence, submits a schema-validated dossier or map artifact, and
continues through module context, taxonomy proposal, independent critic/revision passes, and
repository synthesis. Deterministic validation gives every eligible module exactly one primary
subsystem. No person has to approve this metadata map. Unchanged structural, relationship,
prompt-contract, and intent fingerprints reuse current records; executor and model names are
provenance and do not participate in freshness.

If a matching loopback dashboard/sidecar is live, the command identifies it from the checkout's
Git remote and uses its MCP queue and persistent AnaxiIndex. Container paths therefore do not
create a second host-local baseline. A refused connection or a reachable service with no matching
repository selects the same per-checkout user-state database as `anaxigraph up`; a timeout or
invalid inventory fails closed because the sidecar may be busy. Use `--service-url` or
`ANAXIGRAPH_SERVICE_URL` for a non-default endpoint; use `--db` only when you intentionally want a
standalone local index. The JSON response always names the selected index authority.

When `ANAXIGRAPH_SEMANTIC_STATUS` reports ready, call `ANAXIGRAPH_TAXONOMY` or select **Semantic
map (AI)** in the dashboard. Configured policy and deterministic path inference remain available as
comparison layers; they do not override the semantic default when a current taxonomy exists.

## Recommended: install the agent workflow

The repository ships one shared skill for Codex and Claude Code. It teaches the client repository
selection, semantic resume/release behavior, bounded scope and impact analysis, finding handoff,
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

## Use AnaxiGraph during normal coding

Ask the connected agent to use AnaxiGraph before and after meaningful changes:

- “Map this repository and explain its major boundaries.”
- “Find the smallest safe scope for adding saved prompt exports.”
- “Show the reverse-dependency impact of changing `backend/app/services/chat.py`.”
- “Explain the highest-priority planned architecture finding and prepare a verification plan.”
- “Compare these provider modules for repeated responsibilities and pattern opportunities.”
- “Rescan and verify whether this change improved the relevant architecture evidence.”

The agent should use `ANAXIGRAPH_SCOPE` for a bounded work envelope and its
`architecture-decision-v1` placement, reviewed patterns, constraints, safety advice, and
post-change baseline. After implementation, keep the goal text unchanged, rescan, and pass
`architecture_decision.verification.post_change_baseline` back as `verification_baseline` in the
next scope request. AnaxiGraph then reports exactly which tracked module, finding, and reviewed
pattern facts changed. It deliberately does not call a difference an improvement without the
expected outcome and passing tests. Use `ANAXIGRAPH_IMPACT` for blast radius and a planned finding's
context for approved architecture work. A missing static edge is not proof that code is unused;
dynamic runtime wiring remains an explicit blind spot.

## Understand findings

The Architecture page opens on at most 20 ranked attention items. It suppresses routine
information-level long-function noise unless repository policy opts in. **All diagnostics** keeps
the complete evidence ledger and supports filters and pagination.

- **Mark reviewed** records that someone inspected an active condition.
- **Plan agent work** is explicit approval to prepare a coding handoff.
- **Accept risk** retains monitoring without occupying normal attention.
- **Not actionable** dismisses the current condition.
- **Resolved** and **regressed** are normally determined by later scans, not by a button.

Every finding includes ranking reasons, evidence, plausible false-positive conditions, affected
areas, the smallest next action, and a scan-based verification rule.

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

- hosted OpenAI/Anthropic workers and local Codex/Claude/custom workers;
- semantic privacy, budget, scheduling, and invalidation controls;
- manual Compose review, custom state paths, ports, and endpoints;
- remote servers and SSH forwarding;
- optional coverage reports;
- history jobs, watchers, upgrades, backup diagnostics, and resets; and
- isolated sidecars or the experimental multi-repository registry.

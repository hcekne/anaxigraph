# Get started with AnaxiGraph

AnaxiGraph is designed to run **beside** the repository you are working in:

```text
your repository (read-only) ──→ scanner ──→ AnaxiIndex
                                              ├── dashboard for people
                                              └── AnaxiMCP for coding agents
```

The scanner reads source and Git metadata. AnaxiIndex persists the resulting modules,
relationships, metrics, findings, and history outside the repository. The dashboard and MCP
server are two views of that same evidence. AnaxiGraph does not execute the target project and
does not edit its code.

Model-backed understanding is optional and explicit. It can be executed by the coding agent
already connected through AnaxiMCP, using that agent's own model and tokens, or by a separately
configured model worker. Both paths write versioned interpretations to AnaxiIndex and never
replace deterministic parser facts.

## Check your platform

Linux x86-64 with Docker or the local CLI is supported and release-gated. Linux ARM64, macOS on
Apple silicon or Intel, and WSL2 are currently best effort; Docker Desktop is the recommended
macOS path. Native Windows and Windows containers are not supported yet—use a WSL2 Linux
distribution and keep repositories in its Linux filesystem. See the complete
[platform-support matrix](platform-support.md) before reporting an install-specific issue.

## Fastest path: local loopback runtime

You need Git, Python 3.11+, and [`uv`](https://docs.astral.sh/uv/). Run this from the repository you
want to understand:

```bash
uvx anaxigraph up . --open --semantic agent --connect codex
```

Use `--connect claude` for Claude Code. Omit `--semantic` and `--connect` when you want only the
deterministic dashboard. The command:

- creates or loads `.anaxigraph.yml` without replacing an existing policy;
- keeps a stable per-checkout AnaxiIndex outside the repository in OS user state;
- scans the current checkout before the service becomes healthy;
- imports adaptive Git-history frames in the background;
- serves the dashboard and AnaxiMCP on loopback only;
- permits the connected local agent to request an index-only refresh; and
- prints exact stop and idempotent restart instructions.

The default state root is `$XDG_STATE_HOME/anaxigraph` or `~/.local/state/anaxigraph` on Linux and
`~/Library/Application Support/AnaxiGraph` on macOS. Override the root with
`ANAXIGRAPH_STATE_HOME` or one index with `--db`. Ctrl-C shuts down the HTTP/MCP service cleanly;
history progress is durable and resumes on the next start. Preview every repository and client
change without creating the policy, state directory, or connection:

```bash
uvx anaxigraph up . --semantic agent --connect codex --dry-run --json
```

## Durable path: Docker sidecar

You need Git, Docker with Compose, and [`uv`](https://docs.astral.sh/uv/). From the repository you
want to analyze, create and start the sidecar in one command:

```bash
uvx anaxigraph init . --start
```

To enable the coding-agent-funded semantic queue and connect a client in the same explicit setup,
use either of these commands:

```bash
anaxigraph init . --start --semantic agent --connect codex
anaxigraph init . --start --semantic agent --connect claude
```

The default `user` connection scope is private and available across repositories on that machine.
Choose `--connect-scope project` to write a trusted-repository Codex `.codex/config.toml` or a
team-shared Claude `.mcp.json` instead. A plain `init` never changes a coding-client configuration.
Preview every repository and client action with `--dry-run --json`; existing client files receive
a timestamped backup only when their AnaxiGraph entry actually changes, and repeating the command
is a no-op.

The initializer detects obvious top-level areas and creates two files:

- `.anaxigraph.yml` — editable repository names, groups, optional coverage inputs, and
  architecture review rules.
- `compose.anaxigraph.yml` — a hardened sidecar with a read-only repository mount and a
  persistent AnaxiIndex volume.

It never replaces either file unless you explicitly add `--force`. Preview its result without
writing anything with `uvx anaxigraph init . --dry-run`. If Docker Compose cannot start, the
generated files remain available for inspection and retry.

If you prefer to approve the files before starting, omit `--start`, review them, then run:

```bash
uvx anaxigraph init .
docker compose -f compose.anaxigraph.yml up -d
docker compose -f compose.anaxigraph.yml ps
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). The current repository scan completes before
the service becomes ready. Representative graph frames from the initial Git commit through HEAD
then import in the background; progress appears on the History page.

Follow startup if the health check is still waiting:

```bash
docker compose -f compose.anaxigraph.yml logs -f anaxigraph
```

## Take the guided tour

The first dashboard visit presents four steps:

1. **Index the repository** — confirms the current files and snapshot are in AnaxiIndex.
2. **See the system** — opens the module inventory and architecture graph; History replays how the
   graph grew over Git time.
3. **Turn a signal into a plan** — explains the finding lifecycle. Review or dismiss noise, and
   choose **Plan for agent** only when you want a bounded coding handoff.
4. **Connect your coding agent** — copies the command for giving Codex access to AnaxiMCP.

The guide is local to the browser and repository. Hide it when finished; **Settings → Show guided
tour** restores it.

### Attention is not the complete ledger

The Architecture page opens on a bounded attention queue. It contains at most 20 qualifying new,
reviewed, planned, or regressed signals; routine information-level long-function observations do
not fill it. Switch to **All diagnostics** to recover every stored observation and filter by
detector, module path, architecture area, lifecycle state, severity, and confidence. Repeated
diagnostics are summarized by detector and area before their individual evidence cards.

Each card expands into its ranking evidence, plausible false-positive conditions, affected areas,
and verification rule. **Mark reviewed** keeps a condition active, **Plan agent work** records
explicit approval, **Accept risk** keeps monitoring it without filling the attention queue, and
**Not actionable** dismisses it. Resolution normally comes from the next complete scan: if the
detector no longer sees the same stable condition it becomes resolved, and if it returns later it
becomes regressed.

Presentation thresholds are optional repository policy:

```yaml
findings:
  attention:
    minimum_priority: 35
    minimum_severity: warning
    page_size: 20
    include_info_long_functions: false
  diagnostics:
    page_size: 50
```

## Connect Codex

### Install the guided agent workflow

The shared agent plugin is the easiest way to teach Codex the safe semantic bootstrap, scope,
impact, finding, and verification workflows:

```bash
codex plugin marketplace add hcekne/anaxigraph
codex plugin add anaxigraph@anaxigraph
```

Restart Codex in the target repository and invoke `$anaxigraph`. Claude Code users can install the
same package with `claude plugin marketplace add hcekne/anaxigraph` followed by
`claude plugin install anaxigraph@anaxigraph --scope user`, then invoke
`/anaxigraph:anaxigraph`. See the [agent plugin guide](agent-plugin.md) for the complete behavior
and custom endpoint options.

### Configure only the MCP connection

With the sidecar healthy, add its Streamable HTTP MCP endpoint. Run this in a shell on the machine
where Codex itself runs. It can be run from any directory:

```bash
codex mcp add anaxigraph --url http://127.0.0.1:8765/mcp
codex mcp list
```

The equivalent explicit initializer option is:

```bash
anaxigraph init . --semantic agent --connect codex --connect-scope user
```

By default it saves the server in `~/.codex/config.toml`, so later Codex sessions on that host can
use AnaxiGraph while you work in any repository. Start or restart Codex in the repository you
actually intend to edit:

```bash
cd /path/to/the/repository
codex
```

Codex CLI, the Codex IDE extension, and the ChatGPT desktop app share MCP configuration on the
same host. You can also add the following to global `~/.codex/config.toml` or to a trusted
repository's `.codex/config.toml`:

```toml
[mcp_servers.anaxigraph]
url = "http://127.0.0.1:8765/mcp"
```

See the official [Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp) for client
configuration details.

## Connect Claude Code

AnaxiGraph can also write Claude Code's documented HTTP MCP entry:

```bash
anaxigraph init . --semantic agent --connect claude --connect-scope user
```

Use `--connect-scope project` when the repository should contain a reviewable `.mcp.json` shared
with the team. Claude asks each user to approve a project-scoped MCP server before using it. The
equivalent native command is:

```bash
claude mcp add --transport http --scope user anaxigraph http://127.0.0.1:8765/mcp
```

For either client, pass `--mcp-url` when the agent cannot use the generated loopback URL. An agent
in the generated Compose network uses `http://anaxigraph:8765/mcp`; an agent on a remote host must
use an explicitly reachable or forwarded server URL. Credentials and URL fragments are rejected
rather than written into client configuration.

### Remote Linux server + local browser

If AnaxiGraph and Codex both run on a remote Linux server, Codex connects directly to
`http://127.0.0.1:8765/mcp`. An SSH port forward is only needed to open the dashboard in a browser
on another computer; it is not part of the server-side Codex-to-AnaxiMCP connection.

```text
Codex on server ── http://127.0.0.1:8765/mcp ──→ AnaxiMCP container
Local browser   ── SSH port forward ───────────→ dashboard on :8765
```

Run this on the Linux server:

```bash
curl http://127.0.0.1:8765/healthz
codex mcp add anaxigraph --url http://127.0.0.1:8765/mcp
codex mcp list
cd /path/to/the/repository
codex
```

If Codex runs on your local computer, it can use the forwarded URL while the SSH tunnel remains
active. If Codex runs in another container on the same Docker network, use the service address
`http://anaxigraph:8765/mcp`.

Most AnaxiMCP tools read AnaxiIndex only. When a repository explicitly selects
`semantic.provider: agent`, the semantic work and submission tools may also change its durable
queue and semantic records; they still cannot write the mounted repository. A useful coding
workflow is:

1. Ask the agent to call `ANAXIGRAPH_OVERVIEW` or `ANAXIGRAPH_SEARCH` to orient itself.
2. Before a change, call `ANAXIGRAPH_SCOPE` for a small affected-file and test envelope, or
   `ANAXIGRAPH_IMPACT` for reverse-dependency risk.
3. For an approved architecture finding, choose **Plan for agent** in the dashboard and use
   `ANAXIGRAPH_FINDING_CONTEXT` to retrieve its evidence, scope, and verification steps.
4. Make and test the change in the normal coding repository. AnaxiGraph never writes it.
5. Refresh the scan. The finding resolves only when its measured condition disappears.

Other MCP clients should connect to `http://127.0.0.1:8765/mcp`. When the client runs in another
container on the same Docker network, use the Compose service address
`http://anaxigraph:8765/mcp` instead.

## Build the AI understanding baseline

Connecting Codex to AnaxiMCP normally lets the coding agent read AnaxiIndex. A repository can also
opt into a narrow write-back workflow in which that same agent digests bounded semantic work and
writes only schema-validated interpretations into AnaxiIndex. This keeps the model credential and
token bill in the coding agent instead of the AnaxiGraph container.

The initial bootstrap runs in resumable stages:

1. A normal read-only scan records every module, hash, symbol, interface, dependency, group, and
   Git biography.
2. The selected semantic executor reads every eligible first-party module and stores an intrinsic
   dossier. Large evidence is delivered in bounded pages.
3. It combines those dossiers with dependency evidence to describe each module in context, then
   synthesizes group and repository dossiers. Large scopes use compact child records and a
   hierarchical reduction, so a subsystem with thousands of modules is never sent as one
   unbounded model request.

A repository is semantically ready only when every eligible module has current intrinsic and
contextual understanding and repository synthesis has completed. Explicit exclusions and failed
modules remain visible instead of disappearing from the coverage number.

### Recommended: let the connected coding agent pay for the reasoning

Enable the generated policy without reserializing its unrelated fields or comments:

```bash
anaxigraph init . --semantic agent --no-compose
```

This produces the equivalent policy block:

```yaml
semantic:
  enabled: true
  provider: agent
  refresh: manual
  max_parallel_jobs: 1
  agent_lease_seconds: 1800
  include: [src/**]
  exclude: [src/generated/**, vendor/**]
```

No API key or `ai` Compose profile is required. Refresh the deterministic scan or choose
**Prepare semantic work** in the dashboard, make sure the coding agent is connected to
AnaxiMCP, and give it this task inside the agent chat:

> Use AnaxiGraph to build or resume the semantic baseline for this repository. Call
> `ANAXIGRAPH_SEMANTIC_SCHEMA` once. Then repeat `ANAXIGRAPH_SEMANTIC_WORK`; if it returns an
> evidence manifest, fetch every page with `ANAXIGRAPH_SEMANTIC_EVIDENCE`; analyze the supplied
> module or scope; and submit one complete dossier with `ANAXIGRAPH_SEMANTIC_SUBMIT`. Continue
> until WORK returns `complete`. Do not edit repository source during this mapping task.

The loop is intentionally resumable. Each WORK call leases one job with an expiring opaque token.
SUBMIT verifies the token, current repository snapshot, prompt/schema version, and full dossier
shape before committing. A repeated completed submission is idempotent. If the agent cannot
finish, `ANAXIGRAPH_SEMANTIC_RELEASE` returns the job to the queue without consuming an attempt.
The executor label and model label supplied by the client are retained as provenance.

For a very large repository, one Codex or Claude session may not finish every module. Start a new
session with the same prompt; completed hashes and dossiers are reused, so it resumes at the next
missing or stale job. After the initial full digest, later scans enqueue only changed source or
context affected by changed interfaces, relationships, neighbouring intent, policy, prompt, or
schema.

The semantic MCP tools have explicit read/write annotations: SCHEMA and EVIDENCE are reads; WORK,
SUBMIT, and RELEASE change only AnaxiIndex. Codex can apply per-server or per-tool approval policy
through its MCP configuration; see the official
[Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp).

### Alternative Docker worker: OpenAI or Anthropic API

Edit the generated `.anaxigraph.yml`:

```yaml
semantic:
  enabled: true
  provider: openai             # or anthropic
  model: gpt-5.6-terra         # replace with a model available to your account
  refresh: periodic            # manual | on_scan | watch | periodic
  reconcile_interval_minutes: 1440
  max_jobs_per_run: 100
  max_parallel_jobs: 2
  max_attempts: 3
  max_age_days: 0              # 0 means fingerprints, not age, control refresh
  include: [src/**]
  exclude: [src/generated/**, vendor/**]
```

Keep credentials outside repository configuration. Export the matching key before creating the
containers, then start the optional worker:

```bash
export OPENAI_API_KEY="..."       # or ANTHROPIC_API_KEY
docker compose -f compose.anaxigraph.yml --profile ai up -d
docker compose -f compose.anaxigraph.yml logs -f anaxigraph-semantic
```

The dashboard's **Understand repository** button runs the same durable queue in the main service.
The `ai` profile is the unattended scheduler and processes repositories whose
`semantic.refresh` is `periodic`. The key must be present when the relevant container is created;
restart it after changing the environment.

### Local worker: Codex, Claude, hosted API, or a custom command

When AnaxiGraph and AnaxiIndex run directly on the host, the semantic worker can reuse an already
authenticated coding CLI without putting its credential in repository YAML:

```yaml
semantic:
  enabled: true
  provider: codex              # or claude
  refresh: manual
  max_jobs_per_run: 100
  max_parallel_jobs: 1
```

```bash
anaxigraph understand /path/to/repository
anaxigraph semantic-status /path/to/repository
```

The Codex adapter invokes non-interactive `codex exec` in an ephemeral, read-only sandbox with a
strict JSON output schema. The Claude adapter uses non-persistent, tool-free print mode with a
JSON schema. Neither adapter gives the model a tool for editing the target. A `command` provider
is also available: AnaxiGraph sends one JSON request on standard input and expects
`{"dossier": {...}, "usage": {...}}` on standard output.

The stock Docker image intentionally does not bundle the Codex or Claude CLIs. Prefer
`provider: agent` when a coding agent is already connected to the Docker sidecar, use `openai` or
`anthropic` for an in-container hosted worker, or build an operator-owned image containing your
chosen CLI. A host CLI and a Docker sidecar use different AnaxiIndex files unless you deliberately
give them the same database mount; do not expect a host `anaxigraph understand` command to update
an unrelated named Docker volume.

### What gets sent again—and what does not

Every scan performs cheap deterministic comparisons. The model is called only for missing,
failed/retried, age-expired, prompt/model-stale, structurally changed, or context-invalidated
records:

- raw byte changes trigger a scan comparison;
- the structural hash controls whether source must be reread;
- interface and relationship fingerprints can refresh context without rereading unchanged source;
- normalized intent fingerprints invalidate only affected parent synthesis;
- prompt, model, provider, or dossier-schema changes create new versioned understanding.

Repeated reconciliation of an unchanged repository makes zero new source-reading calls. Jobs,
attempts, leases, failures, token counts, and costs are durable, so interrupted containers resume
after their worker lease expires.

### Cost and privacy controls

`include` and `exclude` are semantic egress rules in addition to the scanner's own ignore rules.
Excluded modules are recorded explicitly. `max_jobs_per_run`, `max_parallel_jobs`, and
`daily_budget_usd` bound work. To turn provider token usage into dollar estimates, configure
`input_cost_per_million` and `output_cost_per_million` for the exact model/account pricing you
use; leaving them at zero still records tokens but reports no inferred dollar cost. Hosted APIs
provide usage counts directly. CLI and custom-command adapters use a conservative estimate when
their output does not include usage, and AnaxiIndex keeps that value as estimated rather than
claiming it is a provider-reported charge.

Source and comments are treated as untrusted data in the provider prompt. The worker supplies only
indexed facts, bounded source, and stored neighbouring dossiers; model output is labeled as an
interpretation with provider, model, prompt/schema version, confidence, and evidence.

## Coverage is optional evidence

AnaxiGraph imports existing Cobertura `coverage.xml` or LCOV `lcov.info` reports; it deliberately
does not run untrusted target tests. The initializer records reports it can already find. Missing
optional coverage remains **No report**, which is distinct from measured 0%.

To add coverage later, list the report paths under `coverage.files` in `.anaxigraph.yml`, generate
them with the repository's normal test or CI command, then choose **Refresh scan**.

## Build and control the Git biography

The configured history import starts in the background with the sidecar. It is a durable job in
AnaxiIndex rather than a browser task: closing the tab does not stop it, and restarting the service
resumes from the last complete frame. The History view shows the selected and completed frames,
current commit subject/date, changed and reused work, rows and bytes added, elapsed time, and a
clearly labeled estimate of the remaining time. The rest of the dashboard remains usable.

The same controls are available from a shell that can access the same index:

```bash
anaxigraph history /path/to/repository --status
anaxigraph history /path/to/repository --cancel
anaxigraph history /path/to/repository --limit auto
```

Cancellation takes effect between atomic frames, so it cannot leave a partial snapshot. Running
the import again retries a failed/cancelled job and reuses every compatible completed frame. A
connected coding agent can call `ANAXIGRAPH_HISTORY_STATUS`, `ANAXIGRAPH_HISTORY_IMPORT`, and
`ANAXIGRAPH_HISTORY_CANCEL` for the same repository-scoped workflow. These tools only mutate the
external AnaxiIndex; they never write the mounted repository.

Before an upgrade or when diagnosing an index, run the safety report. Opening an old index may
perform its normal backed-up schema migration; the command never edits repository source:

```bash
# Host installation
anaxigraph doctor --db "${XDG_STATE_HOME:-$HOME/.local/state}/anaxigraph/anaxi-index.db" --json

# Generated Docker sidecar
docker compose -f compose.anaxigraph.yml exec anaxigraph \
  anaxigraph doctor /repo \
    --db /state/anaxi-index.db \
    --service-url http://127.0.0.1:8765 \
    --json
```

From the agent host, verify the same HTTP service plus the selected client entry:

```bash
anaxigraph doctor /path/to/repository \
  --service-url http://127.0.0.1:8765 \
  --client codex \
  --connect-scope user \
  --mcp-url http://127.0.0.1:8765/mcp \
  --json
```

The report validates database integrity, foreign keys, snapshot ancestry, bounded reconstruction,
schema-9 semantic-fact provenance, the canonical facts/deltas/edges digest, and the checksum of any
schema-6 recovery backup. Its compaction assessment is fail-closed and confirms that the temporary
compatibility staging rows and their semantic references were cleared after validated migration.
The environment report keeps the detailed index integrity result and adds explicit repository,
index-directory, health endpoint, MCP initialization, and client-configuration checks. Omit
`--service-url` or `--client` when that layer is intentionally out of scope.

## Keep the index current

Refresh on demand from the dashboard, or start the optional polling service:

```bash
docker compose -f compose.anaxigraph.yml --profile watch up -d
```

The watcher updates changed files without altering the target. The named Docker volume preserves
AnaxiIndex across restarts and image upgrades.

## Several repositories

Each repository can have its own sidecar and isolated AnaxiIndex. Use another host port when
running several simultaneously:

```bash
ANAXIGRAPH_PORT=8766 docker compose -f compose.anaxigraph.yml up -d
```

An experimental operator deployment can clone AnaxiGraph once and use its allowlisted repository
registry to mount several projects into one service. The browser selector, REST API, and MCP tools
remain repository-scoped, but the service currently has **no authentication or per-user
authorization**. Bind it to loopback or use an SSH tunnel; do not expose it as a shared team service
or to an untrusted network. Anyone who can reach it can inspect every registered repository and
invoke enabled index workflows. See
[Docker operation](docker.md#experimental-multi-repository-service).

## Stop or upgrade

```bash
docker compose -f compose.anaxigraph.yml pull
docker compose -f compose.anaxigraph.yml up -d
docker compose -f compose.anaxigraph.yml down
```

`down` keeps the index volume. `down --volumes` deletes the complete AnaxiIndex and imported
history for that sidecar, so use it only for an intentional reset.

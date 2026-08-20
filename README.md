<p align="center">
  <img src="src/anaxigraph/dashboard/favicon.svg" width="112" alt="AnaxiGraph logo" />
</p>

<h1 align="center">AnaxiGraph</h1>

<p align="center">
  <strong>Keep AI-accelerated codebases coherent as they grow.</strong><br />
  See the architecture, control entropy, and give coding agents grounded context.
</p>

<p align="center">
  <a href="https://github.com/hcekne/anaxigraph/actions/workflows/ci.yml"><img alt="CI status" src="https://github.com/hcekne/anaxigraph/actions/workflows/ci.yml/badge.svg" /></a>
  <a href="LICENSE"><img alt="Apache 2.0 license" src="https://img.shields.io/badge/license-Apache--2.0-167a96" /></a>
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-315f9f" />
  <img alt="MCP Streamable HTTP" src="https://img.shields.io/badge/MCP-Streamable_HTTP-7652a4" />
</p>

<p align="center">
  <a href="docs/onboarding.md">Get started</a> ·
  <a href="docs/docker.md">Docker guide</a> ·
  <a href="CONTRIBUTING.md">Contribute</a>
</p>

AI makes it easy to add code faster than a team can understand the architecture absorbing it.
Hidden coupling, duplicated behavior, inconsistent abstractions, and one-off agent changes can
quietly accumulate into spaghetti code.

AnaxiGraph creates an architectural feedback loop for that problem. It turns a repository and its
Git history into a living, explorable system map, helping people and coding agents understand how
the code fits together before they change it. The goal is not architecture-by-score; it is to make
important trade-offs visible, evidence-backed, and reviewable while there is still time to act.

| | What you get |
|---|---|
| 🧹 **Control entropy** | Catch growing modules, dependency cycles, boundary erosion, and repeated responsibilities before they harden into spaghetti code. |
| 🏛️ **Build for change** | Review whether boundaries, patterns, and abstraction candidates fit the codebase you have and the system you are building toward. |
| 🕸️ **Graph understanding** | Move from a bird's-eye architecture map to the dependencies, history, and evidence behind an individual module. |
| 🕰️ **Repository biography** | Replay how the system grew across real Git history instead of seeing only today's tree. |
| 🧭 **Auditability** | Trace findings and interpretations back to files, relationships, commits, and snapshots. |
| 🤖 **Safer AI coding** | Give Codex a small, evidence-backed work envelope so agent changes respect the wider architecture. |

Under the hood, AnaxiGraph is a standalone temporal architecture observatory. It scans source and
Git history without modifying the target, persists a versioned dependency graph, evaluates
architecture signals, renders an interactive dashboard, and serves bounded context and impact
analysis to coding agents.

The dashboard includes a filterable Modules ledger for purpose, architecture placement, size,
complexity, coupling, Git activity, imported coverage, findings, and review attention. Graph
regions scale with their module populations so dense areas receive proportionally more space.

### Three surfaces, one index

- **🔭 AnaxiGraph** is the dashboard, analysis engine, and overall project.
- **🗂️ AnaxiIndex** is the persistent SQLite knowledge store for repositories, modules, symbols,
  relationships, intent, findings, and history.
- **🔌 AnaxiMCP** exposes that knowledge to Codex and other coding agents over MCP.

The analysis engine is Python-first and supports mixed repositories containing Python,
TypeScript, JavaScript, JSX, CSS, configuration, and documentation.

### Deterministic facts + real module understanding

AnaxiGraph has two separate AI-facing paths that reinforce one another:

```text
source + Git ── deterministic scan/hashes ──→ versioned graph
                                                   │ changed modules only
                                                   ▼
                                  semantic work queue in AnaxiIndex
                                      │                        │
                            connected coding agent      optional model worker
                                      └──────────┬─────────────┘
                                                 ▼
                                versioned semantic dossiers
```

The first opt-in semantic bootstrap reads every eligible first-party module and records its
purpose, contracts, architecture role, related responsibilities, pattern opportunities,
placement guidance, risks, and provenance. It then synthesizes subsystem and repository context.
Later scans compare structural, interface, relationship, prompt, model, and intent fingerprints,
so unchanged source is reused rather than paid for again. Parser facts and model interpretations
remain separate throughout.

## 🚀 Get running in five minutes

AnaxiGraph normally runs as a Docker sidecar beside the repository you are coding in. From that
repository, one command creates the local policy and Compose sidecar, then starts it:

```bash
cd /path/to/your/repository
uvx anaxigraph init . --start
```

The initializer writes `.anaxigraph.yml` and `compose.anaxigraph.yml` without replacing existing
files. The Compose service mounts the repository read-only, persists AnaxiIndex in a named volume,
scans the current tree, and imports representative graph frames from the initial Git commit
through HEAD. If Docker startup fails, the generated files are kept so you can inspect the error
and retry.

To review the generated policy before starting, omit `--start`, inspect both files, and run the
printed Compose command:

```bash
uvx anaxigraph init .
docker compose -f compose.anaxigraph.yml up -d
```

Open <http://127.0.0.1:8765> and follow the four-step dashboard tour.

### Platform support

| Path | Current status |
|---|---|
| Linux x86-64, Docker or local CLI | **Supported** |
| Linux ARM64 | **Best effort**; multi-architecture container is built, native runtime CI is pending |
| macOS Apple silicon / Intel | **Best effort**; Docker Desktop is the recommended path |
| WSL2 | **Best effort**; keep repositories in the Linux filesystem |
| Native Windows / Windows containers | **Not supported yet**; use WSL2 |

See the [platform matrix](docs/platform-support.md) for the exact execution paths, browser status,
filesystem guidance, and what “best effort” means.

## 🤖 Connect Codex

Run the following in a shell on the machine where Codex itself runs. It can be run from any
directory:

```bash
codex mcp add anaxigraph --url http://127.0.0.1:8765/mcp
codex mcp list
```

Current source can make the same explicit, idempotent change while enabling agent-funded semantic
understanding:

```bash
anaxigraph init . --semantic agent --connect codex --connect-scope user
```

Use `--dry-run --json` to preview it or `--connect-scope project` to write the MCP entry to the
trusted repository's `.codex/config.toml`. Existing user configuration is backed up before a real
change; unrelated TOML and comments are preserved.

By default, `codex mcp add` stores the connection in `~/.codex/config.toml`. Future Codex CLI and
IDE sessions on that same host can then use AnaxiMCP from any coding repository. Start a new Codex
session in the project you want to edit:

```bash
cd /path/to/your/repository
codex
```

If you want the connection available only inside one trusted repository, add it to that
repository's `.codex/config.toml` instead:

```toml
[mcp_servers.anaxigraph]
url = "http://127.0.0.1:8765/mcp"
```

### Remote Linux server + local browser

When AnaxiGraph and Codex run on a remote Linux server while you view the dashboard from another
computer, the Codex-to-AnaxiMCP route is direct:

```text
Codex on server ── http://127.0.0.1:8765/mcp ──→ AnaxiMCP container
Local browser   ── SSH port forward ───────────→ dashboard on :8765
```

The SSH tunnel is only needed by the browser. Codex on the server does not go through your local
computer or the tunnel; it reaches the published container port on its own host. A server session
looks like this:

```bash
# Run on the Linux server where Codex runs
curl http://127.0.0.1:8765/healthz
codex mcp add anaxigraph --url http://127.0.0.1:8765/mcp
codex mcp list
cd /path/to/your/repository
codex
```

If Codex runs on your local computer instead, the forwarded URL works while the SSH tunnel is
active. If Codex itself runs in another container on the same Docker network, use
`http://anaxigraph:8765/mcp` instead of `127.0.0.1`.

Other MCP clients use the same endpoint. See the complete [onboarding guide](docs/onboarding.md)
for the human-to-agent workflow, optional coverage, history, custom ports, updates, and reset
behavior, and the official [Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp)
for Codex configuration details.

### Build the semantic baseline with your coding agent (optional)

The recommended Docker path needs no LLM key inside AnaxiGraph. Enable agent-funded semantics in
`.anaxigraph.yml`:

```yaml
semantic:
  enabled: true
  provider: agent
  refresh: manual
  max_parallel_jobs: 1
  agent_lease_seconds: 1800
```

Refresh the scan or choose **Prepare semantic work** in the dashboard. Then ask the coding agent
that is already connected to AnaxiMCP and running in the target repository:

> Use AnaxiGraph to build or resume the semantic baseline for this repository. Call
> `ANAXIGRAPH_SEMANTIC_SCHEMA` once, then repeat `ANAXIGRAPH_SEMANTIC_WORK`, fetch every requested
> evidence page, analyze the module or scope using your own model context, and call
> `ANAXIGRAPH_SEMANTIC_SUBMIT`. Continue until WORK returns `complete`. Do not edit source while
> performing this mapping task.

AnaxiGraph chooses only stale work, supplies source plus deterministic graph/Git evidence, leases
each job, validates the returned dossier, and writes it to AnaxiIndex. The coding agent supplies
the reasoning and uses its own token allowance. The repository mount remains read-only, and the
queue can resume in another agent session if the first session stops.

An in-container hosted worker remains available as an alternative for unattended schedules:

```yaml
semantic:
  enabled: true
  provider: openai       # or anthropic
  model: your-model
  refresh: periodic
```

```bash
export OPENAI_API_KEY="..."       # use ANTHROPIC_API_KEY for provider: anthropic
docker compose -f compose.anaxigraph.yml --profile ai up -d
docker compose -f compose.anaxigraph.yml logs -f anaxigraph-semantic
```

For a local installation, `provider: codex` and `provider: claude` run those authenticated CLIs as
workers. The [semantic onboarding guide](docs/onboarding.md#build-the-ai-understanding-baseline)
explains the agent-funded loop, hosted workers, privacy controls, incremental invalidation, and
scheduling.

## 🎯 Review findings without losing the evidence

The dashboard separates two deliberately different views:

- **Attention queue** shows at most 20 new, reviewed, planned, or regressed signals that cross the
  configured severity or priority threshold. Planned and regressed work is always retained.
- **Diagnostics** is the complete ledger, including routine information-level long-function
  observations. Filter it by detector, module, architecture area, lifecycle state, severity, or
  confidence, and follow its cursor without a hidden result cap.

Every result explains why it is ranked, its deterministic and attached semantic evidence, likely
false-positive conditions, affected contracts and blast radius, the smallest next action, and how
a later scan verifies resolution. A human may review, plan, accept the risk, or dismiss a signal;
only **Planned for agent** means an agent has approval to treat it as work.

Repositories can tune presentation without deleting findings:

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

Coding agents use the same bounded contract through `ANAXIGRAPH_FINDINGS`. Set
`view="diagnostics"` to inspect the complete ledger, pass the returned cursor for the next page,
and set `token_budget` when context size matters. Use `status="planned"` followed by
`ANAXIGRAPH_FINDING_CONTEXT` for human-approved work.

## 🔄 Keep it current

Follow startup or scanning with:

```bash
docker compose -f compose.anaxigraph.yml logs -f anaxigraph
```

To refresh automatically while you code, enable the optional watcher:

```bash
docker compose -f compose.anaxigraph.yml --profile watch up -d
```

## 🗺️ Experimental multi-repository service

The repository also contains an operator setup for one dashboard across several allowlisted
read-only mounts. It is useful for one trusted operator switching projects without running several
ports:

```bash
git clone https://github.com/hcekne/anaxigraph.git
cd anaxigraph
cp .env.example .env
cp repositories.example.yml repositories.yml
# Edit the host mounts and registry, then:
docker compose up --build -d
```

The browser cannot ask the server to browse arbitrary host paths. See
[Docker operation](docs/docker.md) and [MaxOS integration](docs/maxos-agent.md).

> **Security boundary:** the current REST and MCP service has no authentication or per-user
> authorization. Keep it bound to loopback or behind an SSH tunnel, and do not expose it as a team
> service or to an untrusted network. Anyone who can reach it can inspect every registered
> repository and invoke enabled index workflows. Authenticated team mode is roadmap work; use one
> isolated sidecar per developer/repository until it lands.

## 💻 Local CLI

```bash
uv tool install -e .
anaxigraph init /path/to/repository --no-compose
anaxigraph scan /path/to/repository
anaxigraph serve --repository /path/to/repository --scan-on-start --open
```

AnaxiIndex is stored outside the target at
`${XDG_STATE_HOME:-~/.local/state}/anaxigraph/anaxi-index.db`. Override it with `--db` or
`ANAXIGRAPH_DB`.

Useful commands:

```bash
anaxigraph update /path/to/repository
anaxigraph understand /path/to/repository
anaxigraph semantic-status /path/to/repository
anaxigraph history /path/to/repository --limit auto
anaxigraph history /path/to/repository --status
anaxigraph history /path/to/repository --cancel
anaxigraph doctor
anaxigraph review /path/to/repository
anaxigraph scope /path/to/repository --goal "Add saved prompts to Workbench"
anaxigraph impact /path/to/repository --target backend/app/services/chat.py
anaxigraph watch /path/to/repository
anaxigraph mcp --repository /path/to/repository --port 8765
```

Claude Code uses the same initializer contract:

```bash
anaxigraph init . --semantic agent --connect claude --connect-scope user
```

Project scope writes Claude's reviewable `.mcp.json`. Pass `--mcp-url` for an agent in another
container or on another host; the initializer prints loopback, Compose-network, and remote URL
forms so the browser route is not confused with the agent route.

The `serve` and `mcp` commands both expose the dashboard and JSON API at
`http://127.0.0.1:8765`, with Streamable HTTP MCP at `http://127.0.0.1:8765/mcp`. See
[`docs/maxos-agent.md`](docs/maxos-agent.md) for the ready-to-run MaxOS integration.

Git-history reconstruction runs as a durable AnaxiIndex job. The History view reports its current
commit, frame counts, changed/analyzed/reused work, index growth, elapsed time, and estimated time
remaining. It can be cancelled after the current atomic frame and resumed without repeating
completed frames. Coding agents can use the equivalent `ANAXIGRAPH_HISTORY_STATUS`,
`ANAXIGRAPH_HISTORY_IMPORT`, and `ANAXIGRAPH_HISTORY_CANCEL` tools. Current modules, findings,
graphs, and agent scope remain available while the timeline is built.

`anaxigraph doctor` keeps the full SQLite integrity, lineage, reconstruction, semantic provenance,
canonical digest, migration-backup, and compaction report. It can now also verify the readable
repository mount, writable index directory, dashboard health, a real AnaxiMCP initialization
handshake, and the selected Codex/Claude configuration. Opening an old index follows the normal
backed-up migration contract; it never edits repository source. For the Docker sidecar, run:

```bash
docker compose -f compose.anaxigraph.yml exec anaxigraph \
  anaxigraph doctor /repo \
    --db /state/anaxi-index.db \
    --service-url http://127.0.0.1:8765 \
    --json
```

On the host where the coding client runs, add `--client codex` or `--client claude`, the matching
`--connect-scope`, and `--mcp-url http://127.0.0.1:8765/mcp` to verify that final layer.

## 🧠 What is persisted

- repositories, commit/working-tree snapshots, artifacts, and artifact versions
- source symbols and deterministic import/call relationships with evidence
- raw and language-aware structural hashes for incremental scans
- declared and inferred architecture groups
- metrics, coverage measurements, Git change history, and temporal trends
- architecture findings with stable identity and lifecycle state
- durable intrinsic, contextual, subsystem, and repository dossiers with provider/model/prompt
  plus coding-agent executor provenance, resumable work state, fingerprints, token usage, and
  cost estimates

The target repository only needs an optional `.anaxigraph.yml`; analysis state remains external.

## 🛠️ Development

```bash
uv sync --extra dev
uv run pre-commit install --install-hooks
uv run python scripts/run_quality_gate.py --base origin/main
```

The product brief and requirement source is [`repo_instructions.md`](repo_instructions.md).
Contributions are welcome; see [`CONTRIBUTING.md`](CONTRIBUTING.md).

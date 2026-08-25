<p align="center">
  <img src="src/anaxigraph/dashboard/favicon.svg" width="112" alt="AnaxiGraph logo" />
</p>

<h1 align="center">AnaxiGraph</h1>

<p align="center">
  <strong>Keep AI-accelerated codebases coherent as they grow.</strong><br />
  See the system behind the source, control entropy, and give coding agents grounded context.
</p>

<p align="center">
  <a href="https://github.com/hcekne/anaxigraph/actions/workflows/ci.yml"><img alt="CI status" src="https://github.com/hcekne/anaxigraph/actions/workflows/ci.yml/badge.svg" /></a>
  <a href="LICENSE"><img alt="Apache 2.0 license" src="https://img.shields.io/badge/license-Apache--2.0-167a96" /></a>
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-315f9f" />
  <img alt="MCP Streamable HTTP" src="https://img.shields.io/badge/MCP-Streamable_HTTP-7652a4" />
</p>

<p align="center">
  <a href="docs/onboarding.md">Get started</a> ·
  <a href="docs/agent-plugin.md">Agent plugin</a> ·
  <a href="docs/docker.md">Docker</a> ·
  <a href="docs/advanced-operations.md">Advanced</a> ·
  <a href="CONTRIBUTING.md">Contribute</a>
</p>

AI makes it easy to add code faster than a team can understand the architecture absorbing it.
Hidden coupling, duplicated responsibilities, inconsistent abstractions, and one-off agent changes
quietly become spaghetti code.

AnaxiGraph turns a repository and its Git history into a living architecture record. It helps
people and coding agents see how the system fits together, decide what deserves attention, plan a
small change, and verify what the change actually did. Its job is not to hand out a magic
architecture score; it makes trade-offs visible, evidence-backed, and reviewable before entropy
hardens into the design.

| | What it gives you |
|---|---|
| 🧹 **Entropy control** | Detect growing modules, cycles, boundary erosion, hotspots, and repeated responsibilities early. |
| 🕸️ **System visibility** | Move from a bird's-eye architecture map to the dependencies, history, and evidence of one module. |
| 🕰️ **Repository biography** | Replay representative real Git commits and inspect how the architecture grew. |
| 🧭 **Auditability** | Keep facts read from code, AI explanations, recommendations, and recorded decisions distinct. |
| 🏛️ **Design guidance** | Ground patterns, refactors, placement, and consolidation advice in the codebase that actually exists. |
| 🤖 **Safer agent work** | Give a coding agent the smallest useful file list, code that may be affected, active risks, and checks to run. |

## 🚀 Start in four steps

You need Git, Python 3.11+, and [`uv`](https://docs.astral.sh/uv/).

### 1. Run one command in the repository

```bash
cd /path/to/your/repository
uvx anaxigraph up . --open --semantic agent --connect codex
```

Use `--connect claude` for Claude Code. Omit `--semantic agent --connect codex` when you only want
the code-only map.

This command creates or loads repository policy, stores AnaxiIndex outside the target, completes
the current scan, starts the loopback dashboard and AnaxiMCP, and builds representative Git history
in the background. Stop it with Ctrl-C; restart with the same command.

### 2. Open the dashboard

Visit <http://127.0.0.1:8765>. Current architecture is ready before background history finishes.

### 3. Restart Codex in the repository

The explicit `--connect codex` option configures `http://127.0.0.1:8765/mcp` on the machine where
Codex runs. Restart it after first-time setup:

```bash
cd /path/to/your/repository
codex
```

### 4. Ask it to build the AI-created code map

> Use AnaxiGraph to build or resume the AI-created code map for this repository, using your own
> model context and tokens. Start the background coding-agent worker, do not edit source while
> mapping, and monitor it until the status says the map is up to date.

The durable command survives the invoking Codex session:

```bash
anaxigraph understand . --executor codex --background
anaxigraph semantic-status .
```

With `semantic.provider: agent`, `understand` auto-detects an invoking Codex or Claude session and
uses that authenticated local CLI as a read-only semantic executor. Use `--executor codex` or
`--executor claude` to select one explicitly. Use `--executor mcp` when the already-connected agent
should perform the MCP work loop itself; that mode returns `status: agent_action_required`—meaning
the agent still has work to do—until it has submitted every task. `--background` includes the
complete saved task list,
records a durable run handoff in user state, and keeps the host worker alive if the coding-agent
session exits. `semantic-status` reports whether that worker is really running, where its log is,
whether it finished, which saved index it is using, and its model and reasoning effort. The command
deliberately omits a model so the executor can
use its currently supported configured default. Only pass `--model` or `--reasoning-effort` for an
explicit runtime choice; changing either never makes an existing AI description stale. Direct MCP
looping handles one limited task at a time when no authenticated host worker is available; it is
not the default way to build the complete map.

When the loopback dashboard is already running, `understand` matches the checkout to its service by
Git remote identity and executes against that sidecar's AnaxiIndex—even when the container sees the
checkout at `/repo`. It never creates a second default database in that case. Without a matching
service it uses the same stable per-checkout user-state path as `anaxigraph up`; a timeout or
invalid inventory fails closed instead of silently choosing another index. `--db` explicitly
selects a standalone index, and `--service-url` explicitly selects a service. Every command result
reports the chosen `index.authority` and physical/service identity for unambiguous handoff.

That is the key cost model: **the connected coding agent does the reasoning with its own tokens**.
AnaxiGraph needs no model key in `provider: agent` mode. It gives the agent a limited page of
evidence for one file or code area at a time, checks the returned structured description, records
which worker and model created it, and resumes unfinished work in a later session. Once every file
has a current description, the same workflow automatically proposes a
responsibility-based area/subsystem map, runs independent AI critic/revision passes, and applies
exact membership and size checks in code. There is no human approval gate: the result is
versioned map metadata and never edits or controls the analyzed code. Unchanged fingerprints avoid
rereading unchanged files or rebuilding an unchanged file grouping. View the result in the dashboard
Map selector or through `ANAXIGRAPH_TAXONOMY`.

The complete [onboarding guide](docs/onboarding.md) explains the normal coding loop and setup
diagnostics.

## 🐳 Durable Docker sidecar

If you prefer an isolated, persistent container beside the repository:

```bash
cd /path/to/your/repository
uvx anaxigraph init . --start --semantic agent --connect codex
```

The generated Compose service mounts source read-only, drops Linux capabilities, enables
no-new-privileges, persists AnaxiIndex in a named volume, and publishes only to loopback by
default. Use `--connect claude` for Claude Code. Preview the full repository and client change with
`--dry-run --json`.

See [Docker operation](docs/docker.md) for manual Compose review, updates, watchers, and the
experimental multi-repository registry.

## 🔌 Install the guided agent workflow

The shared plugin teaches Codex and Claude Code how to select the right indexed repository, build
or resume the AI-created code map, find a small set of likely files and affected callers, hand off
a planned finding, and verify a completed change.

Codex:

```bash
codex plugin marketplace add hcekne/anaxigraph && \
  codex plugin add anaxigraph@anaxigraph
```

Invoke `$anaxigraph`. Claude Code:

```bash
claude plugin marketplace add hcekne/anaxigraph && \
  claude plugin install anaxigraph@anaxigraph --scope user
```

Invoke `/anaxigraph:anaxigraph`. The plugin includes the default loopback MCP connection, so
plugin users may omit `--connect` from the start command. See the
[agent plugin guide](docs/agent-plugin.md) for the safety contract and custom endpoint behavior.

## How it works

```text
source + Git ── facts read from code and file hashes ──→ versioned AnaxiIndex
                                                       │ changed/stale work only
                                                       ▼
                                             saved AI task list
                                                       │
                                              connected coding agent
                                                       │ own model + tokens
                                                       ▼
                                  versioned, checked code descriptions
```

Structural refresh and semantic execution are separate operations. A dashboard **Refresh scan**
runs asynchronously with observable progress and safe cancellation; semantic prepare/resume uses
the already-current snapshot and never hides a structural rescan inside the command.

Three named surfaces share one index:

- **AnaxiGraph** is the scanner, dashboard, and overall project.
- **AnaxiIndex** is the SQLite record of repositories, files, named code parts, direct code links,
  findings, history, and AI-created descriptions.
- **AnaxiMCP** gives coding agents size-limited repository evidence and controlled ways to update
  the external index.

AnaxiGraph does not execute target code and does not edit repository source. A generated sidecar
mounts the target read-only. The target needs only optional `.anaxigraph.yml` policy; analysis
state stays external.

### Facts are not opinions

AnaxiGraph deliberately separates:

1. **facts read directly from repository data**—hashes, code structure, named code parts, direct
   links, Git changes, branch counts, imported test coverage, and which analyzer produced them;
2. **AI explanations**—purpose, responsibilities, role in the repository, related behavior, and
   pattern opportunities, each with the model, instructions, evidence, and evidence-strength
   rating that produced it; and
3. **recommendations**—reviewable proposals with evidence, counter-evidence, cost, safety, and
   lifecycle state.

Relationship edges say whether they are resolved, ambiguous, unresolved, or external. Dynamic
runtime wiring can still be invisible, so a missing edge is never presented as proof of dead code.

### One index, several views

- **Overview** summarizes areas, evidence completeness, history, and immediate attention.
- **Files** is a sortable and filterable list of purpose, repository area, size, branch count,
  direct code links, Git activity, test coverage, findings, and pattern review.
- **Graph** moves between repository areas and direct links between files.
- **Architecture** separates a short attention list from the complete finding record.
- **History** replays representative first-parent commits from repository initialization to HEAD.
- **Agents** builds evidence-backed work scope, saves a versioned before-change baseline, compares
  it after a rescan, and explains semantic progress without calling every difference an
  improvement. Reviewed patterns keep their size-limited plain-language explanation in this handoff;
  agents do not receive unexplained suitability or opportunity numbers.
- **Pattern intelligence** lets agents query finalized evaluations by target or catalog pattern
  in the **Patterns** view or through `anaxigraph patterns`, `ANAXIGRAPH_PATTERNS`, and the paged
  `/api/patterns` endpoint. Each result leads with a conclusion, evidence, action, cautions, and
  verification; its nine exact ratings are grouped and explained instead of shown as a number wall.
  Candidate results likewise explain why a pair was selected or skipped, what evidence is missing,
  and why the internal selection order is not itself a pattern recommendation.

## 🎯 Findings are a workflow, not a wall

The default attention list shows at most 20 useful findings and excludes routine long-function
notes. The complete record remains filterable and paginated; no evidence is deleted merely to
quiet the UI.

Every finding says what AnaxiGraph saw, why it may matter, what to do, when the code may be fine as
it is, and how to check the result. The dashboard, REST API, MCP tools, scope results, and copied
agent prompt use the same wording. Exact rule IDs, evidence values, and ordering scores remain
structured fields for automation, but each field has an adjacent ordinary-language meaning; they
are never dumped into a jargon-filled “technical details” section. **Plan agent work** selects
a finding for implementation; its handoff also says which retained code map first shows the
problem, where it disappears, and whether it later returns. Resolution and regression normally
come from a later scan. Retained maps are samples, so the named frame bounds the change rather than
claiming that every Git commit was analyzed.

## Current support boundary

The deepest code reading is currently Python-first. JavaScript and TypeScript use the
built-in lexical analyzer; other recognized source and text formats have heuristic or inventory
support. The roadmap deliberately does not call extension recognition “full language support.”
Parser-backed JavaScript/TypeScript, Go, Rust, and Java are the next language-platform phase.

Linux x86-64 is release-gated. Linux ARM64, macOS, and WSL2 are best effort; Docker Desktop is the
recommended macOS path. Native Windows is not supported—use WSL2. See the
[platform matrix](docs/platform-support.md).

The REST and MCP service is a local sidecar. Keep it bound to loopback or access it through a
trusted SSH tunnel; do not expose the port to an untrusted network.

## Advanced operation

The [advanced guide](docs/advanced-operations.md) covers hosted OpenAI/Anthropic workers, local
Codex/Claude/custom workers, semantic cost and privacy, SSH forwarding, custom ports/state,
optional coverage imports, durable history controls, watchers, integrity diagnostics, upgrades,
resets, lower-level CLI commands, and several repositories.

## 🛠️ Development

```bash
uv sync --extra dev
uv run pre-commit install --install-hooks
uv run python scripts/run_quality_gate.py --base origin/main
```

The quality gate includes a fresh, repeatable AnaxiGraph scan of this repository. Its full report
is retained in CI and compared with
[`quality/self-analysis-baseline.json`](quality/self-analysis-baseline.json); new or worsened
warning/error findings fail while unchanged information-level diagnostics remain visible and
non-blocking. Run it directly with
`uv run python scripts/check_self_analysis.py --output /tmp/anaxigraph-self-analysis.json`.

The product brief is [`repo_instructions.md`](repo_instructions.md), the consecutive roadmap is
[`docs/feature-development-plan.md`](docs/feature-development-plan.md), and the release contract is
[`docs/releasing.md`](docs/releasing.md). Contributions are welcome; see
[`CONTRIBUTING.md`](CONTRIBUTING.md).

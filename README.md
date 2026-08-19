<p align="center">
  <img src="src/codeintel/dashboard/favicon.svg" width="112" alt="AnaxiGraph logo" />
</p>

<h1 align="center">AnaxiGraph</h1>

<p align="center">
  <strong>See the system behind the source.</strong><br />
  Architecture visibility for people and grounded repository intelligence for coding agents.
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

AnaxiGraph is a standalone, temporal architecture observatory for software repositories. It scans
source and Git history without modifying the target, persists a versioned dependency graph,
evaluates architecture health, renders an interactive dashboard, and gives coding agents bounded
task context and impact analysis.

| | What you get |
|---|---|
| 🔭 **Visibility** | Move between a bird's-eye architecture map and individual module evidence. |
| 🕰️ **Biography** | Replay how the repository graph grew across real Git history. |
| 🧭 **Auditability** | Trace findings and interpretations back to files, relationships, and snapshots. |
| 🤖 **Agent context** | Give Codex a small, evidence-backed work envelope through read-only MCP tools. |

The dashboard includes a filterable Modules ledger for purpose, architecture placement, size,
complexity, coupling, Git activity, imported coverage, findings, and review attention. Graph
regions scale with their module populations so dense areas receive proportionally more space.

### Three surfaces, one index

- **🔭 AnaxiGraph** is the dashboard, analysis engine, and overall project.
- **🗂️ AnaxiIndex** is the persistent SQLite knowledge store for repositories, modules, symbols,
  relationships, intent, findings, and history.
- **🔌 AnaxiMCP** exposes that knowledge to Codex and other coding agents over MCP.

The initial implementation is deliberately Python-first while supporting the mixed Python,
TypeScript, JavaScript, JSX, CSS, configuration, and documentation repository used by MaxOS.

## 🚀 Get running in five minutes

AnaxiGraph normally runs as a Docker sidecar beside the repository you are coding in. From that
repository, run these commands in a **normal terminal**:

```bash
cd /path/to/your/repository
uvx --from git+https://github.com/hcekne/anaxigraph anaxigraph init .
docker compose -f compose.anaxigraph.yml up -d
```

The initializer writes `.anaxigraph.yml` and `compose.anaxigraph.yml` without replacing existing
files. The Compose service mounts the repository read-only, persists AnaxiIndex in a named volume,
scans the current tree, and imports representative graph frames from the initial Git commit
through HEAD.

Open <http://127.0.0.1:8765> and follow the four-step dashboard tour.

## 🤖 Connect Codex — this is a terminal command

Run the following in a **shell on the machine where Codex itself runs**. It is not a message to
type into a Codex chat, and it can be run from any directory:

```bash
codex mcp add anaxigraph --url http://127.0.0.1:8765/mcp
codex mcp list
```

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

### Linux server + Mac browser

When AnaxiGraph and Codex both run on your Linux server, the route is direct:

```text
Codex on Linux ── http://127.0.0.1:8765/mcp ──→ AnaxiMCP container
Mac browser     ── SSH port forward ───────────→ dashboard on :8765
```

The SSH tunnel is only needed by the Mac browser. Codex on Linux does **not** go through the Mac
or through the tunnel—it reaches the published container port on its own host. A concrete server
session looks like this:

```bash
# Run on the Linux server where Codex runs
curl http://127.0.0.1:8765/healthz
codex mcp add anaxigraph --url http://127.0.0.1:8765/mcp
codex mcp list
cd ~/repos/maxos_agent
codex
```

If Codex runs on your Mac instead, the same URL works only while the SSH port forward is active.
If Codex itself runs in another container on the same Docker network, use
`http://anaxigraph:8765/mcp` instead of `127.0.0.1`.

Other MCP clients use the same endpoint. See the complete [onboarding guide](docs/onboarding.md)
for the human-to-agent workflow, optional coverage, history, custom ports, updates, and reset
behavior, and the official [Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp)
for Codex configuration details.

## 🔄 Keep it current

Follow startup or scanning with:

```bash
docker compose -f compose.anaxigraph.yml logs -f anaxigraph
```

To refresh automatically while you code, enable the optional watcher:

```bash
docker compose -f compose.anaxigraph.yml --profile watch up -d
```

## 🗺️ Shared multi-repository service

The repository also contains an operator setup for one dashboard across several allowlisted
read-only mounts. This is useful for a team installation or for switching projects without
running several ports:

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

## 💻 Local CLI

```bash
uv tool install -e .
anaxigraph init /path/to/repository --no-compose
anaxigraph scan /path/to/repository
anaxigraph serve --repository /path/to/repository --scan-on-start --open
```

AnaxiIndex is stored outside the target at
`${XDG_STATE_HOME:-~/.local/state}/anaxigraph/anaxi-index.db`. Override it with `--db` or
`ANAXIGRAPH_DB`. Existing `CODEINTEL_DB` values and legacy state paths remain supported.

Useful commands:

```bash
anaxigraph update /path/to/repository
anaxigraph history /path/to/repository --limit 64
anaxigraph review /path/to/repository
anaxigraph scope /path/to/repository --goal "Add saved prompts to Workbench"
anaxigraph impact /path/to/repository --target backend/app/services/chat.py
anaxigraph watch /path/to/repository
anaxigraph mcp --repository /path/to/repository --port 8765
```

The `serve` and `mcp` commands both expose the dashboard and JSON API at
`http://127.0.0.1:8765`, with Streamable HTTP MCP at `http://127.0.0.1:8765/mcp`. See
[`docs/maxos-agent.md`](docs/maxos-agent.md) for the ready-to-run MaxOS integration.

## 🧠 What is persisted

- repositories, commit/working-tree snapshots, artifacts, and artifact versions
- source symbols and deterministic import/call relationships with evidence
- raw and language-aware structural hashes for incremental scans
- declared and inferred architecture groups
- metrics, coverage measurements, Git change history, and temporal trends
- architecture findings with stable identity and lifecycle state
- semantic claims with provider/model/prompt provenance kept separate from parser facts

The target repository only needs an optional `.anaxigraph.yml`; legacy `.codeintel.yml` files are
still recognized. Analysis state remains external.

## 🧩 Compatibility

The Python import namespace remains `codeintel`, the `codeintel` CLI remains an alias, and existing
`CODEINTEL_*` environment variables and MCP tool identifiers continue to work. This keeps current
MaxOS and container integrations stable while all new user-facing examples use AnaxiGraph.

## 🛠️ Development

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
```

The product brief and requirement source is [`repo_instructions.md`](repo_instructions.md).
Contributions are welcome; see [`CONTRIBUTING.md`](CONTRIBUTING.md).

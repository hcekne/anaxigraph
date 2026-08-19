# AnaxiGraph

**See the system behind the source.**

AnaxiGraph is a standalone, temporal architecture observatory for software repositories. It scans
source code without modifying the target, persists a versioned dependency graph, evaluates
architecture health, renders an interactive dashboard, and gives coding agents bounded task
context and impact analysis.

The product has three named surfaces:

- **AnaxiGraph** is the dashboard, analysis engine, and overall project.
- **AnaxiIndex** is the persistent SQLite knowledge store for repositories, modules, symbols,
  relationships, intent, findings, and history.
- **AnaxiMCP** exposes that knowledge to Codex and other coding agents over MCP.

The initial implementation is deliberately Python-first while supporting the mixed Python,
TypeScript, JavaScript, JSX, CSS, configuration, and documentation repository used by MaxOS.

## Recommended: Docker Compose

If `anaxigraph` and `maxos_agent` are sibling directories, the checked-in registry starts with both
repositories available in one dashboard:

```bash
docker compose up --build -d
docker compose ps
```

The container scans both allowlisted read-only mounts before becoming healthy, then imports
sampled Git history in the background. Open `http://127.0.0.1:8765`; AnaxiMCP is available at
`http://127.0.0.1:8765/mcp`. The repository is mounted read-only and AnaxiIndex persists in the
Docker state volume.

Follow startup or scan progress with:

```bash
docker compose logs -f anaxigraph
```

To refresh automatically while files change, enable the optional watcher:

```bash
docker compose --profile watch up --build -d
```

For direct container-to-container access from MaxOS, start MaxOS first and add the network overlay:

```bash
docker compose -f compose.yml -f compose.maxos.yml up --build -d
```

MaxOS can then use `http://anaxigraph:8765/mcp`; the previous `codeintel` hostname remains a
network alias. See [Docker operation](docs/docker.md) and
[MaxOS integration](docs/maxos-agent.md) for configuration and lifecycle commands.

To add repositories, copy `repositories.example.yml`, list their container paths and policy files,
and set `ANAXIGRAPH_REGISTRY` in `.env`. The browser can select registered repositories but cannot
ask the server to browse arbitrary host paths. See [Docker operation](docs/docker.md) for the
multi-repository setup and [the product development plan](docs/feature-development-plan.md) for
the semantic intent ledger and scored pattern intelligence roadmap.

## Local CLI

```bash
uv tool install -e .
anaxigraph scan /path/to/repository
anaxigraph serve --repository /path/to/repository --open
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

## What is persisted

- repositories, commit/working-tree snapshots, artifacts, and artifact versions
- source symbols and deterministic import/call relationships with evidence
- raw and language-aware structural hashes for incremental scans
- declared and inferred architecture groups
- metrics, coverage measurements, Git change history, and temporal trends
- architecture findings with stable identity and lifecycle state
- semantic claims with provider/model/prompt provenance kept separate from parser facts

The target repository only needs an optional `.anaxigraph.yml`; legacy `.codeintel.yml` files are
still recognized. Analysis state remains external.

## Compatibility

The Python import namespace remains `codeintel`, the `codeintel` CLI remains an alias, and existing
`CODEINTEL_*` environment variables and MCP tool identifiers continue to work. This keeps current
MaxOS and container integrations stable while all new user-facing examples use AnaxiGraph.

## Development

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
```

The product brief and requirement source is [`repo_instructions.md`](repo_instructions.md).
Contributions are welcome; see [`CONTRIBUTING.md`](CONTRIBUTING.md).

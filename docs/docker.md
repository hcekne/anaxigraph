# Docker operation

Docker Compose is the recommended way to run AnaxiGraph. Target repositories are mounted
read-only, the SQLite graph lives in a named volume, and the dashboard is bound to localhost by
default. One service can index and switch between multiple repositories.

## Recommended: one repository sidecar

From any target repository, generate a dedicated Compose file and editable policy:

```bash
uvx anaxigraph init . --start
```

This pulls `ghcr.io/hcekne/anaxigraph:latest`, binds only the current repository at `/repo` in
read-only mode, and persists its AnaxiIndex in a project-scoped named volume. Existing generated
filenames are not overwritten unless `--force` is explicit. See the [onboarding guide](onboarding.md)
for the guided dashboard and MCP workflow.

Omit `--start` when you want to inspect the generated files before running their printed Compose
command. The remaining sections describe the checked-in operator Compose stack, which is intended
for AnaxiGraph development and an experimental trusted-operator multi-repository service.

## Start the included two-repository setup

The zero-configuration development layout is:

```text
repos/
├── anaxigraph/
└── maxos_agent/
```

From `anaxigraph`:

```bash
docker compose up --build -d
docker compose ps
docker compose logs -f anaxigraph
```

Open `http://127.0.0.1:8765`. The default registry contains MaxOS and AnaxiGraph itself, so both
appear under **Current repository**. Current scans finish before the HTTP service starts; sampled
Git biographies then import in the background and report progress on the History page.

| Endpoint | Address |
|---|---|
| Dashboard | `http://127.0.0.1:8765` |
| Health | `http://127.0.0.1:8765/healthz` |
| REST API | `http://127.0.0.1:8765/api/overview` |
| MCP | `http://127.0.0.1:8765/mcp` |

## Experimental multi-repository service

> **Not an authenticated team deployment:** REST, dashboard, and MCP endpoints currently have no
> login, bearer-token check, or per-user authorization. Keep the published port on
> `127.0.0.1`, access it through a trusted local session or SSH tunnel, and never expose it to an
> untrusted network. Every client that can reach the service can inspect all allowlisted
> repositories and invoke enabled index workflows. Use isolated per-repository sidecars for team
> members until authenticated team mode lands.

Copy the templates:

```bash
cp .env.example .env
cp repositories.example.yml repositories.yml
```

Set the host mounts in `.env`:

```dotenv
# A convenient primary repo; it appears inside the container as /repo.
ANAXIGRAPH_REPOSITORY=/absolute/path/to/repos/project-a

# A parent containing additional repos; it appears as /repositories.
ANAXIGRAPH_REPOSITORIES_ROOT=/absolute/path/to/repos
ANAXIGRAPH_REGISTRY=./repositories.yml
```

Then allowlist the container paths in `repositories.yml`:

```yaml
repositories:
  project-a:
    path: /repo
    config: /repo/.anaxigraph.yml
    history_snapshots: auto

  project-b:
    path: /repositories/project-b
    config: /repositories/project-b/.anaxigraph.yml
    history_snapshots: auto
```

`history_snapshots: auto` is the default. It chooses at most 32 frames for up to 500 eligible files,
24 for 501–2,000, 16 for 2,001–5,000, and 12 above 5,000. Sampling always keeps the initial commit
and HEAD, then prioritizes release tags, architecture/configuration changes, calendar checkpoints,
and dense recent history. Use an integer for an explicit cap, `0` to disable automatic history for
a target, or the CLI `history --all` command to analyze every first-parent commit intentionally.

Apply changes with:

```bash
docker compose up --build -d
```

The registry is an operator-controlled security boundary. The browser and API can select and
refresh registered mounts, but cannot submit arbitrary host paths. All mounts remain read-only;
only the AnaxiIndex file at `/state/anaxi-index.db` changes.

## Import test coverage

AnaxiGraph imports coverage reports; it never runs untrusted repository tests during a scan. Add
the paths produced by each repository's existing test or CI pipeline to its `.anaxigraph.yml`:

```yaml
coverage:
  # Optional by default. Set true only when a missing report should be a warning.
  required: false
  files:
    - backend/coverage.xml
    - frontend/coverage/lcov.info
```

When coverage is optional, a missing report is shown neutrally as **No report** rather than as a
failed scan. Set `required: true` when the dashboard should warn about a missing CI artifact. A
present report whose file paths do not map to the snapshot is reported as unmatched rather than
as 0% coverage. Generate the report with the target repository's own test command, then choose
**Refresh scan** to import it. AnaxiGraph's development suite uses:

```bash
uv run pytest --cov=src/anaxigraph --cov-report=xml:coverage.xml
```

## Keep all repositories current

The main service scans every registry entry on startup. You can click **Refresh scan** for the
selected repository, or enable registry-wide polling:

```bash
docker compose --profile watch up --build -d
docker compose logs -f anaxigraph-watch
```

Set `ANAXIGRAPH_WATCH_INTERVAL` in `.env` to change the default ten-second interval.

## Build and maintain semantic understanding

The model-backed bootstrap is opt-in. The simplest sidecar setup lets the connected coding agent
perform the reasoning with its own tokens and writes only the validated dossier to the shared
AnaxiIndex:

```yaml
semantic:
  enabled: true
  provider: agent
  refresh: manual
  agent_lease_seconds: 1800
```

The normal `anaxigraph` service is sufficient; no model API key or extra profile is needed. In the
coding-agent chat, ask it to call `ANAXIGRAPH_SEMANTIC_SCHEMA` once and then repeat
`ANAXIGRAPH_SEMANTIC_WORK` → optional `ANAXIGRAPH_SEMANTIC_EVIDENCE` pages →
`ANAXIGRAPH_SEMANTIC_SUBMIT` until complete. The queue survives container and agent-session
restarts.

For unattended reconciliation instead, use `provider: openai` or `provider: anthropic`, set a
model and `refresh: periodic`, export the matching key before creating the containers, then run:

```bash
docker compose --profile ai up --build -d
docker compose logs -f anaxigraph-semantic
curl --fail http://127.0.0.1:8765/api/semantic
```

That worker reads all eligible modules on first enrollment, then reconciles at each repository's
`semantic.reconcile_interval_minutes`. Hash and context comparisons happen before model calls, so
an unchanged repository is not resent on each interval. The queue and completed dossiers live in
the shared AnaxiIndex volume and survive container restarts.

Hosted-provider credentials are passed as environment variables to the dashboard and optional worker; they
are not written to `.anaxigraph.yml` or AnaxiIndex. The stock image does not bundle Codex or Claude
CLI binaries. Those CLI adapters are intended for a local AnaxiGraph installation or a custom
operator image. See [semantic onboarding](onboarding.md#build-the-ai-understanding-baseline) for
the full provider, cost, egress, and refresh policy.

To reconstruct history from the command line:

```bash
docker compose exec anaxigraph anaxigraph history /repo \
  --config /repo/.anaxigraph.yml \
  --db /state/anaxi-index.db \
  --limit auto
```

## Use AnaxiMCP from coding agents

For a local Codex or other MCP client, use AnaxiMCP at `http://127.0.0.1:8765/mcp`. The
`ANAXIGRAPH_REPOSITORIES` tool lists selectors. All repository-aware tools accept an optional
`repository` ID or name; omitting it uses the first configured target.

Most tools are read-only. If a selected repository explicitly uses `semantic.provider: agent`,
WORK, SUBMIT, and RELEASE mutate only its AnaxiIndex semantic queue and records. The repository
mount remains read-only.

When another container needs direct access, attach the MaxOS network overlay:

```bash
docker compose -f compose.yml -f compose.maxos.yml up --build -d
```

That client can use `http://anaxigraph:8765/mcp` on the shared Docker network.

## Upgrade, stop, or reset

Rebuild while retaining every repository and historical snapshot:

```bash
docker compose up --build -d
```

Stop containers while retaining the database:

```bash
docker compose down
```

`docker compose down --volumes` deletes the complete multi-repository AnaxiIndex and history. Use
it only for an intentional clean re-index.

Useful diagnostics:

```bash
docker compose ps
docker compose logs --tail 200 anaxigraph
docker compose exec anaxigraph anaxigraph --version
curl --fail http://127.0.0.1:8765/healthz
curl --fail http://127.0.0.1:8765/api/repositories
```

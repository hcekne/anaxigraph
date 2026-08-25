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

> **Trusted-local boundary:** Keep the published port on `127.0.0.1`, access it through a trusted
> local session or SSH tunnel, and never expose it to an untrusted network. Reachability grants
> access to every allowlisted repository and enabled index workflow. Use isolated per-repository
> sidecars when operators should not share the same index boundary.

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
selected repository, or enable registry-wide polling. Dashboard refreshes run in the background,
show phase/file progress, and can be cancelled without discarding the previous current snapshot:

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
  taxonomy:
    enabled: true
    review_passes: 2
    max_areas: 6
    max_subsystems: 30
```

The normal `anaxigraph` service is sufficient; no model API key or extra profile is needed. Launch
a host worker that drives the volume-backed queue independently of the invoking coding-agent
session:

```bash
anaxigraph understand . --executor codex --background
anaxigraph semantic-status .
```

It matches the host checkout to `/repo` by canonical Git remote identity, prepares semantic work
against the sidecar's existing current snapshot without scanning source, then runs the authenticated
host Codex/Claude executor and submits each validated result through AnaxiMCP. The command omits a
model so the executor uses its supported configured default. `--background` persists the worker
PID, heartbeat, log, exact authority, and terminal result outside the chat session. Pass
`--service-url` for a non-default endpoint or `--db` only to intentionally bypass the sidecar.
Structural refresh is a separate explicit scan operation.

Use direct `SCHEMA → WORK → optional EVIDENCE → SUBMIT` calls only for bounded/manual fallback.
Proposal and critic passes run without a human approval step; deterministic validation finalizes
map metadata only. The queue survives process restarts. Read the result with
`ANAXIGRAPH_TAXONOMY` or the dashboard's map-layer selector, and never report the baseline complete
until `semantic-status` says `semantically_ready: true`.

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

Hosted-provider credentials are passed as environment variables to the dashboard and optional
worker; they are not written to `.anaxigraph.yml` or AnaxiIndex. The stock image does not bundle
Codex or Claude CLI binaries. Those CLI adapters are intended for a local AnaxiGraph installation
or a custom operator image. See
[advanced semantic operation](advanced-operations.md#hosted-semantic-worker) for the full provider,
cost, egress, and refresh policy.

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

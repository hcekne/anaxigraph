# Docker operation

Docker Compose is the recommended way to run AnaxiGraph. Target repositories are mounted
read-only, the SQLite graph lives in a named volume, and the dashboard is bound to localhost by
default. One service can index and switch between multiple repositories.

## Recommended: one repository sidecar

From any target repository, generate a dedicated Compose file and editable policy:

```bash
uvx --from git+https://github.com/hcekne/anaxigraph anaxigraph init .
docker compose -f compose.anaxigraph.yml up -d
```

This pulls `ghcr.io/hcekne/anaxigraph:latest`, binds only the current repository at `/repo` in
read-only mode, and persists its AnaxiIndex in a project-scoped named volume. Existing generated
filenames are not overwritten unless `--force` is explicit. See the [onboarding guide](onboarding.md)
for the guided dashboard and MCP workflow.

The remaining sections describe the checked-in operator Compose stack, which is intended for
AnaxiGraph development and a shared multi-repository service.

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

## Shared multi-repository service

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
    history_snapshots: 64

  project-b:
    path: /repositories/project-b
    config: /repositories/project-b/.anaxigraph.yml
    history_snapshots: 48
```

`history_snapshots` is the maximum number of representative graph frames. AnaxiGraph reads the
complete first-parent commit list, always keeps the initial commit and HEAD, and evenly samples the
intervening lifetime. Set it to `0` to disable automatic history for a target. To analyze every
first-parent commit explicitly, use the CLI `history --all` command; large repositories can take a
long time in that mode.

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

To reconstruct history from the command line:

```bash
docker compose exec anaxigraph anaxigraph history /repo \
  --config /repo/.anaxigraph.yml \
  --db /state/anaxi-index.db \
  --limit 64
```

## Use AnaxiMCP from coding agents

For a local Codex or other MCP client, use AnaxiMCP at `http://127.0.0.1:8765/mcp`. The
`ANAXIGRAPH_REPOSITORIES` tool lists selectors. All repository-aware tools accept an optional
`repository` ID or name; omitting it uses the first configured target.

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

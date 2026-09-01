# MaxOS Agent integration

MaxOS is the first-class deployment profile for AnaxiGraph. The analyzer remains a
standalone service; MaxOS consumes its agent tools through the Streamable HTTP MCP boundary it
already uses for external tools. No analyzer code, AnaxiIndex tables, or repository writes
are added to MaxOS.

## Recommended: run with Compose

Start MaxOS normally so its `maxos_agent_default` network exists. Then, from this repository:

```bash
docker compose -f compose.yml -f compose.maxos.yml up --build -d
docker compose -f compose.yml -f compose.maxos.yml ps
```

This builds AnaxiGraph, mounts the allowlisted repositories read-only, performs their current
scans, persists state in a named volume, publishes the dashboard at `http://127.0.0.1:8765`, and
joins the MaxOS network. Git biographies continue importing in the background.
Use `http://anaxigraph:8765/mcp` for the connection URL inside MaxOS. If the repositories are not
siblings, copy `.env.example` to `.env` and set `ANAXIGRAPH_REPOSITORY`.

## Run directly

From this repository:

```bash
uv sync --extra dev
uv run anaxigraph scan ../maxos_agent \
  --config examples/maxos-agent.anaxigraph.yml \
  --db .anaxigraph/maxos-agent.db

uv run anaxigraph mcp \
  --repository ../maxos_agent \
  --config examples/maxos-agent.anaxigraph.yml \
  --db .anaxigraph/maxos-agent.db \
  --scan-on-start \
  --port 8765
```

The dashboard is at `http://127.0.0.1:8765`; AnaxiMCP is available at
`http://127.0.0.1:8765/mcp`.

## Equivalent raw Docker command

The service needs a read-only repository mount, durable state, and the same Docker network as the
MaxOS backend:

```bash
docker build -t anaxigraph:local /absolute/path/to/anaxigraph
docker volume create anaxigraph_anaxi_index
docker run -d \
  --name anaxigraph \
  --network maxos_agent_default \
  --network-alias anaxigraph \
  --read-only \
  --tmpfs /tmp \
  -v /absolute/path/to/maxos_agent:/repo:ro \
  -v anaxigraph_anaxi_index:/state \
  -v /absolute/path/to/anaxigraph/examples:/config:ro \
  anaxigraph:local mcp \
    --repository /repo \
    --config /config/maxos-agent.anaxigraph.yml \
    --db /state/anaxi-index.db \
    --host 0.0.0.0 \
    --port 8765 \
    --allowed-host 'anaxigraph:*' \
    --scan-on-start
```

If the Compose project uses a different network name, obtain it without guessing:

```bash
docker inspect "$(docker compose -f /absolute/path/to/maxos_agent/docker-compose.yml ps -q backend)" \
  --format '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}}{{end}}'
```

## Connect it in MaxOS

In **Settings → MCP connections**, create a connection with:

| Field | Local Docker value |
|---|---|
| Label | `AnaxiMCP` |
| Ownership | Personal or organization, as appropriate |
| Transport | Streamable HTTP |
| URL | `http://anaxigraph:8765/mcp` |
| Authentication | None |

Run **Check** and inspect **Tools**. MaxOS should discover:

- `ANAXIGRAPH_REPOSITORIES`
- `ANAXIGRAPH_OVERVIEW`
- `ANAXIGRAPH_SEARCH`
- `ANAXIGRAPH_FILE`
- `ANAXIGRAPH_GUIDE`
- `ANAXIGRAPH_IMPACT`
- `ANAXIGRAPH_FINDINGS`
- `ANAXIGRAPH_FINDING_CONTEXT`

Enable **Available to chat and workflow agents**, then select the connection under **Context &
tools → Agent tools** in a Workbench chat or on an AI workflow node. A useful first call is:

```text
Call ANAXIGRAPH_GUIDE with intent="build" or intent="improve" for my coding goal before inspecting
files. Stay inside the recommended context unless direct evidence requires expanding it. Call ANAXIGRAPH_IMPACT before changing a
shared interface or protected file. Treat active findings as review signals, not permission to
refactor. Use ANAXIGRAPH_FINDINGS with status="planned" for work I approved in the dashboard, then
call ANAXIGRAPH_FINDING_CONTEXT before editing.
```

For a non-default repository, first call `ANAXIGRAPH_REPOSITORIES`, then pass its ID or name in the
optional `repository` argument of the overview, search, file, guidance, impact, and finding tools.

MaxOS keeps the MCP connection in its trusted backend. Its isolated agent runner receives only a
revocable broker grant and never receives the AnaxiMCP endpoint. Keep AnaxiGraph inside that
trusted network boundary and constrain its accepted hostname with `--allowed-host`.

## MaxOS-specific analysis policy

[`examples/maxos-agent.anaxigraph.yml`](../examples/maxos-agent.anaxigraph.yml) encodes the current
MaxOS source map and its documented directions:

```text
backend api → services → models
frontend app → features → lib
```

It also marks authorization, path safety, MCP egress, launcher containment, provider manifests,
and migrations as protected work-envelope boundaries. The large `data/` runtime tree, credentials,
generated reports, dependency caches, machine-local assistant settings, and archived status
documents are excluded. The target is mounted read-only; only the external SQLite intelligence
AnaxiIndex changes.

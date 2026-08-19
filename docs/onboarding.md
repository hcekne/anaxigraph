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

## Five-minute sidecar setup

You need Git, Docker with Compose, and [`uv`](https://docs.astral.sh/uv/). From the repository you
want to analyze, run:

```bash
uvx --from git+https://github.com/hcekne/anaxigraph anaxigraph init .
```

The initializer detects obvious top-level areas and creates two files:

- `.anaxigraph.yml` — editable repository names, groups, optional coverage inputs, and
  architecture review rules.
- `compose.anaxigraph.yml` — a hardened sidecar with a read-only repository mount and a
  persistent AnaxiIndex volume.

It never replaces either file unless you explicitly add `--force`. Preview its result without
writing anything with `anaxigraph init . --dry-run`.

Review the two generated files, then start the service:

```bash
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

## Connect Codex

With the sidecar healthy, add its Streamable HTTP MCP endpoint. Run this in a shell on the machine
where Codex itself runs. It can be run from any directory:

```bash
codex mcp add anaxigraph --url http://127.0.0.1:8765/mcp
codex mcp list
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

AnaxiMCP is read-only by default. A useful coding workflow is:

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

## Coverage is optional evidence

AnaxiGraph imports existing Cobertura `coverage.xml` or LCOV `lcov.info` reports; it deliberately
does not run untrusted target tests. The initializer records reports it can already find. Missing
optional coverage remains **No report**, which is distinct from measured 0%.

To add coverage later, list the report paths under `coverage.files` in `.anaxigraph.yml`, generate
them with the repository's normal test or CI command, then choose **Refresh scan**.

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

For a long-running team dashboard, clone AnaxiGraph once and use its allowlisted repository
registry to mount several projects into one service. The browser selector, REST API, and MCP tools
remain repository-scoped. See [Docker operation](docker.md#shared-multi-repository-service).

## Stop or upgrade

```bash
docker compose -f compose.anaxigraph.yml pull
docker compose -f compose.anaxigraph.yml up -d
docker compose -f compose.anaxigraph.yml down
```

`down` keeps the index volume. `down --volumes` deletes the complete AnaxiIndex and imported
history for that sidecar, so use it only for an intentional reset.

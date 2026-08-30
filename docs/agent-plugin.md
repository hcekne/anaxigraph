# AnaxiGraph agent plugin

AnaxiGraph is the shared architecture intelligence layer for humans and AI agents. The agent plugin
lets Codex and Claude Code use the same living system model that a person explores in the dashboard.
It packages a shared `anaxigraph` skill and a loopback AnaxiMCP connection; the analysis engine and
durable index remain in the AnaxiGraph service.

The plugin does not duplicate scanning logic, bundle a model, or require an AnaxiGraph API key.
When the skill builds semantic dossiers, the connected coding agent reads bounded evidence with
its own context and tokens and writes validated interpretations back to AnaxiIndex.

## Start AnaxiGraph

Run this from the repository the agent will work on:

```bash
uvx anaxigraph up . --semantic agent
```

The dashboard and MCP endpoint are available on loopback at
<http://127.0.0.1:8765> and <http://127.0.0.1:8765/mcp>. Keep this process running while the coding
agent uses the plugin. The Docker sidecar exposes the same endpoint.

## Install for Codex

Add this GitHub repository as a marketplace and install the plugin:

```bash
codex plugin marketplace add hcekne/anaxigraph
codex plugin add anaxigraph@anaxigraph
```

Then start or restart Codex in the repository you intend to change and invoke the skill:

```text
$anaxigraph map this repository and explain where a new export feature should go
```

The plugin contributes the `anaxigraph` MCP server definition and the `$anaxigraph` workflow.
Codex may ask you to approve the local MCP connection during installation or first use.

## Install for Claude Code

Add the repository marketplace and install the same plugin package:

```bash
claude plugin marketplace add hcekne/anaxigraph
claude plugin install anaxigraph@anaxigraph --scope user
```

Start or restart Claude Code in the target repository, then invoke the namespaced skill:

```text
/anaxigraph:anaxigraph map this repository and ground my next change in its architecture
```

Use a project installation instead of `--scope user` when the team deliberately wants a
reviewable, repository-scoped plugin configuration.

## What the skill does

The skill first calls `ANAXIGRAPH_REPOSITORIES` and matches the agent's current working tree to a
canonical indexed repository. It never silently chooses a similarly named repository. It then
routes the request through a bounded workflow:

- repository explanation uses overview, semantic status, and explicit analyzer/resolution caveats;
- feature and refactor planning uses search, scope, file, and impact evidence;
- architecture review starts with the bounded attention queue and retrieves detailed finding
  context only for a selected signal;
- post-change verification preserves the scope packet's versioned baseline, requests an allowed
  deterministic rescan, and passes that baseline back to the same-goal scope query for a bounded
  module, finding, and reviewed-pattern comparison; and
- semantic bootstrap follows the live server contract in the exact order
  `SCHEMA -> WORK -> every EVIDENCE page -> SUBMIT`, repeating until no work remains.

Semantic work is considered stored only when AnaxiMCP returns `status: completed` or
`status: already_completed`. If a model call ran but timed out or returned an invalid result, the
skill reports that one failed attempt with any executor-reported token use; other jobs in the wave
continue. If the agent is interrupted before model work starts, it releases the job without
counting a failure. A later session asks for work again and naturally resumes the unfinished
baseline. It never submits with an expired or superseded lease token.

Static graph evidence is deliberately conservative. A missing edge is not proof of dead code,
and a finding or model dossier is not automatic permission to refactor or delete source. The
skill keeps semantic mapping separate from source editing and reports uncertainty where dynamic
runtime wiring may be invisible.

## Use a different endpoint

The packaged connection deliberately defaults to `http://127.0.0.1:8765/mcp`, which is safe for
the local sidecar path. If the coding agent runs in another container, on another host, or through
a forwarded port, configure that endpoint with AnaxiGraph's explicit client connector instead:

```bash
anaxigraph init . --semantic agent --connect codex \
  --mcp-url http://anaxigraph:8765/mcp
```

For Claude Code, replace `codex` with `claude`. Keep the service on loopback or behind a trusted
SSH tunnel; do not expose it on a shared network.

## Maintainer validation

The repository keeps Codex and Claude manifests, the shared skill, icons, MCP definition, and
project version under one contract. Validate and build the deterministic distributable ZIP with:

```bash
uv run python scripts/check_agent_package.py
uv run python scripts/build_agent_plugin.py \
  --output dist/anaxigraph-agent-plugin-0.3.0.zip
```

The pre-commit and release workflows run the same validation. The release workflow includes the
plugin ZIP in `SHA256SUMS` alongside the Python artifacts.

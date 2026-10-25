# AnaxiGraph V2

AnaxiGraph helps people and coding agents write better code, make sound architecture decisions,
and leave subsequent changes straightforward.

This is the clean replacement core targeting **anaxigraph 1.0**. The first milestone is a local
`1.0.0a1` alpha, separate from the existing 0.9.1 package. Features are added selectively; this
folder does not import the old runtime or automatically replace an installed service.

## Run with uv

From this repository:

```bash
cd anaxigraph-v2
uv sync --locked
uv run anaxigraph scan --repo /absolute/path/to/your/repo
uv run anaxigraph serve --repo /absolute/path/to/your/repo
```

Open <http://127.0.0.1:8766>. The dashboard uses the same application as CLI and MCP. It includes a
sortable module table, expandable evidence, focused dependency graph, agent-review workflows and
change guidance. Structural results are available before semantic analysis.

From another working directory, use `uv run --project /absolute/path/to/anaxigraph-v2 anaxigraph ...`.
`--project` selects the environment; it does not change the working directory or the target repo.
Always give `--repo` explicitly in agent configuration. See [uv's command reference](https://docs.astral.sh/uv/reference/cli/).

## Connect an agent through MCP

Use this stdio configuration, replacing both absolute paths:

```json
{
  "mcpServers": {
    "anaxigraph-v2": {
      "command": "uv",
      "args": [
        "run", "--project", "/absolute/path/to/anaxigraph-v2",
        "anaxigraph", "--repo", "/absolute/path/to/your/repo", "mcp"
      ]
    }
  }
}
```

The everyday loop is `scan` → `prepare_change` → focused `inspect` → edit → `scan` →
`validate_change`. `assess_plan` checks proposed file placement before a substantial change.
`modules` lists the inventory; `reviews` finds saved proposals. The server never executes target
project code. Test/type/lint receipts supplied by an agent or CI are attributed reports, bound to
the exact snapshot ID. Missing checks remain unchecked; stale receipts cannot pass the candidate.

## Ask for semantics, Patterns or Fresh Eyes

Model reasoning is agent-driven in this milestone. AnaxiGraph supplies explicit packets, validates
coverage and evidence, and saves results. It does not silently pretend a review ran.

```bash
uv run anaxigraph request annotate --repo /path/to/repo --scope src/example.py > /tmp/task.json
# Give the packet and response_schema to a coding agent; save its JSON response.
uv run anaxigraph submit REQUEST_ID /tmp/result.json --repo /path/to/repo
uv run anaxigraph request patterns --repo /path/to/repo --scope src/example.py
uv run anaxigraph request fresh-eyes --repo /path/to/repo
uv run anaxigraph reviews --repo /path/to/repo
uv run anaxigraph inspect review:REVIEW_ID --repo /path/to/repo
```

Requests survive application restart. Annotate/Pattern scopes accept module IDs or relative paths,
up to four modules per batch; an omitted scope selects the first module. Fresh Eyes defaults to
all mapped modules and requires current behavior annotations for every selected module. Explicit
packet size limits can require smaller scopes. Source packets are larger intentional expansions;
ordinary inventories and review lists stay compact.
Saved reviews retain their original results and disclose stale source, semantic, catalogue or
prompt inputs separately from structural readiness.

- **Annotations:** one module sentence, a short paragraph, one sentence for every supplied function,
  capabilities, uncertainty and contracts with declared/inferred basis and source references.
- **Patterns:** every one of the 133 catalogue cards against every selected module, including a
  rating or unknown, current fit, specific pros, costs, a simpler alternative and evidence. Positive
  ratings require a proposed incremental change; an already useful pattern is not itself a reason
  to rewrite. Validation rejects
  missing or duplicate pairs. This establishes declared coverage, not recommendation quality.
- **Fresh Eyes:** only functional statements with opaque requirement IDs. Give the returned packet
  to a fresh worker **without repository/source tools**. Do not append source or dependency context.
  Each of three alternatives must cover all supplied requirements, explain tradeoffs and include a
  high-level Mermaid diagram. The server cannot sandbox an external agent or prove architectural
  novelty; the packet and coverage checks make that boundary explicit. It retains all alternatives.

The dashboard can copy these tasks, accept result JSON and display saved proposals. Pattern ratings
remain hypotheses. Source-aware verification of a frozen alternative is separate from blind design.

## What the first milestone supports

Python/PYI structure, signatures, scoped imports/calls/references, module dependency projections,
observed test links, compact saved semantics, basic lexical/symbol guidance, placement assessment,
current/previous comparison, and agent/CI check attribution. Source is parsed, never imported.

Working-tree fingerprints include eligible untracked changes and distinguish exact worktrees.
Status describes the saved snapshot; scan after editing to refresh source facts.
Dynamic targets, parse errors and unsupported languages remain explicit. JavaScript/TypeScript
are fingerprinted but **not parsed** yet. Missing references do not establish dead code. Placement
assessment is advisory; behavioral correctness and architectural usefulness require real review.

Current understanding lives in `.anaxigraph-v2/knowledge.sqlite`, with a default 100 MB database
ceiling. The store retains current plus previous graph, canonical annotations, up to 64 recent task
packets and 20 completed reviews per checkout. Unchanged repeated cycles do not append history;
failed capacity writes preserve the last valid graph. Old requests/results can expire with bounded
retention. This alpha workspace is not a permanent saved-analysis archive.

Git-portable records, importing legacy paid analyses, shared worktree bases, autonomous model pools,
production deployment and additional languages are later choices. Existing saved analyses are left
intact. Full old-feature parity is not the objective of this first milestone.

## Components and tests

Six components have explicit boundaries: contracts, indexing, storage, analysis, application and
interfaces. See [architecture, component contracts and packaging direction](docs/architecture.md).

From this folder:

```bash
uv sync --locked --extra dev
uv run pytest
uv run ruff check src tests
uv build
```

Tests cover actual Git/worktrees, unresolved references, malformed/incomplete results, dependency
freshness, interrupted/repeated persistence, storage-full rollback, source-blind packets, receipts,
transport contracts and component import boundaries. Browser and actual MCP stdio smoke evidence
is recorded separately from unit tests and live model behavior. No claim of improved agent success
or architectural novelty is made from these checks alone.

## PyPI destination

The existing project name remains `anaxigraph`; this folder has its own uv environment and alpha
metadata. Once the selected product is qualified, it can replace the release-root implementation
and publish as `anaxigraph==1.0.0` using the existing publisher. Older versions need not be deleted.
No new release is published by this milestone.

# Architecture

AnaxiGraph is one process with deliberately boring boundaries. The CLI, REST API, dashboard, and
AnaxiMCP all call the same application functions. Extraction adapters return provider-neutral
records; the scanner resolves those records into AnaxiIndex, a temporal SQLite graph;
architecture and agent services query that index.

```text
target Git repository (read-only)
             │
             ▼
  language / coverage / Git adapters
             │ deterministic facts + evidence
             ▼
      incremental scanner ───────── semantic planner / durable queue
             │                         │                    │
             │                         ▼                    ▼
             │               provider-neutral       connected coding agent
             │                model adapters          through AnaxiMCP
             │                         │ dossiers + provenance │
             └──────────────┬──────────┴──────────────────────┘
                            ▼
                  AnaxiIndex (SQLite)
                       │          │
                       ▼          ▼
             architecture rules  agent scope/impact
                       │          │
                       └────┬─────┘
                            ▼
              CLI / REST / dashboard / AnaxiMCP
```

Dependency direction inside the package is:

```text
cli / api / mcp_server → scanner / agent → analyzers / architecture / storage
```

In multi-repository mode, an operator-owned YAML registry maps stable keys to read-only container
paths, per-repository policy files, and Git history sample budgets. One service and one SQLite
database hold all repositories, while every dashboard, REST, and MCP query remains repository
scoped. The web process can refresh registered targets but cannot add arbitrary filesystem paths.

The target repository is never imported or executed. Working-tree scanning reads regular,
non-symlink files; historical scanning uses `git ls-tree` and `git show` without checkout. The
SQLite database is external by default under the user's state directory.

Deterministic parser facts and probabilistic semantic claims never share a provenance record.
Relationship rows name their evidence source and confidence. Semantic rows name provider, model,
prompt version, time, confidence, and supporting evidence.

Semantic enrollment has three barriers: all intrinsic module dossiers, all contextual module
dossiers, then group/repository synthesis. Structural hashes invalidate source-bound
understanding; interface, relationship, neighbour-intent, model, prompt, and schema fingerprints
invalidate context without blindly rereading source. SQLite jobs carry priorities, attempts,
token/cost estimates, and renewable worker leases, making the pipeline resumable across process
and coding-agent restarts.

The target-code boundary remains read-only. Most AnaxiMCP tools only retrieve current dossiers and
use them in task-file ranking. A repository may explicitly select `semantic.provider: agent` to
enable an index-only write path: AnaxiMCP leases a prepared job, the connected coding agent reasons
with its own model and tokens, and SUBMIT writes a schema-validated interpretation to AnaxiIndex.
Opaque expiring lease tokens, repository/snapshot checks, strict dossier validation, MCP write
annotations, and the repository allowlist bound that path. Hosted and CLI providers remain a
separate executor option for unattended work.

# AnaxiIndex data model

AnaxiIndex is AnaxiGraph's persistent repository memory. Its SQLite schema is created idempotently
by `anaxigraph.storage.AnaxiIndex`. It is temporal rather than a mutable file catalogue: every
module keeps stable identity while its versions, intent, relationships, metrics, findings, and
history accumulate over time.

| Table | Identity and purpose |
|---|---|
| `repositories` | One analyzed target and its remote/default branch metadata |
| `snapshots` | One content fingerprint at a commit or working tree |
| `artifacts` | Persistent file identity, including first seen/deleted commits |
| `file_facts` | Immutable analyzed facts keyed by artifact, content, analyzer, and policy identity |
| `fact_symbols` | Functions, methods, classes, components, endpoints, and models belonging to immutable facts |
| `snapshot_file_changes` | Sparse add/change/delete placement transitions between snapshots |
| `relationship_sets` / `relationship_edges` | Reusable resolver-context results and their imports, calls, extensions, and references with provenance/evidence |
| `snapshot_relationship_changes` | Sparse selection/retraction of a relationship set for each source artifact |
| `snapshot_checkpoints` / `checkpoint_*` | Disposable references that bound reconstruction to at most 16 deltas |
| `groups` | Declared architecture intent and deterministic path hierarchy; current placement is reconstructed rather than stored as another fact |
| `metrics` | Repository and artifact measurements for temporal trends |
| `coverage_measurements` | Node and conservatively proven relationship coverage |
| `findings` / `finding_occurrences` | Stable findings and lifecycle across snapshots |
| `analysis_runs` | Operational audit of explicit and meaningful scan/update/review/history work plus the latest unchanged watcher heartbeat per repository |
| `architecture_rules` | Effective built-in and configured machine-readable policy |
| `semantic_claims` | Compact current module claims used by inventory queries |
| `semantic_documents` | Immutable intrinsic/contextual dossiers, group synthesis, Living Architecture Charters, and optional declared Charter corrections with fingerprints, provenance, evidence, tokens, and costs |
| `semantic_jobs` | Durable prioritized work queue with lifecycle, cost, executor, and lease evidence; full packets remain for actionable/failed work while terminal duplicate metadata is compacted |
| `semantic_scope_states` | Current per-snapshot semantic coverage and document pointers for modules, groups, and repository |
| `semantic_taxonomies` | Snapshot-scoped proposal/review/finalization record with provider provenance, validation summary, facets, and temporal map changes |
| `semantic_taxonomy_nodes` | Stable responsibility-based area and subsystem identities with evidence and confidence |
| `semantic_taxonomy_memberships` | Exactly one primary subsystem per eligible artifact, including repair/lock provenance and alternatives |
| `semantic_taxonomy_reviews` | Ordered autonomous critic passes and deterministic validation results |
| `git_changes` | Bounded file-level commit/change history used for churn and age |

Schema 7 introduced the canonical temporal representation; Schema 8 added direct `file_fact_id`
provenance to every module-scoped semantic claim, document, job, and scope state. Schema 9 makes
that fact identity authoritative and compacts the duplicated materialized frames. Schema 10 adds
the autonomous semantic taxonomy, its exact primary memberships, and critic audit trail. Current
Schema 10 indexes contain 30 product tables. `file_facts` stores each analyzed
artifact/raw/analyzer identity once, `fact_symbols` belongs to that immutable fact, and
`snapshot_file_changes` records only add/change/delete placement transitions.
Relationship edges are grouped into content-deduplicated immutable `relationship_sets`;
`snapshot_relationship_changes` selects or retracts a set for each source.

The scanner writes immutable file facts, symbol facts, relationship sets, and sparse snapshot deltas
directly. It does not materialize `file_versions`, `symbols`, `relationships`, or
`group_memberships`. Those names survive only in migration readers for released indexes; an older
upgraded database may retain the four empty tables as compatibility tombstones, while a fresh index
does not create them. REST, MCP, dashboard, semantic, finding, history, scope, impact, and
architecture evaluation all consume canonical facts or connection-local temporary projections.
`doctor` therefore reports `canonical_only`, validates a stored digest over
facts/deltas/sets/edges, checks semantic-fact references, and verifies the schema-6 recovery backup.
Raw hash equality skips extraction. Structural hash equality after a raw change performs only
deterministic metadata/documentation refresh and reuses semantic claims.
The deterministic architecture-vocabulary version is part of the scan signature. Changing that
vocabulary therefore creates an honest placement transition while reusing unchanged parser work;
old history frames retain the categories they were actually saved with.

`module_search` is a disposable, repository- and snapshot-scoped SQLite FTS5 read model over paths,
names, symbols, deterministic summaries, current AI descriptions, responsibilities, contracts, and
normalized aliases. Its contract identity and refresh state live in `schema_meta`; it is rebuilt
from canonical facts and current semantic documents, so it does not increment the product schema
or become another source of truth. CLI, REST, MCP, dashboard discovery, and goal scoping all use
this projection before any graph expansion. Exact paths, filenames, and symbols receive explicit
deterministic boosts, while every result reports whether semantic and responsibility evidence was
present. A current query reads only a limited FTS candidate page and the matching module records;
it does not reread repository files or walk every saved dossier in Python.

Responsibility maps use four public layers. The **declared map** is optional team intent from
repository policy. The **path map** is deterministic fallback grouping and carries no claim about
meaning. The **inferred responsibility map** is the AI-reviewed area/subsystem interpretation with
stable node keys, separate display labels, confidence, and evidence. The default **current view**
chooses declared placement for each file, then a current inferred responsibility, then path
fallback. Historical facts keep their original placement, while graph replay defaults to projecting
older files through today's stable current-view identities and exposes the original placement
alongside it.

Analyzer facts conform to `anaxigraph-ir-v1`. Fact JSON keeps only non-derivable IR/analyzer state;
module identity, default dependency fields, exports, and symbol details are reconstructed from
artifact paths, typed columns, and `fact_symbols` at the persistence boundary. A tested codec
reconstructs the complete IR during incremental reuse; metadata is not an unversioned dumping
ground. See [`ADR 0001`](adr/0001-internal-layers-and-analyzer-ir.md).
The direct canonical scan decision and its migration boundary are recorded in
[`ADR 0003`](adr/0003-direct-canonical-scan-persistence.md).

Semantic documents are immutable interpretations. A scope-state row points at the intrinsic and
contextual documents current for one snapshot. Matching input hashes reuse an older document;
structural or analyzer changes enqueue new source understanding, while dependency/interface or
neighbour-intent changes enqueue only contextual understanding. Input identities are stage-specific
and exclude provider/model: executor changes alter provenance, not freshness. A compatibility
matcher proves unchanged v4 evidence reusable under the stable signatures without rewriting the
immutable document. Current module dossiers and graph evidence feed a complete area/subsystem
proposal; critic jobs return corrected complete maps, and deterministic validation enforces exact
primary membership before finalization. Group and repository documents are then synthesized from
the semantic taxonomy and child dossier fingerprints rather than from another full source pass.
Repository synthesis stores `architecture-charter-v1`, including its behavior-only
`capability-brief-v1`. Current reads project that same Charter through dashboard, CLI, REST, and
MCP with one identity and an explicit provisional/current/stale state. Optional declared overlays
reuse immutable `semantic_documents` with `document_kind = charter_correction`; they retain the
inferred claim and chain superseding corrections instead of creating a mutable architecture table.

In agent-funded mode, only a SHA-256 digest of the opaque submission token is stored. The token is
scoped to one job and lease; the completed document retains the reported executor label/model for
audit. Unreported coding-agent token use remains zero rather than being estimated as an
AnaxiGraph-hosted model cost.

Findings use a rule-derived stable key. A recurring resolved finding becomes `regressed`; a finding
not observed in the next complete architecture evaluation becomes `resolved`. Dismissed findings
remain dismissed unless a human changes their state. Deterministic history imports record an
occurrence for each retained frame without changing the live attention queue. The selected finding
handoff follows the current snapshot lineage and reports the first retained appearance,
disappearance, and later return. A version marker in snapshot metadata distinguishes a true absence
from an older frame created before per-frame finding observations were recorded.

## Schema evolution and compatibility

Schema migrations fail closed. The current schema is 10; schemas 2, 6, 7, 8, 9, and 10 are the
explicitly tested inputs. Versions 3–5 were never released as migration contracts and are not
guessed at, while a future schema is never opened by an older binary. Before a schema-6 index is
upgraded, SQLite's online-backup API creates and validates an untouched recovery copy. A committed
`schema_migrations` audit row retains the source/target versions, backup path/checksum/size, and
completion time. `anaxigraph doctor` validates that record and exact legacy/canonical frame parity
without modifying the index. The v2 fixture verifies repository preservation, and the schema-6
fixture verifies exact files, symbols, relationship evidence, semantic provenance, canonical
compaction, and temporal reconstruction across the upgrade and restore path.

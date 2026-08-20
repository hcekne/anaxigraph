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
| `groups` | Declared and inferred architecture hierarchy; active assignment is reconstructed from file placement |
| `file_versions` / `symbols` / `relationships` / `group_memberships` | Empty transaction-local staging surfaces cleared after each atomic scan; never product read models |
| `metrics` | Repository and artifact measurements for temporal trends |
| `coverage_measurements` | Node and conservatively proven relationship coverage |
| `findings` / `finding_occurrences` | Stable findings and lifecycle across snapshots |
| `analysis_runs` | Operational audit of every scan/update/review/history run |
| `architecture_rules` | Effective built-in and configured machine-readable policy |
| `semantic_claims` | Compact current module claims used by inventory queries |
| `semantic_documents` | Immutable intrinsic, contextual, group, and repository dossiers with fingerprints, provider/executor provenance, evidence, tokens, and costs |
| `semantic_jobs` | Durable prioritized work queue with invalidation reason, attempts, estimates, result/error state, executor identity, and expiring worker/agent lease |
| `semantic_scope_states` | Current per-snapshot semantic coverage and document pointers for modules, groups, and repository |
| `git_changes` | Bounded file-level commit/change history used for churn and age |

Schema 7 introduced the canonical temporal representation; Schema 8 added direct `file_fact_id`
provenance to every module-scoped semantic claim, document, job, and scope state. Schema 9 makes
that fact identity authoritative and compacts the duplicated materialized frames. `file_facts`
stores each analyzed artifact/raw/analyzer identity once, `fact_symbols` belongs to that immutable
fact, and `snapshot_file_changes` records only add/change/delete placement transitions.
Relationship edges are grouped into content-deduplicated immutable `relationship_sets`;
`snapshot_relationship_changes` selects or retracts a set for each source.

Snapshot reads are reconstructed through the persistence abstraction. The old materialized tables
are populated only inside the scan transaction because deterministic detectors still consume that
projection, then exact parity is checked and every row is cleared before commit. REST, MCP,
dashboard, semantic, finding, history, scope, and impact reads consume canonical facts or temporary
canonical projections. `doctor` therefore reports `canonical_only`, validates a stored digest over
facts/deltas/sets/edges, checks semantic-fact references, and verifies the schema-6 recovery backup.
Raw hash equality skips extraction. Structural hash equality after a raw change performs only
deterministic metadata/documentation refresh and reuses semantic claims.

Analyzer facts conform to `anaxigraph-ir-v1`. Fact JSON keeps only non-derivable IR/analyzer state;
module identity, default dependency fields, exports, and symbol details are reconstructed from
artifact paths, typed columns, and `fact_symbols` at the persistence boundary. A tested codec
reconstructs the complete IR during incremental reuse; metadata is not an unversioned dumping
ground. See [`ADR 0001`](adr/0001-internal-layers-and-analyzer-ir.md).

Semantic documents are immutable interpretations. A scope-state row points at the intrinsic and
contextual documents current for one snapshot. Matching input hashes reuse an older document;
structural or policy changes enqueue new source understanding, while dependency/interface or
neighbour-intent changes enqueue only contextual understanding. Group and repository documents
are synthesized from child dossier fingerprints rather than from another full source pass.

In agent-funded mode, only a SHA-256 digest of the opaque submission token is stored. The token is
scoped to one job and lease; the completed document retains the reported executor label/model for
audit. Unreported coding-agent token use remains zero rather than being estimated as an
AnaxiGraph-hosted model cost.

Findings use a rule-derived stable key. A recurring resolved finding becomes `regressed`; a finding
not observed in the next complete architecture evaluation becomes `resolved`. Dismissed findings
remain dismissed unless a human changes their state.

Schema migrations fail closed. The current schema is 9; schemas 2, 6, 7, 8, and 9 are the
explicitly tested inputs. Versions 3–5 were never released as migration contracts and are not
guessed at, while a future schema is never opened by an older binary. Before a schema-6 index is
upgraded, SQLite's online-backup API creates and validates an untouched recovery copy. A committed
`schema_migrations` audit row retains the source/target versions, backup path/checksum/size, and
completion time. `anaxigraph doctor` validates that record and exact legacy/canonical frame parity
without modifying the index. The v2 fixture verifies repository preservation, and the schema-6
fixture verifies exact files, symbols, relationship evidence, semantic provenance, canonical
compaction, and temporal reconstruction across the upgrade and restore path.

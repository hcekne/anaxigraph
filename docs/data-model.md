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
| `file_versions` | Complete per-snapshot file state, hashes, metrics, summaries, and groups |
| `symbols` | Functions, methods, classes, components, endpoints, and models |
| `relationships` | Imports, calls, extensions, and references with source/confidence/evidence |
| `groups` / `group_memberships` | Declared and inferred hierarchy kept separately |
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

Schema 7 introduced dual-written compatibility frames and a canonical temporal representation.
Schema 8 adds direct `file_fact_id` provenance to every module-scoped semantic claim, document,
job, and scope state. `file_facts` stores each analyzed artifact/raw/analyzer identity
once, `fact_symbols` belongs to that immutable fact, and `snapshot_file_changes` records only
add/change/delete placement transitions. Relationship edges are grouped into immutable
`relationship_sets`; `snapshot_relationship_changes` selects or retracts a set for each source.
Snapshot reads are reconstructed through the persistence abstraction and are tested frame-for-frame
against the compatibility tables before those duplicate rows may be compacted.

The compatibility `file_versions`, `symbols`, and `relationships` tables still contain complete
frames during this validation window. They are not the final scaling model and must not be removed
until `doctor` reports successful migration and the complete Phase 1b compaction gate passes. The
doctor report now validates semantic-fact references in addition to temporal parity, and the
schema-6 recovery backup is retained. Raw hash equality skips extraction. Structural hash
equality after a raw change performs only deterministic metadata/documentation refresh and reuses
semantic claims.

Analyzer facts conform to `anaxigraph-ir-v1`. During the final compatibility window, additional
contract fields are still mirrored in `file_versions.metadata_json.ir`: IR/analyzer versions,
module identity and aliases, resolver inputs, parse status, exports, and symbol visibility/columns.
The ordinary columns and `symbols` table remain the query-efficient v1 projection. A tested codec
reconstructs the complete IR during incremental reuse; the metadata is not an unversioned dumping
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

Schema migrations fail closed. The current schema is 7; released schemas 2 and 6 plus current schema
7 are the explicitly tested inputs. Versions 3–5 were never released as migration contracts and are
not guessed at, while a future schema is never opened by an older binary. Before a schema-6 index is
upgraded, SQLite's online-backup API creates and validates an untouched recovery copy. A committed
`schema_migrations` audit row retains the source/target versions, backup path/checksum/size, and
completion time. `anaxigraph doctor` validates that record and exact legacy/canonical frame parity
without modifying the index. The v2 fixture verifies repository preservation, and the schema-6
fixture verifies exact files, symbols, relationship evidence, and temporal reconstruction across
the upgrade and restore path.

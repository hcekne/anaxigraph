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

Every current snapshot contains a complete set of `file_versions`, but unchanged versions are
cloned from the prior analysis rather than reparsed. That keeps queries simple while preserving
incremental behavior. Raw hash equality skips extraction. Structural hash equality after a raw
change performs only deterministic metadata/documentation refresh and reuses semantic claims.

Analyzer facts conform to `anaxigraph-ir-v1`. Until Phase 1b normalizes the temporal storage model,
the additional contract fields live in `file_versions.metadata_json.ir`: IR/analyzer versions,
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

Schema migrations fail closed. The current schema is 6; released schema 2 and current schema 6 are
the explicitly tested inputs. Versions 3–5 were never released as migration contracts and are not
guessed at, while a future schema is never opened by an older binary. The v2 fixture verifies data
preservation and every column added by the semantic queue/agent provenance migration.

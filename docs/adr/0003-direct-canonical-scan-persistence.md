# ADR 0003: write scans directly to canonical temporal facts

- Status: accepted
- Date: 2026-08-30

## Context

Schema 7 made immutable file facts, fact symbols, relationship sets, and sparse snapshot deltas the
authoritative AnaxiIndex model. The scanner nevertheless continued to materialize complete
`file_versions`, `symbols`, and `relationships` frames, translate that frame into the canonical
model, and delete it in the same transaction. `group_memberships` was retained as a fourth empty
compatibility table. Product reads and deterministic architecture evaluation already used canonical
facts or connection-local `projected_*` read adapters.

The detour duplicated every changed frame, made the write path harder to explain, and forced four
tables into every new index solely for runtime staging. Released schemas 2 and 6 still require those
shapes as migration inputs.

## Decision

Current scans write prepared analysis directly to `file_facts` and `fact_symbols`, record sparse
file placement changes, resolve dependencies directly into immutable relationship sets, and record
sparse relationship selections. A fresh index does not create `file_versions`, `symbols`,
`relationships`, or `group_memberships`.

Legacy table readers, parity validation, and compaction remain migration-bound code. Existing
upgraded indexes may retain the four tables empty because released semantic foreign keys can name
them. The scanner never repopulates those tombstones. Connection-local `projected_*` tables remain
valid read adapters because they are reconstructed from canonical facts and are never persistent
sources of truth.

## Consequences

- Fresh AnaxiIndex databases contain 30 product tables rather than 34.
- One complete write/translate/delete pass disappears from every new snapshot transaction.
- Architecture rules, REST, MCP, dashboard, history, findings, coverage, and semantics continue to
  read the same canonical evidence.
- The stored canonical digest is refreshed after a successful scan, preserving `doctor` integrity
  checks without compatibility-row compaction.
- Schema-2 and schema-6 migration fixtures remain mandatory. Migration code must not leak back into
  the current scanner path.
- Removing the empty tombstone tables from an already-upgraded database is deferred until a future
  schema migration can rebuild every released foreign-key declaration safely and recoverably.

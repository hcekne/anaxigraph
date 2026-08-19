# AnaxiIndex data model

AnaxiIndex is AnaxiGraph's persistent repository memory. Its SQLite schema is created idempotently
by `codeintel.storage.AnaxiIndex` (`Database` remains a compatibility alias). It is temporal rather
than a mutable file catalogue: every module keeps stable identity while its versions, intent,
relationships, metrics, findings, and history accumulate over time.

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
| `semantic_claims` | LLM claims and full provenance, separate from parser facts |
| `git_changes` | Bounded file-level commit/change history used for churn and age |

Every current snapshot contains a complete set of `file_versions`, but unchanged versions are
cloned from the prior analysis rather than reparsed. That keeps queries simple while preserving
incremental behavior. Raw hash equality skips extraction. Structural hash equality after a raw
change performs only deterministic metadata/documentation refresh and reuses semantic claims.

Findings use a rule-derived stable key. A recurring resolved finding becomes `regressed`; a finding
not observed in the next complete architecture evaluation becomes `resolved`. Dismissed findings
remain dismissed unless a human changes their state.

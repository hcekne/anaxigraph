# ADR 0002: Goal-specific architecture decisions

**Status:** Accepted

**Date:** 25 August 2026

## Context

AnaxiGraph already returns a bounded coding scope, deterministic graph evidence, semantic module
dossiers, and independently reviewed pattern evaluations. Agents otherwise have to assemble these
records themselves before deciding where a change belongs. That repeats policy in each client and
can accidentally treat a model suggestion, an unreviewed pattern assessment, or a missing static
edge as permission to refactor or delete source.

The architecture recommendation must remain part of the map. It must not add another provider
pipeline, persistence model, approval stage, or endpoint, and it must remain useful when semantic
work is incomplete.

## Decision

`ANAXIGRAPH_SCOPE` and the existing REST scope response include an additive
`architecture-decision-v1` object assembled for the requested goal. The goal already determines the
ranked primary modules; the decision composes current evidence for those modules into:

- a preferred placement, semantic placement guidance, extension points, public contracts,
  interfaces, and local precedents;
- one bounded task path from the effective architecture area and subsystem to a selected module
  and only the named symbols whose own source names match the coding goal;
- module contracts, invariants, and change risks;
- patterns worth reusing and pattern opportunities, sourced only from current finalized
  `pattern_review` documents and retaining critique and runtime provenance;
- consolidation advice with supporting evidence, counter-evidence, graph degree, responsibility,
  contracts, placement, and an explicit unavailable state for evidence not yet projected;
- bounded large-file decomposition advice that maps current semantic responsibilities back to
  named symbols, callers, dependencies, contracts, tests, and honest destination modules;
- dead-code candidates with deterministic and semantic evidence kept distinct; and
- focused tests, semantic test guidance, a tokenized rescan command, exact post-change facts, and
  an optional machine-readable comparison with an earlier baseline.

This is an application projection over the current snapshot. It adds no database table, model
call, semantic job, REST route, MCP tool, or dashboard state.

## Evidence and safety rules

The packet preserves the product's fact/interpretation/recommendation boundary:

1. Snapshot hashes, graph degree, interfaces, finding keys, and analyzer capabilities remain
   deterministic facts.
2. Dossier responsibilities, placement, consolidation, and dead-code suggestions remain semantic
   interpretations with their existing provenance.
3. Pattern guidance is admitted only after independent critique has finalized the current review.
4. A semantic dead-code suggestion is corroborated only by a deterministic finding at the same
   granularity. A module finding cannot corroborate a symbol suggestion.
5. Dead-code advice never reports `safe_to_remove: true`; dynamic registration, reflection,
   configuration, generated wiring, and external callers remain explicit checks.
6. A deterministic dead-code candidate requires trusted relationship resolution, no resolved or
   ambiguous inbound path, adequate entry-point and registration analyzer capability, no detected
   dynamic-wiring fact, no configured or conventional entry point, and the configured Git age.
7. Consolidation preserves “keep separate” conclusions and exposes contrary evidence. Missing
   temporal co-change evidence is labeled unavailable rather than inferred.
8. Pattern, consolidation, and possible-unused-code advice includes a versioned plain-language
   projection with a direct conclusion, observations, consequence, action, cautions, and checks.
   Machine statuses and scores remain available for automation but never stand in for that
   explanation or move into a separate jargon drawer. Every unused-code projection says that it
   does not authorize deletion.
9. Scope readiness, preferred placement, and change constraints use the same plain-language
   contract. Tight payloads retain direct scope and placement conclusions before duplicate context
   paths.
10. Early AI notes retained in agent file summaries are explicitly labeled as notes rather than
    instructions. The architecture packet checks them against repository evidence before explaining
    pattern, consolidation, or removal advice, and the dashboard renders it without adding a human
    approval gate.
11. File size starts a decomposition inspection but never creates a split. A candidate requires a
    current dossier, explicit supporting and opposing evidence, at least two named responsibilities,
    and an unambiguous deterministic mapping to symbols for at least two jobs. Cohesive, stale,
    ambiguous, or weak evidence produces a keep-together or insufficient-evidence result.
12. Task navigation uses the finalized AI-reviewed taxonomy when available, configured project
    groups otherwise, and clearly labels a file-path guess. It never invents a symbol match: when
    no symbol name, signature, or summary overlaps the goal, the path ends honestly at the module.

## Bounds and freshness

The decision names its snapshot. Normal scan and semantic fingerprints own invalidation, and exact
target queries reuse the bounded pattern application service. If the scope payload exceeds its
configured byte budget, detailed decision evidence is compacted while contract version, status,
preferred path, focused tests, and rescan guidance remain. The bespoke saved-baseline comparison
described by the original version of this ADR was removed before 1.0: History, findings, graph
deltas, and a refreshed scope already own change evidence, so maintaining a second temporal
protocol made the product harder to use and maintain. `large-file-decomposition-v1` returns at most five
files and five responsibility slices, preserves the extraction order in compact packets, and adds
no semantic job, provider call, persistent state, route, or dashboard screen. `task-path-v1`
returns one area, one subsystem, one module, at most eight matching symbols, and at most ten nearby
files. Normal compaction preserves its reasons, contracts, boundaries, and tests; the 4 KB fallback
keeps only the usable breadcrumb and matching names.

## Consequences

Agents receive a consistent architecture recommendation as a normal consequence of semantic
mapping, without a human review gate. Deterministic-only and partially semantic repositories still
receive an honestly labeled packet. Post-change verification compares the same bounded facts after
a rescan through the existing scope surface; longitudinal temporal outcome correlation remains a
later evidence input rather than a fabricated signal.

The explanation is assembled when current evidence is read. It adds no prompt-signature or
freshness input, so adopting clearer language does not invalidate completed semantic dossiers or
restart repository indexing.

The task path is assembled by the same scope read. The dashboard renders it inside the existing
Agents result and highlights the same files on the existing Map; CLI, REST, and MCP receive the
identical additive object without another endpoint or workflow.

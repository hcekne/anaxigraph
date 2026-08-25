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
9. Scope readiness, preferred placement, change constraints, and before/after verification use the
   same plain-language contract. A same-snapshot comparison says that no post-change observation
   was possible, not that the architecture stayed unchanged. Tight payloads retain the direct scope
   and placement conclusions before duplicate context paths.
10. Early AI notes retained in agent file summaries are explicitly labeled as notes rather than
    instructions. The architecture packet checks them against repository evidence before explaining
    pattern, consolidation, or removal advice, and the dashboard renders it without adding a human
    approval gate.
11. File size starts a decomposition inspection but never creates a split. A candidate requires a
    current dossier, explicit supporting and opposing evidence, at least two named responsibilities,
    and an unambiguous deterministic mapping to symbols for at least two jobs. Cohesive, stale,
    ambiguous, or weak evidence produces a keep-together or insufficient-evidence result.

## Bounds and freshness

The decision names its snapshot and preserves file size, file complexity, direct incoming and
outgoing links, structural hashes, architecture placement, bounded semantic responsibilities,
readable finding evidence, and reviewed-pattern scores in
`architecture-verification-baseline-v2`. The baseline is bound to fingerprints of the repository
and normalized coding goal. After a rescan, a client may pass it back to the same scope request.
The resulting `architecture-verification-comparison-v2` keeps the original module, finding, and
pattern deltas and adds a bounded structural-effects list grouped as `introduced`, `worsened`,
`improved`, `resolved`, or `pre_existing`. Every effect states what changed, why it may matter, the
smallest useful response, why the code may be correct as written, and how to check it.

Those labels describe the direction of indexed evidence. `resolved` means that the current scan no
longer reports the condition; it is not proof that every runtime path is correct. Likewise, a
larger or smaller measurement does not prove the whole design became worse or better. The intended
outcome and focused tests still decide that. Same-snapshot requests return `rescan_required`, and
cross-repository or cross-goal baselines are refused. Version-1 and unversioned baselines remain
readable with explicit caveats and do not invent measurements they never stored.

Normal scan and semantic fingerprints continue to own invalidation; this read model has no
separate freshness mechanism or stored state. Exact target queries reuse the bounded pattern
application service. If the scope payload exceeds its configured byte budget, detailed decision
evidence is compacted while contract version, status, preferred path, comparison summary, and the
highest-priority structural effects remain. `large-file-decomposition-v1` returns at most five
files and five responsibility slices, preserves the extraction order in compact packets, and adds
no semantic job, provider call, persistent state, route, or dashboard screen.

## Consequences

Agents receive a consistent architecture recommendation as a normal consequence of semantic
mapping, without a human review gate. Deterministic-only and partially semantic repositories still
receive an honestly labeled packet. Post-change verification compares the same bounded facts after
a rescan through the existing scope surface; longitudinal temporal outcome correlation remains a
later evidence input rather than a fabricated signal.

The explanation is assembled when current evidence is read. It adds no prompt-signature or
freshness input, so adopting clearer language does not invalidate completed semantic dossiers or
restart repository indexing.

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

## Bounds and freshness

The decision names its snapshot and preserves structural hashes and reviewed-pattern scores as the
versioned `architecture-verification-baseline-v1` pre-change baseline. The baseline is bound to
fingerprints of the repository and normalized coding goal. After a rescan, a client may pass that
baseline back to the same scope request. The resulting
`architecture-verification-comparison-v1` reports newly or no-longer tracked modules, structural,
coupling, and placement changes, newly or no-longer reported findings, and reviewed-pattern score
changes. It says “rescan required” when both packets use the same snapshot and refuses to compare a
baseline from a different repository or goal. A legacy unversioned baseline remains readable with
an explicit identity caveat.

The comparison is observational: “no longer reported” is not mislabeled “resolved,” and any change
is not mislabeled an improvement. Passing tests and a stated expected outcome are still required
to make that judgment. Normal scan and semantic fingerprints continue to own invalidation; this
read model has no separate freshness mechanism or stored state. Exact target queries reuse the
bounded pattern application service. If the scope payload exceeds its configured byte budget,
detailed decision evidence is compacted while contract version, status, preferred path, result
counts, and the post-change comparison summary remain.

## Consequences

Agents receive a consistent architecture recommendation as a normal consequence of semantic
mapping, without a human review gate. Deterministic-only and partially semantic repositories still
receive an honestly labeled packet. Post-change verification compares the same bounded facts after
a rescan through the existing scope surface; longitudinal temporal outcome correlation remains a
later evidence input rather than a fabricated signal.

The explanation is assembled when current evidence is read. It adds no prompt-signature or
freshness input, so adopting clearer language does not invalidate completed semantic dossiers or
restart repository indexing.

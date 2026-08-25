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
- focused tests, semantic test guidance, a tokenized rescan command, and exact post-change facts to
  compare.

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

## Bounds and freshness

The decision names its snapshot and preserves structural hashes and reviewed-pattern scores as the
pre-change baseline. Normal scan and semantic fingerprints continue to own invalidation; this read
model has no separate freshness mechanism. Exact target queries reuse the bounded pattern
application service. If the scope payload exceeds its configured byte budget, detailed decision
evidence is compacted while contract version, status, preferred path, and result counts remain.

## Consequences

Agents receive a consistent architecture recommendation as a normal consequence of semantic
mapping, without a human review gate. Deterministic-only and partially semantic repositories still
receive an honestly labeled packet. Post-change verification can compare the same facts after a
rescan, while temporal outcome correlation remains a later evidence input rather than a fabricated
signal.

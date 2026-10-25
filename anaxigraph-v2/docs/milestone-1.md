# First milestone: a working replacement core

**25 October 2026.** The separate V2 project runs through uv, CLI, MCP and a small dashboard.
The development version is `anaxigraph 1.0.0a1`; this is not a published 1.0 release.

The [architecture](architecture.md) records the maintainer's clean-slate decision and selective
scope. This milestone has **3,513 physical production lines in 23 code files**, including normal
comments/whitespace, embedded SQL, prompts and validation. Tests add 1,503 lines in five files.
The 91,978-byte catalogue is data; neither tests, catalogue, lockfile nor evidence are hidden in
the production count. The broader earlier estimates describe larger products.

## What works

- Python source graph, scope-aware references, explicit unknowns and exact checkout identity.
- One canonical annotation per module, complete supplied-function coverage and context freshness.
- Change preparation, symbol-to-owner reuse, placement assessment and previous-snapshot comparison.
- Fingerprint-attributed agent/CI checks, with unchecked/stale/failed outcomes distinguished.
- Persistent annotation, all-133-card selected-module review and blind three-alternative tasks.
- Shared table, inspector, module rollups and review-expansion workflows across the application.
- Bounded SQLite, atomic capacity failure, cross-process cache invalidation and idempotent retry.

The first milestone deliberately uses external coding agents for model reasoning. It excludes
autonomous provider orchestration, JS/TS parsing, old-data import and Git-portable records. Existing
saved analyses remain separate and intact. These can be selected later without preserving the
entire previous product.

## Measured structural performance

On the actual combined legacy/V2 working tree, **664 Python modules, 5,992 symbols and 69,552
relationships** were captured. **33,337 relationships remain unresolved/ambiguous**: the graph is
useful scoped evidence, not a complete runtime call graph. JS/TS are explicitly unparsed.

| Operation | Measured result |
| --- | ---: |
| Cold structural scan and local publication | 11.650 seconds |
| Unchanged scan | 9.237 seconds |
| Retained current database | 4,780,032 bytes |
| Retained database after unchanged scan | 4,780,032 bytes |
| Warm status, median of five | 49.76 ms |
| Warm module page, median of five | 7.28 ms |
| Warm explicit entity expansion, median of five | 66.32 ms |
| Warm change preparation, median of five | 52.95 ms |

These are normal-disk local measurements of an uncommitted candidate, including its then-current
source. Warm reads are in-process, not HTTP round trips or uv startup. No model work is included.
They are not a speedup claim against the earlier multi-language scan or a forecast for full reviews.

The initial large smoke exposed a 71 MB current graph and slow re-materialization. V2 now stores
canonical compressed node/edge sets inside SQLite with small source indexes, and the application
caches one current materialization. No observations were removed to achieve the reduction.
A separate earlier-candidate representation check retained actual source facts plus a **synthetic** second snapshot
fingerprint in 8,241,152 bytes. That check ran on tmpfs and establishes size, not disk latency.

## Verification

The final local suite passed **106 tests**. Coverage includes real Git/worktree identities, source
containment, missing/duplicate analysis members, malformed JSON values, source/dependency/input
staleness, late-result rejection, consistent reads, storage-full rollback and repeated-cycle stability.
Ruff, JavaScript syntax and existing commit checks also passed.

Actual uv-launched MCP stdio and desktop/mobile browser journeys exercised the real Application.
Semantic browser fixtures were explicitly synthetic; they tested presentation and validation.
Installed-wheel proof ran from outside the repository in an isolated uvx environment, checked
version/import origin, scanned a fixture and loaded all 133 catalogue cards. Runtime contents,
README and license were compared with source. Exact artifact hashes and counts are in
[the machine-readable evidence](milestone-1-evidence.json).

The new [V2 workflow](https://github.com/hcekne/anaxigraph/actions/workflows/v2.yml) runs Python
3.11/3.12 tests, lint, build and an installed-wheel journey. Its live GitHub run is the authority
for CI status; local checks alone do not establish that new automation works.

The first V2 workflow passed both Python versions. Its repository-wide legacy counterpart exposed
an import-root collision between the two independent projects; the root legacy config now scopes
its own application, with an explicit whole-repository override still tested. Its accepted baseline
and thresholds are unchanged. The audit's genuine V2 complexity findings also prompted smaller
request/validation, source-capture, resolution, comparison and rendering functions.

A separate pre-existing legacy CI failure had passed all 1,648 tests but collected zero coverage:
`--cov=anaxigraph` selected the portable-data folder. All four existing command locations now name
`src/anaxigraph`; the normal 80% floor is unchanged. The same small real test reproduced zero
coverage with the old target and 2,480 executed lines with the corrected target. The complete
corrected workflow remains the authority for its final coverage result.

## Live model work and its limits

[Preserved inputs and outputs](evidence/live-review-smoke.json) document three Luna agent tasks:
annotation, blind design and a 133-card review of one early production component. A stronger
Sol/high reviewer then checked the pattern draft. All final results were accepted by the real
application and restored into the final store without additional model work.

The blind worker received eleven behavior requirements and retained three alternatives. That
demonstrates packet/result handling and supplied-requirement coverage, not complete product
discovery or useful whole-system novelty. The external agent's filesystem was restricted by its
task instructions, not by an AnaxiGraph sandbox.

The pattern draft sometimes mistook existing good design for a new opportunity. Prompt clarification
and stronger review changed together, so this is not a controlled model comparison. The review
changed 50 scores, leaving 82 zero, 49 unknown and two conditional low opportunities. It rejected
redundant value-equality advice and retained questions about mutable nested values and the storage
port's observable guarantees. These are hypotheses requiring source/caller inspection.

No controlled study yet proves fewer bugs, faster agent delivery, architectural novelty or an easier
subsequent change. That evaluation should guide which capabilities earn their place next.

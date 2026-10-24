# Dead code detection for AnaxiGraph 0.9.2

**Date:** 24 October 2026

**Audited source:** `986a1a744966a3859cbe48ab22da079f8dcbb637`

Code age does not establish use. AnaxiGraph's primary unused-code analysis should classify
reachability and references immediately, including recently replaced code. Modification dates can
remain context. They should not decide whether a candidate is eligible for analysis.

This research feeds the [0.9.2 performance and architecture request](../design/0.9.2-performance-and-architecture-request.md).
No production code, project dependencies or lockfiles were changed by these checks.

## How established tools approach the problem

| Tool | Method | What its result means |
| --- | --- | --- |
| Vulture | Parses Python ASTs, collects defined and used names, and recognizes some unreachable statements. Its name analysis ignores scopes. | Useful unused-object candidates; dynamic or implicit uses need checking. Its confidence categories are rough tool heuristics. [Official documentation](https://github.com/jendrikseipp/vulture/blob/main/README.md). |
| Knip | Starts from entry files, resolves imports into a graph, then checks files, exports and dependencies. Framework plugins and configuration supply additional roots. | Unreached files or unused exports relative to that configured graph. Missing roots and dynamic references can change the result. [How Knip works](https://knip.dev/explanations/how-knip-works), [entry files](https://knip.dev/explanations/entry-files). |
| Ruff | F401 checks unused imports; F841 checks unused local variables. | Local cleanup and mistakes, not a whole-program unused-function analysis. Public re-exports and signatures have their own obligations. [F401](https://docs.astral.sh/ruff/rules/unused-import/), [F841](https://docs.astral.sh/ruff/rules/unused-variable/). |
| Coverage.py | Records executed lines and can attribute execution to test contexts. | Evidence that code executed during the measured runs. Absence of execution is not proof of unreachability; importing a function executes its definition line without calling its body. [Coverage FAQ](https://coverage.readthedocs.io/en/latest/faq.html), [measurement contexts](https://coverage.readthedocs.io/en/latest/contexts.html). |

Production and test reachability must be distinct. Knip's
[production mode](https://knip.dev/features/production-mode) specifically prevents test imports from
keeping otherwise unused production code classified as live. Tests of an obsolete helper do not
establish that the product still needs it. Conversely, a library's deliberately public contract
can matter even when repository-internal callers are absent.

## Why the existing zero-candidate result is inadequate

The `stale-unreferenced-source` rule defaults to `minimum_age_days=90` in
[architecture_models.py](../../src/anaxigraph/architecture_models.py).
[architecture_dead_code.py](../../src/anaxigraph/architecture_dead_code.py) requires no incoming
references, checks entrypoints/dynamic wiring and scope resolution, and then applies the age cutoff.
Age is an additional veto; it is not the sole check. That veto makes the rule unsuitable for finding
newly superseded runtime code.

In the October 24 snapshot, none of 929 saved Git paths met the 90-day cutoff: the oldest recorded
last-change date was August 19. The report therefore had zero candidates, while also marking three
mixed-language fixture files unassessed. That report cannot establish that the rewrite left no
unused code. Simply shortening the cutoff would leave the conceptual problem in place.

## Actual independent checks

| Check | Result |
| --- | --- |
| Vulture 2.16, production Python, minimum confidence 60 | 56 candidates |
| Vulture including tests, scripts and benchmarks | 78 total; 32 in production |
| Vulture production, confidence 100 | Four candidates; all unsuitable for deletion after source inspection |
| Ruff 0.16.3 F401/F841 | Zero findings |
| Knip 6.43.0, production dashboard | 37 reachable JS files; zero unused files; zero unresolved imports; 11 unused cross-file exports |
| Knip excluding exports used within their own files | One remaining unused helper candidate |

Vulture's four highest-confidence findings demonstrate why a reported unused name is not proof of
a removable contract. Three MCP parameters are forwarded through `options = locals()` and consumed
by `_planning_journey`. The `epoch` argument in worktree discovery deliberately participates in an
`lru_cache` key. Removing those parameters would change working behavior.

The dashboard check used only the two real HTML script roots, `app.js` and `theme-boot.js`, and
resolved the `/assets/` alias. Tests and the Playwright plugin were excluded from production roots.
Ten flagged exports have live uses within their own files; removing their function bodies would
break production. `renderFindingHandoff` also has a direct browser-test consumer. Cleaning an export
is different from deleting an unused function.

Knip ran on temporary Node 22.23.4 after a bounded native-binding installation recovery. An independent
manual Tree-sitter export extraction crashed and contributes no findings. Temporary Node/Knip caches
were removed; reports remain under `/tmp/anaxigraph-knip-audit-20261024/`. Python reports and their
machine-readable summary are under `/tmp/anaxigraph-deadcode-audit-20261024/`.

### Reproduce the checks

These commands report candidates without applying fixes or adding project dependencies:

```bash
uvx --from vulture==2.16 vulture src/anaxigraph --min-confidence 60
uvx --from vulture==2.16 vulture src/anaxigraph tests scripts benchmarks --min-confidence 60
uvx --from vulture==2.16 vulture src/anaxigraph --min-confidence 100
uv run --locked ruff check src/anaxigraph --select F401,F841
```

For Knip, use a supported Node environment (the measured run used 22.23.4), pin Knip 6.43.0,
and pass a temporary configuration whose production entry files are the two dashboard scripts,
project files are `src/anaxigraph/dashboard/**/*.js!`, `/assets/*` resolves to that directory,
and the Playwright plugin is disabled. Include `files`, `exports` and `unresolved` reports.
Run production mode twice, adding `ignoreExportsUsedInFile: true` for the second result. Keep
configuration outside the repository and do not pass an autofix flag.

## Source-checked retirement candidates

These are candidates for the implementation's first deletion experiments, not changes already made.
Definition-line counts describe source spans, not guaranteed net project reductions.

| Candidate | Definition lines | Evidence and verification |
| --- | ---: | --- |
| `semantic_graph._module_priority` | 12 | Only its definition appears across source/tests/scripts/benchmarks. Verify planner behavior and any exposed helper contract. |
| `semantic_records._state_intents` | 14 | Definition only; reads old intrinsic intent state. Exercise semantic reuse and migration after removal. |
| `knowledge_grouping.selected_placement` | 7 | Definition only. Exercise current table/graph placement paths. |
| `semantic_fresh_eyes_contract.review_goal_manifest` | 2 | Definition only; legacy goal helper. Check archived-generation reading. |
| `semantic_fresh_eyes_contract.fresh_eyes_manifest_goal` | 9 | Definition only; legacy manifest lookup. Check archived-generation reading. |
| `dashboard-format.js::detailList` | 4 | No references in production JS/HTML, tests, scripts, benchmarks or docs; Knip agrees. Exercise formatting/rendering consumers. |

The five Python definitions total 44 lines. Additional candidates require an explicit compatibility
or obsolete-test decision:

- `pattern_candidates.py`: an 85-line facade with only tests/docs consuming its API. Its planner
  delegates to the newer catalogue planner; its explanation path overlaps the active query path.
- `semantic_graph._module_scope` and `_interface_hash`: 22 definition lines used by legacy tests.
- Six functions in `semantic_evidence_selection.py` form a 102-line test-only helper cluster:
  `evidence_bytes`, `safe_review_evidence`, `responsibility_memberships`, `select_modules`,
  `bounded_evidence`, `_compact`. Keep the module's live `module_role`, `representative_items` and
  `stable_order` helpers.
- `knowledge_unresolved.all_unresolved_nodes`: a two-line eager-list wrapper consumed only by tests;
  production uses the iterator.

A separate bounded AST import check reached 373 of 375 Python modules from package/CLI/API/MCP
roots. The other resource-package initializer is used through `importlib.resources`; the other
unreached module is the facade above. Import reachability does not prove every function or branch
inside those modules is useful. These checks support a concrete small cleanup list, not a claim
that half the current project is dead.

## Required AnaxiGraph detection model

1. Build real production roots from package entrypoints, CLI dispatch, FastAPI routes, MCP tools,
   worker commands, browser scripts and intentional public exports. Keep test roots separate.
2. Traverse module and symbol references, including callback/registration edges and function-object
   flows. An imported module does not make all its function bodies reachable.
3. Recognize common implicit uses: visitor methods, Pydantic validators/config, SQLite callbacks,
   dataclass serialization, resource strings, reflection and cache-key arguments. Keep uncertain
   dynamic use scoped and visible rather than suppressing the entire repository.
4. Find orphan closures and cycles as well as single definitions: dead helpers calling one another
   can look referenced while remaining unreachable from any product root.
5. Classify unused imports, unreachable code, unreferenced symbols, test-only production code,
   optional live features, compatibility surfaces and unassessed dynamic use separately.
6. Attach entrypoint coverage, known callers, registrations, resolution gaps, tool/version/reason
   and optional runtime coverage to every candidate. Do not turn tool confidence into proof.
7. Verify small reversible deletion/consolidation batches against relevant contracts and real user
   journeys. Retire tests of deliberately removed behavior; preserve tests of required compatibility.

Acceptance must include a freshly introduced unreachable helper being detected immediately and an
old, unchanged, reachable helper remaining live. Include framework callbacks, string registrations,
test-only callers, orphan cycles and incomplete-language-support controls. No waiting period is part
of these decisions.

Full-suite test coverage alone cannot answer whether production still needs a feature. Existing
coverage artifacts can support this work, and separate representative execution contexts can show
which journeys actually use a symbol. Avoid adding a new slow pre-push gate; the cleanup work should
reuse normal focused verification and CI.

## Dead code and architectural simplification are different work

Production grew from 73,885 lines/366 files in 0.8.5 to 79,060/423 in 0.9.1. Removing unused helpers
will help, but large reductions also require consolidating active planners, dispatchers, state
models and compatibility paths. A reachable feature can be unnecessarily complicated; an old reader
can still be essential to preserve paid analyses. The 0.9.2 retirement ledger must distinguish
those cases before claiming a 50% reduction.

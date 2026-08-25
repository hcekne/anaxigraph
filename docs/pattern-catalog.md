# Pattern catalog

AnaxiGraph ships a declarative catalog of 128 coding patterns. The catalog is evidence guidance for
the pattern intelligence pipeline: it does not execute or modify an analyzed repository, and it does
not create one Python detector class per pattern.

The baseline is deliberately broad enough to reason at different scales:

| Family | Cards | Typical levels |
|---|---:|---|
| Function construction | 16 | symbol, type, module |
| Object and interface design | 16 | symbol, type, module |
| Data and state | 16 | symbol, type, module, subsystem |
| Module boundaries | 16 | type, module, subsystem, area |
| Composition and workflow | 16 | symbol, type, module, subsystem |
| Integration and concurrency | 16 | symbol, type, module, subsystem |
| Reliability and testing | 16 | symbol, type, module, subsystem |
| Subsystem architecture | 16 | subsystem, area, repository |

The 128-card baseline is a minimum shipped set, not a maximum. `load_pattern_catalog()` accepts any
positive number of valid cards within the operator-selected byte bound. Adding a card does not
require a database migration, route, dashboard component, provider integration, or Python detector.

## Version boundaries

Three identities evolve independently:

- `pattern-card-v1` is the expanded card schema consumed by pattern intelligence;
- `pattern-catalog-source-v1` is the compact source-file format, including family defaults;
- `pattern-catalog-loader-v1` is the implementation that expands and validates source files.

The bundled content has its own catalog version, currently `2026.08.2`. Change that version when
card content changes. Change a schema or loader version only when its corresponding contract changes.
The catalog fingerprint is derived from the fully expanded, sorted cards, so formatting and source
file ordering do not change its identity.

## Source layout

Bundled sources live in `src/anaxigraph/catalog/patterns-*.json`. Each source declares one family,
shared defaults, and a non-empty `cards` list. Defaults are shallow-merged into each card; `relations`
and `scoring` are merged separately so a card can override one category without copying the others.

Every expanded card contains:

- a stable key, positive card version, unique name, family, constructive/failure-mode kind, and intent;
- canonically ordered target levels from symbol through repository;
- structured problem, supporting, and counter-evidence signals;
- sorted analyzer capability requirements;
- semantic questions for evidence that deterministic analysis cannot settle;
- related, complementary, alternative, and conflicting stable pattern keys;
- independent applicability, suitability, conformance, and opportunity guidance;
- benefits, liabilities, migration cautions, verification invariants, and references.

Signals use a feature name, operator, optional value, and weight. Supported operators are
`available`, `unavailable`, `exists`, `contains`, `eq`, `neq`, `gt`, `gte`, `lt`, `lte`,
`count_gte`, and `count_lte`. Capability facts come from the versioned analyzer capability contract;
a card cannot silently demand evidence that no analyzer knows how to declare.

## Add or extend a catalog

Use a `patterns-*.json` filename and keep every stable key globally unique. A new family source can
reuse this compact shape:

```json
{
  "format_version": "pattern-catalog-source-v1",
  "card_schema_version": "pattern-card-v1",
  "catalog_version": "2026.08.2",
  "family": "example_family",
  "defaults": {
    "schema_version": "pattern-card-v1",
    "version": 1,
    "scope_levels": ["symbol", "type", "module"],
    "required_capabilities": [
      {"fact": "calls", "minimum": "structural"}
    ],
    "relations": {
      "related": [],
      "complementary": [],
      "alternatives": [],
      "conflicts": []
    },
    "scoring": {
      "applicability": "State the problem evidence that makes this relevant.",
      "suitability": "State what makes this a proportionate fit.",
      "conformance": "State what a correct implementation looks like.",
      "opportunity": "State when a change would create enough value."
    },
    "migration_cautions": ["Preserve the target's observable behavior."],
    "references": ["A durable primary reference"]
  },
  "cards": [
    {
      "stable_key": "example-pattern",
      "name": "Example Pattern",
      "kind": "constructive",
      "intent": "Describe one reusable design response.",
      "problem_signals": [
        {"feature": "syntax.calls", "operator": "count_gte", "value": 3}
      ],
      "supporting_evidence": [
        {"feature": "semantic.responsibilities", "operator": "exists"}
      ],
      "counter_evidence": [
        {"feature": "code.logical_lines", "operator": "lte", "value": 3}
      ],
      "semantic_questions": ["Does the target actually have the problem this solves?"],
      "benefits": ["Names the concrete improvement."],
      "liabilities": ["Names the concrete cost."],
      "verification_invariants": ["Names what must remain true after a change."]
    }
  ]
}
```

Load and validate a source file or directory without changing AnaxiGraph:

```python
from anaxigraph.pattern_catalog import load_pattern_catalog

catalog = load_pattern_catalog("path/to/catalog")
print(len(catalog.cards), catalog.fingerprint)
```

Validation rejects malformed signals, unsupported capabilities or levels, duplicate keys or names,
self-relations, unknown related keys, mixed catalog versions, and oversized source sets. The bundled
catalog uses a 300 KB source bound and currently occupies less than half of it.

Candidate generation, scoring, independent agent critique, persistence, and target/pattern queries
are separate phases of the pattern engine. Keeping those operations out of the catalog loader is
intentional: cards describe evidence and judgment; the engine controls bounded execution.

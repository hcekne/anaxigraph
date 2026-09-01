# Contributing to AnaxiGraph

AnaxiGraph is an Apache-2.0 open-source project. Bug reports, design feedback, language adapters,
architecture detectors, dashboard improvements, and documentation changes are welcome.

The product direction is deliberately narrow: **understand the system, guide the agent, and keep
the architecture coherent**. People and coding agents must use one shared architecture model. A
contribution should make one of those decisions easier without creating a parallel product surface.

## Local development

```bash
uv sync --extra dev
uv run pre-commit install --install-hooks
uv run pytest
uv run ruff check .
node --check src/anaxigraph/dashboard/app.js
```

The tracked hooks run whitespace/configuration checks, Ruff lint and formatting validation,
JavaScript parsing, credential/generated-file protection, the 500-line module ratchet, function
complexity and coupling ratchets, public-interface change reports, and package layer/cycle checks
before a commit. The complete Python suite, 80% total coverage floor, and 85% changed executable
code target run before a push. Local hooks are fast feedback; the same whole-repository policies
run in CI and remain authoritative if someone uses `--no-verify`.

Run every commit-stage hook against the complete checkout at any time:

```bash
uv run pre-commit run --all-files
```

Run the full Python pre-push gate, including coverage, at any time:

```bash
uv run pre-commit run --hook-stage pre-push --all-files
```

Before a pull request or release, run the single complete gate. It adds Compose validation, the
bounded performance smoke fixture, and Chromium dashboard contracts against a deterministic
repository. Docker must be running; use the branch point with `main` when the change spans several
commits:

```bash
uv run python scripts/run_quality_gate.py --base origin/main
```

The browser runner uses the pinned Playwright container by default, so contributors do not need to
install system browser libraries. `--browser-runner host` is available when Chromium and its
Playwright dependencies are already installed locally. Skip flags are diagnostic conveniences and
do not satisfy the complete pull-request/release gate.

The baselines in `quality/module-size-policy.json` and
`quality/maintainability-policy.json` are shrinking ratchets, not permanent allowances. The latter
also records the combined production Python/dashboard line budget. When production source or a
legacy module, function, or coupling value decreases, lower its recorded baseline in the same
change. Once an exception is within the normal limit, remove it. If an AnaxiIndex contains current
semantic dossiers, maintainers can also produce a non-authorizing cohesion review with:

```bash
uv run python scripts/check_semantic_cohesion.py --database /path/to/anaxi-index.db
```

Dashboard changes also have browser-level visual contracts. Start the Compose service, install
Playwright once, then run them against the live dashboard:

```bash
docker compose up --build -d
npm install
npx playwright install --with-deps chromium
npm run test:visual
```

These tests assert layout behavior that unit tests cannot: first-run onboarding, one architecture
LOC bar per card, coverage warning semantics, contained graph labels, area-filter relayout, module
review scope, repository settings, readable information hierarchy, and phone-width containment.

The dashboard uses one visual hierarchy across every journey:

- `h1` names the product, `h2` names a panel, and `h3` names a bounded section inside it. An
  uppercase eyebrow supplies context; it never replaces the visible heading.
- Normal explanations must remain readable body text. Metadata may be smaller, but a section
  heading must not be smaller than the content it introduces.
- Long semantic collections belong in individually bordered sections, not in an unbroken list or
  a wall of columns. Use existing panel and surface colors from every theme.
- Grid children use `minmax(0, 1fr)` or `min-width: 0`, and long paths and generated text wrap.
  Only tables, code blocks, menus, and the graph may opt into horizontal scrolling.
- Every journey must fit a 390-pixel viewport without document-level horizontal overflow. Add or
  extend a Playwright contract whenever a new content shape could break that rule.

For the container workflow, copy `.env.example` to `.env` and
`repositories.example.yml` to `repositories.yml`, then point the registry only at repositories you
are authorized to inspect. Run `docker compose up --build -d` and open
`http://127.0.0.1:8765`.

## Change principles

- Name the **Understand**, **Guide**, or **Keep coherent** decision the change improves.
- Reuse the existing AnaxiIndex, service, and product surface before adding another abstraction,
  command, MCP tool, table, job coordinator, or dashboard destination.
- Record what the change removes, merges, or replaces and report its production-line/public-surface
  delta. During the convergence roadmap, ordinary feature work must be neutral or negative.
- Keep target repositories read-only; analysis state belongs outside them.
- Label deterministic facts, inferred interpretations, and recommendations separately.
- Preserve repository scoping in every database, REST, dashboard, and MCP query.
- Include evidence and confidence for new detectors; a finding is not permission to refactor.
- Add focused tests for scanner, storage, API, or agent behavior changed by a contribution.

Please avoid including private source, database files, credentials, or analysis exports in issues
and pull requests. Explain the behavior with a minimal synthetic repository when possible.

Maintainers should follow the [protected release procedure](docs/releasing.md). Routine releases
use PyPI trusted publishing and attested artifacts; local `twine upload` is not the normal path.

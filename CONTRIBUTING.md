# Contributing to AnaxiGraph

AnaxiGraph is an Apache-2.0 open-source project. Bug reports, design feedback, language adapters,
architecture detectors, dashboard improvements, and documentation changes are welcome.

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

The baselines in `quality/module-size-policy.json` and
`quality/maintainability-policy.json` are shrinking ratchets, not permanent allowances. When a
legacy module, function, or coupling value decreases, lower its recorded baseline in the same
change. Once it is within the normal limit, remove the exception. If an AnaxiIndex contains
current semantic dossiers, maintainers can also produce a non-authorizing cohesion review with:

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
review scope, and repository settings.

For the container workflow, copy `.env.example` to `.env` and
`repositories.example.yml` to `repositories.yml`, then point the registry only at repositories you
are authorized to inspect. Run `docker compose up --build -d` and open
`http://127.0.0.1:8765`.

## Change principles

- Keep target repositories read-only; analysis state belongs outside them.
- Label deterministic facts, inferred interpretations, and recommendations separately.
- Preserve repository scoping in every database, REST, dashboard, and MCP query.
- Include evidence and confidence for new detectors; a finding is not permission to refactor.
- Add focused tests for scanner, storage, API, or agent behavior changed by a contribution.

Please avoid including private source, database files, credentials, or analysis exports in issues
and pull requests. Explain the behavior with a minimal synthetic repository when possible.

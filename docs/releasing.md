# Releasing AnaxiGraph

AnaxiGraph releases are built once from an exact Git tag, inspected as archives, attested, and
published to PyPI with GitHub's short-lived OpenID Connect identity. A maintainer's local PyPI
token is not part of the normal release path. PyPI files and version numbers are immutable: never
try to repair a published release by replacing its artifacts.

The authored source version can equal the latest public release between version bumps. Only an
immutable `v<project.version>` GitHub release starts a new publication.

## One-time repository configuration

### PyPI trusted publisher

In the existing `anaxigraph` project's PyPI publishing settings, add a trusted GitHub publisher
with these exact values:

| Field | Value |
|---|---|
| Owner | `hcekne` |
| Repository | `anaxigraph` |
| Workflow | `release.yml` |
| Environment | `pypi` |

The publisher is deliberately bound to one workflow and one environment. Do not add a PyPI API
token as a GitHub secret.

**Current operational state (20 August 2026):** the protected GitHub `pypi` environment exists,
requires maintainer approval, and permits only `v*` tags. The matching publisher has been added in
PyPI. Manual workflow run
[`32412357679`](https://github.com/hcekne/anaxigraph/actions/runs/32412357679) proved PyPI accepts the
exact repository, workflow, and environment identity by minting and immediately discarding a
short-lived token without uploading.

After adding or changing the publisher, test the identity without uploading an artifact by manually
dispatching `.github/workflows/release.yml` against an existing release tag, for example
`gh workflow run release.yml --ref v0.5.1`. The diagnostic job obtains the ambient GitHub OIDC
identity, asks PyPI to mint a short-lived project token, masks it, and immediately discards it. It
does not build or upload a distribution, move the tag, or republish its version. Approve the
normal environment gate for this verification-only run. The environment permits only release
tags; do not dispatch from a branch or weaken its tag restriction for this probe. The existing
`v0.5.0` tag was successfully used for this check on 8 September in
[run 34243583653](https://github.com/hcekne/anaxigraph/actions/runs/34243583653).

### Protected GitHub environment

Create a GitHub Actions environment named `pypi`. Require a maintainer review before deployment,
restrict deployment to protected `v*` tags, and prevent administrators from bypassing the rule
unless emergency governance explicitly requires it. The publish job alone receives
`id-token: write`; it does not check out or execute repository code.

Protect `main`, require the quality, package-contract, browser, and container checks, and restrict
creation of release tags to maintainers. These controls make approval meaningful; an environment
review is not sufficient if an unreviewed actor can move the tag being approved.

## Release contract

Every Python release must satisfy all of these invariants:

- `pyproject.toml` is the single authored version; runtime, CLI, and API versions derive from
  installed distribution metadata.
- The release tag is exactly `v<project.version>`.
- That version does not already exist on PyPI.
- Exactly one `py3-none-any` wheel and one source distribution are built.
- Rebuilding the same source revision with its fixed source-date epoch produces byte-identical
  wheel and source archives.
- Both archives contain the dashboard, console entry point, Apache-2.0 license, and corrected
  PEP 639 `License-Expression` / `License-File` metadata.
- The wheel and source distribution install and execute independently on Python 3.11 and 3.12 on
  fresh Linux and macOS runners.
- The release bundle contains SHA-256 checksums, an SPDX JSON SBOM, a dependency/license inventory,
  and GitHub artifact attestations; the verified bundle is attached to the durable GitHub release
  rather than existing only as an expiring Actions artifact.
- The same tag builds the multi-architecture container, whose immutable registry digest receives
  BuildKit provenance, an SBOM, and a GitHub registry attestation.
- The Codex and Claude plugin manifests and Claude marketplace entry match `project.version`, and
  one deterministic `anaxigraph-agent-plugin-<version>.zip` is included in the release checksums.

CI enforces the archive and fresh-install checks on every pull request. The release workflow runs
the same contract again against the immutable tag before requesting permission to publish.

## Prepare a release

1. Decide the next semantic version. Use a new version even when correcting packaging metadata;
   PyPI does not permit replacing an existing file.
2. Update only `project.version` in `pyproject.toml`, then run `uv lock`. Runtime version strings
   must not be edited elsewhere.
3. Update the changelog/release notes and any version-specific compatibility statements.
   Write the website entry into the record now, in the `<!-- changelog -->` block described
   below, while you still remember what you built.
4. Run the complete repository gate and the release preflight:

   ```bash
   ANAXIGRAPH_RELEASE_VERSION=0.4.0
   uv sync --extra dev --locked
   uv run python scripts/run_quality_gate.py --base origin/main
   uv run python scripts/build_release_artifacts.py --outdir dist
   uv run twine check dist/*
   uv run python scripts/verify_release_artifacts.py \
     --dist dist \
     --tag "v${ANAXIGRAPH_RELEASE_VERSION}" \
     --check-pypi \
     --checksums /tmp/anaxigraph-SHA256SUMS
   uv run python scripts/check_agent_package.py
   mkdir -p release
   uv run python scripts/build_agent_plugin.py \
     --output "release/anaxigraph-agent-plugin-${ANAXIGRAPH_RELEASE_VERSION}.zip" \
     >> /tmp/anaxigraph-SHA256SUMS
   ```

   Set `ANAXIGRAPH_RELEASE_VERSION` to the version being prepared. The verifier intentionally fails
   when the tag and package disagree, when required package data is absent, when the license metadata
   regresses, or when the version is already on PyPI.

5. Commit the version change through a pull request and let every required check pass.
6. Create the exact annotated tag from the protected commit and push it:

   ```bash
   git tag -a "v${ANAXIGRAPH_RELEASE_VERSION}" \
     -m "AnaxiGraph ${ANAXIGRAPH_RELEASE_VERSION}"
   git push origin "v${ANAXIGRAPH_RELEASE_VERSION}"
   ```

7. Draft a GitHub release for that existing tag. Review the commit and generated notes, then
   publish the GitHub release. Publishing, rather than merely pushing a tag, triggers
   `.github/workflows/release.yml`.
8. Review and approve the `pypi` environment deployment after the build, archive inspection,
   checksum, SBOM, dependency inventory, and attestation steps pass.
9. Confirm the workflow's clean public-install job and the matching container digest before
   announcing the release.

10. Update the release notes and feature ledger immediately after publication and again after
    deployment or rollback. Do not leave the merged candidate's "not published" language as the
    current release record. Publication, verified artifacts, a protected merge, and successful
    production acceptance are separate facts; checking one does not check the others.

For a local reproducibility check, use a clean exact-tag worktree and run the build under
`umask 022`, matching CI. Git records executable bits but not the group-write mode inherited by
generated package files; a different mask can produce identical contents with different archive
bytes. For SSH pushes whose full pre-push tests outlast an idle connection, use
`git -c core.sshCommand='ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=10' push`
without skipping hooks. Preserve any custom SSH-command configuration when adapting that example.

### Checked release record

Starting with 0.5.0, the current `docs/releases/<project.version>.md` has YAML front matter:
`version`, `ledger` (a repository-relative Markdown path), and four gate statuses with HTTPS
`<gate>_evidence` links. The allowed statuses are:

| Gate | Statuses |
|---|---|
| `publication` | `pending`, `published` |
| `artifacts` | `pending`, `verified` |
| `protected_merge` | `pending`, `verified`, `bypassed` |
| `production` | `pending`, `verified`, `failed`, `rolled_back` |

Every non-pending gate needs its evidence link. The ledger contains exactly one
`- [ ] <!-- release:<gate> -->` entry per gate; only `published`/`verified` statuses may be checked.
For a new version, copy this small record into its notes with pending gates, not prior evidence.
The offline commit check enforces the record, checkbox agreement, lockfile version, and obvious
published-but-still-draft contradictions. Existing agent-package checks cover plugin versions.
Push and CI also compare the current version's publication status with the public PyPI endpoint:

```bash
uv run python scripts/check_release_record.py --verify-pypi
```

The check does not verify what an evidence link claims. Review counts and ancestry must be
inspected on GitHub; deployment needs checks against the real retained index, including semantic
**writes**, not just HTTP liveness and read-only integrity. A rolled-back release remains
published unless PyPI actually says otherwise. A bypass remains `bypassed`, not `verified`.
Finish semantic/review workflows separately, retaining their snapshot and executor provenance;
never launch paid model work from a Git hook or call an older/partial review current.

Use reviewed squash/rebase merges for linear history. GitHub protection must include administrators
to prevent server-side bypass; local hooks cannot enforce that setting. Changing repository
protection or its reviewer policy requires a separate maintainer decision. Hook installation does
not silently change those settings or grant standing authorization for future overrides.

### Website changelog entry

The record also carries the entry anaxigraph.dev publishes, as a JSON block introduced by an
`<!-- changelog -->` comment:

```json
{
  "summary": "under 60 characters, a noun phrase naming the theme",
  "description": "2-3 sentences, under 400 characters",
  "highlights": ["three to eight items, each under 240 characters"]
}
```

Write it as part of the change, not afterwards. Whoever makes a release knows what it does;
reconstructing that later from squashed commit subjects loses almost all of it, and no service
needs to be asked to guess. The offline commit check rejects a release record without a valid
block, so a version cannot ship without its entry.

The website copies the block verbatim and adds the commit, file and line counts from the GitHub
compare API for the tag boundary. Those numbers are never written by hand, so an entry cannot
claim a diff it does not have.

## Verify artifacts

Download the `anaxigraph-<version>-release` workflow artifact. Check its archives against the
included checksum file:

```bash
sha256sum --check SHA256SUMS
gh attestation verify anaxigraph-0.4.0-py3-none-any.whl \
  --repo hcekne/anaxigraph
gh attestation verify oci://ghcr.io/hcekne/anaxigraph:0.4.0 \
  --repo hcekne/anaxigraph
```

The release-contract JSON records archive membership and hashes. The SPDX file describes the
shipped source, while `dependency-licenses.json` records the exact installed runtime environment
used by the release audit. A report is evidence for review, not a substitute for the project's
security and license policies.

## Failure and recovery

- If any build or inspection step fails before PyPI publication, fix it in a reviewed commit,
  create a new tag, and publish a new GitHub release. Do not move a published release tag.
- If environment approval is rejected, no PyPI credential or artifact is released. Correct the
  release record and use a new tag when its commit changes.
- If PyPI accepted the files but a later verification step fails, do not upload replacements.
  Investigate, yank the affected release if installation is unsafe, bump the version, and publish
  corrected artifacts.
- Container consumers should pin the recorded digest when reproducibility matters. Tags are
  discoverability labels, not immutable identities.

Manual `twine upload` remains an emergency-only recovery mechanism. Its use requires an incident
record, a short-lived scoped token, and the same local artifact verifier; it must never read a
maintainer token during routine releases.

## Release incident: 0.2.0 publisher registration

The `v0.2.0` workflow run built and attested every release artifact, then failed closed during the
PyPI token exchange with `invalid-publisher`. The rendered OIDC claims were correct for repository
`hcekne/anaxigraph`, workflow `release.yml`, tag `v0.2.0`, and environment `pypi`; the publisher-side
record was missing.

With explicit maintainer authorization to complete the already-announced release, the exact
workflow artifact was downloaded and its `SHA256SUMS`, GitHub attestations, and Twine metadata were
verified before the wheel and source distribution were uploaded through the configured project
token. PyPI reported the same SHA-256 values as the workflow bundle. A cache-refreshed public
installation and a fresh `uvx anaxigraph up` process both passed. The GitHub release records the
recovery and exposes the verified artifacts, SBOM, dependency inventory, plugin ZIP, release
contract, and container digest.

This recovery did not waive the trusted-publisher requirement. The publisher was subsequently
registered and the non-publishing identity probe succeeded. Require the next release to complete
the OIDC publication and public-install jobs before announcing it.

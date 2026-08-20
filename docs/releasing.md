# Releasing AnaxiGraph

AnaxiGraph releases are built once from an exact Git tag, inspected as archives, attested, and
published to PyPI with GitHub's short-lived OpenID Connect identity. A maintainer's local PyPI
token is not part of the normal release path. PyPI files and version numbers are immutable: never
try to repair a published release by replacing its artifacts.

The current source version is the candidate for the next release. It is not a claim that the
version is already public.

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
  and GitHub artifact attestations.
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
4. Run the complete repository gate and the release preflight:

   ```bash
   uv sync --extra dev --locked
   uv run python scripts/run_quality_gate.py --base origin/main
   uv run python scripts/build_release_artifacts.py --outdir dist
   uv run twine check dist/*
   uv run python scripts/verify_release_artifacts.py \
     --dist dist \
     --tag v0.2.0 \
     --check-pypi \
     --checksums /tmp/anaxigraph-SHA256SUMS
   uv run python scripts/check_agent_package.py
   mkdir -p release
   uv run python scripts/build_agent_plugin.py \
     --output release/anaxigraph-agent-plugin-0.2.0.zip \
     >> /tmp/anaxigraph-SHA256SUMS
   ```

   Replace `v0.2.0` with the version being prepared. The last command intentionally fails when the
   tag and package disagree, when required package data is absent, when the license metadata
   regresses, or when the version is already on PyPI.

5. Commit the version change through a pull request and let every required check pass.
6. Create the exact annotated tag from the protected commit and push it:

   ```bash
   git tag -a v0.2.0 -m "AnaxiGraph 0.2.0"
   git push origin v0.2.0
   ```

7. Draft a GitHub release for that existing tag. Review the commit and generated notes, then
   publish the GitHub release. Publishing, rather than merely pushing a tag, triggers
   `.github/workflows/release.yml`.
8. Review and approve the `pypi` environment deployment after the build, archive inspection,
   checksum, SBOM, dependency inventory, and attestation steps pass.
9. Confirm the workflow's clean public-install job and the matching container digest before
   announcing the release.

## Verify artifacts

Download the `anaxigraph-<version>-release` workflow artifact. Check its archives against the
included checksum file:

```bash
sha256sum --check SHA256SUMS
gh attestation verify anaxigraph-0.2.0-py3-none-any.whl \
  --repo hcekne/anaxigraph
gh attestation verify oci://ghcr.io/hcekne/anaxigraph:0.2.0 \
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

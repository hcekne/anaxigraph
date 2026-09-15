# Working in this repository

Rules earned by getting them wrong. Each one cost real time.

## Ship it yourself

**Commit and push to `main` directly.** No branch, no pull request, no waiting for approval,
unless the maintainer asks for one. `main` has no required reviews and no required checks; CI
still runs and still reports. When asked to finish something, finish it and push it.

**Delete a branch the moment its work is on `main`.** Branches are rebase-merged, so the
original commits are never ancestors of `main` — check with `git cherry origin/main origin/<branch>`,
not `git merge-base --is-ancestor`, or every merged branch looks unmerged. Eleven had piled up.

## Do not add gates

The slow checks run in CI. Do not move them back into `pre-push`: the full suite, coverage,
changed-line coverage and self-analysis cost about ten minutes before a single byte reaches the
remote, and CI runs them anyway. A one-line fix should not cost ten minutes to attempt.

Before adding any new check, ask whether it will ever fail for a *good* change. A rule that only
ever blocks legitimate work is a tax, not a gate.

## Verify automation against reality, not against intent

Automation that writes files must be run end to end before shipping. The release job that records
publication evidence shipped broken **twice in the same file**: once writing `---version:` because
it stripped a four-character delimiter and wrote back three, and once leaving "This is a release
candidate" in a record it had just marked published, which its own checker rejects. Both would have
been caught by running the script against a real record and then running the checker on its output.

Do the same for CI changes. A workflow's first real execution is the only evidence it works. Saying
new automation is "ready" because its no-op path passed is worthless.

## GitHub rules that only bite automation

These are invisible until hit, and all three cost a release:

- **A workflow's `GITHUB_TOKEN` cannot trigger another workflow.** A release or tag created by
  Actions raises no event. Call the other workflow directly with `workflow_call`.
- **PyPI attestations name the workflow that *started* the run.** A reusable publish workflow
  attests as its caller, so PyPI rejects it unless that caller is also a registered trusted
  publisher. `release.yml` must be dispatched top-level, or register `auto-release.yml` too.
- **`docker/metadata-action` derives tags from `github.ref`,** not from your env var. A called
  build runs on the caller's ref, so it published an image tagged `main`.

## Deployment environment settings are all-or-nothing

`PUT /repos/.../environments/<name>` replaces the whole object. Removing a reviewer also wiped the
deployment branch policy, and the next release was refused from a `v*` tag with no failing step to
point at. Read the current settings, change one field, write them all back.

## Optional fields in a contract

`_object(**properties)` sets `required = list(properties)`. Removing a key from `required` keeps
old documents valid, and **breaks OpenAI strict structured output**, which requires every property
to be required. That shipped in 0.7.0 and broke the architecture scan entirely. The Codex adapter
now builds a nullable wire schema; if you add an optional field, check `_codex_schema` still
reports zero strict violations.

## Say what actually happened

Report the number that was measured, not the one that was hoped for. If something was not run, say
so. A benchmark on synthetic data is not a live figure. A release that published but never deployed
keeps its production box open — see `docs/releases/0.6.0.md` and `0.7.1.md`.

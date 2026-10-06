---
name: python-minimum-version-maintenance
description: Audit maintained Python packages and raise obsolete floors.
version: 0.1.0
author: Dave Bunten (d33bs), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [python, packaging, maintenance, compatibility]
    related_skills: []
---

# Python Minimum Version Maintenance

Audit Python packages maintained by the specified person or team and, where justified, raise their minimum supported Python version with small, verified edits. Do not assume every repository should have the same floor.

## When to Use

- Asked to review one or more Python packages maintained by a specified person or team, or by the current user when no maintainer is specified.
- Asked to update a package's minimum Python version and associated CI/docs/configuration.
- Don't use for blanket dependency upgrades or unrelated modernization.

## Procedure

1. Establish scope and maintainer identity. Prefer an explicitly named person, team, account, or organization. Otherwise, inspect local git remotes and `gh api user` or `git config user.name`/`user.email` as clues, never proof. For a GitHub handle, enumerate its own repositories AND relevant organization repositories (`gh api --paginate users/HANDLE/repos` and `gh api --paginate orgs/ORG/repos`); a `user:HANDLE` repository search misses org-owned projects. Identify likely packages by `pyproject.toml`, `setup.cfg`, or `setup.py`, not GitHub's primary-language label alone (notebooks can mask Python packages). Filter out archived/forks and rank by recency, package status, and evidence of actual involvement; `gh api 'repos/OWNER/REPO/commits?author=HANDLE&per_page=1'` is a useful signal, but author matches, push permission, and repo ownership individually do not prove maintainership. Cross-check contributors, package authors/maintainers, docs, and project instructions before changes. Prefer API-side `--jq` projections and bounded batches when listing many repos: unfiltered API responses can exceed terminal output limits and yield truncated invalid JSON; handle missing metadata/files explicitly. Report the shortlist and ask when identity or scope materially changes which repositories would be edited. Do not silently edit every repository or clone/write to unrelated locations without a clear target.
2. On each run, read [Python's version status](https://devguide.python.org/versions/) and record the access date, supported branches, and end-of-life branches. Never hardcode 3.10 as the perpetual cutoff. Treat prereleases as unavailable for a minimum floor; distinguish security-supported branches from actively bugfix-supported branches.
3. Inspect project instructions, git status/branch, packaging metadata (`requires-python`, `python_requires`, classifiers), CI matrices, tox/nox, lockfiles, docs, installation instructions, Docker/Conda/Slurm environments, and downstream user constraints. Trace the canonical minimum and all mirrors. If there is no declared floor, do not equate a CI matrix with a compatibility promise without checking the docs.
4. If the declared minimum is end-of-life, choose the latest *viable* floor: start with the oldest still-supported stable release, then consider newer stable versions only when dependencies, code, CI runners, deployment constraints, and the project's support policy justify them. Check the project's actual dependency constraints and available wheels; avoid selecting a floor solely from the CPython lifecycle table. Explain the candidate and compatibility tradeoff briefly. If the floor is already supported, report it and avoid unnecessary changes.
5. Make the smallest consistent change following local conventions: canonical package metadata, mirrored classifiers/matrices/configuration/docs, and generated files only through their normal generator. Preserve an existing upper bound unless expanding compatibility is independently verified; never add one just to raise the floor. Remove Python-version-specific dependency branches only if they become unreachable. Regenerate lockfiles with the project's tool, inspect the full lockfile diff for unrelated re-resolution, and explain or minimize large churn rather than treating it as a harmless mechanical edit. If older-version CI jobs are removed, ensure the new minimum is tested and an appropriate recent stable version remains tested.
6. Run the project's relevant lint/tests/build and test installation or metadata inspection under the proposed minimum Python interpreter. If that interpreter is unavailable, report precisely what was and wasn't verified; do not assert compatibility based on a newer interpreter alone. Fix issues exposed by the upgrade within scope, or report blockers and leave the floor unchanged if viability cannot be established.
7. Review the final diff and git status; report each package's old and new floor, reason, test evidence, blockers, and any unmodified packages. When explicitly asked for PRs, check existing open PRs for duplicates, commit and push only the scoped files, create a draft PR with a plain description, then read back its exact URL, draft/open state, and check status. Do not call CI green while checks are still queued or running; if CI fails, inspect logs, correct in-scope failures, and verify again. Otherwise do not commit, push, or open PRs.

## Pitfalls

- A `>=3.11` declaration alone does not prove the code and dependencies run on 3.11.
- A project's support policy or downstream platform can require a different floor from the oldest supported CPython; explain exceptions rather than forcing uniformity.
- CI, packaging metadata, README, and environment files can disagree; identify the source of truth before editing.
- An EOL date may change: revisit the official lifecycle page every run. Prefer its supported-version table with status and end-of-life date; the timeline graphic can show stale or conflicting labels. State the actual date when a release just crossed the boundary.
- Verify at least the proposed minimum interpreter directly; separate local skips (network/large-data) from CI coverage, and distinguish pre-existing lint/type errors from regressions. A successful package build can additionally confirm the wheel's `Requires-Python` metadata.
- After CI-triggered pre-commit auto-updates, inspect hook/config diffs and rerun the project's checks before pushing. Do not assume an automated rewrite is related to the Python floor.

## Verification

For every modified repository, confirm packaging metadata advertises the intended floor, all explicit support claims agree, and relevant checks ran with their actual exit status. State whether the proposed minimum interpreter was exercised. Leave unrelated working-tree changes untouched.

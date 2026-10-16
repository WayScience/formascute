---
name: python-latest-version-maintenance
description: Use when adopting the newest stable Python in projects.
version: 0.1.0
author: Dave Bunten (d33bs), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [python, packaging, maintenance, compatibility]
    related_skills: [python-minimum-version-maintenance]
---

# Python Latest Version Maintenance

Move maintained projects toward the newest stable CPython with small, verified
changes. For libraries, prefer adding tested support; for applications, consider
advancing development and deployment defaults. Latest-version adoption does not
itself authorize dropping older supported versions.

## When to Use

- Asked to find maintained Python projects that lag the latest stable release.
- Asked to bump Python in CI, development environments, containers, or applications.
- Asked to add support for a newly released Python version.
- Don't use for end-of-life minimum-version retirement alone; use
  `python-minimum-version-maintenance` for that policy. Don't use for blanket
  dependency upgrades or speculative prerelease migrations.

## Prerequisites

- Inspect files with `read_file` and `search_files`; edit with `patch` and
  `write_file`; run git, package tools, builds, and tests through `terminal`.
- Retrieve current official release information with the available web tools.
  For GitHub discovery or PRs, check CLI availability and authentication with
  `terminal(command="gh auth status")` before relying on `gh`.
- Follow project instructions and existing environment and lockfile tools. Use
  isolated environments; do not replace the system interpreter or destroy a
  working environment.

## Paired Range Review

Read `python-minimum-version-maintenance` once per run before choosing or
changing Python bounds. Review its minimum-version policy alongside this skill's
latest-version policy; do not recursively invoke the companion workflow.

- Record the complete declared range, intended minimum, newest supported/tested
  stable version, and any upper bound or exclusions. Check exact interpreter
  membership with project tooling or `packaging.specifiers.SpecifierSet`, not
  string ordering. A latest CI job is not proof of a valid support range.
- Reconcile metadata, classifiers, CI, docs, lockfiles, and dependency markers.
  Check published dependency `Requires-Python` and installation viability at both
  ends; a dependency update for newer Python must not silently break the minimum.
- Directly exercise the retained/proposed minimum and newest version being
  claimed. Preserve existing intermediate-version CI jobs and report missing
  endpoint or platform evidence instead of claiming the whole range verified.
- Cross-review does not authorize extra changes. Flag an obsolete minimum or
  stale upper bound separately when outside the requested scope; do not raise
  the floor, widen/add an upper bound, or drop compatibility without permission
  and verification. Finish with a consistent, non-empty declared range and
  explicit evidence for its tested endpoints.

## Procedure

1. Establish scope and maintainer identity. Prefer explicitly named repositories,
   people, teams, or organizations; otherwise start with the current repository.
   For account-wide audits, enumerate personal and relevant organization repos
   through `terminal` using `gh api --paginate users/HANDLE/repos` and
   `gh api --paginate orgs/ORG/repos`. A `user:HANDLE` search misses organization
   projects. Identify packages by `pyproject.toml`, `setup.cfg`, or `setup.py`,
   not primary-language labels alone. Skip archived repos and unrelated forks
   unless explicitly included. Ownership, push permission, or an author-matched
   commit alone is not proof of maintenance: cross-check docs, contributors, and
   package maintainers. Use bounded API projections, handle missing metadata,
   and persist multi-repository results before counting. Report the shortlist
   and resolve uncertain scope before cloning or editing other repositories.
   Completion: every target has a stated reason for inclusion.
2. Discover the target fresh every run. Read
   [Python downloads](https://www.python.org/downloads/) and
   [Python version status](https://devguide.python.org/versions/), then confirm
   the chosen version's official release page and release date. Record the
   access date, newest final major/minor branch, and latest final patch on that
   branch. Compare versions numerically, not lexicographically or by whichever
   older branch received a patch most recently. Exclude alpha, beta, RC, future
   scheduled releases, development branches, and free-threaded builds by default.
   Do not infer availability from a schedule or hardcode a version in this skill.
   Completion: target and sources are recorded, with a final release available
   as of the run date.
3. Map current policy and all version surfaces. Read project instructions and
   inspect git status/branch before edits. Inspect `requires-python`/
   `python_requires`, classifiers, CI matrices and interpreter selectors,
   tox/nox, `.python-version`, lockfiles, lint/type targets, docs, Docker/Conda/HPC
   environments, and deployment constraints. Distinguish the minimum compatibility
   promise, latest tested version, development default, and deployed runtime.
   A CI matrix is not itself a complete support policy. Record relevant OS and
   architecture coverage.
   Completion: canonical settings and mirrors are identified, with old values.
4. Choose the smallest adoption change. For libraries, preserve the supported
   minimum and lower-version CI jobs; add the latest stable test job and promote
   the development default only where practical. For applications, consider
   advancing runtime pins, base images, development interpreters, and CI together
   when deployment permits. Change `requires-python` only if it excludes the
   target or a floor change is independently authorized. Preserve upper bounds
   unless expansion is verified; do not add one just to adopt newer Python.
   Keep lint/type minimum targets that protect older-version compatibility.
   An audit-only request produces recommendations, not edits.
   Completion: intended changes and preserved compatibility promises are explicit.
5. Probe viability before claiming support. Provision the target using the
   project's approved interpreter manager or an isolated environment. Print the
   actual executable, version, implementation, and build variant. Resolve and
   install actual dependency constraints, including relevant test/build extras.
   Check critical compiled dependencies and wheel availability on required
   platforms, especially scientific/ML stacks. Classifiers or a wheel on one OS
   do not prove universal compatibility. Check CI runner/interpreter action,
   container, and platform availability; consult official porting notes for
   failures. Run a small smoke test, then relevant tests. Distinguish resolver
   conflicts, missing wheels, source-build failures, interpreter provisioning
   failures, and code regressions.
   Completion: the exact target ran, or a reproducible blocker with its error
   and affected platform is recorded.
6. If blocked, do not force adoption. Try a small dependency or tooling update
   when justified and in scope, preserving the existing minimum where promised.
   Never remove working dependencies, weaken assertions, or make the latest
   stable CI job permanently optional to manufacture success. Separate optional
   prerelease experiments from required stable CI. If newest stable remains
   unavailable or incompatible, retain working defaults and report it blocked.
   Offer the next-newest viable stable as an explicit fallback, never as
   "latest"; apply it only when the requested scope permits that fallback.
   Completion: each target has an evidence-backed adoption decision or blocker.
7. Apply minimal consistent edits after viability is established. Add rather than
   replace lower-version library CI jobs. Update intentional runtime/dev pins,
   accurate support classifiers and docs, and relevant environment mirrors.
   Keep exact patch pins where reproducibility requires them; use major/minor
   selectors where existing policy tracks patches. Update dependency constraints
   only as needed for compatibility. Regenerate generated files with normal
   project tooling, inspect the full lockfile diff for unrelated re-resolution,
   and minimize or explain churn. Keep dependency marker branches that remain
   reachable on supported older versions.
   Completion: every changed file maps to an intended adoption surface or a
   demonstrated compatibility fix.
8. Verify the proposed state, not just the initial probe. Run required lint/type
   checks, relevant tests, and a package build where applicable. Install the
   built artifact in a clean target environment; exercise an import plus a
   representative CLI or application smoke path. For libraries, run relevant
   checks on the preserved minimum interpreter as well: newer-only execution
   cannot establish that older support survived. Record actual interpreter
   versions, commands, exit statuses, and skips. Inspect built `Requires-Python`
   metadata if changed. Do not claim untested platforms or unavailable
   interpreters passed. When coverage is incomplete, label the change provisional
   and name missing CI or platform evidence. Fix in-scope regressions or report
   them as blocking adoption; distinguish pre-existing failures from regressions.
   Completion: support claims match observed execution.
9. Review final diff and git status, leaving unrelated changes untouched. Report
   per repository: newest stable target, old/new latest-tested or runtime values,
   unchanged or explicitly approved floor, changed surfaces, verification,
   blockers, and fallbacks. Already-current projects get a no-change result.
   Completion: every change is scoped and the local verification outcome is clear.
10. Publish one PR per changed repository as the final stage of an authorized
    end-to-end upgrade. Establish publishing permission at the start: an explicit
    request to open PRs authorizes the required scoped commits and branch pushes.
    Audit-only, local-only, and no-commit/no-push instructions override this stage;
    when publication is not authorized, leave edits local and explicitly report
    that no PR was opened. Never silently stop after local edits when PRs were
    requested. Check open PRs for the same branch or upgrade before creating one.
    Commit only reviewed files with a short plain message, push the branch to the
    intended fork with tracking, and confirm the remote head matches local HEAD.
    Specify the upstream repository, base branch, and fork owner/head explicitly
    when creating the PR. Use a short title and a two-sentence description: what
    changed, then what was actually verified. No long template, process narrative,
    or agent attribution. Open ready-for-review when local gates passed; use a
    draft for incomplete verification or when requested. Do not merge.
    Completion: the requested PR exists for the correct repository and branch.
11. Read back each exact PR using `gh pr view` or `gh api` and verify its URL,
    open state, intended draft state, base/head repositories and branches, head
    SHA, title, and short body against the intended payload. Check actual CI for
    that head. Pending/running checks are not green; report them as pending.
    Inspect failed logs, fix in-scope regressions, rerun local checks, and publish
    fixes only within the authorized scope. Report blockers rather than claiming
    remote success. Return each PR URL with its current CI status.
    Completion: all scoped repositories are accounted for and published state is
    verified by read-back.

## Pitfalls

- For a PyPI package shortlist, query the live XML-RPC `user_packages` method
  with the supplied username, for example
  `xmlrpc.client.ServerProxy('https://pypi.org/pypi').user_packages('HANDLE')`.
  Validate returned owner/maintainer roles, then cross-check live package JSON
  and canonical repositories. An HTML profile can return a CAPTCHA with HTTP
  200; this does not mean the package list is empty. If the API is unavailable,
  report the limitation and use verified alternate evidence, not guessed names.
- Bound organization discovery to relevant source organizations. Membership in
  enormous ecosystems such as conda-forge does not justify enumerating all their
  repositories; feedstocks are not canonical package sources. Save completed
  batches before moving to another endpoint.
- Compare published metadata, current source metadata, and actual test-workflow
  selectors separately. A latest-version classifier can exist without a matching
  test job; a release can lag an updated floor. Report mismatches, not presumed
  compatibility or passing CI.
- An older interpreter manager can list only a prerelease after final is out.
  Try a current isolated tool, for example `uv tool run --from uv uv python list`,
  rather than upgrading global tooling or testing the beta. Install the exact
  final target and assert `sys.version_info.releaselevel == 'final'` plus the
  intended build variant before tests. Scope `UV_PROJECT_ENVIRONMENT` per command
  and pass `--python` explicitly so existing environments are not replaced and
  automatic fallback cannot make a newer-version probe run on older Python.
- For hook packages, test a real consumer installation under each new interpreter,
  not just pytest or a system-language hook pointing at the current environment.
  For example, `pre-commit try-repo . check --files <compliant fixtures>` exercises
  isolated hook bootstrapping. Old virtualenv-seeded pip can fail on removed
  standard-library APIs even when the package's tests and installed CLI pass.
  Diagnose with a temporary dependency overlay; encode the verified requirement
  in the appropriate development group, not runtime dependencies. Check that
  selected releases are not yanked and avoid unnecessary major upgrades.
- Clear inherited `PYTHONPATH` and `PYTHONHOME` when launching verification
  subprocesses from an agent interpreter. Otherwise a hook running one Python
  can import packages and incompatible compiled extensions from the agent's
  different interpreter. Confirm import paths before blaming project code.
- Separate upstream support PRs from published dependency availability. A ready
  PR is not a PyPI release, and the next release can fall outside a downstream
  project's current dependency range. Report the release/range-change prerequisite;
  do not auto-publish packages or pin downstream projects to unpublished branches
  to manufacture compatibility.
- Treat wheel-only failures as binary-installation blockers, not proof that all
  source installations are impossible. Allow bounded small source builds when
  appropriate, but do not start unbounded scientific builds just to force a bump.
  Separate runtime, optional extras, and test/dev blockers; a passing core API
  probe does not establish the entire declared dependency graph is supported.
- Inspect dependency wheel or installed `Requires-Python` metadata independently
  when resolver output contradicts published support bounds. A successful
  compile/dry-run is not permission to bypass a dependency's declared upper bound.
  Verify interpreter, ABI and platform compatibility, including usable `abi3`
  wheels; don't infer availability from a `cp315` filename count alone. Source
  overrides to sibling repos cannot establish ordinary published installation.
- "Newest available" means newest final CPython, not prerelease, nightly, PyPy,
  or free-threaded variants. Alternative builds need separate verification.
- A newer patch on an older branch does not make that branch the newest stable.
- Adding latest support is not permission to raise the floor or delete working
  older-version CI coverage.
- Runtime/dev pins and lint/type minimum targets serve different purposes.
  Changing every version-looking string can silently break older-version users.
- Successful resolution is not successful installation; editable source tests
  are not a clean built-artifact test. A passing import is only a probe.
- Compiled extensions, containers, and HPC modules can lag final releases.
  Report concrete blockers instead of claims based on an unbounded source build.
- Lockfile regeneration and pre-commit rewrites can introduce unrelated changes.
  Inspect those changes and rerun checks after accepting any rewrite.

## Verification

For every scoped repository, record one outcome: already current, verified
adoption, provisional adoption with missing evidence, or blocked. Confirm the
latest release was checked live; intended version surfaces agree; older
compatibility promises are preserved unless explicitly changed; and the exact
target executed the reported checks. Installing or structurally validating this
skill does not verify a project upgrade.

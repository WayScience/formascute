---
name: gh-triage-dependabot-prs
description: Safely review and merge Dependabot PRs requesting your review.
version: 0.1.0
author: Dave Bunten (d33bs), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [dependabot, github, pull-requests, ci, triage]
    related_skills: []
---

# Dependabot PR Triage

Safely triage open GitHub pull requests that request review from the current
user and are authored by the Dependabot GitHub App: inspect CI, classify each
PR into a risk tier, approve and merge green dependency updates, and apply
narrowly scoped mechanical `prek` fixes to eligible CI failures. Every GitHub
mutation stays inside the explicitly authorized Dependabot PR scope; a request
to inspect or report never authorizes reviews, pushes, or merges.

## When to Use

- Asked to process, recheck, approve, merge, or report on Dependabot PRs
  requesting the current user's review, including PRs the user explicitly names
  and directs you to process.
- Asked to apply pre-commit (`prek`) fixes to a Dependabot PR whose CI failed
  on a mechanical formatting hook.
- Don't use for non-Dependabot PRs or generic dependency upgrades outside a PR
  triage workflow.

## Prerequisites

- GitHub CLI (`gh`) authenticated as the intended user; `repo` token scope for
  private repositories and PR mutations, `workflow` scope when a PR changes
  `.github/workflows/`. Confirm with `terminal(command="gh auth status")`.
- Python 3 for the read-only snapshot helper.
- `prek` when local hook execution is needed.

## Procedure

1. Run `gh auth status`; require `repo`, and `workflow` before merging a PR
   that changes `.github/workflows/`. Resolve the login with
   `gh api user --jq .login`.
2. Run the read-only snapshot helper from this skill directory for a
   candidate list:
   `python3 scripts/snapshot.py` (add `--compact` for single-line JSON).
   Inspect each entry's changed paths, check rollup, CI classification, and
   risk hints.
3. Reconfirm each candidate is open, requests review from the authenticated
   user, and uses the Dependabot GitHub App identity (`dependabot[bot]` in
   search results or `app/dependabot` in PR metadata). Never select by title
   alone. A PR the user explicitly names and directs you to process satisfies
   the authorization requirement even without a review request; record that
   the PR was user-directed.
4. Do not approve, commit, push, or merge unless the user explicitly
   requested those actions.
5. Classify every candidate into a risk tier before approving or merging:
   - Routine: patch/minor bumps, single-package lockfile updates, and grouped
     updates whose changed paths are lockfiles or hook-rev-only
     `.pre-commit-config.yaml` edits with no removed-option usage. Green CI
     is sufficient evidence.
   - Major: any major version bump, grouped update containing one, transitive
     major change visible in the lockfile, or security-driven update with
     documented behavior changes. Green CI is necessary but not sufficient —
     perform a substantive review first: read the upstream release notes,
     identify removed APIs or behavior changes, and search the repository for
     usages that would break. Merge only when no affected usage exists. If a
     risky path is plausibly exercised but not covered by CI, report instead
     of merging.
   - Report-only: changes to `.github/workflows/` beyond action-version
     bumps, permission or security-policy changes, semantic source changes,
     deployment changes, and ambiguous grouped updates. Do not merge these on
     green CI alone; describe the diff and wait for explicit user direction.
6. A user instruction can promote a PR across tiers ("major updates are fine
   if green", "workflow bumps are fine if green"); the promotion applies only
   to that session and that risk class. Never treat a blanket approval as
   covering report-only items the user did not mention.
7. Approve or merge only when all of these are true (the merge gate):
   - The PR is not a draft and has at least one completed GitHub Actions CI
     check; an external-only status (for example CodeRabbit) does not satisfy
     this requirement.
   - Every check run is successful, skipped, or neutral, and every external
     status context is successful; no check is pending, action-required,
     cancelled, timed out, or failing. GitHub's `statusCheckRollup` uses
     `status`/`conclusion` for check runs but `state` for status contexts, so
     do not treat a context's absent `status` as pending.
   - The tested head SHA still equals the current head SHA.
   - The authenticated user still has a pending review request on the PR, or
     has already approved it — `gh pr review --approve` consumes the review
     request, so a re-checked gate must accept a prior approval — and the PR
     uses the Dependabot GitHub App identity.
   - The changed files are consistent with Dependabot dependency maintenance,
     including manifests, lockfiles, hook configuration, GitHub Actions
     workflow/action version bumps, or Dependabot-managed grouped updates.
   - The risk-tier classification allows merging: routine on green CI, major
     only after the substantive review found no affected usage, and workflow
     files only when the diff is exclusively action-version ref bumps or the
     user promoted the class.
   Leave missing-check, pending-check, failing-check, non-Dependabot,
   non-review-requested (and not user-directed), draft, ambiguous semantic
   source-change, and merge-conflict PRs untouched. Report the reason.
8. For each candidate that passes the merge gate: record the exact head SHA
   and inspect changed files enough to confirm the PR is Dependabot
   dependency maintenance; re-read the check rollup immediately before
   mutation; approve with
   `gh pr review <url> --approve --body "CI checks pass."`; merge with a
   merge commit — `gh pr merge <url> --merge --match-head-commit <sha>` — to
   avoid synthesized co-author trailers. Never use squash merge. If
   repository policy forbids merge commits, stop and report instead of
   silently choosing another method. Verify `state`, `mergedBy`, `mergedAt`,
   and `mergeCommit` with `gh pr view`.
9. Stuck mergeability: if `gh pr merge` fails with "Head branch is out of
   date" but `gh api repos/<owner>/<repo>/compare/<base>...<head>` reports
   `behind_by` 0 and the base branch is unprotected, the PR is stuck in
   GitHub's `mergeable: null` recomputation, not genuinely stale. Do not
   force; re-fetch to prompt recomputation and report if it persists.
   Merging several PRs into the same base in quick succession commonly
   triggers a transient `mergeable: UNKNOWN`/`BLOCKED` on the next sibling
   while GitHub recomputes — re-fetch once and retry the same guarded gate;
   never widen the gate. Leave conflicted (`DIRTY`/`CONFLICTING`) PRs
   untouched and report them. `@dependabot rebase`/`recreate` are mutations;
   post them only with explicit user authorization, and re-run the full merge
   gate afterward.
10. Diagnose failed CI before any repair: read failed GitHub Actions logs
    before cloning, and treat external checks as report-only unless
    separately authorized. For failed `prek`, `pre-commit`, lint, or
    formatting checks, check whether one additional mechanical `prek` commit
    can plausibly make CI pass. The canonical eligible case is a
    `prek`/`pre_commit_checks` failure whose log shows *files were modified
    by this hook* together with *skip: triggered by a bot* (from
    `pre-commit-ci/lite-action`): a formatter reformatted files and the fix
    was never committed because the PR is bot-authored. Eligible fixes are
    deterministic whitespace/EOF/format changes, formatter normalization, and
    narrowly extending an existing lint exception when a tool update split an
    already-ignored rule. Ineligible: changing function signatures, runtime
    logic, tests, workflow behavior, permissions, dependency selections, or
    broad lint policy merely to make CI green. Leave unrelated, flaky,
    infrastructure, documentation-build, or conditional-skip failures
    untouched and report them.
11. Apply an eligible `prek` fix only when the user authorized it:
    confirm the head repository is writable and the remote branch has not
    moved; clone the exact Dependabot branch into a dedicated temporary
    directory (large repositories sequentially); from the failed CI log,
    identify the hook(s) that modified files and run just that formatter
    (`prek run <hook-id> --all-files`) using the repository's pinned/preferred
    runner instead of invoking heavy hooks that need the built project;
    inspect every generated diff and revert anything outside the eligible
    mechanical scope; rerun the affected hook (or the complete
    `prek run --all-files` when the environment can run every hook) until it
    reports no further changes, then run `git diff --check`; confirm the
    remote head still matches the cloned parent before committing; commit
    under the user's configured Git identity with a concise message and no
    `Co-authored-by` or other attribution trailers, verifying author,
    committer, subject, and body with `git show -s`; push only to the exact
    existing Dependabot branch; delete only the dedicated temporary checkout,
    never performing broad cache or filesystem deletion without resolving
    exact targets first.
12. Recheck and finish: monitor the newly created check rollup and wait for
    newly-triggered downstream jobs — a fixed gating check can start jobs
    that were previously skipped, so an empty or all-skipped rollup right
    after the push is not yet a pass. If it becomes green and still passes
    the merge gate, approve and merge against the exact pushed SHA. Otherwise
    leave it open.

## Pitfalls

- `gh pr review --approve` consumes the review request; a re-run of the merge
  gate must accept a prior approval rather than waiting for a new pending
  request.
- External-only success (for example CodeRabbit) is not CI; require at least
  one completed GitHub Actions check run.
- `statusCheckRollup` mixes check runs (`status`/`conclusion`) and status
  contexts (`state`); a context's absent `status` field is not "pending".
- Green CI alone never justifies merging a major or report-only change.
- Do not treat a blanket user approval as covering report-only classes the
  user did not mention; promotions are per session and per risk class.
- CI on the pushed branch is the authoritative full-suite check; a local
  `prek` run of a single hook is only a reproduction, not the final gate.

## Verification

- For every merged PR, read back `state`, `mergedBy`, `mergedAt`, and
  `mergeCommit` with `gh pr view` and confirm the merge method was a merge
  commit with no co-author trailers.
- For every fixed-and-merged PR, confirm the final CI rollup is green on the
  exact pushed SHA.
- Report per PR: URL, dependency scope, risk tier and (for majors) the
  substantive-review evidence, initial CI state, action taken, fix commit SHA
  if any, final CI state, merge commit if any, and the reason every untouched
  PR was left alone. State explicitly that non-Dependabot PRs were untouched
  and whether all commits lack co-author trailers.
- `scripts/snapshot.py` stays read-only: it may query GitHub but must not
  submit reviews, edit branches, or merge PRs.
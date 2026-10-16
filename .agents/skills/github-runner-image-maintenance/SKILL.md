---
name: github-runner-image-maintenance
description: Use when auditing or updating GitHub runner images.
version: 0.1.0
author: Dave Bunten (d33bs), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [github-actions, runners, maintenance, packages, ci]
    related_skills: [python-minimum-version-maintenance, python-latest-version-maintenance]
---

# GitHub Runner Image Maintenance

Proactively audit GitHub-hosted runner images across maintained, published
packages, then propose small upgrades on separate branches and draft PRs.
Prefer the newest viable, explicit, generally available OS label that is not
being deprecated. A registry entry, a runner catalog row, and a green local
lint check are three different pieces of evidence; none proves hosted CI passed.

## When to Use

- Asked to audit runner freshness or retirement exposure across maintained repos.
- Asked to replace deprecated runners or floating `*-latest` OS labels.
- Asked to act on brownout notices without waiting for an email or CI outage.
- Don't use for blanket action-version, language-version, dependency, or hardware
  upgrades. Don't migrate self-hosted runners or Azure pipelines with this skill.

## Prerequisites

- Authenticated GitHub CLI: check with `terminal(command="gh auth status")`.
  Workflow pushes require a credential authorized to change workflow files.
  Never print tokens or change permissions to get around a rejected push.
- Python 3.11+ and `uv` for the read-only helper's declared PyYAML dependency.
  The helper reads registry/GitHub APIs; it never clones, edits, commits, pushes,
  creates PRs, or dispatches workflows. An explicit `--output` writes a local
  report only. Use `read_file`, `search_files`, `patch`, and `write_file` for
  project inspection and edits; use `terminal` for CLI commands and checks.
- Establish approved repos and publishing scope. Building this skill or asking
  for an audit is not permission to update every discovered package. Preserve
  local-only/no-commit/no-push instructions. Do not merge PRs or publish releases.

## How to Run

From the repository root, use `terminal` to run a read-only PyPI-maintainer audit:

```sh
uv run --script .agents/skills/github-runner-image-maintenance/scripts/audit.py \
  --pypi-user HANDLE --output runner-audit.json
```

Put the report in the task's scratch directory rather than committing it.
Add repeated `--repo OWNER/REPO` arguments to limit the published-package
inventory to selected projects. Run `--help` for the exact supported options.

The helper covers PyPI discovery. For other formal registries, use their
current official APIs and perform the same publication/maintainership checks
manually; do not claim automated npm, crates.io, CRAN, or Bioconductor discovery.
A source manifest or a GitHub Release alone is not proof of a registry package.

## Procedure

1. Establish maintainer and package scope. For PyPI, use the helper's live
   owner/maintainer discovery and registry project URLs, then cross-check the
   canonical GitHub repo and current maintenance status. When PyPI omits source
   URL fields, the helper requires a published-description GitHub link plus a
   matching, SHA-pinned package manifest; name similarity alone is not proof.
   Unlinked or legacy setup-only sources remain explicit manual-review outcomes.
   For other registries,
   record the package name, published version, source URL, and maintainer proof.
   Exclude archived repos and unrelated mirrors; report unreachable, ambiguous,
   or missing sources instead of guessing. The helper conservatively excludes
   forks: review a genuinely published canonical fork separately if requested.
   Account for every discovered entry, including skipped/error outcomes; persist
   batches and compute totals programmatically before reporting a shortlist.
   Completion: selected repos are maintained, published, non-archived, and scoped.
2. Refresh official runner evidence on every run. Read the
   [runner image catalog](https://github.com/actions/runner-images), its current
   [announcements](https://github.com/actions/runner-images/issues?q=label%3AAnnouncement),
   the relevant image's software README and completed image releases, and
   [GitHub's runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
   Record UTC access time, catalog commit SHA, source URLs, image status,
   architecture, size, and any deprecation/brownout/removal dates. Follow an
   announcement before trusting an unbadged catalog row. Check closed notices
   too: closed does not necessarily mean a retirement was cancelled. Exclude
   previews, betas, retired/deprecating images, and unconfirmed future releases.
   Resolve contradictory official sources or flag uncertainty; do not use an
   email, search snippet, remembered label mapping, or OS vendor lifecycle alone.
   Completion: each proposed label has fresh, source-backed GA/support evidence.
3. Inventory runner selection on each repo's pinned default-branch SHA. Inspect
   all workflow files, reusable workflows and their inputs/defaults, job-level
   `runs-on`, groups/labels, matrix axes/include/exclude, variables, and invoked
   local actions/scripts. Trace dynamic selectors to definitions and callers;
   report unresolved expressions and remote reusable workflows for manual review.
   Arrays in `runs-on` combine labels; they are not an OS matrix. Preserve
   self-hosted/custom-group selectors. A label in an unrelated example/comment
   is not an active job, and changing a matrix axis must also update matching
   conditional branches, includes/excludes, artifact names, and cache keys where
   they actually depend on that value. Inspect test and Dependabot jobs together
   so essential setup steps do not drift.
   Completion: every affected job has a resolved selector or explicit review flag.
4. Classify each selector: deprecated/retired, floating alias, older supported
   GA, current explicit GA, preview, or unknown/custom. Prioritize imminent
   removals and brownouts, but also consider supported pins behind the newest GA.
   Resolve aliases from current evidence, not string substitution. Select the
   newest viable explicit version within the same OS family, architecture,
   runner size, and required toolchain flavor. Compare version numbers
   numerically; keep Ubuntu Slim/container and Windows client/server variants
   distinct. Never invent a label from an OS version or add a patch number that
   GitHub does not expose. Catalog-generated suggestions are review candidates,
   not proof that the replacement is supported for this particular project.
   Completion: old/new label, reason, evidence, and compatibility risks are stated.
5. Check the project's actual compatibility constraints before editing. Inspect
   minimum and newest tested language versions, action architecture support,
   dependency wheels, native libraries, browser/GPU/headless setup, Xcode/SDKs,
   signing, containers, shell behavior, caches, and hardcoded install paths.
   Compare old/new included software; explicitly provision required tools rather
   than relying on an image's incidental defaults. For Python, read both
   `python-minimum-version-maintenance` and `python-latest-version-maintenance`
   once to review the whole supported range. A runner change does not authorize
   raising the Python floor or dropping an existing OS/architecture test job.
   Keep paid runner size/cost and Intel/ARM transitions separate unless explicitly
   authorized. If the newest GA cannot run the support matrix, record the blocker
   and propose an explicit, non-deprecated fallback with evidence; never silently
   use `latest`, preview, fewer tests, or a different architecture to get green.
   Completion: the candidate preserves support promises or has an explicit blocker.
6. For approved repos, inspect status/remotes/guidance and fetch the current
   upstream default branch. Create a fresh, non-tracking branch from that base,
   not from another package upgrade PR. Check existing PRs for duplicates and
   avoid overwriting uncommitted work. Make the narrow runner/related selector
   edits with `patch`; preserve triggers, permissions, secrets, release guards,
   dependencies, Python versions, and test assertions. Do not globally replace
   matching strings or retrofit archival docs. Run a dry-run/diff inspection
   before staging and account for every changed file.
   Completion: a small diff changes only intended runner selection and necessary
   compatibility setup, with unrelated work untouched.
7. Run configured workflow/YAML/action lint and relevant local package checks.
   Exercise the supported minimum and newest tested runtime locally where
   available, plus build/installed-artifact smoke paths when image tools affect
   packaging. If current lint tooling lacks an officially confirmed GA label,
   update the tool first, then document only the exact source-backed exception
   if still necessary; never disable runner validation wholesale.
   A local Mac or Linux container is not the GitHub-hosted image.
   Record commands, actual interpreters/platforms, skips, and pre-existing errors
   separately; keep unexercised remote combinations provisional.
   Completion: local checks pass or the draft accurately names remaining evidence.
8. When publishing is authorized, commit only the scoped files, push to the
   intended fork, and verify the remote SHA. Open one draft PR per project with
   explicit base/head and a short title plus two-sentence body: the runner change
   and actual verification. Include the official notice link when deprecation
   motivated the change. Keep detailed logs and the full audit in scratch, not
   in the PR description. Read back exact URL, draft/open state, base/head repos,
   branches, head SHA, title, and body. Do not mark ready or merge automatically.
   Completion: the correct draft PR exists for each approved changed project.
9. Inspect hosted CI on the exact published head. Use check-run app ownership
   and workflow jobs, not just a review bot's green status. Read the job's actual
   runner labels/architecture and image/setup logs; compare expected matrix jobs
   with those executed. A required job skipped by a stale condition is missing
   coverage, not a pass. Distinguish image brownouts, missing tools, architecture
   failures, and code/test regressions. Fix small in-scope issues, rerun checks,
   and verify new head state. Report queued, approval-required, draft-skipped,
   absent, timed-out, or failing CI honestly. Do not bypass security guards,
   dispatch publishing workflows, or mark a draft ready just to force execution.
   Completion: PR URLs and observed CI outcomes are reported, with unverified
   combinations/blockers explicit and all PRs left as drafts.

## Pitfalls

- Read [source notes](references/runner-sources.md) for a dated worked example;
  its version labels and retirement dates must be refreshed, not reused as policy.
- `macos-14`, `macos-14-large`, and `macos-14-xlarge` are not interchangeable
  hardware classes. The same warning applies to newer labels and `*-latest`.
- An explicit OS label still receives rolling image/tool updates; it is not an
  immutable image digest. Record the actual image version from hosted CI.
- An image README's announcement table can mention a different image's retirement.
  An issue's unchecked platform list and mitigation labels are not affected labels.
- Preserve UTC date boundaries and the source's exact tokens. Flag impossible or
  contradictory brownout intervals rather than silently correcting their dates.
- Draft PRs can be skipped by project policy or need fork approval. Never call
  zero check runs, external-only statuses, or a skipped matrix green validation.

## Verification

Every scoped repo has a published-package eligibility decision, a complete runner
inventory or explicit gaps, current official evidence, and a no-change/proposed/
blocked result. Every published change has a read-back-verified draft PR and an
honest hosted-CI outcome. Skill tests and a live read-only audit must run before
calling the helper verified; they do not establish that package runner upgrades
passed hosted CI.

# Runner Evidence and Migration Notes

Use live official sources on every run. This worked example was checked on
October 16, 2026; it is evidence for the skill's first trial, not a permanent
replacement map or retirement calendar.

## Source precedence

1. [Current runner catalog](https://github.com/actions/runner-images/blob/main/README.md):
   supported label spelling, architecture, image status, and image README links.
   Record its commit SHA; do not use a cached search result as the catalog.
2. [Announcement issues](https://github.com/actions/runner-images/issues?q=label%3AAnnouncement):
   GA promotion, deprecation, image removals, brownouts, alias migrations, and
   breaking software changes. Read the body and relevant updates, not just tags.
3. The chosen image's software README and completed release: actual tools,
   image version, OS version, and deployment evidence. A software release's
   pre-release flag can mean deployment is underway; do not confuse it with an
   OS being generally available everywhere.
4. [Runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
   and [larger-runner labels](https://docs.github.com/en/actions/using-github-hosted-runners/using-larger-runners/running-jobs-on-larger-runners):
   hardware class, access/billing, architecture restrictions, and label syntax.
5. Exact-head hosted job logs: the image and architecture actually exercised.
   This final observation, not a local test or an available-image row, establishes
   that the proposed project's jobs ran on the intended image.

If sources disagree, compare dates and the specific image/architecture in the
newer announcement. Stop or flag manual review if the conflict remains. A current
catalog row can lack a deprecation badge even when an active notice exists.

## First-trial snapshot

Catalog commit:
`ee1ff4569e381a9649b400338bdc8ceb7e18a80e`.

The catalog's macOS 26 rows distinguish standard ARM64 `macos-26`, ARM64 larger
`macos-26-xlarge`, and Intel `macos-26-intel`/`macos-26-large`. Preserve size and
architecture, then verify availability and project compatibility. Do not map
all retired macOS labels to one new label or assume a suffix guarantees the same
CPU count, memory, price, or toolchain forever.

The [macOS 14 notice](https://github.com/actions/runner-images/issues/13518)
sets retirement for November 2, 2026 and affects `macos-14`, `macos-14-large`,
and `macos-14-xlarge`. Its October 16 brownout spans 14:00 UTC on October 16
through 00:00 UTC on October 17. Keep the cross-midnight boundary explicit.
The catalog identifies the standard/xlarge variants as ARM64 and large as Intel.
The [macOS 26 ARM64 software inventory](https://github.com/actions/runner-images/blob/main/images/macos/macos-26-arm64-Readme.md)
provides a separate check on tools and preinstalled runtimes; provision missing
supported runtimes with the project's setup action rather than removing tests.

The [Ubuntu 26.04 GA announcement](https://github.com/actions/runner-images/issues/14747)
confirms GA on September 17, 2026 for `ubuntu-26.04` and `ubuntu-26.04-arm`.
The catalog still associates `ubuntu-latest` with 24.04 in this snapshot, so
resolving `latest` alone does not find the newest available explicit GA label.
A public-preview entry in an older documentation/search copy is not enough to
contradict a newer, explicit GA announcement.

The [Ubuntu 22.04 notice](https://github.com/actions/runner-images/issues/14254)
states retirement on April 17, 2027, although the catalog's 22.04 rows lack a
retirement badge. Several brownout lines in that notice give a same-day end time
earlier than the start time. Preserve that discrepancy, flag it for confirmation,
and do not invent corrected intervals. Its unchecked lists of other images do
not mean that those images are also deprecated.

## Validator catalog lag

The current actionlint release, 1.7.12, recognizes macOS 26 but does not yet
recognize the confirmed GA `ubuntu-26.04` label. Update an old validator first;
if its current release still lags GitHub's official catalog, a narrowly documented
additional-label entry can validate the real hosted label without disabling
workflow lint. The skill's draft CI uses that exact exception in
`.github/actionlint.yaml`. Despite actionlint's configuration key being named
`self-hosted-runner`, it does not change how GitHub schedules the workflow.
Remove the exception when the validator's built-in catalog catches up. Never
allow arbitrary unknown labels or suppress all runner-label diagnostics.

## Required compatibility review

- Compare image tools against the commands actually used by the workflow:
  compilers, SDKs, Xcode, browsers, native dependencies, display/headless setup,
  shell features, package manager paths, signing, containers, and caches.
- Check action/runtime and wheel availability for both the package's minimum
  and newest tested runtime on the target architecture. Do not infer ARM support
  from an x64 wheel, or successful installation from a resolver-only result.
- Preserve Intel/ARM and standard/larger classes by default. A larger-runner
  label may require organization configuration and paid access even when the
  image itself is GA; ask before changing cost or resource class.
- Keep test selection conditions and matrix include/exclude entries consistent.
  A new runner label can cause `if: matrix.os == 'old-label'` to skip the only
  coverage job while the rollup still appears green.
- Read duplicated test/Dependabot/release setup paths together. Do not drop a
  display service, system package, tool setup, or release guard in one path.
- Retain the draft PR until a maintainer reviews the actual hosted CI result.
  Migrating the runner does not authorize merging, publishing, or rewriting
  another open Python-version PR.

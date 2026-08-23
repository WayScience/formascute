---
name: isilon
description: Use before mounting, testing, transferring, or documenting CU Anschutz DBMI Isilon storage access, especially SMB mounts, local transfer behavior, data-handling rules, or Isilon-to-PetaLibrary movement.
---

# Isilon Skill

Use this note before mounting, testing, or transferring data to/from CU
Anschutz's DBMI Isilon storage from a local machine. See
`.agents/skills/petalibrary/SKILL.md` for the PetaLibrary side of an
Isilon-to-PetaLibrary transfer, and `.agents/skills/alpine/SKILL.md` for
Alpine/HPC knowledge — this file covers Isilon specifically. For measured
performance numbers, see `docs/storage-mount-benchmark.md` and the reproducible script at
`examples/benchmark_storage_mount.sh` — this skill intentionally does not
carry exact benchmark figures itself, since they're time/location/session-
specific and go stale fast; re-run the script rather than trusting a number
recorded here. It does carry a rough, order-of-magnitude expectation for
off-campus-VPN vs. on-campus speed below, since that's useful for planning a
transfer even without a fresh benchmark run.

**Data handling rule for this file, and for working with any real Isilon
mount in this project: never record real share names, file names, directory
names, or directory listings from inside an Isilon share in this skill, in
commit messages, or anywhere else committed to the repo.** Isilon shares here
are lab-specific and can contain Confidential or Highly Confidential data per
CU's data classification policy — the share name itself can identify a lab.
It's fine to create, read, and delete disposable throwaway test files/dirs on
a live share to validate behavior — just don't name or describe real shares
or content anywhere durable. This applies equally to `docs/storage-mount-
benchmark.md` — that file records methodology and results, not real share
names.

## Current Position

- Isilon here means CU Anschutz's "Isilon Central File Server," accessed over
  SMB from host `data.ucdenver.pvt`, requested per-lab via
  `dbmi@medschool.zendesk.com` with a SpeedType for billing. See What Isilon
  Is.
- The CU-DBMI `data-storage` repo ships a mount script
  (`src/mount_isilon.sh`) that mounts any share at
  `//data.ucdenver.pvt/dept/SOM/DBMI/<share>` to `~/mnt/<share>` using
  `mount_smbfs` on macOS or `mount.cifs` on Linux. See Mounting A Share.
- A real, live share on this machine follows that convention exactly and has
  been used to validate the mount behavior and failure modes below. Its name
  is intentionally not recorded here (see the data handling rule above); if
  you need to reference it directly, check `mount | grep smbfs` locally
  rather than looking for a name in this file.
- A serious gotcha was found while probing this mount: unmounting a live
  share to try to get a clean cache-free measurement can leave it unable to
  reconnect non-interactively, even with working credentials. See Important
  Failure Modes, and the full writeup in `docs/storage-mount-benchmark.md`.

## What Isilon Is

*Source: CU-DBMI `data-storage` repo, `docs/data-transfer-guide.md`.*

Isilon is described there as the primary named storage system for CU
Anschutz DBMI work — a "Central File Server" billed via SpeedType allocation.
To request Isilon storage for DBMI work, contact
`dbmi@medschool.zendesk.com`; current rates are listed under "Isilon Central
File Server" on the CU Anschutz OIT Billing and Rates page. For Confidential
or Highly Confidential data, the share itself must be separately confirmed as
approved for that classification, with access limited to authorized users —
requesting a share doesn't automatically clear it for sensitive data.

## Mounting A Share

*Scope: general — macOS and Linux, from a local machine or any host with
network/VPN reachability to `data.ucdenver.pvt`. VPN is required when
off-campus.*

The CU-DBMI mount script, run directly from GitHub:

```bash
curl https://raw.githubusercontent.com/CU-DBMI/data-storage/main/src/mount_isilon.sh | sh
```

Safer variant that lets you read the script before running it:

```bash
curl -fsSL https://raw.githubusercontent.com/CU-DBMI/data-storage/main/src/mount_isilon.sh -o /tmp/mount_isilon.sh
less /tmp/mount_isilon.sh
sh /tmp/mount_isilon.sh
```

The script accepts any of these input styles interactively (placeholders
below stand in for a real lab/share name — the CU-DBMI doc's own examples use
real lab names, which this skill deliberately doesn't repeat):

```text
<LabOrShareName>
dbmi/<LabOrShareName>
smb://data.ucdenver.pvt/dept/som/dbmi/dbmi/<LabOrShareName>
```

What it actually does (read directly from the script, confirmed by matching
its behavior manually — see below):

- A bare name (no `/` prefix, no `smb://`) is expanded to
  `//data.ucdenver.pvt/dept/SOM/DBMI/<name>`.
- A `smb://...` or `//...` input is used as the literal UNC path instead.
- The local mount point is always `~/mnt/<last-path-component>`, matching
  this machine's existing `~/mnt/<share>` convention for other mounts.
- Prompts for a local file/dir permission mode, default `775`.
- Pings the extracted host first and fails fast with a VPN/network hint if
  unreachable, before attempting the mount.
- macOS: `mount_smbfs -d <mode> -f <mode> "<share>" "<mount_point>"`, using
  the current login keychain for credentials if available (no interactive
  prompt in that case).
- Linux: installs `cifs-utils` if missing (`apt-get` or `yum`), prompts for a
  CIFS/Anschutz username, then
  `mount -t cifs "<share>" "<mount_point>" -o username=...,uid=...,gid=...,domainauto,file_mode=...,dir_mode=...`.

**Manually reproducing the same mount** (equivalent to what the script does,
useful when scripting or testing without the interactive prompts), macOS:

```bash
mount_smbfs -d 0775 -f 0775 "//data.ucdenver.pvt/dept/SOM/DBMI/<share>" "$HOME/mnt/<share>"
```

Confirmed in this project: this exact invocation authenticated automatically
via the existing login keychain entry for `data.ucdenver.pvt` — no
interactive credential prompt — for both a share that exists (already
mounted, so it correctly reported already-in-use) and a share name that
doesn't exist (cleanly rejected server-side). This means the manual form is
safe to script/test with non-interactively on a machine that already has a
working keychain entry for the host; a machine without one would presumably
need the interactive credential prompt the script relies on `mount_smbfs`'s
own default behavior for — not yet tested here.

Windows and a from-scratch macOS Finder walkthrough are documented separately
in the CU SOM knowledge base:
`https://medschool.zendesk.com/hc/en-us/sections/360005463054-Map-to-SOM-Network-Drive`
(not fetched into this skill — check there directly if the command-line path
doesn't fit).

## Distinguishing "Share Doesn't Exist" From Network/Auth Failures

*Scope: general troubleshooting, macOS `mount_smbfs`.*

Confirmed directly in this project: `mount_smbfs` gives a clearly different
error depending on failure cause, which is a fast first diagnostic:

- **`No such file or directory`** — the server was reached and the client
  authenticated, but the specific share/path doesn't exist. Don't chase VPN
  or credentials on this error; re-check the share name and case with
  whoever administers it instead.
- **`File exists`** — a local mount-point conflict, not a remote problem. See
  the CU-DBMI doc's own FAQ for this (stale mount entry, already mounted,
  or a directory in a state macOS won't mount over):

  ```bash
  mount | grep <ShareName>          # already mounted?
  umount ~/mnt/<ShareName>          # unmount if so
  diskutil unmount ~/mnt/<ShareName>  # if umount reports "Resource busy"
  ls -la ~/mnt/<ShareName>          # if not mounted, is it just an empty dir?
  rmdir ~/mnt/<ShareName>           # remove if empty and unmounted, then retry
  ```

- **A variant of the `File exists` case found in this project**: attempting
  to `umount` a share that's *currently mounted and working* (not stale) can
  itself return `Resource busy` if something still holds it open, and an
  immediate `mount_smbfs` retry on the same mount point then correctly fails
  `File exists` because the old mount never actually released. This is a
  different root cause than the doc's own FAQ (an active, healthy mount vs.
  a leftover/failed one) but produces the same-shaped error. Use
  `diskutil unmount` first in this case too, and re-check `mount | grep
  <ShareName>` before retrying rather than assuming the first `umount`
  succeeded.
- No network/ping failure was reproduced in this project (VPN/network was
  reachable throughout), so that failure path is documented from the
  CU-DBMI guide only, not independently confirmed here.

## Expected Speeds: Off-Campus VPN vs. On-Campus

*Scope: general expectation, not a guarantee. Based on one client machine's
measurements in `docs/storage-mount-benchmark.md` (greater Denver, CO,
off-campus over CU Anschutz VPN vs. on-campus with no VPN, same share both
times). Treat this as "what order of magnitude to expect," and re-run
`examples/benchmark_storage_mount.sh` for a current number before relying on
anything more precise.*

- **Off-campus, over VPN:** expect sequential write throughput in the
  **low tens of MB/s** (~17-26 MB/s measured across two sessions).
- **On-campus, no VPN:** expect roughly **4x faster** sequential write
  throughput than the VPN case — around **85-95 MB/s** measured, same share,
  same client.
- Small-directory listing/creation stayed sub-second in both conditions
  (roughly 0.02-0.1s on-campus vs. up to a few seconds for a large root
  listing over VPN) — write throughput is the more load-bearing number for
  planning a transfer, not listing latency.
- If a transfer or interactive session feels unexpectedly slow off-campus,
  VPN overhead is a more likely explanation than an Isilon-side problem —
  the on-campus/VPN gap observed here (~4x) was large enough that network
  path, not the storage backend, was the dominant variable.
- This says nothing about read throughput (not validly measured in either
  condition — see the cache-inflation caveat in Important Failure Modes
  below) or behavior under concurrent access/many-small-files/larger
  transfers.
- Isilon and PetaLibrary tracked each other reasonably closely within each
  condition (see `.agents/skills/petalibrary.md` for its own version of this
  section, and `docs/storage-mount-benchmark.md` for the numbers) — this is
  about location/network, not a claim that one storage system beats the
  other.

## Isilon → PetaLibrary Transfer (Globus)

*Scope: when moving data from an Isilon share to a PetaLibrary allocation.
Documented from the CU-DBMI guide; see `.agents/skills/petalibrary.md`
Globus Access for the PetaLibrary-side setup steps referenced here.*

The CU-DBMI guide's recommended workflow:

1. Connect to VPN if off-campus.
2. Mount the Isilon share on a workstation (Mounting A Share above).
3. Install and configure Globus Connect Personal on that workstation.
4. Expose the mounted Isilon folder through the local Globus endpoint.
5. In the Globus web interface, connect the local endpoint to the
   PetaLibrary endpoint (see `.agents/skills/petalibrary.md` for the actual
   PetaLibrary-side collection name and login flow).
6. Start with a small test transfer; validate it before running the full
   transfer.
7. Validate files at the destination (file counts/sizes, checksum a sample)
   before removing or archiving the source copy.

The guide explicitly warns: Isilon snapshots and disaster-recovery
replication are not a substitute for transfer validation — confirm the
destination copy directly even when both are in place. It also warns against
routing this kind of transfer through OneDrive or another constrained
intermediate location.

## Before You Transfer (checklist from the CU-DBMI guide)

*Scope: general — applies to any Isilon-involving transfer, not just
Isilon→PetaLibrary.*

Confirm before starting:

- Source and destination locations, and the data owner (PI is the default
  accountable owner unless a different technical owner is required).
- The SpeedType/funding source for billable Isilon or PetaLibrary storage.
- Data classification: Public, Confidential, or Highly Confidential, per
  CU's Data Classification guidance.
- Whether the data include HIPAA, PHI, identifiable participant data, or
  other data with additional restrictions.
- Who/which service accounts need access at the destination.
- VPN access for internal CU Anschutz resources.
- Expected data size and file count; whether the transfer needs to be
  resumable and verified (favor Globus over manual copy for large/many-file
  transfers).
- Whether the old copy must be retained temporarily for rollback.

For large transfers, move a small test folder first and validate it before
starting the full transfer. **Do not transfer Highly Confidential data**
until the data owner and campus IT/security have confirmed the source,
destination, workstation, transfer tool, and access controls are approved
for that classification — this applies to Isilon, PetaLibrary, Globus,
Globus Connect Personal, and any intermediate system. CU Boulder OIT
guidance says to contact the Office of Information Security before choosing
a tool for Highly-Confidential-classified research data specifically.

## Important Failure Modes

- Do not treat `mount_smbfs: ... No such file or directory` as a VPN/network
  problem — it means the server was reached and auth succeeded, but that
  specific share/path doesn't exist. Re-check the name/case instead of
  troubleshooting connectivity.
- Do not assume a failed `umount` means the mount is gone — check `mount |
  grep <name>` again before retrying `mount_smbfs`, and use `diskutil
  unmount` if plain `umount` reports `Resource busy`.
- Do not benchmark "read throughput" by reading a file immediately after
  writing it on the same mount without clearing the client cache first — the
  local page cache will report multi-GB/s numbers that have nothing to do
  with the actual network/share performance. See
  `docs/storage-mount-benchmark.md`.
- Do not unmount a live, in-use Isilon mount to try to force a cold read for
  benchmarking. Confirmed in this project: the remount can fail with
  `Authentication error` even using the exact command and keychain entry
  that mounted it successfully moments earlier, leaving it unmounted until a
  human reconnects interactively. The benchmark number isn't worth the risk
  of an unplanned outage on a mount someone is actively relying on. Full
  incident writeup: `docs/storage-mount-benchmark.md`.
- Do not write real Isilon share names, file/directory names, listings, or
  content into this skill, commit messages, or any other durable repo
  artifact — share names here are lab-identifying, and some shares may hold
  Confidential or Highly Confidential data. Disposable, clearly-marked test
  files are fine to create and immediately delete for validation.
- Do not initiate a Highly Confidential data transfer through Isilon,
  PetaLibrary, or Globus without the data owner's and campus IT/security's
  explicit sign-off on every hop (source, destination, workstation, tool).

## Open Questions

- What is a second real, accessible DBMI Isilon share to properly compare
  against the one validated so far? Still open — see
  `docs/storage-mount-benchmark.md` Open Questions for the fuller list of
  what a repeat run should try to answer.
- Why did a remount fail with `Authentication error` right after a clean
  `umount`, using the same command and keychain entry that worked moments
  before? Worth asking CU Anschutz IT/DBMI directly rather than guessing —
  possibly session-token vs. keychain-password behavior specific to this SMB
  server or client.
- Does this machine's keychain-based no-prompt `mount_smbfs` behavior hold
  for other DBMI Isilon shares/users, or is it specific to already having a
  cached credential for `data.ucdenver.pvt`? Untested against a host with no
  prior keychain entry.

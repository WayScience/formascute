# Storage Mount Benchmark: Directory Listing, Write, And Read Timing

A small, reproducible experiment comparing basic operation timing on two
network-mounted storage systems used by this project: DBMI Isilon (SMB) and
CURC PetaLibrary (sshfs). See `.agents/skills/isilon/SKILL.md` and
`.agents/skills/petalibrary/SKILL.md` for what these systems are and how to
mount them — this doc is just the benchmark methodology and results, kept separate
so the skills don't carry numbers that go stale.

**Data handling:** results below are aggregate timings only. No real share
name, allocation name, file name, or directory listing from either system
appears in this document — see the data handling rule in both skills for why.

**Location/network:** the first round of numbers below was measured from one
client machine, physically in the greater Denver, Colorado area, off-campus.
Isilon access requires CU Anschutz VPN when off-campus (confirmed reachable
throughout); whether VPN was active for the PetaLibrary/Alpine SSH leg
specifically wasn't independently confirmed. A second round was later
measured from the same client machine, physically on-campus, with no VPN in
use for either system. Neither round generalizes to a different client
location, network path, or time of day — re-run the script for a current
number rather than trusting anything here.

## Reproduce it yourself

```bash
./examples/benchmark_storage_mount.sh <mount-path> [size-mb]
```

The script:

1. Times listing the existing root of `<mount-path>`.
2. Creates a disposable, PID-suffixed test directory (`.benchmark-test-<pid>`)
   under it — never touches anything else.
3. Times listing that empty test dir.
4. Times a sequential write of a `[size-mb]`-sized (default `20`) zero-filled
   test file into it.
5. Times listing the dir again (now containing one file).
6. Times reading that file back immediately — labeled clearly as a
   cache-warm number, not a network read (see Known Limitation below).
7. Deletes the test file and directory and confirms removal, via a `trap` so
   cleanup runs even on failure.

It never unmounts anything and never touches content outside the test
directory it creates. Run it against any mounted path, e.g.:

```bash
./examples/benchmark_storage_mount.sh ~/mnt/<isilon-share> 20
./examples/benchmark_storage_mount.sh ~/mnt/alpine/active/<writable-allocation-subdir> 20
```

Note: the top-level PetaLibrary `/pl/active` mount root is not directly
writable by every account (it's shared across many allocations) — pointing
the script straight at `~/mnt/alpine/active` will fail at the
"create disposable test dir" step with `Permission denied`. Point it at a
specific allocation subdirectory you have write access to instead.

## Known limitation: read timing isn't a real network number

Reading a file immediately after writing it is served from the local OS page
cache on both macOS SMB and sshfs, at multi-GB/s — this has nothing to do
with actual network/share read performance. The script still runs and
reports this step (so the timing loop stays simple and uniform across
storage systems), but the read number should not be cited as a real
performance figure without independently forcing a cold read.

**Do not try to force a cold read by unmounting and remounting the target on
the same client.** This was tried by hand once against a live Isilon mount
in this project (not via the script, which deliberately doesn't attempt it)
and caused a real incident:

- `umount` on the live share succeeded cleanly (no `Resource busy`).
- The immediate `mount_smbfs` remount — the exact same command, same
  login-keychain credential, that had mounted the share successfully minutes
  earlier — failed with `server rejected the connection: Authentication
  error`.
- Network/VPN reachability was independently confirmed fine via `ping`
  immediately after, and a second remount attempt failed the same way.
- This left the share **unmounted** for the rest of that session. Recovery
  required the human user to reconnect interactively (Finder → Connect to
  Server); no further non-interactive `mount_smbfs` retry succeeded, and
  retrying repeatedly was avoided to reduce account-lockout risk.
- Root cause unconfirmed. A plausible explanation: the original mount was
  established through a different flow (e.g. an interactive session at some
  point in the past) that isn't equivalent to a fresh non-interactive
  `mount_smbfs` call, even with a matching keychain entry present — not
  isolated further. Worth asking CU Anschutz IT/DBMI directly.

Because of this, the PetaLibrary side of this experiment (run in the same
session, minutes later) deliberately did not attempt the same unmount/remount
trick — not worth risking a second live mount the same way. If a genuinely
cold read number is needed, the safer approach is reading from a second,
independent client/host rather than disrupting a mount someone else may be
relying on.

## Results: off-campus, VPN (Denver area)

Two runs against one live Isilon share, one run against one PetaLibrary
allocation subdirectory (via sshfs), same session unless noted.

| Step | Isilon (SMB), run 1 | Isilon (SMB), run 2 | PetaLibrary (sshfs) |
| --- | --- | --- | --- |
| List existing root | not measured | 3.55s | 1.44s |
| Create test dir | not measured | 0.32s | 0.75s |
| List empty test dir | not measured | 0.32s | 0.35s |
| Write 20MB | 0.81s (~26 MB/s) | 1.19s (~17.7 MB/s) | 1.25s (~16.8 MB/s) |
| Write 50MB | 1.98s (~26 MB/s) | not measured | not measured |
| List dir w/ 1 file | not measured | 0.36s | 0.65s |
| Read 20MB back | cache-inflated (multi-GB/s) | attempted forced cold read — broke the mount, see above | cache-inflated (~5 GB/s) |

Observations:

- Write throughput landed in a **~17-26 MB/s** range across both Isilon runs
  and the one PetaLibrary run — consistent enough to call
  low-tens-of-MB/s the right order of magnitude for this client/network path
  on both systems, but with enough spread (26 vs. 17.7 on Isilon alone,
  different times of day) that the exact number shouldn't be treated as
  fixed.
- Isilon's root-listing time (3.55s) was roughly 10x the empty-test-dir
  listing time (0.32s) in run 2, consistent with per-entry listing cost
  dominating fixed per-call overhead — but this is one measurement against
  one share with an unrecorded entry count, not a calibrated per-entry rate.
- PetaLibrary's root listing (1.44s) was faster than Isilon's (3.55s) in the
  same session, but the two roots almost certainly contain different numbers
  of entries, so this is not a valid protocol-level comparison — it would
  need matched entry counts (or listing the same-sized test dir on both,
  which the create/list-empty/list-with-1-file rows do give a cleaner
  comparison for: Isilon ~0.32-0.36s vs. PetaLibrary ~0.35-0.75s for
  directory-creation and small-listing operations).
- No valid read (network, cold-cache) number exists for either system yet.

## Results: on-campus, no VPN

Two runs each against the same live Isilon share and the same PetaLibrary
allocation subdirectory used above, same session, back-to-back. For
PetaLibrary, "root" here means the same writable allocation subdirectory the
test dir was created under (not the top-level `/pl/active` mount root, which
this account can't write into directly and which lists hundreds of unrelated
entries — not a fair comparison target). That makes the two "root" listings
below closer to apples-to-apples than the VPN round above, since both are
now a single, similarly-sized personal/working directory rather than one
huge shared root vs. one small one.

| Step | Isilon (SMB), run 1 | Isilon (SMB), run 2 | PetaLibrary (sshfs), run 1 | PetaLibrary (sshfs), run 2 |
| --- | --- | --- | --- | --- |
| List existing root | 0.244s | 0.087s | 0.278s | 0.073s |
| Create test dir | 0.108s | 0.102s | 0.066s | 0.036s |
| List empty test dir | 0.028s | 0.018s | 0.024s | 0.020s |
| Write 20MB | 0.233s (~85.8 MB/s) | 0.212s (~94.3 MB/s) | 0.259s (~77.2 MB/s) | 0.244s (~82.0 MB/s) |
| List dir w/ 1 file | 0.018s | 0.016s | 0.024s | 0.022s |
| Read 20MB back | cache-inflated (multi-GB/s) | cache-inflated (multi-GB/s) | cache-inflated (~16.6 GB/s) | cache-inflated (~16.3 GB/s) |

Observations:

- **On-campus is dramatically faster than VPN for both systems.** Average
  write throughput: Isilon ~90.1 MB/s on-campus vs. ~21.9 MB/s over VPN
  (**~4.1x faster**); PetaLibrary ~79.6 MB/s on-campus vs. ~16.8 MB/s over
  VPN (**~4.7x faster**, though the VPN figure is n=1). Both systems moved
  from "low tens of MB/s" to "high tens/~90 MB/s" the moment the VPN hop was
  removed — consistent with the VPN tunnel (not the storage backend) being
  the dominant bottleneck in the earlier round.
- **On-campus, Isilon and PetaLibrary are close, with Isilon modestly
  ahead.** Write: Isilon averaged ~90.1 MB/s vs. PetaLibrary's ~79.6 MB/s
  across two runs each — about 13% faster for Isilon, but with only n=2 per
  system and a single run's spread (85.8 vs. 94.3 MB/s on Isilon alone)
  already covering nearly that whole gap. Not a confident win either way.
- **Directory listing/creation on-campus is essentially tied.** Empty-dir
  listing: Isilon ~0.023s avg vs. PetaLibrary ~0.022s avg. No meaningful
  difference at this scale — both are dominated by fixed per-call/round-trip
  overhead rather than anything protocol-specific.
- Read numbers are still cache-inflated on both systems and still don't tell
  us anything about real read throughput, on-campus or otherwise.

## Open Questions

- What does a genuinely cold read look like on either system, on-campus or
  over VPN? Needs a second, independent client/host to avoid the unmount
  risk above.
- Why did the Isilon remount fail with `Authentication error` right after a
  clean `umount`, using the same command and keychain entry that worked
  moments before? Worth asking CU Anschutz IT/DBMI directly. (The mount was
  later recovered interactively and is in use again for the on-campus
  round.)
- ~~What would these numbers look like from a client on-campus, off VPN
  entirely?~~ Answered above: both systems are roughly 4-5x faster on-campus
  than over VPN for writes, and the Isilon-vs-PetaLibrary gap narrows to
  "close, Isilon modestly ahead" on-campus vs. the VPN round (too little VPN
  data to compare fairly there — n=1 for PetaLibrary over VPN). Still open:
  numbers from VPN on a different geography, or on-campus at a different
  time of day — only one on-campus session (n=2 per system) has been
  measured so far.
- A genuine second Isilon share (to compare against the one used here) and a
  larger/more representative directory-entry-count comparison across systems
  are both still open — repeat the script against each once available.
- Does this hold up under concurrent access, many-small-files patterns, or
  larger file sizes? This experiment only covers a single sequential
  20-50MB file against an otherwise-idle mount.

# Alpine Findings

These findings come from small synthetic formascute runs on CURC Alpine. No NF1
image data were used.

## Validated Setup

- Submit from the Alpine login node with `SUBMIT_HOST=Persistence1`.
- `Persistence1` is the selected submission location for this project.
- Use the project allocation supplied by the user.
- Use partition `acpu` and QoS `cpu-normal`.
- The coordinator job loads `nextflow/25.10.2`.
- `Persistence1` exposes the Nextflow module tree; the regular login node did
  not expose that module during testing.
- `/usr/bin/apptainer` and `/usr/bin/singularity` are available on the tested
  compute environment.
- A project-owned `uv` install under `/projects/$USER/software/uv` can build a
  Python 3.12 ZedProfiler environment when the documented CURC `uv` module is
  not visible.

The validated smoke command was:

```bash
make submit EXPERIMENT=nf1_featurization_independent ITEMS=4 ACCOUNT=<allocation> SUBMIT_HOST=Persistence1 RUN_ID=remote-smoke-persistence
```

Result:

- coordinator job completed
- Nextflow exit status was `0`
- validation passed
- `trace.tsv` contained native Slurm job IDs
- `slurm.tsv` was collected

## Small Experiment Results

All runs validated successfully.

| mode | experiment | items | batch | coordinator elapsed | native jobs | median wait |
| --- | --- | ---: | ---: | --- | ---: | ---: |
| burst | `nf1_minimal_overhead` | 1 | 1 | 00:00:21 | 2 | 1 s |
| burst | `nf1_featurization_independent` | 4 | 1 | 00:00:27 | 5 | 1 s |
| burst | `nf1_featurization_independent` | 16 | 1 | 00:00:52 | 17 | 1 s |
| burst | `nf1_featurization_batched_2` | 16 | 2 | 00:00:41 | 9 | 1 s |
| burst | `nf1_featurization_batched` | 16 | 4 | 00:00:37 | 5 | 0 s |
| burst | `nf1_queue_size_4` | 16 | 1 | 00:00:57 | 17 | 0 s |
| burst | `nf1_queue_size_20` | 16 | 1 | 00:01:06 | 17 | 0 s |
| burst | `nf1_submit_rate_4` | 16 | 1 | 00:04:16 | 17 | 1 s |
| sequential | `nf1_featurization_independent` | 16 | 1 | 00:00:51 | 17 | 1 s |
| sequential | `nf1_featurization_batched_2` | 16 | 2 | 00:00:42 | 9 | 1 s |
| sequential | `nf1_featurization_batched` | 16 | 4 | 00:00:41 | 5 | 1 s |
| sequential | `nf1_queue_size_4` | 16 | 1 | 00:01:02 | 17 | 1 s |
| burst | `zp_synthetic_features` | 4 | 1 | about 00:00:42 | 5 | 0-1 s |
| direct `uv` env | `zp_synthetic_features` | 4 | 1 | about 00:00:16 task span | 5 | 0-1 s |
| burst | `nf1_submit_rate_prod_ratio` (`queueSize=200`, `submitRateLimit='200/60min'`) | 16 | 1 | 00:05:10 | 17 | ~18 s between submits |

## ZedProfiler-Shaped Probe

`zp_synthetic_features` is a tiny generated-volume workload shaped after
ZedProfiler's CPU-first 3D feature extraction. It creates small object-like
volumes, computes intensity and volume-style summaries, records deterministic
feature checksums, and validates expected item completion. It does not import
ZedProfiler or use NF1 image data.

The validated command was:

```bash
make submit EXPERIMENT=zp_synthetic_features ITEMS=4 ACCOUNT=<allocation> SUBMIT_HOST=Persistence1 RUN_ID=zp-sim-01
```

Result:

- coordinator job completed
- Nextflow exit status was `0`
- validation passed for 4 expected items
- the run emitted 16 feature rows
- `trace.tsv` contained 4 feature tasks and 1 validation task
- Slurm accounting showed feature tasks completed in about 1-3 seconds each
- peak RSS for feature tasks was about 9-32 MB

The base Python environment on `Persistence1` is not sufficient for real
ZedProfiler execution:

- Python: 3.9.13
- NumPy: 1.21.5
- Pandas: 1.4.4
- scikit-image: 0.19.2
- missing: `mahotas`, `pyarrow`, `zedprofiler`

ZedProfiler requires Python `>=3.11,<3.15` and depends on packages that are not
present in the tested base environment. A production NF1/ZedProfiler run should
therefore use a project-owned environment or container instead of the default
`Persistence1` Python.

## uv Environment Probe

CURC documents `module load uv`, with `$UV_ENVS` set to
`/projects/$USER/software/uv/envs`, as the preferred `uv` environment location.
During validation on `2026-08-04`, `module avail uv` and `module spider uv` did
not find that module on either the regular login node or `Persistence1`.

A user-space fallback worked:

```bash
export UV_HOME="/projects/$USER/software/uv"
export UV_INSTALL_DIR="$UV_HOME/bin"
export UV_ENVS="$UV_HOME/envs"
export UV_CACHE_DIR="/scratch/alpine/$USER/uv-cache"
export PATH="$UV_INSTALL_DIR:$PATH"
export UV_LINK_MODE=copy

uv venv "$UV_ENVS/zedprofiler-simple" --python 3.12
source "$UV_ENVS/zedprofiler-simple/bin/activate"
uv pip install zedprofiler
```

Observed result:

- `uv 0.12.1` installed under `/projects/$USER/software/uv/bin`.
- The environment used `/usr/bin/python3.12`, reporting Python `3.12.13`.
- ZedProfiler `0.1.1` installed and imported.
- Wheels resolved for previously missing dependencies including `mahotas`,
  `pyarrow`, `numpy`, `pandas`, and `scikit-image`.
- Keeping `UV_CACHE_DIR` on scratch and the environment under `/projects` causes
  cross-filesystem hardlink fallback; `UV_LINK_MODE=copy` should be set
  intentionally for this layout.

The simple Nextflow experiment also completed with the `uv` environment active:

```bash
cd /scratch/alpine/$USER/formascute-codex-test
module load nextflow/25.10.2
source "/projects/$USER/software/uv/envs/zedprofiler-simple/bin/activate"
make run EXPERIMENT=zp_synthetic_features ITEMS=4 ACCOUNT=amc-general PROFILE=alpine RUN_ID=zp-sim-uv-01
```

Result:

- Nextflow exit status was `0`.
- validation passed for 4 expected items.
- the run emitted 16 simulated feature rows.
- `trace.tsv` contained 4 feature tasks and 1 validation task.
- `slurm.tsv` was collected for account `amc-general`.

This upgrades the ZedProfiler runtime recommendation from "project-owned
environment or container" to "`uv` environment first, Apptainer if native wheels
or system libraries fail." It still does not validate real NF1 image I/O or a
real ZedProfiler feature call inside a workflow task.

## CURC Guidance And Follow-Up Experiments (2026-08-06)

CURC's contact answered four open questions from this project: the 200-job
limit, imaging software choice (Apptainer/Singularity vs. conda vs. `uv`),
batching within the job limit, and `Persistence1` orchestrator RAM. Three small
follow-up experiments confirmed or sharpened that guidance.

### submitRateLimit paces from job 1, not just near the ceiling

CURC framed `submitRateLimit = '200 / 60 min'` as a fallback for when
`queueSize` submissions approach the 200-job campus limit ("the rest of the
jobs will likely go pending"). A same-shape experiment at small scale
(`nf1_submit_rate_prod_ratio`: `queueSize=200`, `submitRateLimit='200 / 60 min'`,
16 items, i.e. far under the 200-job ceiling) shows the limiter is not dormant
below that ceiling:

- task submissions landed about 18 seconds apart starting with the first job,
  matching `60 min / 200 = 18s` exactly
- the coordinator took `5m 10s` versus `51-52s` unthrottled for the same
  16-item workload (`nf1_featurization_independent`)
- validation still passed (16/16 items, exit `0`)

`submitRateLimit` is a steady-rate limiter from the first submission, so it
imposes a wall-clock floor of roughly `task_count × (window / rate)` regardless
of `queueSize` or how fast each task actually runs. Real ZedProfiler feature
tasks were `1-3s` each in the synthetic probe; at `200 / 60 min` a 200-task run
would take at least `~60` minutes from submit pacing alone. Prefer batching to
cut task count before adding a submit-rate limit for many-short-task workloads.

### Persistence1 cgroup limits, confirmed exactly

CURC's stated "about 20% RAM / 80% CPU" per-user cap was confirmed by reading
cgroup and systemd state directly on `Persistence1` (read-only, no job
submitted). The limit lives on `user-<uid>.slice`, not the SSH session scope:

- host total RAM: `8069439488` bytes (about 7.51 GiB); host CPUs: `8`
- `memory.limit_in_bytes` on the user slice: `1613885440` bytes, exactly `20%`
  of host RAM (about 1.6 GB)
- `cpu.cfs_quota_us` / `cpu.cfs_period_us`: `640000 / 100000`, i.e. `6.4` of `8`
  CPUs, exactly `80%`
- enforced via legacy cgroup v1 fields (systemd `MemoryLimit` /
  `CPUQuotaPerSecUSec`), not the newer `MemoryMax`/`MemoryHigh`, which both read
  `infinity` and would misleadingly suggest no cap
- idle `MemoryCurrent` for the user slice was about `8 MB`

The earlier `zp_synthetic_features` probe peaked at `9-32 MB` RSS per task, only
`1-2%` of the confirmed `~1.6 GB` cap. Real ZedProfiler-scale runs should
compare orchestrator RSS against this exact `~1.6 GB` number, not the VM's full
`8 GB`.

### Apptainer confirmed for Python 3.11 on Alpine compute nodes

CURC's contact recommended Apptainer/Singularity over `uv`/conda for
reproducibility on this shared project and stated the site versions (Apptainer
`1.4.5`, Singularity `3.7.4`) should handle Python 3.11. A minimal smoke test
(short batch job on `acpu`, not on `Persistence1`) confirms the mechanics:

```bash
apptainer pull python311.sif docker://python:3.11-slim
apptainer exec python311.sif python3 --version
```

- `apptainer version 1.4.5-3.el8`, matching CURC's stated version
- pulling `python:3.11-slim` from Docker Hub took about `25s`
- `python3 --version` reported `Python 3.11.15` inside the container
- basic standard-library imports (`sqlite3`, `zlib`) worked

This does not install or import `zedprofiler`, `mahotas`, `pyarrow`, or
`scikit-image` inside a container, and does not test real NF1 image data. It
upgrades Apptainer from "available fallback, not preferred" to "confirmed
working for Python 3.11 on Alpine compute nodes," which is enough evidence to
justify building a real ZedProfiler-dependency Apptainer image and comparing it
against the validated `uv` environment before committing to one runtime for
production.

### Apptainer proven with real ZedProfiler dependencies (2026-08-06)

Built a project-owned image (`python:3.12-slim` base, `pip install zedprofiler
mahotas pyarrow numpy pandas scikit-image` in `%post`) via
`apptainer build --fakeroot` on `acpu` (fakeroot works via a root-mapped
namespace fallback despite no `/etc/subuid`/`/etc/subgid` entries for this
user). Import validation matched the `uv` probe on the `zedprofiler` version:

- `zedprofiler 0.1.1` (same as `uv`), plus `numpy 2.5.1`, `pandas 3.0.5`,
  `mahotas 1.4.18`, `pyarrow 25.0.0`, `scikit-image 0.26.0` (newer than `uv`'s
  pinned versions, since this was an unconstrained resolve)
- image size about `294 MB`; build took `2-3` minutes

First attempt at actually running the workload through Nextflow failed every
task with `Command 'ps' required by nextflow to collect task metrics cannot be
found` — a bare `python:3.12-slim` image has no `procps`/`ps`, and Nextflow's
Slurm+container executor needs `ps` inside the container for trace/RSS
metrics. This is a container-specific plumbing gap with no `uv` equivalent
(`uv` runs on the host, no container boundary) and does not show up in a plain
`apptainer exec` smoke test. Adding `procps` to `%post` and rebuilding fixed
it:

```bash
FORMASCUTE_ENABLE_CONTAINER=true make run EXPERIMENT=zp_apptainer_probe ITEMS=4 ACCOUNT=amc-general PROFILE=alpine RUN_ID=zp-sim-apptainer-02
```

- `nextflow_exit_status: 0`, `validation.json` `"valid": true`, `4/4` items
- 4 feature tasks + 1 validation task, all `COMPLETED`
- per-task `realtime` about `1.3s`, `peak_rss` about `21 MB` — comparable to the
  `uv` path's `9-32 MB` peak RSS on the same synthetic workload
- coordinator `Duration: 1m 16s` for 4 items + validation

Both runtimes are now confirmed end-to-end on the same synthetic workload with
comparable resource footprints. Neither has been tested against real NF1 image
I/O or ZedProfiler's actual feature calls yet. The choice between them is now
an operational one (CURC's reproducibility argument for images vs. `uv`'s
faster iteration for a still-changing dependency set), not a technical
blocker.

### Real ZedProfiler feature calls on real data (2026-08-06)

Closed the "actual feature calls" gap noted above. Pulled one image/mask pair
from a small real CellProfiler-3D-tutorial nuclei dataset bundled with
ZedProfiler's own test suite (`100×258×258` `uint16` volumes + masks, `5`
objects), built the loader exactly as ZedProfiler's own
`tests/featurization/test_real_world_data.py` does, and called three real
extractors through the `uv` environment (no Nextflow, `2` CPU / `4` GB / `15`
min batch job):

- `compute_intensity`: `5` rows, `2.835s`
- `compute_volume_size_shape`: `5` rows, `0.599s`
- `compute_granularity` (`radius=1`, `granular_spectrum_length=2`,
  `subsample_size=1.0`, `image_sample_size=1.0`): `5` rows, `12.878s`
- all finite, `5/5` expected objects, exit `0`
- peak RSS: `~1.01 GB` for just these `3` of `6` feature calls on one image

Two findings fall out of this:

1. **Granularity ran well above what upstream ZedProfiler benchmarking has
   reported for comparable real-world data at other points in time**
   (`12.9s` here vs. a roughly `~7×` lower number seen upstream previously for
   the same feature). Unresolved — possibly a different installed
   version/branch, different `granularity` parameters (this probe used no
   downsampling), or hardware. Treat any remembered upstream benchmark number
   as stale; re-measure against the exact `zedprofiler` version actually
   installed before using it for Alpine time-budget planning.
2. **The memory gap below is now confirmed, not hypothetical**: `~1.01 GB` for
   a partial single-image run lands right at Nextflow's silent per-task default.

### Full 6-feature real-data run through Nextflow, with explicit memory (2026-08-07)

Closed both remaining gaps in one run. A small standalone workflow
(`workflows/real_feature_probe.nf`, not part of the `bin/formascute`
experiment framework) called all `6` real ZedProfiler feature extractors
(adding `neighbors`, `texture`, `colocalization` to the three above) with
explicit `memory '4 GB'` / `cpus 2` process directives, through real
Nextflow-and-Slurm orchestration:

- `intensity` `1.37s`, `volume_size_shape` `0.382s`, `neighbors` `0.107s`,
  `texture` `1.269s`, `granularity` `12.47s`, `colocalization` `7.376s`
- **total: `~23.0s` per real image set, all 6 features, `5/5` objects
  finite, exit `0`**
- `sacct` confirmed `AllocTRES=cpu=2,mem=4G,node=1` (directives honored) and
  `MaxRSS=1052144K` (`~1.0 GB`) — same peak as the partial run, no OOM,
  confirming memory use is dominated by one internal peak, not additive per
  feature call
- `granularity` + `colocalization` together are about `86%` of total per-image
  time

This is now a real, measured per-task cost (not a range) to plan production
timing from, and confirms an explicit `process.memory` directive is both
necessary (see above) and sufficient (this run) to run real ZedProfiler work
safely under Nextflow.

**Unrelated blocker found and fixed along the way**: the first attempt at this
run failed every submission with `sbatch: error: Error 17: Time has not been
specified ... Specifying job run time is now required`. Neither
`conf/alpine.reference.config`'s base `process {}` block nor
`workflows/synthetic.nf` has ever set `process.time`, so this would break
every existing experiment config, not just this probe, the next time any of
them runs. Likely a platform policy rollout tied to CURC's `2026-08-05`
maintenance window (worked as recently as `2026-08-06`). Fixed by adding
`time = 30.m` to the base `process {}` block in
`conf/alpine.reference.config`.

### Nextflow's default per-task allocation is smaller than the partition default

Neither `nextflow.config` nor `conf/alpine.reference.config` sets
`process.memory`/`process.cpus` for `CHARACTERIZE_ITEM`, so every task so far
has silently run under Nextflow's own default. Confirmed via `sacct
--format=ReqMem,ReqCPUS,AllocTRES` across several completed jobs:

- every task got exactly `ReqMem=1G`, `ReqCPUS=1`
- the `acpu` partition's own default is larger: `scontrol show partition acpu`
  reports `DefMemPerCPU=3840` (MB, `~3.75 GB` for `1` CPU) — Nextflow's default
  undercuts what a bare `sbatch` with no `--mem` would get
- this was invisible in every synthetic run (none came close to `1 GB`) but is
  no longer safe to assume: the real-data probe above hit `~1.01 GB` using only
  half the feature extractors on one image

Set an explicit, generous `process.memory` before any real ZedProfiler/NF1
production run.

### Fairshare/priority checked ahead of a 4200-image production estimate (2026-08-07)

Read-only Slurm checks (`sshare`, `sacctmgr show qos`, `sacctmgr show assoc`,
`scontrol show partition`), prompted by planning a ~4200-image-set production
run:

- the `200`-job limit is a hard `MaxJobs=200` Slurm *association* cap for this
  account+user, confirmed via `sacctmgr show assoc` — not a soft guideline,
  and not visible in the QOS record itself (`cpu-normal` only sets
  `MaxSubmitPU=1000`)
- that `200` is shared across every QOS on the association (`cpu-normal`,
  `gpu-normal`, etc.) — concurrent CPU and GPU work would split one pool
- user-level fairshare standing is very healthy: `FairShare=0.198764`,
  `LevelFS=1721` (far above `1`, deeply underused relative to target share). A
  `~29`-core-hour run is negligible against the account's `4,452,778,012`-unit
  cumulative usage and would not trigger priority decay
- `acpu` is `420` nodes / `26,976` CPUs at baseline `PriorityTier=1`; a
  `200`-core ask is under `1%` of partition capacity

### Correction: the fairshare picture above was incomplete (2026-08-07, same day)

CURC's own allocations and FAQ docs (linked by the user) surfaced three things
the checks above missed:

1. **`levelfs $USER` reports a separate institution-level number.**
   `LevelFS_User=1687.66` (matches the `sshare` reading), but
   `LevelFS_Inst=1.0104` for institution `amc` — at parity, not headroom. Our
   own usage being tiny doesn't protect against Anschutz-wide usage on Alpine
   depressing priority for every AMC account, a risk with no visibility and no
   project-side control.
2. **Fairshare is not the dominant priority factor.** `scontrol show config`:
   `PriorityWeightJobSize=40320` > `PriorityWeightQOS=30240` >
   `PriorityWeightAge=20160` = `PriorityWeightFairShare=20160`. `cpu-normal`
   (used) has QOS `Priority=0`; `cpu-long` (also available on this
   association) has `Priority=200` — a real, currently-unused priority
   contribution worth asking CURC about, not a "switch now" call without
   understanding `cpu-long`'s tradeoffs.
3. **`amc-general`'s allocation tier is administratively invisible from
   here.** CURC's docs state AMC allocations are managed separately by that
   institution, and that jobs on properly-approved tiers (Ascent/Peak) get
   higher priority than auto-granted (Trailhead) ones. `sacctmgr show account
   amc-general` returns nothing useful — confirming this can't be
   self-verified via Slurm queries; it needs a direct question to
   `hpcsupport@cuanschutz.edu` or the project's CURC contact.

Revised interpretation: this project's own usage is not a deprioritization
risk — but "fairshare rules it out" overstated what one check can show.
Institution-wide AMC usage, job-size/QOS priority weights, and allocation tier
are all real factors this project hasn't verified and doesn't control.
Ordinary multi-tenant queue contention (`squeue -p acpu | wc -l`, `sinfo -p
acpu` immediately before a real run) is still the most directly checkable
residual risk, but no longer the only one.

### CURC answered directly (2026-08-07): mostly good news, one new seasonal risk

CURC's contact (Gregory Way) responded to the questions above. Full detail in
`.agents/skills/alpine/SKILL.md` under "CURC's Direct Answer"; summary:

- **Institution fairshare confirmed and quantified**: AMC holds `6,459` of
  Alpine's priority shares (`~1,085,112` SU/week sustainable budget
  institution-wide); current `levelfs_inst=1.002854`, matching this project's
  own independent reading (`1.0104`) closely. Validates the self-check
  methodology.
- **`queueSize=200` for the `4200`-task run: explicitly "no harm."** Batch
  only if walltimes grow long. This is a direct, meaningful confidence
  increase for the production estimate's core approach.
- **`cpu-long` question closed**: it's for walltime `>24h`, not a priority
  shortcut for short jobs. `cpu-normal` remains correct for this workload.
- **New risk, unrelated to this project's config**: Alpine's `cpu-normal`/
  `cpu-long` QOS structure is new (rolled out over the summer, replacing an
  older setup specifically to reduce long wait times), and CURC "cannot
  guarantee" it holds up during named peak season, **September through
  November**. Every queue-wait measurement in this document was taken during a
  quieter period. Treat a production run scheduled in that window as having
  materially higher queue-wait uncertainty than anything measured here, for
  reasons independent of this project.
- **GPU work confirmed** to need a separate partition/QOS; reference doc and
  profiling tool guidance provided (`nvidia-smi`, `nvitop`, `sacct -Pno
  TRESUsageInMax/InAve`, `nsys`/`ncu`).
- **Orchestrator guidance mostly matches existing practice** (bash script in
  `screen`/`tmux`, one walltime via Nextflow `params`), but CURC's suggested
  `ulimit -m 2G` self-limit is higher than this project's own measured hard
  cgroup cap (`~1.6 GB`) — unreconciled, use the lower measured number.

## Production Time Estimate: 4200 Image Sets (2026-08-07)

Synthesizes every finding above into one working estimate for the real
NF1/ZedProfiler production scale (`4200` image sets). Treat this as a planning
number, not a guarantee — see "What this does not account for" below.

**Assumption stated up front:** one Nextflow task computes all needed feature
families per image set (`4200` tasks total). If production fan-out is instead
per channel/feature-family/compartment (`nf1_featurization_independent`-style
splitting, hinted at in Recommended NF1 Orchestration Direction below), total
task count could be `5-10×` higher and this estimate would need rescaling
before use.

**Per-task cost — measured, not guessed:** `~23.0s` for a real image set, all
`6` feature extractors, confirmed via a real Nextflow+Slurm run with explicit
`memory '4 GB'` / `cpus 2` (see ZedProfiler Runtime). `granularity` (`12.47s`)
and `colocalization` (`7.376s`) are `~86%` of that.

**Math:**

- total compute: `4200 × 23.0s ≈ 96,600s` (`~26.8` task-hours)
- concurrency ceiling: `MaxJobs=200` (confirmed hard Slurm association cap,
  not a soft guideline — see Fairshare, Priority, And The 200-Job Limit), each
  task using `2` CPUs → up to `400` of the partition's `26,976` cores, under
  `2%` of capacity
- `4200 / 200 = 21` exactly — `21` pipelined waves of `~23.0s` compute each
- best case (perfect pipelining, no dispatch/queue overhead):
  `21 × 23.0s ≈ 483s ≈ 8` minutes
- realistic range once per-wave Slurm dispatch/scheduling overhead is added:
  **roughly `15-40` minutes**

**What would make this estimate wrong, ranked by how much it would move:**

1. **Task-count assumption above** — if fan-out is per-feature-family/channel
   instead of per-image-set, this is off by `5-10×`.
2. **`submitRateLimit` at CURC's suggested `200 / 60 min`.** Confirmed this
   paces every submission `~18s` apart from job 1, regardless of task count or
   `queueSize` headroom (see Queue And Batching Policy). At `4200` tasks that
   alone adds `4200 × 18s ≈ 21 hours` — do not enable it for this run.
3. **`process.memory` not actually set on the real production process.**
   `conf/alpine.reference.config` now defaults `process.time = 30.m` for every
   process, but does *not* default `process.memory` — that was only proven
   safe at `4 GB` on the one-off validation workflow
   (`workflows/real_feature_probe.nf`), not yet wired into whatever process
   runs real production ZedProfiler calls. Skipping this risks OOM + retry
   storms (`maxRetries=3`, each retry repeats the full `~23s` task), not just
   slowness.
4. **Priority/deprioritization: mostly de-risked by CURC's direct answer, one
   new seasonal caveat remains.** CURC confirmed `queueSize=200` for this
   exact workload shape is fine, closed the `cpu-long` question, and quantified
   institution-level fairshare as healthy (see "CURC answered directly"
   above). The one real remaining unknown is seasonal: Alpine's QOS structure
   is new this summer and CURC "cannot guarantee" it holds up during named
   peak season (September-November) — a run scheduled in that window carries
   materially more queue-wait uncertainty than this estimate reflects, for
   reasons independent of this project's own config or usage. Check live
   queue depth (`squeue -p acpu | wc -l` / `sinfo -p acpu`) immediately before
   any real run regardless of season.

**What this does not account for:**

- `n=1`: the `~23.0s` figure is one real image set with `5` objects. Production
  images will vary in size and object count; `granularity`/`texture` cost
  plausibly scales with both. This is a calibration point, not a
  statistically characterized distribution.
- Real production-path image I/O. The probe read pre-staged local-scratch
  copies of small (`~13 MB`) tutorial images, not the actual production data
  location, volume, or concurrent-read pattern at `4200`-image scale.
- Sustained-scale orchestrator behavior. Nextflow task tracking has only been
  exercised up to `~17` concurrent synthetic items and `1` real-data item —
  never at anything close to `200` concurrent real tasks.

A moderate rehearsal (tens to ~100 real image sets, through Nextflow, with
`process.memory` explicitly set) — proposed and deferred earlier as "not yet
ready for" — is what would close the remaining gaps (`n=1` variance, real I/O,
sustained-scale orchestrator/queue behavior) before committing to the full
`4200`.

## Interpretation

- Nextflow can successfully submit and track Slurm jobs on Alpine when submitted
  through `Persistence1`.
- Queue wait was negligible for these tiny runs, usually around 0-1 seconds.
- The fixed overhead for a one-item run was about 21 seconds.
- Independent 16-item fan-out completed in about 51-52 seconds.
- Batching reduced the number of Slurm jobs and slightly reduced elapsed time.
- Batch size 4 was fastest in the burst run, but only slightly faster than batch
  size 2 in the sequential run.
- `queueSize=4` was slower than the default independent run at this scale.
- `submitRateLimit='4 / 1 min'` was much slower and should not be the first
  control knob for NF1-style work.
- The ZedProfiler-shaped probe behaved like the earlier tiny fan-out tests:
  scheduler wait was negligible, and task overhead dominated actual work.
- `uv` is a practical first runtime path for ZedProfiler on Alpine, even though
  the documented module was not visible during testing.
- The current `make submit` coordinator is not yet the best `uv` interface
  because it treats `FORMASCUTE_ENV_DIR` as a replacement for module loading.
  For now, direct `Persistence1` runs should load Nextflow first and then
  activate the `uv` environment.

## Recommended NF1 Orchestration Direction

Start with a Nextflow wrapper around the existing Stage 3 CPU featurization work
list rather than rewriting feature code.

Recommended first implementation:

- Generate a manifest equivalent to `3.cellprofiling/load_data/load_combinations.txt`.
- Use one Nextflow process for CPU featurization work items.
- Keep the existing Python feature scripts as the task payload.
- Use Slurm executor with `acpu`, `cpu-normal`, and account configuration.
- Use a project-owned `uv` environment as the first ZedProfiler runtime before
  real data tests.
- Update the coordinator bootstrap so it can load the Nextflow module and
  activate a separate Python runtime environment in the same submitted job.
- Start with independent jobs for real feature tasks when each task loads a
  single image-set and runs enough feature work to amortize Slurm overhead.
- Add optional batching when individual feature calls are very short or repeatedly
  reload the same image data.
- Prefer batch sizes of 2-4 when batching is needed.
- Do not start with aggressive submit-rate throttling.
- Use `queueSize` as the first scheduler pressure control, then tune only after
  observing real queue behavior.
- Consider changing the NF1/ZedProfiler integration so one task can load an
  image-set once and compute multiple compatible feature families before writing
  outputs. That direction should reduce repeated image I/O compared with one
  Slurm job per feature family, channel, and compartment.

Avoid for the first production-facing iteration:

- Rewriting the image-processing code.
- Moving directly to Slurm job arrays.
- Mixing CPU and GPU work in one executor profile.
- Running real NF1 image data before a tiny real-work probe is designed.
- Relying on the base `Persistence1` Python environment for ZedProfiler.
- Assuming the documented CURC `uv` module is available without checking
  `module spider uv`.
- Pointing `FORMASCUTE_ENV_DIR` at the `uv` environment before the submit
  wrapper can separately load Nextflow.

## Questions For CURC

Answered on `2026-08-06` by CURC's contact (see "CURC Guidance And Follow-Up
Experiments" above):

- `queueSize`/job-limit range: `queueSize` up to `1000` is accepted, but Slurm
  still caps concurrency near 200 for this campus/user context, with the
  remainder pending; `submitRateLimit` is an alternative pressure valve.
- Imaging software choice: CURC recommends Apptainer/Singularity over
  `uv`/conda for shared-project reproducibility, confirmed the site version
  handles Python 3.11, and had no strong opinion on `uv` specifically.
- `Persistence1` RAM guidance: monitor with `top`/`htop -u $USER`; VM is `8`
  cores / `8` GB, per-user cgroups at `20%` RAM / `80%` CPU, orchestrator risks
  cancellation if it exceeds the RAM limit for too long.

Still open, ask before scaling further:

- Given the `2026-08-06` finding that `submitRateLimit` paces every submission
  at a steady rate from job 1 (not just once near the 200-job ceiling), is
  `200 / 60 min` still the right shape for many short ZedProfiler tasks, or
  would CURC rather see task-count reduction via batching first?
- Should production runs use `acpu`/`cpu-normal` now, or keep compatibility with
  `amilan`/`normal` during the transition?
- Are Slurm job arrays recommended for this workload, or is Nextflow-managed
  independent submission easier for accounting and retries?
- Should CPU featurization and SAMMed3D GPU work be split into separate Nextflow
  profiles and runs?
- Is CURC's documented `uv` module expected to be available on Alpine now, and
  if so, which module tree or host should expose it?
- Now that a bare Python 3.11 Apptainer smoke test has passed, does CURC prefer
  a project-owned Apptainer image over the validated `uv` environment for
  production NF1/ZedProfiler runs, once both are compared on the same real
  workload?

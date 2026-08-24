# Cytotable Alpine Findings

These notes record the CytoTable-on-Alpine benchmarking that produced the
concrete performance findings now driving
`.agents/skills/cytotable/SKILL.md`: an initial tiny-fixture mechanics check
and a same-day real-scale S3 benchmark on `2026-08-21`, followed by a
larger-scale benchmark against two bigger real plates on `2026-08-24` that
tested whether the `2026-08-21` findings hold as source data size grows (they
mostly don't as fixed numbers, but do as relationships — see Larger-Scale
Benchmark).

## Goal

Compare Cytotable Parsl configuration on Alpine compute nodes:

- `ThreadPoolExecutor`
- Cytotable-style default `HighThroughputExecutor`
- capped `HighThroughputExecutor`
- Slurm CPU requests of `1`, `4`, and `8` CPUs

The run intentionally avoided `Persistence1`; each Cytotable conversion was a
plain Slurm batch job submitted from the Alpine login node.

## Dataset (Tiny Fixture Phase)

The initial benchmark used Cytotable's current `main` source archive and
bundled test fixture:

```text
tests/data/cellprofiler/cpg0043-segmentation
```

Observed on Alpine:

- `48` CSV files
- `256020900` CSV bytes

This fixture is large enough to exercise CSV parsing, chunking, joining, and
Parquet writing, while still being appropriate for short `acpu` jobs — but, as
the real-scale phase below shows, it is not large enough to reveal the
memory/executor behavior that actually matters for production data. Treat
results from this phase as mechanics/correctness smoke tests, not performance
guidance.

## Runtime

Scratch root:

```text
/scratch/alpine/$USER/cytotable-alpine-bench-20260821
```

Environment:

- `uv` environment under `/projects/$USER/software/uv/envs/cytotable-alpine`
- `UV_CACHE_DIR=/scratch/alpine/$USER/uv-cache`
- `UV_LINK_MODE=copy`
- Cytotable source archive installed with
  `SETUPTOOLS_SCM_PRETEND_VERSION_FOR_CYTOTABLE=0.0.0+alpinebench`
- Parsl `2026.8.10`
- DuckDB `1.5.5`
- PyArrow `25.0.1`

GitHub source archives do not include `.git` metadata, so Cytotable's
`setuptools-scm` build fails unless a pretend version is supplied or the package
is installed from PyPI or a real git checkout.

## Experiment Matrix (Tiny Fixture Phase)

First submitted job IDs:

| job IDs | status | finding |
| --- | --- | --- |
| `31536860-31536868` | failed | harness called `convert.convert(...)` after importing `convert` as a function |

The failed jobs still confirmed submission mechanics and showed one Slurm
accounting quirk: nominal `--cpus-per-task=1` jobs appeared in `sacct` with
`AllocCPUS=3` on this `acpu` run, while `4` and `8` CPU requests reported as
requested.

Corrected submitted job IDs:

| job ID | run |
| ---: | --- |
| `31536906` | `rerun-threadpool-1c` |
| `31536907` | `rerun-threadpool-4c` |
| `31536908` | `rerun-threadpool-8c` |
| `31536909` | `rerun-htex-default-1c` |
| `31536910` | `rerun-htex-default-4c` |
| `31536911` | `rerun-htex-default-8c` |
| `31536912` | `rerun-htex-capped-1c` |
| `31536913` | `rerun-htex-capped-4c` |
| `31536914` | `rerun-htex-capped-8c` |

The corrected jobs left the queue within a few minutes. Their JSON result files
and Slurm accounting could not be collected until the account home directory was
freed enough for SSH to work again.

After collection, all nine corrected jobs had failed before conversion. The
common failure was DuckDB attempting to install/load extensions under
`$HOME/.duckdb` while Alpine home was full:

```text
IO Error: Cannot open file "/home/.../.duckdb/extensions/v1.5.5/linux_amd64/..."
No space left on device
```

All executor variants failed in about `5-6s`, so those runs do not compare
ThreadPoolExecutor and HTEX performance.

## Scratch-Home Fix

Two focused reruns set `HOME` to a scratch-backed per-job directory after
activating the reusable `uv` environment and before starting Python. This
redirected DuckDB's extension cache away from Alpine home.

Job IDs:

| job ID | run | status |
| ---: | --- | --- |
| `31541899` | `homefix-threadpool-4c` | completed |
| `31541900` | `homefix-htex-capped-4c` | completed |

Results:

| run | Cytotable elapsed | Slurm elapsed | Slurm batch MaxRSS | rows | columns | parquet size |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `homefix-threadpool-4c` | `43.83s` | `1:24` | `5966192K` | `397` | `6049` | `22.85 MB` |
| `homefix-htex-capped-4c` | `49.35s` | `1:30` | `4110988K` | `397` | `6049` | `22.85 MB` |

The scratch job-home directories were about `54 MB` each, dominated by DuckDB
extension cache state.

At this tiny scale, capped HTEX looked slightly more memory-frugal (lower
Slurm MaxRSS) than ThreadPoolExecutor, at a small speed cost. **The real-scale
phase below reverses this reading** — do not use the tiny-fixture memory
comparison to justify HTEX for production data.

## Real-Scale S3 Benchmark

Later the same day, a second matrix targeted a real production-shaped input
instead of the bundled fixture: one real JUMP Cell Painting Gallery plate,
read directly from the public `cellpainting-gallery` S3 bucket with anonymous
access (`no_sign_request=True`, no AWS credentials configured):

```text
s3://cellpainting-gallery/cpg0016-jump/source_4/workspace/backend/2021_08_23_Batch12/BR00126114/BR00126114.sqlite
```

Conversion parameters: `source_datatype="sqlite"`,
`preset="cellprofiler_sqlite_cpg0016_jump"`, `chunk_size=30000`, scratch-backed
`HOME` and `local_cache_dir` per the scratch-home fix above. Slurm request for
every job in this matrix: `--mem=16G`, `--time=1:00:00`, `node=1`.

Submitted job IDs:

| job ID | run | executor | cpus | arrow mmap |
| ---: | --- | --- | ---: | ---: |
| `31542591` | `large-tpe-4c-c30000-a1` | ThreadPoolExecutor | 4 | 1 (default) |
| `31542592` | `large-tpe-8c-c30000-a1` | ThreadPoolExecutor | 8 | 1 (default) |
| `31542593` | `large-htexcap-4c-c30000-a1` | HighThroughputExecutor, capped to 4 workers | 4 | 1 (default) |
| `31542594` | `large-tpe-4c-c30000-a0` | ThreadPoolExecutor | 4 | 0 |

Results (`sacct` and GNU `time`-wrapped process stats):

(Memory figures are KiB→GiB, matching the correction applied throughout this
document — see Larger-Scale Benchmark below.)

| run | status | elapsed | CPU% | process MaxRSS (`time`) | Slurm cgroup MaxRSS (`sacct`) |
| --- | --- | ---: | ---: | ---: | ---: |
| `large-tpe-4c-c30000-a1` | completed | `18m26s` | `143%` | `13.93 GiB` | `16.00 GiB` |
| `large-tpe-8c-c30000-a1` | completed | `22m23s` | `392%` | `12.71 GiB` | `16.00 GiB` |
| `large-tpe-4c-c30000-a0` | completed | `19m49s` | `177%` | `12.94 GiB` | `16.00 GiB` |
| `large-htexcap-4c-c30000-a1` | **OOM-killed** | `5m30s` | `4%` (driver process only) | `0.39 GiB` (driver process only) | `16.00 GiB` (killed) |

All three successful runs produced identical output: `74226` rows, `5946`
columns, `~3.8 GB` parquet — confirming the executor/CPU/mmap choice did not
change correctness, only speed and memory behavior.

The failed HTEX run left a partially-written `dest_path` directory
(`cells/`, `cytoplasm/`, `image/`, `nuclei/` subdirectories, `~3.7 GB` total)
on disk, and its `.err` log shows:

```text
slurmstepd: error: Detected 1 oom_kill event in StepId=31542593.batch. Some of the step tasks have been OOM Killed.
```

with the Cytotable-side exception surfacing as a generic Parsl
`DependencyError([(WorkerLost(1, '<node>'), 'task 23')], 24)` rather than an
explicit out-of-memory message — worth recognizing that shape as a likely OOM
when triaging failures, since it does not say "memory" anywhere in the text.

Other measured storage facts from this phase:

- `local_cache_dir` (the local S3 staging cache for the source `.sqlite` file)
  used about `3.7 GB` per run, separate from the destination parquet and the
  scratch job-home.
- The scratch job-home DuckDB extension cache stayed at the same `~54 MB` seen
  in the tiny-fixture phase — it does not scale with dataset size.

### Interpretation

1. **ThreadPoolExecutor is the only executor validated at real-plate scale.**
   The capped `HighThroughputExecutor` run OOM-killed under the identical
   `16G`/4-cpu request, dying during the final join/concat stage after
   already writing the full set of per-compartment intermediate parquet
   output. The tiny-fixture reading that capped HTEX was more memory-frugal
   does not hold at real scale — it inverts. Do not extrapolate small-fixture
   executor/memory comparisons to production data; re-validate at real scale
   before trusting a memory claim about an executor.
2. **More CPUs made this workload slower, not faster — at this data size.**
   Going from `4` to `8` CPUs increased ThreadPoolExecutor wall time by about
   `21%` (`18m26s` to `22m23s`) while total CPU-seconds consumed nearly
   tripled. System time specifically exploded (`756s` to `3228s`, i.e. from
   about `48%` to `145%` of user time), a strong signature of contention —
   likely DuckDB's internal thread pool or shared scratch/GPFS I/O —
   outweighing added parallelism at this data shape. **This finding does not
   hold at larger data sizes — see Larger-Scale Benchmark below, where `8`
   CPUs became faster than `4` on an `~11 GB` plate.** Re-benchmark before
   scaling CPU count up for a given data size; do not assume the optimal CPU
   count is fixed across dataset sizes.
3. **Default Arrow memory mapping is a real, measured win, with a memory
   tradeoff.** `CYTOTABLE_ARROW_USE_MEMORY_MAPPING=1` (the default) was about
   `7%` faster than disabling it at 4 CPUs (`18m26s` vs `19m49s`), at the cost
   of about `1 GiB` more process-level peak RSS (`13.93 GiB` vs `12.94 GiB`).
4. **`16G` was exactly enough, not generous.** Slurm's cgroup-reported MaxRSS
   landed at exactly `16.00 GiB` against the `16G` (`16.00 GiB` — Slurm's `G`
   suffix is binary) request for every configuration tested, including the
   successful runs — every run, passing or OOM-killed, was pinned right at
   the cgroup ceiling. Treat `16G` as an exact floor for a single real
   single-plate SQLite conversion at this column count (`~5946` columns after
   join), not a comfortable production number.
5. **`chunk_size` does not bound the peak.** All memory pressure showed up at
   the final join/concat stage, not during chunked reads — the failed HTEX
   run had already written complete per-compartment intermediate output
   before dying. `chunk_size=30000` is validated as workable for this real
   single-plate conversion under ThreadPoolExecutor, but it is a per-chunk
   read/write knob, not a memory ceiling on the run as a whole.
6. **Real single-plate wall-clock is `~18-22` minutes end-to-end** (S3
   download plus conversion), not the `~44-50` seconds seen on the tiny
   bundled CSV fixture. Use this, not the fixture number, as the time-budget
   calibration point for real production submissions.

## Larger-Scale Benchmark

The `~4 GB`-source plate above (`BR00126114`) turned out to be the *smallest*
of `17` plates in the same JUMP batch on S3 — the other plates range up to
`~30 GB` per `.sqlite` source file. On `2026-08-24`, three more real
conversions tested whether the small-plate findings (executor choice, `4`
CPUs, `--mem`/`--time` sizing) hold as source size grows, using the same
validated configuration (`ThreadPoolExecutor`, `chunk_size=30000`,
`CYTOTABLE_ARROW_USE_MEMORY_MAPPING=1`, scratch-backed `HOME`):

| job ID | run | plate | source size | cpus |
| ---: | --- | --- | ---: | ---: |
| `31608776` | `xl-tpe-4c-BR00126115` | `BR00126115` | `11.06 GB` | 4 |
| `31608777` | `xl-tpe-8c-BR00126115` | `BR00126115` | `11.06 GB` | 8 |
| `31608778` | `xl-tpe-4c-BR00126116` | `BR00126116` | `18.82 GB` | 4 |

`--mem=64G` for the two `BR00126115` jobs, `--mem=96G` for the `BR00126116`
job; `--time=3:00:00` and `6:00:00` respectively, sized with deliberate
headroom over a naive linear extrapolation from the small-plate numbers.

Results (memory figures corrected to KiB→GiB; an earlier pass mislabeled the
`BR00126114` figure using a decimal-KB shortcut — `16775024 KiB / 1024^2 =
16.00 GiB`, not `16.78 GB` as originally written):

| run | source size | cpus | status | elapsed | CPU% | Slurm cgroup MaxRSS | rows | columns | parquet size |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `large-tpe-4c-c30000-a1` (`BR00126114`, prior phase) | `3.87 GB` | 4 | completed | `18m26s` | `143%` | `16.00 GiB` | `74226` | `5946` | `~3.8 GB` |
| `xl-tpe-4c-BR00126115` | `11.06 GB` | 4 | completed | `1h59m` | `253%` | `43.99 GiB` | `215296` | `5946` | `~11.5 GB` |
| `xl-tpe-8c-BR00126115` | `11.06 GB` | 8 | completed | `1h36m` | `576%` | `54.24 GiB` | `215296` | `5946` | `~11.5 GB` |
| `xl-tpe-4c-BR00126116` | `18.82 GB` | 4 | completed | `5h42m` | `680%` | `62.67 GiB` | `366678` | `5946` | `~19.6 GB` |

All completed runs (`BR00126114` through `BR00126116`) share the same `5946`
columns (same CellProfiler/JUMP schema across plates); row counts and output
size scale with each plate's own well/cell count and track source `.sqlite`
size closely (output-to-source byte ratio: `0.98x`, `1.04x`, `1.04x` across
the three plates). 4c and 8c on `BR00126115` produced identical row/column
counts and identical drop-duplicate results, matching the correctness
pattern from the small-plate phase; correctness held across all three sizes.

### A Scheduling Quirk That Explains Some Of The CPU% Readings

`sacct AllocCPUS` for these jobs does not match `--cpus-per-task`:

| job | `--cpus-per-task` | `--mem` | `AllocCPUS` |
| --- | ---: | ---: | ---: |
| `31542591` (`BR00126114`, 4c) | 4 | `16G` | `5` |
| `31542592` (`BR00126114`, 8c) | 8 | `16G` | `8` |
| `31608776` (`BR00126115`, 4c) | 4 | `64G` | `18` |
| `31608777` (`BR00126115`, 8c) | 8 | `64G` | `18` |
| `31608778` (`BR00126116`, 4c) | 4 | `96G` | `26` |

The pattern is exactly `AllocCPUS = max(--cpus-per-task, ceil(--mem_GB /
3.75))` — this partition's `DefMemPerCPU=3840 MB` (`~3.75 GB`) means a large
`--mem` request silently grants a proportionally larger CPU allocation
regardless of `--cpus-per-task`, matching the `acpu` accounting quirk noted
in the tiny-fixture phase (`--cpus-per-task=1` reporting `AllocCPUS=3` there,
consistent with an `8G` request: `ceil(8/3.75)=3`). Two consequences:

- **CPU% readings above the nominal `--cpus-per-task × 100%` are not purely
  a contention signal.** The `BR00126116` job nominally requested `4` CPUs
  but was actually allocated `26` — background library threads not gated by
  `CYTOTABLE_MAX_THREADS` (BLAS, Arrow's own I/O thread pool, etc.) had a much
  wider cgroup CPU budget available than "4" implies. The CPU-count
  comparison in this doc is still valid as a comparison of
  `ThreadPoolExecutor(max_threads=...)`/`CYTOTABLE_MAX_THREADS` — that
  parameter is what was actually varied and is what controls
  Cytotable/DuckDB-level parallelism — but do not read the raw `%CPU` figure
  as a clean measure of contention without checking `AllocCPUS` first.
- **A memory-headroom-driven `--mem` request buys (and consumes fairshare
  for) far more CPU allocation than requested.** Pushing `--mem` up for
  safety, per the memory guidance below, silently multiplies the job's actual
  CPU footprint too — worth knowing before submitting many such jobs
  concurrently.

### Interpretation

1. **The CPU-count finding from the small plate does not generalize — it
   inverts.** On `BR00126114` (`3.87 GB`), `4` CPUs beat `8` (`18m26s` vs
   `22m23s`). On `BR00126115` (`11.06 GB`), `8` CPUs beat `4` by about `20%`
   (`1h36m` vs `1h59m`). There is a real crossover somewhere between these two
   sizes where added `ThreadPoolExecutor` parallelism stops being dominated
   by overhead and starts paying off. Do not treat "`4` CPUs is fastest" as a
   fixed rule; treat it as true only below roughly `~5 GB` of source data,
   pending a finer-grained sweep. (`BR00126116` was only tested at `4` CPUs,
   so it doesn't yet confirm whether `8` stays ahead at `~19 GB` — worth a
   follow-up run.)
2. **The `8`-CPU speedup is not free.** It cost about `2.75x` more total
   system-CPU-time (`9305s` to `25652s` sys time) and about `23%` more peak
   memory (`43.99 GiB` to `54.24 GiB`) than the `4`-CPU run on the same
   plate. Choose `8` CPUs when minimizing wall-clock matters most and the
   memory budget allows it; choose `4` CPUs when running many jobs
   concurrently or when resource efficiency (CPU-seconds, memory, and the
   `AllocCPUS` fairshare footprint above) matters more than any one job's
   wall-clock.
3. **Peak memory does not scale in strict proportion to source size — the
   multiplier trends down as data grows, at `4` CPUs.** Ratio of Slurm cgroup
   MaxRSS to source `.sqlite` size: `4.14x` at `3.87 GB`, `3.98x` at
   `11.06 GB`, `3.33x` at `18.82 GB` (all at `4` CPUs); `8` CPUs pushed the
   ratio up to `4.90x` on the `11.06 GB` plate, the one size tested at both
   CPU counts. All three plates share the same `5946`-column schema, so this
   looks like fixed per-run overhead (Python/Parsl/DuckDB baseline working
   set) being a larger fraction of peak memory at small scale and amortizing
   as source size grows, rather than a fixed multiplier. Planning rule from
   these three points: `~4.5x` source size for anything under `~5 GB`,
   `~4x` for a single-plate conversion in the `~10-20 GB` range, `~5x` if
   running at `8` CPUs — with real headroom in all cases, since this is only
   three data points across one dataset family.
4. **Wall-clock scaling is confirmed superlinear across all three points, not
   just the first two.** A power-law fit (least-squares in log-log space)
   across all three `(source_GB, elapsed_s)` pairs gives
   `time ∝ size^1.83` — very close to the `^1.77` estimated from just the
   first two points, and it predicts the `BR00126116` result (`336` min)
   within `~2%` of the actual `342` min. Treat `time ≈ T_ref × (size /
   size_ref)^1.8` as a validated planning formula for this dataset family,
   not a rough guess — but keep giving real headroom on top of it, since it's
   still anchored by only three points from one JUMP batch.

## HTEX Retest With Real Memory Headroom

The `2026-08-21` finding that capped `HighThroughputExecutor` OOM-killed
under a `16G`/4-cpu request (see Real-Scale S3 Benchmark) had only ever been
tested at that one tight memory budget. On `2026-08-24`, the same
`BR00126115` plate (`11.06 GB` source) that `ThreadPoolExecutor` converted in
`1h59m` at `4` CPUs was re-run with `HighThroughputExecutor(
max_workers_per_node=4)`, this time with deliberately generous headroom —
`--mem=128G` (`~3x` ThreadPoolExecutor's observed `43.99 GiB` peak on the same
plate) and `--time=4:00:00` (`~2x` ThreadPoolExecutor's runtime) — to find
out whether the earlier failure was a memory-starvation artifact or a real
limitation of the executor.

Job `31624016` (`htex-retest-4c-BR00126115`):

| metric | ThreadPoolExecutor (4c) | HighThroughputExecutor, capped (4c) |
| --- | ---: | ---: |
| status | completed | completed |
| elapsed | `1h59m` (`7081s`) | `25m48s` (`1548s`) |
| Slurm cgroup MaxRSS | `43.99 GiB` | `35.01 GiB` |
| rows / columns | `215296` / `5946` | `215296` / `5946` |
| parquet bytes | `11546075654` | `11546075654` |

**Given real headroom, capped HTEX was `~4.6x` faster than ThreadPoolExecutor
on the identical plate, and used `~20%` less memory (`35.01 GiB` vs
`43.99 GiB`, a `3.16x` multiple of source size vs ThreadPoolExecutor's
`3.98x`).** Output was byte-identical to the corresponding ThreadPoolExecutor
run (same row/column counts, same parquet byte size), confirming this is a
performance difference, not a correctness one.

### Interpretation

1. **The original "avoid HTEX" finding was a memory-starvation artifact, not
   an executor limitation.** Once HTEX had real headroom instead of a budget
   that was already tight for ThreadPoolExecutor, it did not just survive —
   it substantially outperformed ThreadPoolExecutor on both wall-clock and
   peak memory on the one real plate this was tested against. Do not read
   the `2026-08-21` OOM as "HTEX can't handle real data"; read it as "HTEX
   needs a properly-sized `--mem`, same as anything else, and the `16G`
   budget was sized for ThreadPoolExecutor's footprint, not HTEX's."
2. **A process-based executor plausibly wins here precisely because it's not
   thread-based.** `ThreadPoolExecutor` runs everything inside one Python
   process; HTEX runs separate OS worker processes. That costs more baseline
   memory per worker (which is exactly what starved it under `16G`), but it
   sidesteps Python-level contention (GIL, shared-object contention, or
   contention inside DuckDB's own thread pool when driven by multiple
   Python threads in one process) that the `4`-vs-`8`-CPU
   `ThreadPoolExecutor` findings elsewhere in this doc suggest is a real,
   measurable cost at this data scale. This is a plausible explanation, not
   directly instrumented — worth deeper profiling if the pattern holds up.
3. **This is one comparison at one size and one CPU count — it needs
   replication before being treated as a general rule.** Not yet tested:
   capped HTEX with headroom on the `3.87 GB` or `18.82 GB` plates, HTEX at
   `8` workers, or Cytotable-style *default* (uncapped) HTEX with headroom.
   Given how large and consistent-with-a-real-mechanism this result is,
   though, it's strong enough to flip the *default* recommendation from
   "avoid HTEX" to "prefer HTEX when you can afford real memory headroom,
   fall back to ThreadPoolExecutor when memory is tight" — see the updated
   guidance in `.agents/skills/cytotable/SKILL.md`.

## Collection Commands

```bash
ROOT=/scratch/alpine/$USER/cytotable-alpine-bench-20260821
cd "$ROOT"

for f in results/large-*.json results/xl-*.json results/htex-retest-*.json; do
  printf 'FILE %s\n' "$f"
  cat "$f"
done

sacct -j 31542591,31542592,31542593,31542594,31608776,31608777,31608778,31624016 \
  --format=JobIDRaw,JobName%30,State,ExitCode,Elapsed,AllocCPUS,ReqCPUS,ReqMem,MaxRSS,MaxVMSize,NNodes,NodeList -P

for f in logs/large-*.err logs/xl-*.err logs/htex-retest-*.err; do
  printf 'ERR %s\n' "$f"
  grep -E 'Elapsed|Maximum resident|Percent of CPU|Exit status|Command exited|oom_kill' "$f" || true
done
```

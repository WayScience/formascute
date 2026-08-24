---
name: cytotable
description: Use before running, tuning, or documenting CytoTable conversions on CURC Alpine, especially for Parsl executor choice, Slurm CPU and memory shape, DuckDB/Arrow settings, S3-backed large tests, scratch-backed HOME, or uv runtime setup.
---

# Cytotable Skill

Use this note before running, tuning, or documenting CytoTable conversions on
CURC Alpine, especially when choosing a Parsl executor, Slurm CPU/memory
shape, Python runtime, or scratch/project storage layout.

Also read `.agents/skills/alpine/SKILL.md` for Alpine-wide Slurm, storage, and
SSH facts. This skill is Cytotable-specific; keep general Alpine policy in the
Alpine skill instead.

The guidance below is ordered by what actually determines whether a real
conversion finishes: executor choice and CPU count first (they change
wall-clock and whether the job OOMs), then memory/mmap/chunk sizing, then
runtime setup, then failure modes. All performance numbers below come from
real JUMP Cell Painting Gallery plate conversions pulled from S3, at three
confirmed source sizes (`~3.9 GB`, `~11 GB`, `~19 GB` — see Real-Scale
Benchmark), not the tiny bundled test fixture —
`docs/cytotable-alpine-findings.md` has the raw job IDs and logs. **The
"best" CPU count is not a single fixed number — it depends on source data
size**, and **the executor recommendation flipped once HTEX was given real
memory headroom instead of a memory-starved budget** (see both below);
numbers from the tiny fixture are called out explicitly where used, since
they're too small to trust for performance decisions on their own. All
memory figures below are GiB (binary, matching Slurm's own `--mem=NG` units
and `sacct`'s KiB-based `MaxRSS`), not decimal GB.

## Performance Guidance (Start Here)

- **Prefer capped `HighThroughputExecutor` over `ThreadPoolExecutor` when you
  can afford real memory headroom — it was `~4.6x` faster and used `~20%`
  less memory on the one real plate this has been tested against.** This
  reverses earlier guidance in this skill, so the history matters: a capped
  `HighThroughputExecutor(max_workers_per_node=4)` run OOM-killed under a
  `16G`/4-cpu Slurm request that ThreadPoolExecutor completed successfully
  (peaking at exactly `16.00 GiB`, itself pinned right at that request). That
  looked like an executor-level limitation, so this skill recommended
  ThreadPoolExecutor instead. It wasn't one — it was memory starvation. When
  the same `11.06 GB` plate was re-run with capped HTEX given real headroom
  (`128G`, about `3x` ThreadPoolExecutor's own peak on that plate) instead of
  the tight `16G` budget, it completed in `25m48s` versus ThreadPoolExecutor's
  `1h59m` on the identical plate — and used `35.01 GiB` peak versus
  ThreadPoolExecutor's `43.99 GiB`. Same row/column counts, same output
  bytes — a real performance difference, not a correctness one. The likely
  mechanism: HTEX uses separate OS worker processes, not threads inside one
  Python process, so it avoids whatever GIL- or shared-object-level
  contention the `4`-vs-`8`-CPU ThreadPoolExecutor findings below suggest is
  a real cost at this scale — at the price of needing more memory per worker
  up front, which is exactly what starved it under `16G`. **This is one
  comparison at one size (`11 GB`) and one CPU count (`4`, capped)** — not
  yet retested at the `3.87 GB` or `18.82 GB` plates, at `8` workers, or
  uncapped. Given the size and mechanism-consistency of the result, treat it
  as the new default recommendation when `--mem` isn't tightly constrained,
  and fall back to ThreadPoolExecutor specifically when memory is the binding
  constraint (it needs meaningfully less to succeed, even though it's
  slower). Re-validate before trusting this at a size or CPU count not yet
  tested. HTEX also remains the only Parsl executor here that can fan out
  across *multiple* Slurm nodes — ThreadPoolExecutor is confined to one
  process on one node.
- **For `ThreadPoolExecutor`, the best CPU count depends on source data
  size — there is no single right answer.** (This CPU-count comparison has
  only been run under `ThreadPoolExecutor`; HTEX's own CPU-count scaling is
  untested — see above.) On a `~3.9 GB` plate, `4` CPUs beat `8` by `~21%`
  (`18m26s` vs `22m23s`). On a `~11 GB` plate, that inverts: `8` CPUs beat `4`
  by `~20%` (`1h36m` vs `1h59m`). There is a real crossover somewhere between
  those two sizes where added `ThreadPoolExecutor(max_threads=...)`
  parallelism stops being dominated by overhead and starts paying off. As a
  starting rule: use `4` CPUs below roughly `~5 GB` of source data; use `8`
  CPUs at `~10 GB` and above if minimizing wall-clock matters most (only
  tested up to `~11 GB` at `8` CPUs so far — the `~19 GB` plate was only run
  at `4` CPUs). The `8`-CPU win is not free — it cost `~2.75x` more total
  system-CPU-time and `~23%` more peak memory on the `11 GB` plate — so
  prefer `4` CPUs instead when running many jobs concurrently or when
  resource efficiency matters more than one job's wall-clock. Note also that
  raw CPU% readings on Alpine's `acpu` partition are not a clean contention
  signal by themselves: a large `--mem` request silently grants far more
  actual CPU allocation than `--cpus-per-task` requests (`AllocCPUS = max(
  --cpus-per-task, ceil(--mem_GB / 3.75))` — a `96G` request got `26`
  allocated CPUs against a nominal `4`), so background library threads (not
  gated by `CYTOTABLE_MAX_THREADS`) can use more cores than the "4 vs 8"
  framing implies. The wall-clock comparison itself remains the reliable
  signal. Do not assume a fixed CPU count transfers across data sizes;
  re-benchmark at the target scale, especially outside the `~4-11 GB` range
  actually tested.
- **Leave `CYTOTABLE_ARROW_USE_MEMORY_MAPPING=1` (the default) on.** It was
  about `7%` faster than disabling it in the same real conversion, at the
  cost of about `1 GB` more process-level peak RSS. Only disable it
  (`CYTOTABLE_ARROW_USE_MEMORY_MAPPING=0`) if a run is memory-constrained
  enough that trading that speed for roughly `1 GB` of headroom matters.
- **Size `--mem` at roughly `4-4.5x` the source `.sqlite` file size at `4`
  CPUs, not off `chunk_size` or a flat number — and expect the multiplier to
  trend down, not up, as source size grows.** Peak memory (Slurm cgroup
  MaxRSS) to source-size ratio across the three confirmed plate sizes, all at
  `4` CPUs: `4.14x` at `3.9 GB` (`16.00 GiB` peak), `3.98x` at `11 GB`
  (`43.99 GiB` peak), `3.33x` at `19 GB` (`62.67 GiB` peak). `8` CPUs pushed
  the ratio higher (`4.90x`) on the one plate tested at both CPU counts. All
  three plates share the same `~5946`-column schema, so the declining ratio
  looks like fixed per-run overhead (Python/Parsl/DuckDB baseline working
  set) mattering more at small scale and amortizing at larger scale — not
  evidence that bigger conversions need proportionally *more* headroom. All
  of the memory pressure itself shows up during the final join/concat, not
  during chunked reads, regardless of `chunk_size`. Use `~4.5x` source size
  as a starting point for a single-plate conversion under `~10 GB`, `~4x` in
  the `~10-20 GB` range, and `~5x` if running at `8` CPUs or when in doubt;
  this ratio is anchored by only three real data points from one dataset
  family so far, so re-measure rather than trusting it blindly outside
  `~4-19 GB`.
- **Budget `--time` with a superlinear formula, not a flat number or linear
  scaling — this is now confirmed across three sizes, not just two.** A
  power-law fit (least-squares in log-log space) across all three
  `(source_GB, elapsed_s)` points gives `time ∝ size^1.83`, and that formula
  predicted the `~19 GB` plate's actual runtime within `~2%` from the
  smallest plate alone. A linear guess from the small plate would have
  predicted about `53` minutes for the `11 GB` plate (real: `1h59m`, `>2x`
  off) and about `1h30m` for the `19 GB` plate (real: `5h42m`, nearly `4x`
  off). The tiny bundled CSV fixture finishes in well under a minute and is
  not a usable calibration point for real production `--time` at all. Treat
  `time ≈ T_ref × (size / size_ref)^1.8` as a validated planning formula for
  this dataset family, and still pad it — a `6h` request for the `19 GB`
  plate left only `~17` minutes of slack against the actual `5h43m` runtime,
  closer than is comfortable.
- **Budget scratch storage for the S3 staging cache in proportion to source
  size, not just the parquet output.** `local_cache_dir` (the local copy of
  the S3-staged source file) tracks the source `.sqlite` size roughly 1:1
  (`~3.7 GB` cache for a `3.87 GB` source), and the parquet destination has
  landed close to source size across all three tested plates (output/source
  byte ratio `0.98x`, `1.04x`, `1.04x` at `3.87 GB`, `11.06 GB`, and
  `18.82 GB` respectively) — separate from the `~54 MB` scratch job-home
  DuckDB extension cache, which does not scale with dataset size. Multiply
  source-file size by roughly `2x` (cache plus output) per source file a run
  touches when planning scratch quota.
- **Recognize OOM disguised as a generic Parsl error — and know the fix is
  more memory, not abandoning HTEX.** An HTEX worker that gets OOM-killed
  surfaces to Cytotable as `DependencyError([(WorkerLost(1, '<node>'), 'task
  N')], M)`, not an explicit memory message — check the Slurm `.err` log for
  `oom_kill event` before assuming a `DependencyError` is a code or data
  problem. This is exactly what happened in the original HTEX test that once
  drove this skill to recommend ThreadPoolExecutor instead; the actual fix
  (real headroom, not a different executor) turned out to make HTEX the
  faster, leaner choice — see above.
- **A practical first production request**, sized off the source `.sqlite`
  file in hand. Executor choice: prefer capped HTEX where it's been
  validated (`~10-15 GB`); ThreadPoolExecutor remains the only validated
  choice outside that range, or whenever `--mem` is tightly constrained
  (HTEX's own memory floor hasn't been found yet — `128G` is known to work
  comfortably for the `~11 GB` tier, `48-64G` might too, but that hasn't been
  tested):
  - **Under `~5 GB` source:** `ThreadPoolExecutor(max_threads=4)`,
    `--cpus-per-task=4`, `--mem` at `~4.5x` source size (`24G` covers up to
    about a `5 GB` source with headroom), `--time=00:45:00`,
    `CYTOTABLE_MAX_THREADS=4`. (Capped HTEX is untested with headroom at this
    size — the only real-scale HTEX test at `~4 GB` was the tight-budget OOM
    run. Worth trying HTEX here too, but ThreadPoolExecutor is what's
    actually validated.)
  - **`~10-15 GB` source:** prefer capped `HighThroughputExecutor(
    max_workers_per_node=4)`, `--cpus-per-task=4`, `--mem` at `~6x` source
    size as a generous starting point (`64G` for an `~11 GB` source; the
    validated run used `128G` against a `35.01 GiB` observed peak, so this
    has real room to be tightened once a narrower-budget run finds the
    actual floor), `--time=01:00:00` (the validated run took `25m48s` — this
    is deliberately more padded than the observation warrants, since only
    one run confirms the runtime). Fall back to `ThreadPoolExecutor(
    max_threads=8)`, `--mem` at `~5x` source size (`64G`), `--time=03:00:00`
    if `--mem` can't stretch to HTEX's headroom.
  - **`~15-20 GB` source:** only validated with `ThreadPoolExecutor` at `4`
    CPUs so far — `ThreadPoolExecutor(max_threads=4)`, `--cpus-per-task=4`,
    `--mem` at `~4x` source size (`80G` comfortably covers a `~19 GB` source;
    the actual validated run used `96G` against a `62.67 GiB` observed peak,
    more headroom than necessary), `--time=06:00:00` (the validated run took
    `5h42m` — do not shave this down; it left only `~17` minutes of slack at
    `6h`). HTEX is untested at this size; given the `~11 GB` result, it's
    worth trying with generous `--mem` headroom before defaulting to
    ThreadPoolExecutor here too.
  - `CYTOTABLE_ARROW_USE_MEMORY_MAPPING=1` (default) in all cases.
  Re-measure against the real dataset in hand rather than assuming these
  numbers transfer to a meaningfully different column count, row count, or
  source size — especially outside the `~4-19 GB` range actually tested.

## Current Position

- Run Cytotable as a regular Slurm batch job on compute nodes. Do not route it
  through `Persistence1` unless another orchestrator actually needs that host.
- Put source data, destination parquet, S3 staging cache, Parsl run
  directories, and Cytotable benchmark logs under `/scratch/alpine/$USER`.
- Put reusable Python environments under `/projects/$USER/software/uv/envs` and
  keep the `uv` cache on scratch with `UV_LINK_MODE=copy`.
- Run the Cytotable Python process with a scratch-backed `HOME` so DuckDB
  extension installs do not touch Alpine's small home quota. Cytotable loads
  DuckDB extensions (`sqlite_scanner`, `httpfs`) via DuckDB's default
  extension cache under `$HOME/.duckdb`; a full home directory causes
  immediate conversion failure before executor differences matter.
- Set `CYTOTABLE_MAX_THREADS` before Python starts. Cytotable reads it at import
  time and passes it into DuckDB thread configuration.
- Start with one Cytotable conversion per Slurm job, using one node, explicit
  `--time`, explicit `--mem`, and `--cpus-per-task` matched to
  `CYTOTABLE_MAX_THREADS`.
- Prefer capped `HighThroughputExecutor(max_workers_per_node=<cpus>)` over
  `ThreadPoolExecutor(max_threads=<cpus>)` when `--mem` can afford real
  headroom — on the one real plate both have been tested against at
  adequate memory, capped HTEX was `~4.6x` faster and used `~20%` less peak
  memory. This reverses this skill's earlier position, which was based on an
  HTEX run that OOM-killed under a tight `16G` budget; that turned out to be
  memory starvation, not an executor limitation (see Performance Guidance
  and Real-Scale Benchmark above). Fall back to `ThreadPoolExecutor` when
  `--mem` is tightly constrained, or outside the `~11 GB` scale actually
  validated for HTEX.
- `CYTOTABLE_MAX_THREADS`/`--cpus-per-task` has no single best value — it
  depends on source data size. `4` CPUs measured faster on a `~3.9 GB` plate;
  `8` CPUs measured `~20%` faster (at higher memory/CPU-time cost) on a
  `~11 GB` plate; the `~19 GB` plate was only tested at `4` CPUs. Pick based
  on source size and whether wall-clock or resource efficiency matters more;
  re-benchmark for sizes outside `~4-19 GB`. See Performance Guidance above
  for the current split.
- Size Slurm memory requests at roughly `4-4.5x` the source `.sqlite` file
  size (trending down, not up, as source size grows — see Performance
  Guidance), not off the tiny bundled fixture or off `chunk_size`.
- Budget `--time` with a superlinear formula (`time ∝ size^1.83`, validated
  across three real plate sizes), not a flat number or a linear guess from a
  smaller dataset — see Performance Guidance above.
- A large `--mem` request on `acpu` silently grants a proportionally larger
  `AllocCPUS` than `--cpus-per-task` requests (`DefMemPerCPU=3840 MB` drives
  `AllocCPUS = max(--cpus-per-task, ceil(--mem_GB / 3.75))`). Know this before
  reading raw CPU% figures as a contention signal, and before submitting many
  large-`--mem` jobs concurrently — each one consumes more of the fairshare
  CPU budget than its `--cpus-per-task` implies.

## Real-Scale Benchmark

On `2026-08-21`, a real-data matrix converted one JUMP Cell Painting Gallery
plate directly from the public `cellpainting-gallery` S3 bucket
(`no_sign_request=True`, no AWS credentials needed):

```text
s3://cellpainting-gallery/cpg0016-jump/source_4/workspace/backend/2021_08_23_Batch12/BR00126114/BR00126114.sqlite
```

`source_datatype="sqlite"`, `preset="cellprofiler_sqlite_cpg0016_jump"`,
`chunk_size=30000`. Every job requested `--mem=16G`, `--time=1:00:00`.

| run | executor | cpus | arrow mmap | status | elapsed | Slurm cgroup MaxRSS |
| --- | --- | ---: | ---: | --- | ---: | ---: |
| `large-tpe-4c-c30000-a1` | ThreadPoolExecutor | 4 | 1 (default) | completed | `18m26s` | `16.00 GiB` |
| `large-tpe-8c-c30000-a1` | ThreadPoolExecutor | 8 | 1 (default) | completed | `22m23s` | `16.00 GiB` |
| `large-tpe-4c-c30000-a0` | ThreadPoolExecutor | 4 | 0 | completed | `19m49s` | `16.00 GiB` |
| `large-htexcap-4c-c30000-a1` | HighThroughputExecutor, capped to 4 workers | 4 | 1 (default) | **OOM-killed** | `5m30s` | `16.00 GiB` (killed) |

All three successful runs produced identical output (`74226` rows, `5946`
columns, `~3.8 GB` parquet), confirming the executor/CPU/mmap choice changes
speed and memory behavior but not correctness. The failed HTEX run had
already written complete per-compartment intermediate parquet
(`cells/`, `cytoplasm/`, `image/`, `nuclei/`, `~3.7 GB` total) before dying at
the join stage — the memory pressure is in the join, not the chunked reads.

Full job IDs, `sacct`/`time` output, and the interpretation this section
summarizes are in `docs/cytotable-alpine-findings.md`. Treat this as one
real-scale comparison, not an exhaustive sweep — CPU counts other than `4`/`8`,
chunk sizes other than `30000`, and dataset shapes other than this one plate
have not been tested. Re-run a comparable comparison before trusting these
exact numbers for a meaningfully different dataset.

### Larger-Scale Benchmark (Bigger Plates)

The `3.87 GB` plate above turned out to be the *smallest* of `17` plates in
the same JUMP batch on S3 — the rest range up to `~30 GB`. On `2026-08-24`,
the same validated configuration (ThreadPoolExecutor, `chunk_size=30000`,
mmap default-on) was tested against two bigger real plates to check whether
the small-plate numbers above generalize:

| plate | source size | cpus | status | elapsed | Slurm cgroup MaxRSS |
| --- | ---: | ---: | --- | ---: | ---: |
| `BR00126114` (above) | `3.87 GB` | 4 | completed | `18m26s` | `16.00 GiB` |
| `BR00126115` | `11.06 GB` | 4 | completed | `1h59m` | `43.99 GiB` |
| `BR00126115` | `11.06 GB` | 8 | completed | `1h36m` | `54.24 GiB` |
| `BR00126116` | `18.82 GB` | 4 | completed | `5h42m` | `62.67 GiB` |

**They mostly don't generalize as a fixed number, but they do generalize as a
relationship:**

- The CPU-count finding flips: `4` CPUs was faster at `3.87 GB`, `8` CPUs was
  `~20%` faster at `11.06 GB` (at `~23%` more memory and `~2.75x` more
  system-CPU-time). There's a real crossover between these two sizes.
  `BR00126116` was only run at `4` CPUs, so whether `8` stays ahead at
  `~19 GB` is still open.
- Peak memory did *not* stay at a rising or flat multiple of source size —
  the ratio actually declined at `4` CPUs (`4.14x` → `3.98x` → `3.33x` as
  source size grew from `3.87 GB` to `11.06 GB` to `18.82 GB`), consistent
  with fixed per-run overhead mattering less at larger scale. `8` CPUs pushed
  the ratio higher (`4.90x`) on the one plate tested at both CPU counts.
- Wall-clock scaling is confirmed superlinear with all three points now in:
  a power-law fit gives `time ∝ size^1.83` and predicts the `18.82 GB`
  result within `~2%` from the smallest plate alone — a strong signal this
  relationship, not just a rough two-point guess, is real for this dataset
  family. A linear guess from the small plate would have underestimated the
  `18.82 GB` runtime by nearly `4x`.
- A Slurm scheduling quirk on `acpu` matters for reading these numbers: a
  large `--mem` request silently grants far more `AllocCPUS` than
  `--cpus-per-task` (the `96G` request behind the `18.82 GB` run got `26`
  allocated CPUs against a nominal `4`) — see
  `docs/cytotable-alpine-findings.md` for the exact rule and why it means raw
  CPU% figures aren't a clean contention signal by themselves.

See `docs/cytotable-alpine-findings.md` for the full data, job IDs, and
interpretation.

### HTEX Retest With Real Memory Headroom

The `16G`-budget HTEX OOM above was only ever tested at that one tight
memory budget. On `2026-08-24`, capped `HighThroughputExecutor(
max_workers_per_node=4)` was re-run against the same `BR00126115`
(`11.06 GB`) plate that `ThreadPoolExecutor` converted in `1h59m`, this time
with `--mem=128G` (`~3x` ThreadPoolExecutor's own peak on that plate) and
`--time=4:00:00`:

| executor | elapsed | Slurm cgroup MaxRSS |
| --- | ---: | ---: |
| ThreadPoolExecutor (4c) | `1h59m` | `43.99 GiB` |
| HighThroughputExecutor, capped (4c) | `25m48s` | `35.01 GiB` |

Given real headroom, capped HTEX was `~4.6x` faster than ThreadPoolExecutor
and used `~20%` less memory, on byte-identical output. The original OOM was
memory starvation from a `16G` budget that was sized for
ThreadPoolExecutor's footprint, not HTEX's — not an inherent HTEX
limitation. This is one comparison at one size and one CPU count; see
`docs/cytotable-alpine-findings.md` for the full writeup and what's still
untested (other sizes, `8` workers, uncapped HTEX).

### Mechanics Smoke Test (Tiny Fixture)

An earlier same-day pass used Cytotable's bundled test fixture
(`tests/data/cellprofiler/cpg0043-segmentation`, `48` CSV files, `~256 MB`)
with `preset="cellprofiler_csv"` to validate submission mechanics and the
scratch-backed-`HOME` fix before the real-scale matrix above. Two runs
completed:

| run | elapsed | Slurm MaxRSS |
| --- | ---: | ---: |
| `homefix-threadpool-4c` | `43.83s` | `5966192K` |
| `homefix-htex-capped-4c` | `49.35s` | `4110988K` |

Use this fixture for correctness/mechanics checks (env setup, scratch-`HOME`
fix, package install) only — it's too small to trust for performance
decisions on its own. Its direction (capped HTEX using less RSS than
ThreadPoolExecutor) turned out to match the real-scale HTEX-with-headroom
result above, not contradict it; what looked like a contradiction after the
first real-scale test was actually that test being memory-starved, not a
genuine reversal. Still don't use fixture-scale numbers for actual
memory/time sizing — the real-scale figures above are the ones to plan from.

## DuckDB And Arrow Settings

- Set `CYTOTABLE_MAX_THREADS="$SLURM_CPUS_PER_TASK"` in the batch job before
  Python starts. Cytotable reads this at import time and uses it for DuckDB
  `PRAGMA threads`; setting it later in Python is too late. Start from `4`
  per Performance Guidance above rather than the node's full CPU count.
- Set `HOME` to a scratch job-home after activating the reusable environment
  and before starting Python, for example:

  ```bash
  export CYTOTABLE_JOB_HOME="/scratch/alpine/$USER/cytotable-job-home/$SLURM_JOB_ID"
  mkdir -p "$CYTOTABLE_JOB_HOME"
  export HOME="$CYTOTABLE_JOB_HOME"
  ```

  This redirects DuckDB's default extension cache (`$HOME/.duckdb`) to
  scratch. Validated at about `54 MB` per scratch job-home, and that figure
  did not scale up with real production-size data.
- Leave Cytotable's default Arrow memory mapping enabled:
  `CYTOTABLE_ARROW_USE_MEMORY_MAPPING=1`. Measured `~7%` faster than disabling
  it on a real conversion, at the cost of `~1 GB` more peak RSS. Disable it
  only when a run is memory-constrained enough to need that headroom instead
  of the speed.
- `chunk_size` controls per-chunk read/write memory, not the run's overall
  peak — the real-scale benchmark's memory pressure showed up entirely at the
  final join/concat stage regardless of `chunk_size`. `chunk_size=30000` is
  now validated as workable for a real single-plate SQLite conversion under
  ThreadPoolExecutor; treat it as a reasonable starting point for
  comparably-shaped real sources rather than always starting from a much
  smaller value. Size `--mem` off the destination table's joined
  row × column shape, not off `chunk_size`.
- Do not try to tune DuckDB `memory_limit` first. Cytotable exposes thread
  control through `CYTOTABLE_MAX_THREADS`, but not a clean per-run DuckDB memory
  limit hook. Control memory with Slurm `--mem`, `chunk_size`, and one
  conversion per Python process.
- Keep `sort_output=True` (the default) when reproducibility or output
  comparison matters; the real-scale benchmark used the default and produced
  byte-identical output across all three successful executor/CPU/mmap
  combinations. Test `sort_output=False` only when downstream consumers do
  not require stable sorted output.

## Parsl Config Pattern

Prefer capped `HighThroughputExecutor` when `--mem` can afford real headroom
(`~11 GB`-scale conversions confirmed: `~4.6x` faster, `~20%` less memory than
ThreadPoolExecutor — see Performance Guidance and HTEX Retest With Real
Memory Headroom above). It's also the only option here that can fan out
across multiple Slurm nodes:

```python
from parsl.config import Config
from parsl.executors import HighThroughputExecutor

capped_htex = Config(
    executors=[
        HighThroughputExecutor(
            label="cytotable_htex",
            max_workers_per_node=cpus,
        )
    ],
    run_dir=f"{scratch_root}/parsl-runs/{run_name}-htex-capped",
)
```

Fall back to `ThreadPoolExecutor` when `--mem` is tightly constrained (it
needs meaningfully less to succeed, even though it's slower — validated down
to `16G` on a `~3.9 GB` plate) or outside the `~11 GB` scale HTEX has
actually been validated at:

```python
from parsl.config import Config
from parsl.executors import ThreadPoolExecutor

parsl_config = Config(
    executors=[ThreadPoolExecutor(label="cytotable_tpe", max_threads=cpus)],
    run_dir=f"{scratch_root}/parsl-runs/{run_name}",
)
```

Call `convert(...)` with the config:

```python
from cytotable import convert

convert(
    source_path=source_path,
    dest_path=dest_path,
    dest_datatype="parquet",
    source_datatype="csv",
    preset="cellprofiler_csv",
    chunk_size=30000,
    parsl_config=parsl_config,
)
```

## Runtime Setup

Cytotable itself has no dependency on any particular Python environment
manager — it's an ordinary `pip`-installable package, so `uv`, `conda`, plain
`venv`+`pip`, or Apptainer/Singularity (see `.agents/skills/alpine/SKILL.md`'s
Runtime Direction for the project-wide tradeoffs between those) all work
mechanically. `uv` is what this skill documents and what every benchmark
above actually ran through — the performance numbers are conditioned on that
runtime, though there's no specific reason to expect DuckDB/PyArrow/Parsl
behavior to differ under a different manager. CURC's general project guidance
favors Apptainer/Singularity for reproducibility and considers conda harder to
maintain long-term; `uv` was picked here for faster iteration while pinning
down the Slurm/executor/memory findings above, not because the other options
are unsupported. Re-validate the performance numbers if switching runtimes,
same as for any other untested configuration change.

Use a project-owned `uv` environment:

```bash
export UV_HOME="/projects/$USER/software/uv"
export UV_INSTALL_DIR="$UV_HOME/bin"
export UV_ENVS="$UV_HOME/envs"
export UV_CACHE_DIR="/scratch/alpine/$USER/uv-cache"
export UV_LINK_MODE=copy
export PATH="$UV_INSTALL_DIR:$PATH"
mkdir -p "$UV_INSTALL_DIR" "$UV_ENVS" "$UV_CACHE_DIR"

if [[ ! -x "$UV_INSTALL_DIR/uv" ]]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi

uv venv "$UV_ENVS/cytotable-alpine" --python 3.12
source "$UV_ENVS/cytotable-alpine/bin/activate"
uv pip install cytotable
```

If installing from a GitHub source archive rather than PyPI or a real git
checkout, Cytotable's `setuptools-scm` build needs an explicit pretend version:

```bash
export SETUPTOOLS_SCM_PRETEND_VERSION_FOR_CYTOTABLE=0.0.0+alpinebench
uv pip install /scratch/alpine/$USER/cytotable-alpine-bench-20260821/CytoTable-main
```

## Failure Modes

- Alpine home at `100%` full can prevent even simple SSH commands from running;
  commands were observed failing with `sed: couldn't open temporary file
  /home/.../.ssh/sed...: No space left on device`.
- Avoid writing Cytotable data, archives, virtual environments, caches, or
  Parsl run directories under home. Use scratch/project paths as above.
- Do not let DuckDB use `$HOME/.duckdb` on Alpine. Either run Cytotable with
  scratch-backed `HOME` as above, or use a code-level DuckDB
  `extension_directory` configuration if Cytotable exposes one in the future.
- Do not use an existing Cytotable `dest_path`; Cytotable intentionally raises
  instead of overwriting. On a failed run, `dest_path` can be left as a
  partially-written directory (per-compartment subdirectories) rather than
  cleanly absent — remove it explicitly before retrying rather than assuming
  a failed run left nothing behind.
- Set `parsl_config` on the first Cytotable call in a Python process. Cytotable
  reuses an already-loaded Parsl DFK and will not switch configs mid-process.
- An HTEX worker OOM does not surface as an out-of-memory error to Cytotable —
  it surfaces as a generic Parsl `DependencyError([(WorkerLost(...), 'task
  N')], M)`. Check the Slurm `.err` log for `oom_kill event` before treating
  this as a code or data bug.
- A large `--mem` request on `acpu` grants more actual CPU allocation than
  `--cpus-per-task` alone implies: `AllocCPUS = max(--cpus-per-task,
  ceil(--mem_GB / 3.75))`, driven by the partition's `DefMemPerCPU=3840 MB`.
  Confirmed across five jobs (`16G`/`4c`→`5` allocated, `16G`/`8c`→`8`,
  `64G`/`4c or 8c`→`18` both times, `96G`/`4c`→`26`). Check `sacct AllocCPUS`
  before reading a job's CPU% as a clean measure of thread contention, and
  remember that pushing `--mem` up for safety also multiplies the job's real
  CPU/fairshare footprint.

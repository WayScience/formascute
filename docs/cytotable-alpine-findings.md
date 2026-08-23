# Cytotable Alpine Findings

These notes record the `2026-08-21` CytoTable-on-Alpine experiment setup and
what was learned before Alpine account-home exhaustion blocked result
collection.

## Goal

Compare Cytotable Parsl configuration on Alpine compute nodes:

- `ThreadPoolExecutor`
- Cytotable-style default `HighThroughputExecutor`
- capped `HighThroughputExecutor`
- Slurm CPU requests of `1`, `4`, and `8` CPUs

The run intentionally avoided `Persistence1`; each Cytotable conversion was a
plain Slurm batch job submitted from the Alpine login node.

## Dataset

The benchmark used Cytotable's current `main` source archive and bundled test
fixture:

```text
tests/data/cellprofiler/cpg0043-segmentation
```

Observed on Alpine:

- `48` CSV files
- `256020900` CSV bytes

This fixture is large enough to exercise CSV parsing, chunking, joining, and
Parquet writing, while still being appropriate for short `acpu` jobs.

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

## Experiment Matrix

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

Interpretation:

- Scratch-backed `HOME` is a required Alpine best practice for Cytotable unless
  Cytotable exposes a DuckDB `extension_directory` hook in the future.
- Threadpool is the current first-choice `4` CPU baseline for speed on this
  fixture.
- Capped HTEX is still worth testing for larger memory-sensitive runs because
  it used less Slurm-reported peak RSS in this one comparison.
- Default uncapped HTEX should not be used for production guidance until it
  passes a scratch-home benchmark.

## Current Guidance

Until the corrected matrix is collected, use this as provisional guidance:

- Use one Cytotable conversion per Slurm job on `acpu`.
- Submit directly from the Alpine login node; do not use `Persistence1` for
  this non-Nextflow shape.
- Run the Cytotable process with a scratch-backed `HOME` so DuckDB extension
  installs use scratch rather than `$HOME/.duckdb`.
- Start with `ThreadPoolExecutor(max_threads=<cpus>)`, `--cpus-per-task=4`,
  `--mem=8G`, and `CYTOTABLE_MAX_THREADS=<cpus>`.
- Keep all Cytotable inputs, outputs, Parsl `run_dir`, and logs on scratch.
- Keep reusable `uv` environments under project storage and the `uv` cache on
  scratch.
- Use capped HTEX as a comparison candidate for memory-sensitive larger runs,
  but do not treat default uncapped HTEX as validated.

## Collection Commands

After freeing Alpine home space:

```bash
ROOT=/scratch/alpine/$USER/cytotable-alpine-bench-20260821
cd "$ROOT"

for f in results/rerun-*.json; do
  printf 'FILE %s\n' "$f"
  cat "$f"
done

sacct -j 31536906,31536907,31536908,31536909,31536910,31536911,31536912,31536913,31536914 \
  --format=JobIDRaw,JobName%26,State,ExitCode,Elapsed,AllocCPUS,ReqCPUS,ReqMem,MaxRSS,MaxVMSize,NNodes,NodeList -P

for f in logs/rerun-*.err; do
  printf 'ERR %s\n' "$f"
  grep -E 'Elapsed|Maximum resident|Percent of CPU|Exit status|Command exited' "$f" || true
done
```

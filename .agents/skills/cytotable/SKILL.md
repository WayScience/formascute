---
name: cytotable
description: Use before running, tuning, or documenting CytoTable conversions on CURC Alpine, especially for Parsl executor choice, Slurm CPU and memory shape, DuckDB/Arrow settings, S3-backed large tests, scratch-backed HOME, or uv runtime setup.
---

# Cytotable Skill

Use this note before running, tuning, or documenting CytoTable conversions on
CURC Alpine, especially when choosing a Parsl executor, Slurm CPU shape, Python
runtime, or scratch/project storage layout.

Also read `.agents/skills/alpine/SKILL.md` for Alpine-wide Slurm, storage, and
SSH facts. This skill is Cytotable-specific; keep general Alpine policy in the
Alpine skill instead.

## Current Position

- Run Cytotable as a regular Slurm batch job on compute nodes. Do not route it
  through `Persistence1` unless another orchestrator actually needs that host.
- Put source data, destination parquet, Parsl run directories, and Cytotable
  benchmark logs under `/scratch/alpine/$USER`.
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
- Use `ThreadPoolExecutor(max_threads=<cpus>)` as the first candidate for
  local Alpine conversion jobs. In one validated `4` CPU comparison on the
  bundled CSV fixture, threadpool was slightly faster than capped HTEX.
- Keep capped `HighThroughputExecutor(max_workers_per_node=<cpus>)` as the
  comparison candidate when memory is the concern. In the same single
  comparison, capped HTEX used less Slurm-reported peak RSS but ran slightly
  slower. Do not use default uncapped HTEX for production guidance until it has
  passed the same scratch-home benchmark.
- A practical first production-shaped request is `--cpus-per-task=4`,
  `--mem=8G`, `--time=00:20:00` for the bundled test-size CSV conversion, then
  scale from measured walltime and RSS. Re-measure for larger real datasets.

## DuckDB And Arrow Settings

- Set `CYTOTABLE_MAX_THREADS="$SLURM_CPUS_PER_TASK"` in the batch job before
  Python starts. Cytotable reads this at import time and uses it for DuckDB
  `PRAGMA threads`; setting it later in Python is too late.
- Set `HOME` to a scratch job-home after activating the reusable environment
  and before starting Python, for example:

  ```bash
  export CYTOTABLE_JOB_HOME="/scratch/alpine/$USER/cytotable-job-home/$SLURM_JOB_ID"
  mkdir -p "$CYTOTABLE_JOB_HOME"
  export HOME="$CYTOTABLE_JOB_HOME"
  ```

  This redirects DuckDB's default extension cache (`$HOME/.duckdb`) to scratch.
  A validated run created about `54 MB` per scratch job-home.
- Leave Cytotable's default Arrow memory mapping enabled for initial runs:
  `CYTOTABLE_ARROW_USE_MEMORY_MAPPING=1`. This is the default and should be a
  reasonable fit for scratch-backed parquet reads.
- If a run shows unexpectedly high `MaxVMSize`, file-handle/unlink behavior, or
  memory pressure during concat/join, run a controlled comparison with
  `CYTOTABLE_ARROW_USE_MEMORY_MAPPING=0`.
- Use `chunk_size` as the first memory tuning knob. Smaller chunks lower peak
  memory and larger chunks reduce intermediate-file overhead. Start with
  `chunk_size=1000` for validation, then tune upward only after Slurm `MaxRSS`
  is comfortably below the memory request.
- Do not try to tune DuckDB `memory_limit` first. Cytotable exposes thread
  control through `CYTOTABLE_MAX_THREADS`, but not a clean per-run DuckDB memory
  limit hook. Control memory with Slurm `--mem`, `chunk_size`, and one
  conversion per Python process.
- Keep `sort_output=True` when reproducibility or output comparison matters.
  Test `sort_output=False` only when downstream consumers do not require stable
  sorted output; it can avoid some `ORDER BY` work.

## Runtime Setup

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

## Parsl Config Pattern

Thread pool baseline:

```python
from parsl.config import Config
from parsl.executors import ThreadPoolExecutor

parsl_config = Config(
    executors=[ThreadPoolExecutor(label="cytotable_tpe", max_threads=cpus)],
    run_dir=f"{scratch_root}/parsl-runs/{run_name}",
)
```

HTEX comparison candidates:

```python
from parsl.config import Config
from parsl.executors import HighThroughputExecutor

default_htex = Config(
    executors=[HighThroughputExecutor(label="cytotable_htex")],
    run_dir=f"{scratch_root}/parsl-runs/{run_name}-htex-default",
)

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

Call `convert(...)` with the config:

```python
from cytotable import convert

convert(
    source_path=source_path,
    dest_path=dest_path,
    dest_datatype="parquet",
    source_datatype="csv",
    preset="cellprofiler_csv",
    chunk_size=1000,
    parsl_config=parsl_config,
)
```

## Alpine Benchmark State

On `2026-08-21`, a benchmark harness was created under:

```text
/scratch/alpine/$USER/cytotable-alpine-bench-20260821
```

The source fixture was Cytotable's current `main` archive, using:

```text
tests/data/cellprofiler/cpg0043-segmentation
```

Fixture size observed on Alpine:

- `48` CSV files
- `256020900` CSV bytes

Environment installed successfully:

- Python `3.12.13` environment requested via `uv`
- Cytotable source archive installed as `0.0.0+alpinebench`
- Parsl `2026.8.10`
- DuckDB `1.5.5`
- PyArrow `25.0.1`

The first matrix submitted and failed because the harness called
`convert.convert(...)` after `from cytotable import convert`. This was a harness
bug, not a Cytotable or Slurm finding. Failed job IDs:

```text
31536860-31536868
```

The corrected matrix submitted as:

```text
31536906 rerun-threadpool-1c
31536907 rerun-threadpool-4c
31536908 rerun-threadpool-8c
31536909 rerun-htex-default-1c
31536910 rerun-htex-default-4c
31536911 rerun-htex-default-8c
31536912 rerun-htex-capped-1c
31536913 rerun-htex-capped-4c
31536914 rerun-htex-capped-8c
```

Those jobs left the queue within a few minutes, but their result files could
not be collected until Alpine home space was freed. After collection, all nine
corrected jobs were found to have failed before conversion because DuckDB tried
to install extensions under `$HOME/.duckdb` while home was full:

```text
IO Error: Cannot open file "/home/.../.duckdb/extensions/v1.5.5/linux_amd64/..."
No space left on device
```

This is an Alpine/Cytotable runtime finding, not an executor-performance
finding: all executor variants failed in about `5-6s`, before the conversion
work began.

Validated scratch-home follow-up runs:

```text
31541899 homefix-threadpool-4c: completed, 43.83s Cytotable elapsed,
         397 rows x 6049 columns, 22.85 MB parquet, Slurm elapsed 1:24,
         Slurm batch MaxRSS 5966192K
31541900 homefix-htex-capped-4c: completed, 49.35s Cytotable elapsed,
         397 rows x 6049 columns, 22.85 MB parquet, Slurm elapsed 1:30,
         Slurm batch MaxRSS 4110988K
```

Interpretation: the scratch-home pattern fixes the DuckDB extension-cache
failure. Threadpool is the current first-choice baseline for speed at `4` CPUs;
capped HTEX remains worth testing for memory-sensitive larger runs. Treat the
memory comparison as one-run evidence, not a universal rule.

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
  instead of overwriting.
- Set `parsl_config` on the first Cytotable call in a Python process. Cytotable
  reuses an already-loaded Parsl DFK and will not switch configs mid-process.

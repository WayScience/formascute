---
name: plaid-platemap
description: Use when designing or improving plate layouts with plaid (MiniZinc).
version: 0.1.0
author: Dave Bunten (d33bs), Hermes Agent
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [plaid, minizinc, platemap, plate-layout, screening]
    related_skills: [cytotable, petalibrary]
---

# Plaid Platemap Skill

Improves hit-validation plate layouts with plaid (pharmbio/plaid, constraint
programming in MiniZinc) to reduce well-related cross-effects: same-compound
wells touching each other, edge clustering, and unbalanced row/column spread.
The companion script handles the non-standard workbook format of the Way Lab
hit-validation platemap (three sheets, fixed two-zone cell plating) that plaid
cannot consume directly, and translates plaid's solution back into the same
Excel format for collaborators.

## When to Use

- Asked to design, randomize, or improve a microplate layout, especially when
  worried about proximity effects between wells.
- Asked to use plaid (or MiniZinc/Gecode) for plate design on this project.
- Reviewing a hit-validation workbook ("Hit Validation ... for Way Lab.xlsx")
  for cross-effect weaknesses before an experiment is run.
- Don't use for analysis of already-run experiments (cytotable territory), for
  Alpine/Slurm submission, or when the layout has no fixed-zone constraint and
  plaid's web GUI alone is enough.

## Prerequisites

- MiniZinc with the Gecode solver: `terminal(command="brew install minizinc")`
  on macOS (`apt`/`dnf` equivalents on Linux). Verify with
  `terminal(command="minizinc --version")`; Gecode ships in the bundle.
- `uv` for the companion script (PEP 723 inline metadata pulls openpyxl):
  `terminal(command="uv --version")`.
- The plaid model files are vendored in `assets/` (plate-design.mzn and
  layout_predicates.mzn, pinned at pharmbio/plaid commit ecf4cfe). To refresh,
  clone the plaid repo and diff; do not silently upgrade the model.
- The workbook under test: 'Platemap grid' is the authoritative per-well table
  (WellRow/WellCol/well_position/heart_number/cell_type/heart_failure_type
  plus one treatment_plate N column per plate); 'Visual Platemaps' holds the
  rosters ('Randomized order' table) and sketches. Sketches in V3 are stylized
  and contradict the grid - the grid wins, and apply corrects the sketches.

## How to Run

All commands from the repo root. The pipeline is five subcommands of one
script; each consumes the previous output.

```sh
# 1. workbook -> canonical layout JSON (validates the V3 structure)
uv run --script .agents/skills/plaid-platemap/scripts/plaid_platemap.py extract \
  --input "path/to/Hit Validation V3 for Way Lab.xlsx" \
  --output layout.json

# 2. layout JSON -> plaid .dzn (compounds-only model on the used plate area)
uv run --script .agents/skills/plaid-platemap/scripts/plaid_platemap.py dzn \
  --layout layout.json --output plate.dzn

# 3. solve with MiniZinc/Gecode until a seed passes verification
uv run --script .agents/skills/plaid-platemap/scripts/plaid_platemap.py solve \
  --mzn .agents/skills/plaid-platemap/assets/plate-design.mzn \
  --dzn plate.dzn --layout layout.json --output solution.json

# 4. write the redesigned workbook (original untouched) + QC sheet
uv run --script .agents/skills/plaid-platemap/scripts/plaid_platemap.py apply \
  --input "path/to/Hit Validation V3 for Way Lab.xlsx" \
  --output "path/to/Hit Validation V3 for Way Lab - plaid.xlsx" \
  --layout layout.json --solution solution.json

# 5. independently re-verify the output workbook (exit non-zero on failure)
uv run --script .agents/skills/plaid-platemap/scripts/plaid_platemap.py verify \
  --input "path/to/Hit Validation V3 for Way Lab - plaid.xlsx" \
  --layout layout.json --reference layout.json
```

Put layout.json, plate.dzn, solution.json, and the output workbook in the
task's scratch/work directory (not the repo) unless asked to commit them.

## Procedure

1. **Extract and validate.** Run `extract`. It asserts the used region is the
   96-well inner area (rows B-G, cols 2-11), compounds sit only on failing
   wells, per-plate compound rosters match the grid, and all plates share one
   compound well pattern. Completion: extract prints zone sizes and the
   before-metrics (V3: 17 same-compound adjacent pairs per plate).
2. **Generate the dzn.** Run `dzn`. V3 translates to 3 compounds x 8 replicates
   on an 8x12 plate with a 1-well empty edge (inner area = the 60 used wells).
   Completion: dzn written with the roster dose as the single concentration.
3. **Solve.** Run `solve`. It tries seeds 1..25, relocates plaid wells that
   land on nonfailing wells onto free failing wells (king-distance >= 2 from
   the compound's other wells, same row preferred), and checks the final
   pattern: 24 compound wells, 8 per compound, all inside the failing zone,
   same-compound king distance >= 2. First passing seed wins.
   Completion: solution.json written; PASS line printed.
4. **Apply.** Run `apply` to write the new workbook: updated 'Platemap grid'
   treatments, 'Visual Platemaps' sketches/per-well block corrected to match
   the grid, plus a 'Platemap QC' sheet with before/after metrics. The
   original file is never modified. Completion: output workbook path printed.
5. **Verify.** Run `verify` on the output workbook. It re-reads the grid
   independently and checks every invariant per plate (rosters, replicate
   counts, zones, adjacency, shared pattern) and prints before/after metrics.
   Completion: "VERIFY OK" with exit code 0; any violation exits non-zero.

## Pitfalls

- **Color coding must follow values.** 'Visual Platemaps' color-codes by value
  (V3: Failing 25 / Nonfailing 7 / Cpd 1-3 / DMSO fills). apply learns the
  legend from the source workbook at extract time and recolors every cell it
  rewrites; verify re-checks each sketch cell's fill against the legend and
  fails on any mismatch ("color check: N mismatches" plus details on stderr).
- **DMSO cannot be a plaid control here.** 36 DMSO/60 wells exceeds the max
  independent set (~30), so plaid's same-kind control separation would be
  UNSAT. DMSO is the complement of the compound pattern instead.
- **Labels-only reshuffling cannot fix V3.** The V3 compound band
  (C10-C11, D-E, F02-F03) cannot host 8 king-separated replicates per
  compound (max ~6 in that shape); the well pattern itself must spread over
  the full failing region, so apply also updates the Visual Platemaps
  sketches to the new reality.
- **The V3 sketches are stale.** Hearts/compound sketches and the Platemap 4/5
  headers disagree with the grid; the grid is authoritative, apply rewrites
  the sketches, and verify only trusts the grid.
- **plaid geometry vs physical plate.** The model uses the full 8x12 plate
  with size_empty_edge=1, so inner coordinates map identically to physical
  wells B-G x 2-11 - no row/col arithmetic in the relocation step.
- **Random seed matters.** Gecode returns the first satisfying layout for a
  seed; different seeds give different layouts. The solve loop accepts the
  first verified seed and records it in solution.json and the QC sheet.
- **MiniZinc timeouts.** `solve --timeout` bounds each seed (default 60 s);
  raise it for bigger compound sets or denser plates.

## Verification

- `verify` passes on the output workbook (exit 0) with min same-compound
  distance >= 2 on every plate and a clean color check (0 mismatches).
- 'Platemap grid' still has 60 wells; failing/nonfailing zones and heart
  numbers unchanged; every plate keeps its 3 compounds x 8 replicates + 36
  DMSO (18 failing + 18 nonfailing).
- 'Visual Platemaps' fills match the learned legend exactly: sketch cells
  carry the fill of their current value, not the fill of the previous layout's
  occupant (a flipped well changes color with its content).
- 'Platemap QC' sheet records the before/after numbers (V3: 17 adjacent
  same-compound pairs per plate -> 0).
- The original workbook is byte-identical after the run (apply refuses
  --output equal to --input).
- Tests: `uv run --no-project --with pytest --with openpyxl pytest
  .agents/skills/plaid-platemap/tests/test_plaid_platemap.py` exercises
  extract/dzn/solve/apply/verify round trips on a small synthetic workbook
  fixture (the solve test skips automatically when minizinc is missing).

#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["openpyxl>=3.1,<4"]
# ///
"""Translate a hit-validation platemap workbook to/from a plaid model.

The experiment workbook fixes a cell-plating layout with two irregular zones
(failing vs nonfailing wells). plaid (pharmbio/plaid) cannot express irregular
zones or 36-well DMSO density, so this tool models the compound-placement
problem, lets plaid solve it, relocates any out-of-zone placements, and
retranslates the result into a workbook in the original format.

Subcommands:
  extract  workbook -> canonical layout JSON (zones, rosters, before-metrics)
  dzn      layout JSON -> plaid .dzn (compounds-only model)
  solve    run MiniZinc/Gecode per seed until a verified layout passes
  apply    write redesigned workbook (styles preserved) + QC sheet
  verify   independently re-check an output workbook against invariants

Run with: uv run --script plaid_platemap.py <subcommand> --help
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import openpyxl
from openpyxl.cell import Cell
from openpyxl.styles import Font, PatternFill
from openpyxl.styles.colors import Color

PLAID_COMMIT = "ecf4cfe6d8029dfadfceb79f5d6f2a1814d792c5"  # pharmbio/plaid pin
GRID_SHEET = "Platemap grid"
VISUAL_SHEET = "Visual Platemaps"
QC_SHEET = "Platemap QC"
ROSTER_HEADER = "Randomized order"
TREATMENT_PREFIX = "treatment_plate "
ROW_LETTERS = "ABCDEFGH"
DESCRIPTION = "Translate platemap workbooks to/from plaid constraint models."


# ---------------------------------------------------------------- well utils

def parse_well(well: str) -> tuple[str, int]:
    m = re.fullmatch(r"([A-H])(\d{2})", str(well).strip())
    if not m:
        raise ValueError(f"bad well label: {well!r}")
    return m.group(1), int(m.group(2))


def well_sort_key(well: str) -> tuple[str, int]:
    return parse_well(well)


def well_label(row: str, col: int) -> str:
    return f"{row}{col:02d}"


def king_distance(a: str, b: str) -> int:
    (ra, ca), (rb, cb) = parse_well(a), parse_well(b)
    return max(abs(ord(ra) - ord(rb)), abs(ca - cb))


def set_cell(ws, row: int, col: int, value) -> None:
    cell = ws.cell(row=row, column=col)
    if not isinstance(cell, Cell):
        raise RuntimeError(f"unexpected non-writable cell at {ws.title} r{row}c{col}")
    cell.value = value


# ---------------------------------------------------------------- layout

@dataclass
class Layout:
    wells: list[dict] = field(default_factory=list)  # pos/row/col/heart/cell_type/hf_type/treatments
    plates: list[dict] = field(default_factory=list)  # index/compounds/dose per plate
    problems: list[str] = field(default_factory=list)
    color_legend: dict | None = None  # value -> fill spec, learned from the source workbook

    @property
    def n_plates(self) -> int:
        return len(self.plates)

    def by_pos(self) -> dict[str, dict]:
        return {w["pos"]: w for w in self.wells}

    def failing(self) -> set[str]:
        return {w["pos"] for w in self.wells if w["cell_type"] == "failing"}

    def nonfailing(self) -> set[str]:
        return {w["pos"] for w in self.wells if w["cell_type"] != "failing"}

    def compound_wells(self, plate_idx: int) -> set[str]:
        return {w["pos"] for w in self.wells if w["treatments"][plate_idx] != "DMSO"}


def load_layout(path: str) -> Layout:
    payload = json.loads(Path(path).read_text())
    return Layout(wells=payload["wells"], plates=payload["plates"],
                  color_legend=payload.get("color_legend"))


def fill_spec(fill) -> dict | None:
    """Serialize a cell fill (pattern + foreground color) for JSON storage."""
    if fill is None or fill.patternType is None:
        return None
    fg = fill.fgColor
    spec: dict = {"patternType": fill.patternType, "fg": {"type": fg.type, "tint": fg.tint}}
    if fg.type == "rgb" and isinstance(fg.rgb, str):
        spec["fg"]["rgb"] = fg.rgb
    if fg.type == "theme" and isinstance(fg.theme, int):
        spec["fg"]["theme"] = fg.theme
    if fg.type == "indexed" and isinstance(fg.indexed, int):
        spec["fg"]["indexed"] = fg.indexed
    return spec


def fill_from_spec(spec: dict | None) -> PatternFill:
    """Rebuild a fill from a stored spec; empty fill for None."""
    if spec is None:
        return PatternFill(fill_type=None)
    fg = spec.get("fg", {})
    color = None
    if fg.get("type") == "theme":
        color = Color(theme=fg["theme"], tint=fg.get("tint", 0.0))
    elif fg.get("type") == "rgb":
        color = Color(rgb=fg.get("rgb", "FF000000"))
    if color is None:
        return PatternFill(fill_type=None)
    return PatternFill(patternType=spec.get("patternType", "solid"), fgColor=color)


def capture_color_legend(ws) -> tuple[dict, list[str]]:
    """Learn the value -> fill legend from the source Visual Platemaps sheet.

    Keys: 'Failing', 'Nonfailing' (from '<word> <heart>' sketch cells),
    'Cpd N' labels, and 'DMSO'. Cells without a fill do not define the legend
    (plaid-era formula cells were uncolored); conflicting fills for the same
    key are reported so validation can fail loudly.
    """
    legend: dict[str, dict] = {}
    conflicts: list[str] = []
    for row in ws.iter_rows():
        for c in row:
            v = c.value
            if not isinstance(v, str):
                continue
            s = v.strip()
            key = None
            m = re.fullmatch(r"(Failing|Nonfailing) \d+", s)
            if m:
                key = m.group(1)
            elif re.fullmatch(r"Cpd \d+", s):
                key = s
            elif s == "DMSO":
                key = "DMSO"
            if key is None:
                continue
            spec = fill_spec(c.fill)
            if spec is None:
                continue
            if key in legend and legend[key] != spec:
                conflicts.append(f"{key}: {legend[key]} vs {spec}")
            else:
                legend[key] = spec
    return legend, conflicts


def legend_fill(legend: dict | None, key: str | None) -> PatternFill:
    """Fill for a legend key; empty (cleared) fill for None or unknown keys."""
    if legend and key and key in legend:
        return fill_from_spec(legend[key])
    return PatternFill(fill_type=None)


def find_anchor(ws, label: str, col: int = 1) -> int | None:
    """Row of the first cell in a column whose value matches label (case-insensitive)."""
    for r in range(1, ws.max_row + 1):
        v = ws.cell(row=r, column=col).value
        if isinstance(v, str) and v.strip().lower() == label:
            return r
    return None


def read_grid_sheet(ws) -> tuple[list[dict], list[str], int]:
    rows = list(ws.iter_rows(values_only=True))
    header = list(rows[0])
    n_plates = sum(1 for h in header if str(h).startswith(TREATMENT_PREFIX))
    expected = ["WellRow", "WellCol", "well_position", "heart_number",
                "cell_type", "heart_failure_type"] + [f"{TREATMENT_PREFIX}{i}" for i in range(1, n_plates + 1)]
    if header[: len(expected)] != expected:
        raise ValueError(f"unexpected {GRID_SHEET} header: {header}")
    wells, problems = [], []
    for r in rows[1:]:
        if r[2] is None:
            continue
        pos = str(r[2]).strip()
        row_letter, col = parse_well(pos)
        if str(r[0]).strip() != row_letter or int(r[1]) != col:
            problems.append(f"{pos}: WellRow/WellCol disagree with well_position")
        wells.append({
            "pos": pos, "row": row_letter, "col": col,
            "heart": int(r[3]), "cell_type": str(r[4]).strip(),
            "hf_type": str(r[5]).strip(),
            "treatments": [str(r[6 + i]).strip() for i in range(n_plates)],
        })
    return wells, problems, n_plates


def read_rosters(ws, n_plates: int) -> tuple[list[dict], list[str]]:
    """Read the 'Randomized order' table: New identifier / plate / dose columns."""
    header_row = None
    for row in ws.iter_rows(values_only=True):
        if any(str(v).strip() == ROSTER_HEADER for v in row if v is not None):
            header_row = row
            break
    if header_row is None:
        raise ValueError(f"'{ROSTER_HEADER}' table not found in {VISUAL_SHEET}")
    col = {str(v).strip(): i for i, v in enumerate(header_row) if v is not None}
    need = ["New identifier", "Validation plate map #", "Dose (uM)"]
    missing = [k for k in need if k not in col]
    if missing:
        raise ValueError(f"roster table missing columns {missing}: {col}")
    id_c, plate_c, dose_c = col["New identifier"], col["Validation plate map #"], col["Dose (uM)"]
    plates: dict[int, dict] = {}
    problems = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        label = row[plate_c] if plate_c < len(row) else None
        if label is None or not str(label).strip().lower().startswith("plate"):
            continue  # not a roster row (skips headers, mini-table rows, blanks)
        m = re.search(r"(\d+)", str(label))
        if not m:
            problems.append(f"roster row {row[id_c]!r}: bad plate label {label!r}")
            continue
        plate_idx = int(m.group(1))
        ident = row[id_c] if id_c < len(row) else None
        if not isinstance(ident, str) or not ident.strip():
            problems.append(f"plate {plate_idx} roster row has no identifier: {row[:6]!r}")
            continue
        plates.setdefault(plate_idx, {"compounds": [], "dose": None})
        plates[plate_idx]["compounds"].append(ident.strip())
        plates[plate_idx]["dose"] = row[dose_c] if dose_c < len(row) else None
    ordered = []
    for i in range(1, n_plates + 1):
        if i not in plates:
            raise ValueError(f"no roster entries for plate {i}")
        ordered.append({"index": i, "compounds": plates[i]["compounds"], "dose": plates[i]["dose"]})
    return ordered, problems


def layout_metrics(layout: Layout, plate_idx: int) -> dict:
    """Per-plate cross-effect metrics for the assignments in layout."""
    by_cpd: dict[str, list[str]] = {}
    for w in layout.wells:
        t = w["treatments"][plate_idx]
        if t != "DMSO":
            by_cpd.setdefault(t, []).append(w["pos"])
    adjacent, min_dist, rows_used = [], {}, {}
    for cpd, ws in by_cpd.items():
        pairs = [(king_distance(a, b), a, b) for a, b in itertools.combinations(sorted(ws), 2)]
        adjacent += [(cpd, a, b) for d, a, b in pairs if d == 1]
        min_dist[cpd] = min((d for d, _, _ in pairs), default=None)
        rows_used[cpd] = "".join(sorted({parse_well(w)[0] for w in ws}))
    counts = {cpd: len(ws) for cpd, ws in by_cpd.items()}
    return {
        "plate": plate_idx + 1,
        "compound_counts": dict(sorted(counts.items())),
        "same_compound_adjacent_pairs": len(adjacent),
        "same_compound_adjacent_pairs_detail": sorted(adjacent),
        "min_same_compound_distance": dict(sorted(min_dist.items())),
        "rows_used_per_compound": dict(sorted(rows_used.items())),
    }


def validate_layout(layout: Layout) -> None:
    p = list(layout.problems)
    positions = [w["pos"] for w in layout.wells]
    if len(set(positions)) != len(positions):
        p.append("duplicate well_position values")
    rows = {w["row"] for w in layout.wells}
    cols = {w["col"] for w in layout.wells}
    combos = {(w["row"], w["col"]) for w in layout.wells}
    if len(combos) != len(rows) * len(cols):
        p.append(f"used region is not a full rectangle: {len(rows)} rows x {len(cols)} cols "
                 f"but {len(combos)} distinct wells; plaid models rectangular inner areas only")
    failing = layout.failing()
    for i in range(layout.n_plates):
        cw = layout.compound_wells(i)
        off_zone = sorted(cw - failing)
        if off_zone:
            p.append(f"plate {i + 1}: compounds on nonfailing wells {off_zone}")
        counts = Counter(w["treatments"][i] for w in layout.wells if w["treatments"][i] != "DMSO")
        roster = layout.plates[i]["compounds"]
        if sorted(counts) != sorted(roster):
            p.append(f"plate {i + 1}: grid compounds {sorted(counts)} != roster {sorted(roster)}")
        if len(set(counts.values())) > 1:
            p.append(f"plate {i + 1}: uneven replicate counts {dict(counts)}")
    patterns = [layout.compound_wells(i) for i in range(layout.n_plates)]
    if all(x == patterns[0] for x in patterns):
        print(f"note: all {layout.n_plates} plates share one compound well pattern "
              f"({len(patterns[0])} wells); the redesign keeps this property")
    else:
        p.append("plates use different compound well patterns; solve each plate separately")
    if p:
        raise SystemExit("layout validation failed:\n  - " + "\n  - ".join(p))


def cmd_extract(args: argparse.Namespace) -> None:
    wb = openpyxl.load_workbook(args.input, data_only=True)
    if GRID_SHEET not in wb.sheetnames or VISUAL_SHEET not in wb.sheetnames:
        raise SystemExit(f"workbook must contain '{GRID_SHEET}' and '{VISUAL_SHEET}' sheets")
    wells, problems, n_plates = read_grid_sheet(wb[GRID_SHEET])
    rosters, roster_problems = read_rosters(wb[VISUAL_SHEET], n_plates)
    color_legend, legend_conflicts = capture_color_legend(wb[VISUAL_SHEET])
    layout = Layout(wells=wells, plates=rosters,
                    problems=problems + roster_problems + legend_conflicts, color_legend=color_legend)
    validate_layout(layout)
    payload = {
        "source": str(Path(args.input).resolve()),
        "n_plates": n_plates,
        "wells": layout.wells,
        "plates": layout.plates,
        "color_legend": layout.color_legend,
        "before_metrics": [layout_metrics(layout, i) for i in range(n_plates)],
    }
    Path(args.output).write_text(json.dumps(payload, indent=2))
    m = payload["before_metrics"][0]
    print(f"extracted {len(wells)} wells, {n_plates} plates -> {args.output}")
    print(f"zone sizes: failing={len(layout.failing())} nonfailing={len(layout.nonfailing())}")
    print(f"color legend keys: {sorted(color_legend)}")
    print(f"plate 1 before: {m['same_compound_adjacent_pairs']} same-compound adjacent pairs, "
          f"min distances {m['min_same_compound_distance']}")


# ---------------------------------------------------------------- dzn

def cmd_dzn(args: argparse.Namespace) -> None:
    layout = load_layout(args.layout)
    # derive plate geometry from the used region and the requested empty edge
    rows = sorted({w["row"] for w in layout.wells})
    cols = sorted({w["col"] for w in layout.wells})
    e = args.size_empty_edge
    num_rows = ord(rows[-1]) - ord(rows[0]) + 1 + 2 * e
    num_cols = cols[-1] - cols[0] + 1 + 2 * e
    inner_rows = ord(rows[-1]) - ord(rows[0]) + 1
    inner_cols = cols[-1] - cols[0] + 1
    if inner_rows % 2 != 0 or inner_cols % 2 != 0:
        raise SystemExit(f"plaid requires even inner dimensions; used region is "
                         f"{inner_rows} x {inner_cols}; choose another --size-empty-edge "
                         f"or adjust the layout region")
    reps = Counter()
    for i in range(layout.n_plates):
        for w in layout.wells:
            if w["treatments"][i] != "DMSO":
                reps[w["treatments"][i]] += 1
    per_plate = [len(layout.plates[i]["compounds"]) for i in range(layout.n_plates)]
    if len(set(per_plate)) != 1:
        raise SystemExit(f"unequal compounds per plate {per_plate}; single-pattern dzn unsupported")
    n_cpd = per_plate[0]
    if len(set(reps.values())) != 1:
        raise SystemExit(f"unequal replicate counts across compounds: {dict(reps)}")
    seen: dict[str, set[int]] = {}
    for i in range(layout.n_plates):
        for c in layout.plates[i]["compounds"]:
            seen.setdefault(c, set()).add(i)
    multi = {c: sorted(ps) for c, ps in seen.items() if len(ps) > 1}
    if multi:
        raise SystemExit(f"compounds appearing on multiple plates are unsupported by the "
                         f"single-pattern model: {multi}")
    reps_per = next(iter(reps.values()))
    dose = layout.plates[0]["dose"]
    conc = f"{dose} uM" if dose is not None else "1x"
    names = ", ".join(f'"Cpd {i}"' for i in range(1, n_cpd + 1))
    conc_names = " ".join(f'| "{conc}"' for _ in range(n_cpd))
    text = f"""%% Generated by plaid_platemap.py dzn - compound placement on the used plate area.
%% Physical plate derived from the used region {rows[0]}{cols[0]:02d}-{rows[-1]}{cols[-1]:02d}
%% plus a {e}-well empty edge on each side ({num_rows} x {num_cols} total).
%% Compounds only: the DMSO controls are too dense for plaid's same-kind
%% separation and are assigned as the complement of the compound wells by this
%% tool.
num_rows = {num_rows};
num_cols = {num_cols};

horizontal_cell_lines = 1;
vertical_cell_lines = 1;
allow_empty_wells = true;
size_empty_edge = {args.size_empty_edge};

concentrations_on_different_rows = true;
concentrations_on_different_columns = true;
replicates_on_different_plates = false;
replicates_on_same_plate = true;

%%% Compounds %%%
compounds = {n_cpd};
compound_names = [{names}];
compound_replicates = [{", ".join(str(reps_per) for _ in range(n_cpd))}];
compound_concentrations = [{", ".join("1" for _ in range(n_cpd))}];
compound_concentration_names = [{conc_names} |];
compound_concentration_indicators = [""];

%%% Combinations %%%
combinations = 0;
combination_concentrations = 0;
combination_names = [];
combination_concentration_names = [];

%%% Controls %%%
num_controls = 0;
control_concentrations = [];
control_replicates = [];
control_names = [];
control_concentration_names = [];
"""
    Path(args.output).write_text(text)
    print(f"wrote {args.output}: {n_cpd} compounds x {reps_per} replicates, concentration {conc!r}")


# ---------------------------------------------------------------- solve

def run_plaid(mzn: Path, dzn: Path, seed: int, timeout: int) -> dict[str, str]:
    cmd = ["minizinc", "--solver", "gecode", "-r", str(seed),
           "--time-limit", str(timeout * 1000), str(mzn), str(dzn)]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True,
                            timeout=timeout + 5, check=True)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"seed {seed}: minizinc timed out after {timeout + 5}s")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"seed {seed}: minizinc failed: {e.stderr[-500:]}")
    assign = {}
    for line in out.stdout.splitlines():
        m = re.match(r"^plate_1,([A-H])(\d{2}),(.+?),", line.strip())
        if m:
            assign[well_label(m.group(1), int(m.group(2)))] = m.group(3)
    if not assign:
        raise RuntimeError(f"seed {seed}: no layout rows in minizinc output")
    return assign


def relocate(assign: dict[str, str], layout: Layout, min_dist: int) -> dict[str, str]:
    """Move compound wells that fall on out-of-zone wells onto free in-zone wells."""
    failing = layout.failing()
    placed = dict(assign)
    displaced = sorted(w for w in placed if w not in failing)
    free = sorted(failing - set(placed))
    for w in displaced:
        cpd = placed.pop(w)
        same = [x for x, c in placed.items() if c == cpd]
        cands = [f for f in free if all(king_distance(f, s) >= min_dist for s in same)]
        if not cands:
            raise RuntimeError(f"no in-zone relocation candidate for {w} ({cpd})")

        def score(f: str) -> tuple:
            row_count = Counter(parse_well(x)[0] for x in placed)
            return (0 if parse_well(f)[0] == parse_well(w)[0] else 1,
                    -min(king_distance(f, s) for s in same),
                    row_count.get(parse_well(f)[0], 0),
                    well_sort_key(f))

        best = min(cands, key=score)
        placed[best] = cpd
        free.remove(best)
    return placed


def check_pattern(assign: dict[str, str], layout: Layout, n_cpd: int, reps: int,
                  min_dist: int) -> tuple[list[str], dict]:
    problems, by_cpd = [], {}
    for w, c in assign.items():
        by_cpd.setdefault(c, []).append(w)
    if sorted(by_cpd) != [f"Cpd {i}" for i in range(1, n_cpd + 1)]:
        problems.append(f"compound labels {sorted(by_cpd)} != expected {n_cpd} compounds")
    for c, ws in sorted(by_cpd.items()):
        if len(ws) != reps:
            problems.append(f"{c}: {len(ws)} wells, expected {reps}")
    off_zone = sorted(set(assign) - layout.failing())
    if off_zone:
        problems.append(f"wells outside failing zone: {off_zone}")
    for c, ws in sorted(by_cpd.items()):
        for a, b in itertools.combinations(sorted(ws), 2):
            if king_distance(a, b) < min_dist:
                problems.append(f"{c}: {a}/{b} closer than {min_dist} (king)")
    metrics = {
        "min_same_compound_distance": {
            c: min(king_distance(a, b) for a, b in itertools.combinations(sorted(ws), 2))
            for c, ws in sorted(by_cpd.items())},
        "rows_used_per_compound": {
            c: "".join(sorted({parse_well(w)[0] for w in ws})) for c, ws in sorted(by_cpd.items())},
        "compound_wells_per_row": dict(sorted(Counter(parse_well(w)[0] for w in assign).items())),
    }
    return problems, metrics


def cmd_solve(args: argparse.Namespace) -> None:
    layout = load_layout(args.layout)
    n_cpd = len(layout.plates[0]["compounds"])
    reps = len(layout.compound_wells(0)) // n_cpd
    seeds = list(range(args.first_seed, args.first_seed + args.max_seeds))
    failures = []
    for seed in seeds:
        try:
            assign = run_plaid(Path(args.mzn), Path(args.dzn), seed, args.timeout)
            placed = relocate(assign, layout, args.min_dist)
        except RuntimeError as e:
            failures.append(f"seed {seed}: {e}")
            continue
        problems, metrics = check_pattern(placed, layout, n_cpd, reps, args.min_dist)
        if problems:
            failures.append(f"seed {seed}: " + "; ".join(problems[:4]))
            continue
        n_displaced = sum(1 for w in assign if w not in layout.failing())
        solution = {
            "seed": seed,
            "min_dist": args.min_dist,
            "displaced_wells_relocated": n_displaced,
            "plaid_commit": PLAID_COMMIT,
            "mzn": str(Path(args.mzn).resolve()),
            "dzn": str(Path(args.dzn).resolve()),
            "n_compounds": n_cpd,
            "replicates": reps,
            "pattern": placed,
            "metrics": metrics,
        }
        Path(args.output).write_text(json.dumps(solution, indent=2))
        print(f"seed {seed}: PASS (relocated {n_displaced} out-of-zone wells)")
        print(f"  min same-compound distance: {metrics['min_same_compound_distance']}")
        print(f"  compound wells per row: {metrics['compound_wells_per_row']}")
        print(f"solution -> {args.output}")
        return
    raise SystemExit(f"no seed passed out of {len(seeds)} tried:\n  - " + "\n  - ".join(failures[:10]))


# ---------------------------------------------------------------- apply

def pattern_treatments(layout: Layout, pattern: dict[str, str]) -> list[dict]:
    """Materialize per-well treatments for every plate from a well->'Cpd N' pattern."""
    new_wells = []
    for w in layout.wells:
        cpd = pattern.get(w["pos"])
        treatments = ["DMSO" if cpd is None
                      else layout.plates[p]["compounds"][int(cpd.split()[1]) - 1]
                      for p in range(layout.n_plates)]
        new_wells.append({**w, "treatments": treatments})
    return new_wells


def cmd_apply(args: argparse.Namespace) -> None:
    src, dst = Path(args.input).resolve(), Path(args.output).resolve()
    if src == dst:
        raise SystemExit("refusing to overwrite the input workbook; choose a different --output")
    layout = load_layout(args.layout)
    solution = json.loads(Path(args.solution).read_text())
    pattern: dict[str, str] = solution["pattern"]
    legend = layout.color_legend
    wb = openpyxl.load_workbook(args.input)

    def set_value_fill(ws, row: int, col: int, value, fill_key: str | None) -> None:
        set_cell(ws, row, col, value)
        cell = ws.cell(row=row, column=col)
        if not isinstance(cell, Cell):
            raise RuntimeError(f"unexpected non-writable cell at {ws.title} r{row}c{col}")
        cell.fill = legend_fill(legend, fill_key)

    # 1. Platemap grid: new per-plate treatments (grid carries no fill scheme
    # in V3, so no recoloring here; the Visual Platemaps sheet holds the colors)
    ws = wb[GRID_SHEET]
    for row_cells in ws.iter_rows(min_row=2, min_col=1, max_col=6 + layout.n_plates):
        pos = row_cells[2].value
        if pos is None:
            continue
        pos = str(pos).strip()
        for plate_idx in range(layout.n_plates):
            cpd = pattern.get(pos)
            value = "DMSO" if cpd is None else layout.plates[plate_idx]["compounds"][int(cpd.split()[1]) - 1]
            set_cell(ws, row_cells[0].row or 0, 7 + plate_idx, value)

    # 2. Visual Platemaps: hearts + compounds sketches now mirror the grid,
    # with fills recolored from the learned legend so flipped wells match
    ws = wb[VISUAL_SHEET]
    by_pos = layout.by_pos()
    rows_in_region = sorted({w["row"] for w in layout.wells})
    cols_in_region = sorted({w["col"] for w in layout.wells})

    hearts_anchor = find_anchor(ws, "hearts")
    if hearts_anchor is not None:
        for row_letter in rows_in_region:
            r = hearts_anchor + 1 + (ord(row_letter) - ord("A"))
            for c in cols_in_region:
                w = by_pos[well_label(row_letter, c)]
                if w["cell_type"] == "failing":
                    label, key = f"Failing {w['heart']}", "Failing"
                else:
                    label, key = f"Nonfailing {w['heart']}", "Nonfailing"
                set_value_fill(ws, r, c + 1, label, key)
    compounds_anchor = find_anchor(ws, "compounds")
    if compounds_anchor is not None:
        for row_letter in rows_in_region:
            r = compounds_anchor + 1 + (ord(row_letter) - ord("A"))
            for c in cols_in_region:
                cpd = pattern.get(well_label(row_letter, c))
                set_value_fill(ws, r, c + 1, cpd if cpd is not None else "DMSO", cpd or "DMSO")
    # per-well block: located by the 'Initial list' header in column C; rows
    # below it list well index 1..N in raster order. C holds the "Initial list"
    # (sequential grouping: reps wells per compound in raster order), D the
    # "Randomized" assignment from the new pattern, E.. per-plate K-IDs as
    # values (V3 kept formulas here; values survive programmatic re-reads).
    # Fix the stale plate headers (V3 mislabels plates 4/5) when present.
    positions = sorted(by_pos, key=well_sort_key)
    n_cpd = len(layout.plates[0]["compounds"])
    reps = sum(1 for pos in positions if pos in pattern) // n_cpd if n_cpd else 0
    block_header = None
    for r in range(1, ws.max_row + 1):
        v = ws.cell(row=r, column=3).value
        if isinstance(v, str) and v.strip().lower() == "initial list":
            block_header = r
            break
    if block_header is not None:
        for i in range(1, layout.n_plates + 1):
            set_cell(ws, block_header, 4 + i, f"Platemap {i}")
        initial: dict[str, str] = {}
        for k, pos in enumerate([p for p in positions if p in pattern], start=1):
            initial[pos] = f"Cpd {(k - 1) // reps + 1}"
        for idx, pos in enumerate(positions, start=1):
            r = block_header + idx
            cpd = pattern.get(pos)
            set_cell(ws, r, 2, idx)
            set_value_fill(ws, r, 3, initial.get(pos), initial.get(pos))
            set_value_fill(ws, r, 4, cpd, cpd)
            for plate_idx in range(layout.n_plates):
                value = "DMSO" if cpd is None else layout.plates[plate_idx]["compounds"][int(cpd.split()[1]) - 1]
                set_value_fill(ws, r, 5 + plate_idx, value, "DMSO" if value == "DMSO" else None)

    # 3. QC sheet with before/after metrics
    if QC_SHEET in wb.sheetnames:
        del wb[QC_SHEET]
    qc = wb.create_sheet(QC_SHEET)
    new_layout = Layout(wells=pattern_treatments(layout, pattern), plates=layout.plates)
    before = layout_metrics(layout, 0)
    after = layout_metrics(new_layout, 0)
    qc_rows = [
        ["Platemap QC - plaid redesign"],
        [f"Generated {date.today().isoformat()} from {src.name}"],
        [f"Model: pharmbio/plaid plate-design.mzn @ {solution.get('plaid_commit', PLAID_COMMIT)[:7]}, "
         f"solver Gecode via MiniZinc, seed {solution['seed']}"],
        [f"Compound wells relocated from out-of-zone plaid positions: {solution['displaced_wells_relocated']}"],
        [f"Metrics identical for all {layout.n_plates} plates: one shared well pattern, relabeled per plate."],
        [],
        ["Metric", "Before", "After"],
        ["Same-compound adjacent pairs (king distance 1), per plate",
         before["same_compound_adjacent_pairs"], after["same_compound_adjacent_pairs"]],
        ["Minimum same-compound distance (king), plate 1",
         min(before["min_same_compound_distance"].values()),
         min(after["min_same_compound_distance"].values())],
        ["Rows used per compound, plate 1",
         str(before["rows_used_per_compound"]), str(after["rows_used_per_compound"])],
        ["Compound wells per row",
         str(dict(sorted(Counter(parse_well(w)[0] for w in pattern).items()))), ""],
        [],
        ["Design notes"],
        ["Compounds are spread across the full failing-heart region; DMSO fills the remaining "
         "failing wells and all nonfailing wells (36 DMSO per plate, unchanged from V3)."],
        ["Same-compound wells are at least 2 king-moves apart (one well between in every direction), "
         "enforced by plaid's 2x2-block constraint plus post-solve relocation and verification."],
        ["Corrected stale 'Visual Platemaps' content to match 'Platemap grid': plate headers 4/5 "
         "and the hearts/compounds sketches (the V3 sketches were stylized and disagreed with the grid)."],
        ["Per-well block formulas (E41:I64) were flattened to values matching the new layout."],
    ]
    for r, row in enumerate(qc_rows, start=1):
        for c, v in enumerate(row, start=1):
            cell = qc.cell(row=r, column=c, value=v)
            if r in (1, 7, 11):
                cell.font = Font(bold=True)
    qc.column_dimensions["A"].width = 72
    wb.save(dst)
    print(f"wrote {dst}")
    print(f"QC: adjacent pairs {before['same_compound_adjacent_pairs']} -> "
          f"{after['same_compound_adjacent_pairs']}; min distance "
          f"{min(before['min_same_compound_distance'].values())} -> "
          f"{min(after['min_same_compound_distance'].values())}")


# ---------------------------------------------------------------- verify

def check_colors(ws, check: Layout, layout: Layout) -> list[str]:
    """Verify the Visual Platemaps sketch fills match the learned legend.

    Checks the hearts sketch and the compounds sketch against the zones and
    the plate-1 pattern. Returns a list of mismatch descriptions.
    """
    problems = []
    legend = layout.color_legend or {}
    by_pos = check.by_pos()
    rows_in_region = sorted({w["row"] for w in check.wells})
    cols_in_region = sorted({w["col"] for w in check.wells})

    hearts_anchor = find_anchor(ws, "hearts")
    if hearts_anchor is not None and legend:
        for row_letter in rows_in_region:
            r = hearts_anchor + 1 + (ord(row_letter) - ord("A"))
            for c in cols_in_region:
                pos = well_label(row_letter, c)
                expected_zone = "Failing" if by_pos[pos]["cell_type"] == "failing" else "Nonfailing"
                cell = ws.cell(row=r, column=c + 1)
                if fill_spec(cell.fill) != legend.get(expected_zone):
                    problems.append(f"hearts sketch {pos} ({cell.coordinate}): fill does not "
                                     f"match {expected_zone} legend")
    compounds_anchor = find_anchor(ws, "compounds")
    if compounds_anchor is not None and legend:
        # map well -> Cpd N using the plate-1 treatments of the checked layout
        cpd_of_pos = {}
        for w in check.wells:
            t = w["treatments"][0]
            if t != "DMSO":
                try:
                    cpd_of_pos[w["pos"]] = f"Cpd {layout.plates[0]['compounds'].index(t) + 1}"
                except ValueError:
                    pass
        for row_letter in rows_in_region:
            r = compounds_anchor + 1 + (ord(row_letter) - ord("A"))
            for c in cols_in_region:
                pos = well_label(row_letter, c)
                expected_key = cpd_of_pos.get(pos, "DMSO")
                cell = ws.cell(row=r, column=c + 1)
                if fill_spec(cell.fill) != legend.get(expected_key):
                    problems.append(f"compounds sketch {pos} ({cell.coordinate}): fill does not "
                                    f"match {expected_key} legend")
    return problems


def cmd_verify(args: argparse.Namespace) -> None:
    layout = load_layout(args.layout)
    n_cpd = len(layout.plates[0]["compounds"])
    reps = len(layout.compound_wells(0)) // n_cpd
    wb = openpyxl.load_workbook(args.input, data_only=True)
    if GRID_SHEET not in wb.sheetnames:
        raise SystemExit(f"no {GRID_SHEET} sheet in {args.input}")
    wells, problems, n_plates = read_grid_sheet(wb[GRID_SHEET])
    check = Layout(wells=wells, plates=layout.plates, problems=problems)
    failures = []
    if {w["pos"] for w in check.wells} != {w["pos"] for w in layout.wells}:
        failures.append("well set differs from extracted layout")
    if check.failing() != layout.failing():
        failures.append("failing zone changed")
    patterns = []
    for i in range(n_plates):
        m = layout_metrics(check, i)
        print(f"plate {m['plate']}: adjacent_pairs={m['same_compound_adjacent_pairs']} "
              f"min_dist={m['min_same_compound_distance']} counts={m['compound_counts']}")
        counts = m["compound_counts"]
        if sorted(counts) != sorted(layout.plates[i]["compounds"]):
            failures.append(f"plate {i + 1}: compounds {sorted(counts)} != roster {sorted(layout.plates[i]['compounds'])}")
        if counts and any(v != reps for v in counts.values()):
            failures.append(f"plate {i + 1}: replicate counts {counts} != {reps}")
        off = sorted(check.compound_wells(i) - check.failing())
        if off:
            failures.append(f"plate {i + 1}: compounds on nonfailing wells {off}")
        if m["same_compound_adjacent_pairs"]:
            failures.append(f"plate {i + 1}: {m['same_compound_adjacent_pairs']} same-compound adjacent pairs")
        if m["min_same_compound_distance"] and min(m["min_same_compound_distance"].values()) < args.min_dist:
            failures.append(f"plate {i + 1}: min same-compound distance below {args.min_dist}")
        patterns.append(check.compound_wells(i))
    if not all(p == patterns[0] for p in patterns):
        failures.append("plates do not share one compound well pattern")
    # color coding: every sketch cell's fill must match the learned legend
    if layout.color_legend:
        wsv = openpyxl.load_workbook(args.input)[VISUAL_SHEET]
        color_fail = check_colors(wsv, check, layout)
        failures += color_fail
        print(f"color check: {len(color_fail)} mismatches")
    if args.reference:
        ref = load_layout(args.reference)
        for i in range(n_plates):
            b = layout_metrics(ref, i)
            print(f"plate {i + 1} before: adjacent_pairs={b['same_compound_adjacent_pairs']} "
                  f"min_dist={b['min_same_compound_distance']}")
    if args.output:
        Path(args.output).write_text(json.dumps({"failures": failures}, indent=2))
    if failures:
        raise SystemExit("VERIFY FAILED:\n  - " + "\n  - ".join(failures))
    print(f"VERIFY OK: {n_plates} plates, all invariants hold "
          f"(min same-compound distance >= {args.min_dist})")


# ---------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("extract", help="read workbook -> layout JSON")
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("dzn", help="layout JSON -> plaid .dzn (compounds-only model)")
    p.add_argument("--layout", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--size-empty-edge", type=int, default=1)
    p.set_defaults(func=cmd_dzn)

    default_mzn = Path(__file__).resolve().parent.parent / "assets" / "plate-design.mzn"
    p = sub.add_parser("solve", help="run MiniZinc per seed until a verified layout passes")
    p.add_argument("--mzn", default=str(default_mzn))
    p.add_argument("--dzn", required=True)
    p.add_argument("--layout", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--min-dist", type=int, default=2,
                   help="minimum king distance between same-compound wells (default 2)")
    p.add_argument("--first-seed", type=int, default=1)
    p.add_argument("--max-seeds", type=int, default=25)
    p.add_argument("--timeout", type=int, default=60, help="per-seed minizinc timeout in seconds")
    p.set_defaults(func=cmd_solve)

    p = sub.add_parser("apply", help="write redesigned workbook from a solution")
    p.add_argument("--input", required=True, help="original workbook (kept untouched)")
    p.add_argument("--output", required=True)
    p.add_argument("--layout", required=True)
    p.add_argument("--solution", required=True)
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("verify", help="independently re-check an output workbook")
    p.add_argument("--input", required=True)
    p.add_argument("--layout", required=True)
    p.add_argument("--reference", help="layout JSON of the original, for a before/after report")
    p.add_argument("--output", help="optional JSON report path")
    p.add_argument("--min-dist", type=int, default=2)
    p.set_defaults(func=cmd_verify)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
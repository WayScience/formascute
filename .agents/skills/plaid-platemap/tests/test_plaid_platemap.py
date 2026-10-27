# /// script
# requires-python = ">=3.11"
# dependencies = ["openpyxl>=3.1,<4", "pytest>=8,<9"]
# ///
"""Round-trip tests for plaid_platemap.py on a synthetic mini workbook.

Builds an in-memory workbook with the V3 structure (grid + visual sheets, two
zones, two plates) and exercises extract/dzn/apply/verify and the pure-Python
helpers (relocate/check_pattern). The minizinc solve step is covered by an
end-to-end test that skips when minizinc or the vendored assets are missing.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import openpyxl
import pytest

SKILL = Path(__file__).resolve().parents[1]
SCRIPT = SKILL / "scripts" / "plaid_platemap.py"
ASSETS = SKILL / "assets"

spec = importlib.util.spec_from_file_location("plaid_platemap", SCRIPT)
assert spec is not None and spec.loader is not None
pp = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = pp  # dataclass introspection requires registration
spec.loader.exec_module(pp)

# Synthetic experiment: rows B-G x cols 2-5, 2 compounds x 2 reps per plate,
# 2 plates. Failing zone: rows D,E fully plus B02,B03 (mirrors the two-zone
# structure of the real workbook at a small scale).
ROWS = "BCDEFG"
COLS = [2, 3, 4, 5]
FAILING = {f"D{c:02d}" for c in COLS} | {f"E{c:02d}" for c in COLS} | {"B02", "B03"}
ROSTER = {1: ["C-100", "C-200"], 2: ["C-300", "C-400"]}


def build_workbook(path: Path) -> None:
    wb = openpyxl.Workbook()
    grid = wb.active
    grid.title = pp.GRID_SHEET
    grid.append(["WellRow", "WellCol", "well_position", "heart_number", "cell_type",
                 "heart_failure_type", "treatment_plate 1", "treatment_plate 2"])
    # V3-like bad pattern: same-compound wells adjacent, packed into rows D-E
    bad = {"D02": 0, "D03": 0, "E04": 1, "E05": 1}
    for row_letter in ROWS:
        for col in COLS:
            pos = f"{row_letter}{col:02d}"
            failing = pos in FAILING
            t = bad.get(pos) if failing else None
            grid.append([row_letter, col, pos, 25 if failing else 7,
                         "failing" if failing else "nonfailing",
                         "dilated_cardiomyopathy" if failing else "NA",
                         "DMSO" if t is None else ROSTER[1][t],
                         "DMSO" if t is None else ROSTER[2][t]])
    vis = wb.create_sheet(pp.VISUAL_SHEET)
    # roster table at row 22, cols N-S (14-19), same shape as the real workbook
    vis.cell(row=22, column=14, value="Randomized order")
    vis.cell(row=22, column=15, value="UCD")
    vis.cell(row=22, column=16, value="New identifier")
    vis.cell(row=22, column=17, value="Validation plate map #")
    vis.cell(row=22, column=19, value="Dose (uM)")
    order = 0
    for plate, cpds in sorted(ROSTER.items()):
        for c in cpds:
            order += 1
            vis.cell(row=22 + order, column=14, value=order)
            vis.cell(row=22 + order, column=16, value=c)
            vis.cell(row=22 + order, column=17, value=f"Plate {plate}")
            vis.cell(row=22 + order, column=19, value=10)
    # hearts + compounds sketches with a V3-like color legend
    from openpyxl.styles import PatternFill
    fills = {
        "Failing": PatternFill("solid", fgColor="FFDD8368"),
        "Nonfailing": PatternFill("solid", fgColor="FF92D050"),
        "Cpd 1": PatternFill("solid", fgColor="FFFFC000"),
        "Cpd 2": PatternFill("solid", fgColor="FF00B0F0"),
        "DMSO": PatternFill("solid", fgColor="FFBFBFBF"),
    }
    vis.cell(row=1, column=1, value="Hearts")
    vis.cell(row=11, column=1, value="Compounds")
    vis.cell(row=22, column=3, value="Initial list")
    vis.cell(row=22, column=4, value="Randomized")
    for col in COLS:
        vis.cell(row=1, column=col + 1, value=col)
        vis.cell(row=11, column=col + 1, value=col)
    for row_letter in ROWS:
        r = 1 + ord(row_letter) - ord("A") + 1
        for col in COLS:
            pos = f"{row_letter}{col:02d}"
            failing = pos in FAILING
            cell = vis.cell(row=r, column=col + 1,
                            value=f"Failing 25" if failing else "Nonfailing 7")
            cell.fill = fills["Failing" if failing else "Nonfailing"]
        r2 = 11 + ord(row_letter) - ord("A") + 1
        for col in COLS:
            pos = f"{row_letter}{col:02d}"
            t = bad.get(pos) if pos in FAILING else None
            label = f"Cpd {t + 1}" if t is not None else "DMSO"
            cell = vis.cell(row=r2, column=col + 1, value=label)
            cell.fill = fills[label]
    # per-well block rows 23+: raster well index 1..N with C/D labels and E.. plate values
    positions = sorted([f"{r}{c:02d}" for r in ROWS for c in COLS],
                       key=lambda w: (w[0], int(w[1:])))
    for idx, pos in enumerate(positions, start=1):
        r = 22 + idx
        vis.cell(row=r, column=2, value=idx)
        t = bad.get(pos) if pos in FAILING else None
        if t is not None:
            vis.cell(row=r, column=3, value=f"Cpd {t + 1}")
            vis.cell(row=r, column=4, value=f"Cpd {t + 1}")
        for plate, cpds in sorted(ROSTER.items()):
            v = "DMSO" if t is None else cpds[t]
            c = vis.cell(row=r, column=4 + plate, value=v)
            if v == "DMSO":
                c.fill = fills["DMSO"]
    wb.save(path)


@pytest.fixture()
def workbook(tmp_path: Path) -> Path:
    path = tmp_path / "mini.xlsx"
    build_workbook(path)
    return path


def run_cli(*argv: str, expect_ok: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run([sys.executable, str(SCRIPT), *argv],
                          capture_output=True, text=True, timeout=300)
    if expect_ok and proc.returncode != 0:
        raise AssertionError(f"command failed: {argv}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")
    return proc


def test_well_helpers() -> None:
    assert pp.parse_well("C10") == ("C", 10)
    assert pp.well_label("C", 10) == "C10"
    assert pp.king_distance("D02", "E03") == 1
    assert pp.king_distance("D02", "E04") == 2
    assert pp.well_sort_key("B11") < pp.well_sort_key("C02")
    with pytest.raises(ValueError):
        pp.parse_well("C1")
    with pytest.raises(ValueError):
        pp.parse_well("I01")


def test_extract_reports_v3_style_problem(workbook: Path, tmp_path: Path) -> None:
    layout_path = tmp_path / "layout.json"
    run_cli("extract", "--input", str(workbook), "--output", str(layout_path))
    payload = json.loads(layout_path.read_text())
    assert payload["n_plates"] == 2
    assert len(payload["wells"]) == len(ROWS) * len(COLS)
    before = payload["before_metrics"][0]
    assert before["same_compound_adjacent_pairs"] > 0
    assert min(before["min_same_compound_distance"].values()) == 1
    assert [p["compounds"] for p in payload["plates"]] == [ROSTER[1], ROSTER[2]]


def test_dzn_matches_roster(workbook: Path, tmp_path: Path) -> None:
    layout_path = tmp_path / "layout.json"
    dzn_path = tmp_path / "plate.dzn"
    run_cli("extract", "--input", str(workbook), "--output", str(layout_path))
    run_cli("dzn", "--layout", str(layout_path), "--output", str(dzn_path))
    text = dzn_path.read_text()
    assert "compounds = 2;" in text
    assert "compound_replicates = [2, 2];" in text
    assert '"10 uM"' in text
    # mini fixture region B-G x 2-5 with edge 1 -> 8 x 6 plate
    assert "num_rows = 8;" in text
    assert "num_cols = 6;" in text
    assert "size_empty_edge = 1;" in text


def make_layout():
    return pp.Layout(
        wells=[{"pos": f"{r}{c:02d}", "row": r, "col": c,
                "heart": 25 if f"{r}{c:02d}" in FAILING else 7,
                "cell_type": "failing" if f"{r}{c:02d}" in FAILING else "nonfailing",
                "hf_type": "NA", "treatments": ["DMSO", "DMSO"]}
               for r in ROWS for c in COLS],
        plates=[{"index": 1, "compounds": ROSTER[1], "dose": 10},
                {"index": 2, "compounds": ROSTER[2], "dose": 10}],
    )


def test_relocate_and_check_pattern() -> None:
    layout = make_layout()
    # plaid-style assignment: two wells land on nonfailing wells and must be relocated
    assign = {"D02": "Cpd 1", "C04": "Cpd 2", "B11": "Cpd 1", "G04": "Cpd 2"}
    placed = pp.relocate(assign, layout, min_dist=2)
    assert "B11" not in placed and "G04" not in placed
    assert set(placed) <= layout.failing()
    problems, metrics = pp.check_pattern(placed, layout, n_cpd=2, reps=2, min_dist=2)
    assert problems == []
    assert min(metrics["min_same_compound_distance"].values()) >= 2


def test_check_pattern_flags_violations() -> None:
    layout = make_layout()
    bad = {"D02": "Cpd 1", "D03": "Cpd 1", "E02": "Cpd 2", "E03": "Cpd 2"}
    problems, _ = pp.check_pattern(bad, layout, n_cpd=2, reps=2, min_dist=2)
    assert any("closer than 2" in p for p in problems)


def test_apply_and_verify_roundtrip(workbook: Path, tmp_path: Path) -> None:
    layout_path = tmp_path / "layout.json"
    solution_path = tmp_path / "solution.json"
    out_path = tmp_path / "mini-plaid.xlsx"
    run_cli("extract", "--input", str(workbook), "--output", str(layout_path))
    solution = {
        "seed": 1, "min_dist": 2, "displaced_wells_relocated": 0,
        "plaid_commit": pp.PLAID_COMMIT, "n_compounds": 2, "replicates": 2,
        "pattern": {"B02": "Cpd 1", "D04": "Cpd 1", "E02": "Cpd 2", "E05": "Cpd 2"},
        "metrics": {},
    }
    solution_path.write_text(json.dumps(solution))
    run_cli("apply", "--input", str(workbook), "--output", str(out_path),
            "--layout", str(layout_path), "--solution", str(solution_path))
    proc = run_cli("verify", "--input", str(out_path), "--layout", str(layout_path),
                   "--reference", str(layout_path))
    assert "VERIFY OK" in proc.stdout
    # grid treatments relabeled per plate from the same pattern
    wb = openpyxl.load_workbook(out_path, data_only=True)
    ws = wb[pp.GRID_SHEET]
    rows = {r[2]: r for r in ws.iter_rows(values_only=True) if r[2]}
    assert rows["B02"][6] == "C-100" and rows["B02"][7] == "C-300"
    assert rows["E02"][6] == "C-200" and rows["E02"][7] == "C-400"
    assert rows["D04"][6] == "C-100" and rows["E05"][7] == "C-400"
    assert rows["B04"][6] == "DMSO"  # nonfailing stays DMSO
    # QC sheet exists with before/after
    assert pp.QC_SHEET in wb.sheetnames
    # original untouched
    proc = run_cli("verify", "--input", str(workbook), "--layout", str(layout_path),
                   expect_ok=False)
    assert proc.returncode != 0  # original still has adjacent pairs


def test_verify_catches_wrong_colors(workbook: Path, tmp_path: Path) -> None:
    layout_path = tmp_path / "layout.json"
    solution_path = tmp_path / "solution.json"
    out_path = tmp_path / "mini-plaid.xlsx"
    run_cli("extract", "--input", str(workbook), "--output", str(layout_path))
    solution = {
        "seed": 1, "min_dist": 2, "displaced_wells_relocated": 0,
        "plaid_commit": pp.PLAID_COMMIT, "n_compounds": 2, "replicates": 2,
        "pattern": {"B02": "Cpd 1", "D04": "Cpd 1", "E02": "Cpd 2", "E05": "Cpd 2"},
        "metrics": {},
    }
    solution_path.write_text(json.dumps(solution))
    run_cli("apply", "--input", str(workbook), "--output", str(out_path),
            "--layout", str(layout_path), "--solution", str(solution_path))
    # find a flipped cell: a sketch cell holding Cpd 2 whose old fill was DMSO
    wb = openpyxl.load_workbook(out_path)
    vis = wb[pp.VISUAL_SHEET]
    anchor = pp.find_anchor(vis, "compounds")
    assert anchor is not None
    flipped = None
    for row_letter in "BCDEFG":
        for col in COLS:
            cell = vis.cell(row=anchor + 1 + ord(row_letter) - ord("A"), column=col + 1)
            if cell.value == "Cpd 2":
                flipped = cell
                break
        if flipped is not None:
            break
    assert flipped is not None
    # give it the DMSO fill (wrong color) and expect verify to fail
    dmso_cell = next(c for r in vis.iter_rows() for c in r if c.value == "DMSO")
    flipped.fill = pp.fill_from_spec(pp.fill_spec(dmso_cell.fill))
    wb.save(out_path)
    proc = run_cli("verify", "--input", str(out_path), "--layout", str(layout_path),
                   expect_ok=False)
    assert proc.returncode != 0
    assert "color check: 1 mismatches" in proc.stdout
    assert "does not match Cpd 2 legend" in proc.stderr


@pytest.mark.skipif(shutil.which("minizinc") is None or not (ASSETS / "plate-design.mzn").exists(),
                    reason="minizinc or vendored plaid assets not available")
def test_solve_end_to_end(workbook: Path, tmp_path: Path) -> None:
    layout_path = tmp_path / "layout.json"
    dzn_path = tmp_path / "plate.dzn"
    solution_path = tmp_path / "solution.json"
    out_path = tmp_path / "mini-plaid.xlsx"
    run_cli("extract", "--input", str(workbook), "--output", str(layout_path))
    run_cli("dzn", "--layout", str(layout_path), "--output", str(dzn_path))
    run_cli("solve", "--mzn", str(ASSETS / "plate-design.mzn"), "--dzn", str(dzn_path),
            "--layout", str(layout_path), "--output", str(solution_path), "--timeout", "30")
    run_cli("apply", "--input", str(workbook), "--output", str(out_path),
            "--layout", str(layout_path), "--solution", str(solution_path))
    proc = run_cli("verify", "--input", str(out_path), "--layout", str(layout_path))
    assert "VERIFY OK" in proc.stdout
    # original workbook must be untouched by apply
    before = workbook.read_bytes()
    run_cli("apply", "--input", str(workbook), "--output", str(out_path),
            "--layout", str(layout_path), "--solution", str(solution_path))
    assert workbook.read_bytes() == before
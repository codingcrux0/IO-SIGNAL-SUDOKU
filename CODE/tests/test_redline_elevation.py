from __future__ import annotations

import io

import openpyxl
import pytest

from io_sudoku.core.allocio import allocation_bytes, read_allocation
from io_sudoku.core.elevation import IO_COLOURS, cabinet_svg, elevation_html
from io_sudoku.core.pipeline import solve
from io_sudoku.core.redline import FILLS, redline_bytes, write_redline
from io_sudoku.core.revision import compare, solve_incremental
from tests.mutate import mutated, row_of


@pytest.fixture(scope="module")
def base(mdb_path):
    return solve(mdb_path)


@pytest.fixture(scope="module")
def revised(mdb_path, base):
    def change(h, rows):
        rows.pop(row_of(h, rows, "320-LT   -80002"))
        i = row_of(h, rows, "320-PT   -80002")
        from tests.mutate import col
        rows[i][col(h, "Old Tag Number")] = rows[i][col(h, "Tag Number")]
        rows[i][col(h, "Tag Number")] = "320-PT   -80002-X"
        rows[i][col(h, "TagNumber")] = "320PT80002X"
    return solve_incremental(mutated(mdb_path, change), base.rows)


# ---------------------------------------------------------------------------- redline
def coloured_rows(data: bytes) -> dict[str, int]:
    ws = openpyxl.load_workbook(io.BytesIO(data)).worksheets[0]
    seen = {}
    for r in range(2, ws.max_row + 1):
        fill = ws.cell(r, 1).fill
        if fill.fill_type == "solid":
            seen[fill.start_color.rgb[-6:]] = seen.get(fill.start_color.rgb[-6:], 0) + 1
    return seen


def test_redline_colours_exactly_the_changed_rows(revised):
    res, report = revised
    data, wr = redline_bytes(res.rows, report)
    assert wr.verified
    colours = coloured_rows(data)
    expected = {FILLS[c.category]: 0 for c in report.changes}
    for c in report.changes:
        expected[FILLS[c.category]] += 1
    assert colours == expected and sum(colours.values()) == len(report.changes) == 2
    wb = openpyxl.load_workbook(io.BytesIO(data))
    assert wb.sheetnames[-2:] == ["Legend", "Changes"] and wb["Changes"].max_row == 3
    legend = {wb["Legend"].cell(r, 1).value: wb["Legend"].cell(r, 3).value for r in range(2, 6)}
    assert legend == {"Added": 0, "Moved": 0, "Renamed": 1, "Deleted": 1}


def test_the_official_allocation_stays_pristine(revised):
    res, report = revised
    plain, _ = allocation_bytes(res.rows)
    red, _ = redline_bytes(res.rows, report)
    assert read_allocation(plain) == read_allocation(red)                      # same data
    assert coloured_rows(plain) == {} and coloured_rows(red) != {}              # only the redline is coloured


def test_empty_report_colours_nothing(base):
    data, _ = redline_bytes(base.rows, compare(base.rows, base.rows))
    assert coloured_rows(data) == {} and "Legend" in openpyxl.load_workbook(io.BytesIO(data)).sheetnames


def test_redline_survives_a_broken_styler_and_unwritable_target(base, monkeypatch, tmp_path):
    import openpyxl.styles
    monkeypatch.setattr(openpyxl.styles, "PatternFill", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    data, wr = redline_bytes(base.rows, compare([], base.rows))
    assert data and len(read_allocation(data)) == 1152
    monkeypatch.undo()
    assert write_redline(base.rows, compare(base.rows, base.rows), str(tmp_path / "nope" / "x.xlsx")).verified is False
    assert write_redline(base.rows, compare(base.rows, base.rows), str(tmp_path / "ok.xlsx")).verified


def test_redline_with_no_rows_does_not_crash():
    data, _ = redline_bytes([], compare([], []))
    assert data


# -------------------------------------------------------------------------- elevation
def test_each_side_draws_192_cells_and_the_right_ciocs(base):
    front = cabinet_svg(base.rows, "P30-DCM-32001-01", "F")
    rear = cabinet_svg(base.rows, "P30-DCM-32001-01", "R")
    assert front.count('class="cell"') == 192 and rear.count('class="cell"') == 192
    assert "P30DCIOC3201001" in front and "P30DCIOC3201002" in front and "P30DCIOC3201003" not in front
    assert "P30DCIOC3201003" in rear and "P30DCIOC3201004" in rear and "P30DCIOC3201001" not in rear
    assert front.count('data-status="Cabinet Alarm"') == 6 and rear.count('data-status="Cabinet Alarm"') == 0


def test_status_is_never_colour_alone(base):
    svg = cabinet_svg(base.rows, "P30-DCM-32001-04", "F")
    assert "url(#h-" in svg or 'data-status="Wired Spare"' in svg            # hatch pattern for wired spares
    assert svg.count(">A</text>") == svg.count('data-status="Cabinet Alarm"') == 3
    assert 'fill="none"' in svg and svg.count('class="cell"') == 192
    for colour in IO_COLOURS.values():
        assert colour.startswith("#") and len(colour) == 7


def test_accessibility_and_safety_of_the_svg(base):
    svg = cabinet_svg(base.rows, "P24-DCM-50002-01", "F")
    assert 'role="img"' in svg and "aria-labelledby=" in svg and "<title" in svg and "<desc" in svg
    for forbidden in ("http", "<script", "javascript:", "onclick"):
        assert forbidden not in svg


def test_tags_are_escaped_in_tooltips(base):
    rows = [dict(r) for r in base.rows]
    field = next(r for r in rows if r["Tag Status"] == "Field" and r["Electronic/ Marshalling Cabinet"] == "P30-DCM-32001-01"
                 and r["CIOC/CSLS Name"].endswith(("001", "002")))
    field["Tag Name"] = '<script>alert("x")</script>'
    svg = cabinet_svg(rows, "P30-DCM-32001-01", "F")
    assert "<script" not in svg and "&lt;script&gt;" in svg


def test_deterministic_and_empty_states(base):
    assert cabinet_svg(base.rows, "P24-DCM-50002-01", "R") == cabinet_svg(base.rows, "P24-DCM-50002-01", "R")
    assert "No data for this cabinet." in cabinet_svg(base.rows, "NOPE", "F")
    assert "No data for this cabinet." in cabinet_svg([], "P30-DCM-32001-01", "R")
    assert cabinet_svg(base.rows, "P30-DCM-32001-01", "x").count('class="cell"') == 192      # odd side value -> front


def test_elevation_page(base):
    html = elevation_html(base.rows)
    assert html.count("<section>") == 3 and html.count('class="cell"') == 3 * 2 * 192
    assert "@media print" in html and "Cabinet alarm" in html
    for forbidden in ("http", "<script", "<link"):
        assert forbidden not in html
    assert elevation_html([]) .count("No cabinets to draw.") == 1
    assert elevation_html(base.rows, ["P24-DCM-50002-01"]).count("<section>") == 1

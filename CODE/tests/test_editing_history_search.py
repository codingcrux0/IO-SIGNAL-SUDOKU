"""Editing the uploaded file, the revision history and the search bar (logic, no browser)."""
from __future__ import annotations

from io_sudoku.core.pipeline import solve
from io_sudoku.samples import case_bytes, sample_mdb_bytes
from io_sudoku.ui import editing, history, search


def _fix_target(name: str, tq_id: str):
    data = case_bytes(name)
    result = solve(data)
    tq = next(t for t in result.tqs if t.tq_id == tq_id)
    return data, result, editing.cell_for_tq(tq.tq_id, tq.ref, editing.build_index(data), result.quarantined)


def test_edit_button_finds_the_exact_cell_and_the_fix_clears_the_error():
    data, result, target = _fix_target("09_cable_and_pair_errors.xlsx", "PAIR-BEYOND-CABLE")
    sheet = editing.read_editable(data)[0]
    assert sheet.headers[target.col] == "Pair Number" and sheet.row(target.row)[target.col] == "Pair 30"
    fixed = editing.apply_edits(data, "x.xlsx", [editing.CellEdit(target.sheet, target.row, target.col, "Pair Number",
                                                                  "Pair 30", "Pair 20")])
    assert editing.read_editable(fixed)[0].row(target.row)[target.col] == "Pair 20"
    assert not any(t.tq_id == "PAIR-BEYOND-CABLE" for t in solve(fixed).tqs)


def test_two_rows_with_the_same_tag_open_different_rows():
    data = case_bytes("07_tag_errors.xlsx")
    result = solve(data)
    index = editing.build_index(data)
    dup = [t for t in result.tqs if t.tq_id == "DUPLICATE-TAG"]
    rows = {editing.cell_for_tq(t.tq_id, t.ref, index, result.quarantined, n).row for n, t in enumerate(dup)}
    assert len(dup) == 2 and len(rows) == 2


def test_csv_edits_keep_the_delimiter_and_other_cells():
    data = case_bytes("05_clean_semicolon_PIB-24.csv")
    sheet = editing.read_editable(data)[0]
    row, values = sheet.rows[0]
    col = sheet.headers.index("Pair Number")
    out = editing.apply_edits(data, "x.csv", [editing.CellEdit("csv", row, col, "Pair Number", values[col], "Pair 9")])
    again = editing.read_editable(out)[0]
    assert again.row(row)[col] == "Pair 9" and b";" in out.splitlines()[0]
    assert [v for i, v in enumerate(again.row(row)) if i != col] == [v for i, v in enumerate(values) if i != col]


def test_typed_values_keep_numbers_numeric():
    assert editing.typed_value("12", 3) == 12 and editing.typed_value("", "x") is None
    assert editing.typed_value("Pair 2", "Pair 1") == "Pair 2" and editing.same(320, "320") and editing.same(None, "")


def test_unreadable_file_cannot_be_edited_but_does_not_crash():
    assert editing.read_editable(case_bytes("19_corrupt_file.xlsx")) == []


def test_history_names_dedupes_and_compares():
    r0, r1 = solve(sample_mdb_bytes()), solve(case_bytes("09_cable_and_pair_errors.xlsx"))
    past = history.add([], history.make_snapshot([], r0, source="run", file_name="a", input_sha="x", solve_key="k0", created="1"))
    same = history.make_snapshot(past, r0, source="run", file_name="a", input_sha="x", solve_key="k0", created="2")
    assert history.add(past, same) == past                                   # the same run twice is stored once
    past = history.add(past, history.make_snapshot(past, r1, source="run", file_name="b", input_sha="y", solve_key="k1",
                                                    created="3"))
    assert [s.name for s in past] == ["Original", "Revision 1"]
    assert len(past[0].rows_z) < 100_000 and past[0].rows() == [dict(r) for r in r0.rows]
    report = history.compare_snapshots(past[0], past[1])
    assert report.counts["Deleted"] > 0 and history.summary_row(past[0], past[1], report)["From"] == "Original"
    assert history.pairs(past, "first") == [(past[0], past[1])]


def test_history_keeps_the_original_when_full():
    r = solve(sample_mdb_bytes())
    past = []
    for i in range(history.MAX_SNAPSHOTS + 5):
        past = history.add(past, history.make_snapshot(past, r, source="run", file_name="a", input_sha="x",
                                                       solve_key=f"k{i}", created=str(i)))
    assert len(past) == history.MAX_SNAPSHOTS and past[0].name == "Original"


def test_search_closest_match_for_free_text():
    labels = [p.label for p in search.PLACES]
    assert search.closest("warnings", labels) == "TQ Board › Sign Off The Warnings"
    assert search.closest("drawngs", labels).startswith("Cabinet Layout")
    assert search.closest("history", labels) == "Revision › Revision History"
    assert search.closest("", labels) is None


def test_search_places_point_at_real_views():
    from io_sudoku.ui.state import VIEWS
    assert all(p.view in VIEWS for p in search.PLACES)
    assert len({p.label for p in search.PLACES}) == len(search.PLACES)

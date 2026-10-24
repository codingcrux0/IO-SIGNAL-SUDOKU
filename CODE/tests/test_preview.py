"""The read-only file viewer: every output previews, search/filter/export behave, nothing ever raises."""
from __future__ import annotations

import io
import json
import zipfile
from collections import Counter

import pytest

from io_sudoku.core.revision import solve_incremental
from io_sudoku.core.rulepack import default_pack
from io_sudoku.core.simulate import make_revision
from io_sudoku.samples import sample_mdb_bytes
from io_sudoku.ui import preview as pv
from io_sudoku.ui import ui_logic


@pytest.fixture(scope="module")
def ctx():
    mdb = sample_mdb_bytes()
    result = ui_logic.solve_inputs(mdb, "", "[]", "{}", "{}", "00")
    return {"result": result, "mdb_bytes": mdb, "pack": default_pack(), "overrides": [], "pins": {},
            "rev_label": "00", "template_bytes": None}


EXPECTED_KIND = {"allocation": "table", "tq": "table", "violations": "table", "parts": "table", "trace": "table",
                 "summary": "html", "drawings": "html", "manifest": "json", "workspace": "zip", "support": "zip"}


@pytest.mark.parametrize("key", sorted(EXPECTED_KIND))
def test_every_output_previews(ctx, key):
    data, name, _ = ui_logic.build_download(key, ctx)
    preview = pv.preview_bytes(data, name)
    assert preview.kind == EXPECTED_KIND[key], (key, preview.note)
    assert preview.size == len(data)


def test_allocation_preview_shows_every_row_and_column(ctx):
    data, name, _ = ui_logic.build_download("allocation", ctx)
    (sheet,) = pv.preview_bytes(data, name).sheets
    assert len(sheet.columns) == 76 and sheet.total_rows == len(ctx["result"].rows) and not sheet.truncated
    assert sheet.columns[:3] == ["Sr. No.", "Revision No", "Tag Name"]


def test_preview_does_not_change_the_file(ctx):
    data, name, _ = ui_logic.build_download("allocation", ctx)
    before = ui_logic.sha256_hex(data)
    pv.preview_bytes(data, name)
    assert ui_logic.sha256_hex(data) == before


def test_input_mdb_and_csv_preview(ctx):
    assert pv.preview_bytes(ctx["mdb_bytes"], "in.xlsx").sheets[0].total_rows > 0
    csv_sheet = pv.preview_bytes(b"Tag;IO\nT-1;AI\nT-2;DO\n", "in.csv").sheets[0]
    assert csv_sheet.columns == ["Tag", "IO"] and csv_sheet.rows == [["T-1", "AI"], ["T-2", "DO"]]


def test_zip_contents_and_member_preview(ctx):
    data, _, _ = ui_logic.build_download("workspace", ctx)
    preview = pv.preview_bytes(data, "w.zip")
    assert "allocation.xlsx" in [e["File"] for e in preview.entries]
    assert pv.preview_member(data, "allocation.xlsx").kind == "table"
    assert pv.preview_member(data, "pack.json").kind == "json"
    assert pv.preview_member(data, "missing.txt").kind == "unsupported"


def test_html_inside_a_zip_is_never_rendered():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("page.html", "<script>alert(1)</script>")
    assert pv.preview_member(buf.getvalue(), "page.html").kind == "text"


def test_redline_colours_become_change_labels(ctx):
    mdb = ctx["mdb_bytes"]
    rev_b = make_revision(mdb, 10, 3)
    result_b, report = solve_incremental(rev_b, ctx["result"].rows, ui_logic.config_for_pack(default_pack()), "B")
    data, name, _ = ui_logic.build_download("redline", dict(ctx, result=result_b, impact=report, rev_a_rows=ctx["result"].rows))
    sheet = pv.preview_bytes(data, name).sheets[0]
    counts = Counter(m for m in sheet.marks if m)
    assert counts and all(counts[k] == report.counts[k] for k in counts)
    cols, rows, marks = pv.filter_rows(sheet, "", ["Tag Name"], "Moved")
    assert cols == ["Tag Name"] and len(rows) == report.counts["Moved"] and set(marks) == {"Moved"}
    assert pv.mark_colour("Moved") and not pv.mark_colour("")


def test_search_looks_at_hidden_columns_too():
    sheet = pv.SheetPreview("s", ["Tag", "Cable"], [["T-1", "C-9"], ["T-2", "C-8"]], 2)
    cols, rows, marks = pv.filter_rows(sheet, "c-9", ["Tag"])
    assert cols == ["Tag"] and rows == [["T-1"]] and marks == []


def test_csv_export_defuses_formulas():
    text = pv.rows_to_csv(["a"], [["=HYPERLINK(1)"], ["+1"], ["@x"], ["-12"], ["-x"], [None]]).decode("utf-8-sig")
    assert text.splitlines() == ["a", "'=HYPERLINK(1)", "'+1", "'@x", "-12", "'-x", '""']


def test_frame_keeps_numbers_numeric_and_mixed_columns_as_text():
    frame = pv.to_frame(["n", "m"], [[1, "x"], [2.5, 3], [None, None]])
    assert frame["n"].dtype.kind == "f" and list(frame["m"]) == ["x", "3", ""]


def test_duplicate_and_blank_headers_are_made_unique():
    sheet = pv.preview_bytes(b"Tag,,Tag\n1,2,3\n", "x.csv").sheets[0]
    assert sheet.columns == ["Tag", "Column 2", "Tag (2)"]


@pytest.mark.parametrize("data,name", [(b"", "a.xlsx"), (b"not a zip", "a.xlsx"), (b"PK\x03\x04junk", "a.zip"),
                                       (b"{bad", "a.json"), (b"\xff\xfe\x00", "a.csv"), (b"abc", "a.bin"), (None, "a.txt")])
def test_garbage_never_raises(data, name):
    preview = pv.preview_bytes(data, name)
    assert preview.kind in {"empty", "unsupported", "text", "table", "json"}


def test_bundle_all_holds_every_file(ctx):
    data = ui_logic.bundle_all("test-bundle", ctx)
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert len(names) == len(ui_logic.available_downloads(False))
    assert ui_logic.bundle_all_name(ctx).endswith(".zip")
    assert json.loads(zipfile.ZipFile(io.BytesIO(data)).read(next(n for n in names if n.endswith(".json"))))

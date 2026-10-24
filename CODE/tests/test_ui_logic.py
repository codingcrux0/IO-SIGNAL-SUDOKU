"""UI helpers that need no browser: grid HTML, paging, solve wiring, every download."""
from __future__ import annotations

import io
import json
import zipfile

import pytest
from openpyxl import load_workbook

from io_sudoku.core.pipeline import output_hash
from io_sudoku.core.revision import solve_incremental
from io_sudoku.core.rulepack import default_pack
from io_sudoku.core.tq import TQ
from io_sudoku.samples import golden_hash, load_sample_result, sample_mdb_bytes
from io_sudoku.ui import ui_logic


@pytest.fixture(scope="module")
def sample():
    return load_sample_result()


def test_solve_inputs_matches_golden():
    result = ui_logic.solve_inputs(sample_mdb_bytes(), ui_logic.pack_json(default_pack()), "[]", "{}", "{}", "00")
    assert output_hash(result.rows) == golden_hash()


def test_solve_inputs_tolerates_garbage_text():
    result = ui_logic.solve_inputs(sample_mdb_bytes(), "not json", "garbage", "[1,2]", "[]", "")
    assert len(result.rows) == 1152


def test_pins_from_json_drops_malformed():
    assert ui_logic.pins_from_json('{"C-1": ["CAB", 2], "bad": 5, "x": ["a", "b"]}') == {"C-1": ("CAB", 2)}
    assert ui_logic.pins_from_json("nope") == {}


def test_grid_has_384_labelled_slots_and_escapes(sample):
    cab = ui_logic.cabinet_names(sample.rows)[0]
    html = ui_logic.cabinet_grid_html(sample.rows, cab)
    assert html.count('class="iosg-slot') == 384 and html.count("aria-label=") >= 384
    evil = [dict(r, **{"Tag Name": '"><script>x</script>'}) for r in sample.rows]
    out = ui_logic.cabinet_grid_html(evil, cab)
    assert "<script>" not in out and "&lt;script&gt;" in out


def test_grid_for_unknown_cabinet_is_all_empty(sample):
    assert ui_logic.cabinet_grid_html(sample.rows, "NOPE").count("s-none") == 384


def test_filter_and_paging():
    tqs = [TQ("A", "error", "c", "Instrument", f"ref{i}", "m", "f") for i in range(250)] + [TQ("B", "info", "c", "Process", "z", "m", "f")]
    assert len(ui_logic.filter_tqs(tqs, "error")) == 250 and len(ui_logic.filter_tqs(tqs, "all", "ref12")) == 11
    page, n, pages = ui_logic.page_slice(tqs, 99)
    assert pages == 3 and n == 2 and len(page) == 51
    assert ui_logic.page_slice([], 5) == ([], 0, 1)


def test_list_headers_reads_the_sample():
    headers = ui_logic.list_headers(sample_mdb_bytes())
    assert "Tag Number" in headers or any("Tag" in h for h in headers)
    assert ui_logic.list_headers(b"garbage") == []


def make_ctx(result, impact=None, rows_a=None, mdb=None):
    return {"result": result, "mdb_bytes": mdb or sample_mdb_bytes(), "pack": default_pack(), "overrides": [], "pins": {},
            "rev_label": "00", "template_bytes": None, "impact": impact, "rev_a_rows": rows_a}


def test_every_download_builds(sample):
    result_b, impact = solve_incremental(sample_mdb_bytes(), sample.rows)
    ctx = make_ctx(result_b, impact, sample.rows)
    for spec in ui_logic.DOWNLOADS:
        data, name, mime = ui_logic.build_download(spec.key, ctx)
        assert data and name and mime, spec.key
        if name.endswith(".xlsx"):
            assert load_workbook(io.BytesIO(data)).sheetnames, spec.key
        if name.endswith(".zip"):
            assert zipfile.ZipFile(io.BytesIO(data)).namelist(), spec.key
    assert json.loads(ui_logic.build_download("manifest", ctx)[0])["rows"] == 1152


def test_draft_results_get_a_suffix(sample):
    ctx = make_ctx(sample)
    name = ui_logic.build_download("allocation", ctx)[1]
    assert name.startswith("IO_Allocation_Rev00") and ("_DRAFT" not in name) == (sample.readiness.status == "ISSUE-READY")


def test_available_downloads_hide_revision_items_without_impact():
    keys = {d.key for d in ui_logic.available_downloads(False)}
    assert "impact" not in keys and "redline" not in keys and "allocation" in keys
    assert {"impact", "redline"} <= {d.key for d in ui_logic.available_downloads(True)}


def test_workspace_round_trip_through_the_ui_callback(sample):
    from io_sudoku.core.workspace import import_workspace
    data, _, _ = ui_logic.build_download("workspace", make_ctx(sample))
    state, why = import_workspace(data)
    assert state is not None and why == "" and len(state.rows) == 1152


def test_tqs_sort_errors_first_and_label_their_severity():
    from io_sudoku.core.tq import TQLog
    log = TQLog()
    for tq_id in ("DELETED-IN-MDB", "TOPOLOGY-INFERRED", "BLANK-TAG", "SECTION-UNDERIVABLE", "MISSING-PAIR"):
        log.add(tq_id, "x")
    ordered = ui_logic.by_severity(log.items())
    assert [t.severity for t in ordered] == ["error", "error", "warning", "info", "info"]
    assert [t.tq_id for t in ordered][:2] == ["BLANK-TAG", "MISSING-PAIR"]          # stable inside a group
    assert [r["Severity"] for r in ui_logic.tq_rows(ordered)] == ["● Error", "● Error", "▲ Warning", "ℹ Info", "ℹ Info"]
    assert set(ui_logic.SEVERITY_COLOURS) == {"error", "warning", "info"}

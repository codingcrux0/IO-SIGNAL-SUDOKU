"""TQ lifecycle and the Excel report builders."""
from __future__ import annotations

import copy
import io

from openpyxl import load_workbook

from io_sudoku.core import report as rep
from io_sudoku.core.models import Quarantined, Violation
from io_sudoku.core.revision import compare
from io_sudoku.core.tq import TQ
from io_sudoku.core.tqlife import diff_tqs, group_by_owner, tq_key, tqs_as_email_text
from tests.helpers import make_signal
from tests.test_revision import row


def tq(tid="MISSING-PAIR", ref="CAB-1", owner="Instrument", sev="error", msg="Which pair?", fix="Confirm."):
    return TQ(tid, sev, "Data", owner, ref, msg, fix)


def book(data: bytes):
    return load_workbook(io.BytesIO(data))


# ---------------------------------------------------------------------------- lifecycle
def test_diff_new_open_resolved():
    prev = [tq(ref="a"), tq(ref="b")]
    cur = [tq(ref="B"), tq(ref="c")]                 # 'B' matches 'b' (case-insensitive key)
    d = diff_tqs(prev, cur)
    assert [t.ref for t in d.still_open] == ["B"] and [t.ref for t in d.new] == ["c"] and [t.ref for t in d.resolved] == ["a"]
    assert tq_key(tq(ref="Cab-1")) == tq_key(tq(ref="cab-1"))


def test_diff_dedups_resolved_and_handles_empty():
    d = diff_tqs([tq(ref="a"), tq(ref="a")], [])
    assert len(d.resolved) == 1 and d.new == [] and d.still_open == []
    assert diff_tqs([], []).new == []


def test_group_by_owner_fixed_order_then_alphabetical():
    tqs = [tq(owner="Zeta"), tq(owner="Process"), tq(owner="Instrument"), tq(owner="Alpha"), tq(owner="Instrument")]
    groups = group_by_owner(tqs)
    assert list(groups) == ["Instrument", "Process", "Alpha", "Zeta"] and len(groups["Instrument"]) == 2


def test_email_text():
    text = tqs_as_email_text([tq(msg="Q1"), tq(owner="Process", msg="Q2")], "Instrument")
    assert "1 open query" in text and "Q1" in text and "Q2" not in text and "Suggested fix: Confirm." in text
    assert "no open queries" in tqs_as_email_text([], "Electrical")


# ----------------------------------------------------------------------------- reports
def test_tq_register_orders_by_severity_and_numbers():
    data = rep.tq_register_bytes([tq(sev="info", ref="i"), tq(sev="error", ref="e"), tq(sev="warning", ref="w")])
    ws = book(data)["TQ Register"]
    assert [ws.cell(r, 3).value for r in (2, 3, 4)] == ["error", "warning", "info"]
    assert ws["A2"].value == "TQ-0001" and ws.freeze_panes == "A2"


def test_tq_register_status_column_and_resolved_rows():
    d = diff_tqs([tq(ref="gone"), tq(ref="stay")], [tq(ref="stay"), tq(ref="fresh")])
    ws = book(rep.tq_register_bytes([tq(ref="stay"), tq(ref="fresh")], diff=d))["TQ Register"]
    statuses = {ws.cell(r, 6).value: ws.cell(r, 9).value for r in range(2, ws.max_row + 1)}
    assert statuses == {"stay": "Open", "fresh": "New", "gone": "Resolved"}


def test_register_has_quarantine_and_assumption_sheets():
    q = Quarantined(make_signal(tag="T-1"), "MISSING-PAIR")
    class A:  # minimal assumption stand-in
        id, text, source, confirm_by = "A01", "txt", "rules", "Instrument"
    wb = book(rep.tq_register_bytes([], [q], assumptions=[A()]))
    assert wb["Quarantined Signals"]["A2"].value == "T-1" and wb["Assumptions"]["A2"].value == "A01"


def test_formula_like_text_is_stored_as_text():
    wb = book(rep.tq_register_bytes([tq(msg="=1+1")]))
    cell = wb["TQ Register"]["G2"]
    assert cell.data_type == "s" and cell.value == "=1+1"


def test_violations_report():
    ws = book(rep.violations_bytes([Violation("V06", "error", "T-1", "bad")]))["Verification"]
    assert [c.value for c in ws[2]] == ["V06", "error", "T-1", "bad"]
    assert book(rep.violations_bytes([]))["Verification"].max_row == 1


def test_impact_report_sheets_and_summary():
    a = [row(f"T-{i}", i) for i in range(1, 4)]
    b = copy.deepcopy(a)
    b[0]["Channel_No"] = 9                           # moved
    b.append(row("NEW-1", 10))                       # added
    del b[2]                                         # deleted
    report = compare(a, b)
    wb = book(rep.impact_report_bytes(report, a, b))
    assert wb.sheetnames == ["Summary", "Added", "Deleted", "Moved", "Renamed", "Conversions"]
    summary = {r[0].value: r[1].value for r in wb["Summary"].iter_rows(min_row=2)}
    assert (summary["Added"], summary["Deleted"], summary["Moved"], summary["Unchanged"]) == (1, 1, 1, 1)
    assert wb["Added"]["A2"].value == "NEW-1" and "channel 10" in wb["Added"]["D2"].value


def test_reports_never_raise_and_write_twins(tmp_path):
    bad = rep.impact_report_bytes(object())          # not a report at all
    assert "could not be built" in book(bad)["Report"]["A2"].value
    path = tmp_path / "v.xlsx"
    rep.write_violations([], path)
    buf = io.BytesIO()
    rep.write_tq_register([tq()], None, buf)
    assert path.stat().st_size > 0 and len(buf.getvalue()) > 0

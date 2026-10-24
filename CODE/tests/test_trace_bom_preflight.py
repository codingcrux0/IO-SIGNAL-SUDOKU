from __future__ import annotations

import io

import openpyxl
import pytest

from io_sudoku.core import bom as bomlib
from io_sudoku.core.allocio import CANONICAL_COLUMNS
from io_sudoku.core.config import load_config
from io_sudoku.core.pipeline import solve
from io_sudoku.core.preflight import preflight
from io_sudoku.core.trace import explain, trace_bytes
from tests.mutate import col, mutated, read_table, row_of, to_xlsx_bytes


@pytest.fixture(scope="module")
def result(mdb_path):
    return solve(mdb_path)


# ----------------------------------------------------------------------------- trace
def test_explain_a_field_tag(result):
    lines = explain(result, "320-FT   -20645-A")
    assert any("logic group" in l for l in lines) and any("-> P30-DCM" in l and "Group" in l for l in lines)
    assert any("A-family cable -> CIOC" in l for l in lines) and any(l.startswith("Placed at baseplate") for l in lines)
    assert explain(result, "  320-ft -20645-a ") == lines                       # same lookup rules as everywhere


def test_every_placed_cable_has_a_story_and_every_wired_spare_a_quota_line(result):
    cables = {r["Field Cable No"].casefold() for r in result.rows if r["Tag Status"] == "Field"}
    for cable in cables:
        assert len(explain(result, cable)) >= 3, cable
    spares = [r["Tag Name"] for r in result.rows if r["Tag Status"] == "Wired Spare"]
    assert spares and all("Wired spare" in " ".join(explain(result, s)) and "quota" in " ".join(explain(result, s)) for s in spares)
    alarms = [r["Tag Name"] for r in result.rows if r["Tag Status"] == "Cabinet Alarm"]
    assert all("CIOC 1, baseplate 1" in " ".join(explain(result, a)) for a in alarms)


def test_unknown_query_and_blank_query(result):
    assert explain(result, "no such tag") == [] and explain(result, "") == [] and explain(result, None) == []   # type: ignore[arg-type]
    assert explain(object(), "x") == []


def test_tracing_does_not_change_rows_and_the_workbook_round_trips(result, mdb_path):
    assert solve(mdb_path).rows == result.rows
    ws = openpyxl.load_workbook(io.BytesIO(trace_bytes(result))).worksheets[0]
    assert [c.value for c in ws[1]] == ["Key", "Step", "Reason"] and ws.max_row > 100


# ------------------------------------------------------------------------------- bom
def test_bom_counts_match_the_rows(result):
    rows = result.rows
    parts = bomlib.bom(rows)
    total = {p["Part No"]: p["Qty"] for p in parts if p["Cabinet"] == "TOTAL"}
    for charm in {r["CHARM Type"] for r in rows}:
        assert total[charm] == sum(1 for r in rows if r["CHARM Type"] == charm)
    for tb in ("SE4501", "SE4502"):
        assert total[tb] == sum(1 for r in rows if r["CHARM TB Part No"] == tb)
    used_bps = {(r["CIOC/CSLS Name"], r["Baseplate"]) for r in rows if r["Tag Status"] != "Spare Slot"}
    assert total["SE6103"] > 0 and total["CABINET"] == 3
    assert total["BASEPLATE"] == len(used_bps) and total["CIOC/CSLS"] == len({c for c, _ in used_bps})
    assert sum(1 for p in parts if p["Cabinet"] != "TOTAL" and p["Part No"] == "CABINET") == 3
    assert bomlib.bom([]) == [] and bomlib.cable_utilisation([]) == []


def fake(status, cable="-", pair="-", ch=1, bp="013-CBP-2", cioc="P30DCIOC3201013", cab="CAB"):
    r = {c: "-" for c in CANONICAL_COLUMNS}
    r.update({"Tag Status": status, "Field Cable No": cable, "Field Cable Pair": pair, "Channel_No": ch, "Baseplate": bp,
              "CIOC/CSLS Name": cioc, "Electronic/ Marshalling Cabinet": cab, "CHARM Type": "SE6103", "CHARM TB Part No": "SE4501"})
    return r


def test_cable_advisory_depends_on_the_highest_used_pair():
    rows = [fake("Field", "C1", f"Pair {p}", p) for p in range(1, 10)] + [fake("Spare Slot", "C1", f"Pair {p}", p) for p in range(10, 25)]
    line = bomlib.cable_utilisation(rows)[0]
    assert line["Size"] == 24 and line["Field"] == 9 and line["Reserved Pairs"] == 15 and line["Highest Used Pair"] == 9
    assert "Could be 12P" in line["Advisory"] and "engineering review" in line["Advisory"] and line["Utilisation %"] == 37.5
    rows2 = [fake("Field", "C1", f"Pair {p}", p) for p in range(1, 14)] + [fake("Spare Slot", "C1", f"Pair {p}", p) for p in range(14, 25)]
    assert bomlib.cable_utilisation(rows2)[0]["Advisory"] == "OK"
    rows3 = [fake("Field", "C1", f"Pair {p}", p) for p in range(1, 4)] + [fake("Spare Slot", "C1", f"Pair {p}", p) for p in range(4, 13)]
    assert "Could be 6P" in bomlib.cable_utilisation(rows3)[0]["Advisory"]


def test_headroom_on_a_hand_built_cabinet():
    cfg = load_config()
    rows = []
    for bp in range(1, 9):                      # CIOC 2 (name ...014): everything free except baseplate 3
        for ch in range(1, 13):
            used = bp == 3
            rows.append(fake("Field" if used else "Spare Slot", "X" if used else "-", f"Pair {ch}" if used else "-", ch,
                             f"014-CBP-{bp}", "P30DCIOC3201014"))
    line = bomlib.headroom(rows, cfg)[0]
    # baseplates 1-2 are a free run of 2 -> one 24-pair slot; 4-8 are a run of 5 -> two more
    assert (line["Free baseplates"], line["Free 24-pair slots"], line["Free 12-pair slots"], line["Free 6-pair slots"]) == (7, 3, 7, 14)
    assert "3 x 24-pair" in line["Statement"]


def test_headroom_ignores_the_alarm_baseplate_and_end_reserve(result):
    lines = bomlib.headroom(result.rows, result.cfg_used)
    assert len(lines) == 3
    for l in lines:
        assert l["Free baseplates"] <= 31 - 4 and l["Free 24-pair slots"] <= l["Free baseplates"] // 2 + 4


def test_parts_report_has_three_sheets(result):
    wb = openpyxl.load_workbook(io.BytesIO(bomlib.parts_report_bytes(result.rows, result.cfg_used)))
    assert wb.sheetnames == ["BOM", "Cable Utilisation", "Headroom"]
    assert wb["BOM"].max_row > 20


def test_these_reports_never_change_the_rows(result):
    before = [dict(r) for r in result.rows]
    bomlib.bom(result.rows); bomlib.cable_utilisation(result.rows); bomlib.headroom(result.rows, result.cfg_used)
    assert result.rows == before


# --------------------------------------------------------------------------- preflight
def test_preflight_on_the_sample(mdb_path):
    r = preflight(mdb_path)
    assert r.score >= 95 and r.total_rows == 190 and r.needs_human == 0
    assert r.auto_fixed["io_alias_fixed"] > 0 and r.auto_fixed["deleted_excluded"] == 1 and r.auto_fixed["io_type2_rows"] == 6
    tag = next(c for c in r.columns if c.field == "tag")
    assert (tag.filled, tag.total, tag.pct) == (190, 190, 100.0) and tag.method == "exact"
    assert not [t for t in r.issues if t.severity == "error"]


def test_score_drops_and_never_rises_as_more_rows_break(mdb_path):
    scores = []
    for n in (0, 5, 10, 30):
        def change(h, rows, n=n):
            for i in range(n):
                rows[i][col(h, "I/O Type Name")] = None
        r = preflight(mutated(mdb_path, change))
        scores.append(r.score)
        assert r.needs_human >= n - 1                       # a couple of the first rows may be alarms (not field)
    assert scores == sorted(scores, reverse=True) and scores[0] > scores[-1]


def test_preflight_counts_ten_broken_rows(mdb_path):
    def change(h, rows):
        c = col(h, "Status")
        done = 0
        for r in rows:
            if r[c] != "DELETED" and r[col(h, "Instrument Type Description")] != "Cabinet Diagnostic Alarm" and done < 10:
                r[col(h, "I/O Type Name")] = "XYZ"
                done += 1
    r = preflight(mutated(mdb_path, change))
    assert r.needs_human == 10 and r.score < preflight(mdb_path).score


@pytest.mark.parametrize("junk", [b"garbage", b"", b"\xd0\xcf\x11\xe0xxxx"])
def test_preflight_of_garbage_scores_zero(junk):
    r = preflight(junk)
    assert r.score == 0 and r.total_rows == 0 and r.issues


def test_preflight_header_only_scores_zero():
    assert preflight(to_xlsx_bytes(["Tag Number", "I/O Type Name", "Technical Room"], [])).score == 0

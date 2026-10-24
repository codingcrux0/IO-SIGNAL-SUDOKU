from __future__ import annotations

import copy
from collections import Counter

import pytest

from io_sudoku.core.allocio import CANONICAL_COLUMNS, read_allocation
from io_sudoku.core.config import load_config
from io_sudoku.core.pipeline import solve
from io_sudoku.core.revision import (
    Change, ImpactReport, cabinets_from_rows, compare, layout_from_rows, location, solve_incremental,
    solve_revision, stamp_changes,
)
from io_sudoku.core.textnorm import match_key
from io_sudoku.core.tq import TQLog
from io_sudoku.core.verify import verify
from tests.mutate import col, mutated, read_table, row_of, to_xlsx_bytes


# -------------------------------------------------------------------- compare (synthetic)
def row(tag, ch=1, cab="CAB-1", cioc="C001", bp="001-CBP-2", status="Field", old="-", charm="SE4303T01", cable="X-1"):
    r = {c: "-" for c in CANONICAL_COLUMNS}
    r.update({"Tag Name": tag, "Channel_No": ch, "Electronic/ Marshalling Cabinet": cab, "CIOC/CSLS Name": cioc,
              "Baseplate": bp, "Tag Status": status, "Old Tag": old, "CHARM Type": charm, "Field Cable No": cable,
              "Revision No": "00"})
    return r


def cats(report):
    return {(c.category, c.tag): c for c in report.changes}


def test_identical_inputs_have_no_changes():
    rows = [row(f"T-{i}", i) for i in range(1, 6)]
    rep = compare(rows, copy.deepcopy(rows))
    assert rep.changes == [] and rep.unchanged == 5 and rep.counts == {"Added": 0, "Deleted": 0, "Moved": 0, "Renamed": 0}


def test_moved_by_channel_and_by_cabinet():
    a = [row("T-1", 1), row("T-2", 2)]
    b = [row("T-1", 5), row("T-2", 2, cab="CAB-2")]
    rep = compare(a, b)
    assert rep.counts["Moved"] == 2 and rep.unchanged == 0
    assert rep.affected_cabinets == ["CAB-1", "CAB-2"]


def test_rename_with_old_tag_and_without():
    a = [row("OLD-1", 1), row("OLD-2", 2)]
    b = [row("NEW-1", 1, old="OLD-1"), row("NEW-2", 2)]
    rep = compare(a, b)
    c = cats(rep)
    assert c[("Renamed", "NEW-1")].old_tag == "OLD-1" and c[("Renamed", "NEW-2")].old_tag == "OLD-2"
    assert rep.counts == {"Added": 0, "Deleted": 0, "Moved": 0, "Renamed": 2}


def test_renamed_and_relocated_is_reported_once_as_moved():
    rep = compare([row("OLD-1", 1)], [row("NEW-1", 9, old="old-1")])
    assert [(c.category, c.note) for c in rep.changes] == [("Moved", "also renamed")]
    assert rep.counts["Added"] == 0 and rep.counts["Deleted"] == 0 and len(rep.changes) == 1


def test_added_deleted_and_conversion():
    a = [row("KEEP", 1), row("GONE", 2)]
    b = [row("KEEP", 1), row("-", 2, status="Spare Slot"), row("NEW", 3)]
    rep = compare(a, b)
    assert rep.counts == {"Added": 1, "Deleted": 1, "Moved": 0, "Renamed": 0}
    assert [c.note for c in rep.conversions] == ["now a Spare Slot"]
    b2 = [row("KEEP", 1), row("3201DSP0100001", 2, status="Wired Spare")]
    assert compare(a, b2).conversions[0].note == "now a Wired Spare"


def test_spare_slot_to_field_at_same_location_is_added_not_renamed():
    rep = compare([row("-", 4, status="Spare Slot")], [row("NEWTAG", 4)])
    assert rep.counts == {"Added": 1, "Deleted": 0, "Moved": 0, "Renamed": 0}


def test_tags_match_ignoring_spacing_and_case():
    rep = compare([row("320-FT   -1", 1)], [row("320-ft -1", 1)])
    assert rep.changes == [] and rep.unchanged == 1


def test_hardware_change_detected():
    rep = compare([row("T", 1, charm="SE4303T01")], [row("T", 1, charm="SE4301T02")])
    assert len(rep.hardware_changes) == 1 and "SE4303T01 -> SE4301T02" in rep.hardware_changes[0].note


def test_compare_handles_empty_and_duplicates():
    assert compare([], []).changes == []
    rep = compare([], [row("A", 1)])
    assert rep.counts["Added"] == 1
    dup = compare([row("A", 1), row("a", 2)], [row("A", 1)])
    assert dup.warnings and dup.unchanged == 1


def test_stamp_changes_marks_only_changed_rows():
    a = [row("KEEP", 1), row("GONE", 2), row("OLD", 3)]
    b = [row("KEEP", 1), row("-", 2, status="Spare Slot"), row("NEW", 3, old="OLD"), row("ADD", 4)]
    rep = compare(a, b)
    out = stamp_changes(a, b, rep, "B")
    by = {r["Channel_No"]: r for r in out}
    assert by[1]["Change Type"] == "-" and by[1]["Revision No"] == "00"
    assert (by[2]["Change Type"], by[2]["Remarks"], by[2]["Revision No"]) == ("Deleted", "Tag Deleted", "B")
    assert (by[3]["Change Type"], by[3]["Old Tag"], by[3]["Remarks"]) == ("Renamed", "OLD", "Tag Renamed")
    assert (by[4]["Change Type"], by[4]["Remarks"]) == ("Added", "Tag Added")
    assert b[0]["Revision No"] == "00" and b[3]["Change Type"] == "-"      # inputs untouched


# ------------------------------------------------------------------- layout and helpers
def test_cabinets_from_rows_reproduces_the_configured_cabinets(mdb_path):
    rows = solve(mdb_path).rows
    cfg = load_config()
    for built, known in zip(cabinets_from_rows(rows), cfg.cabinets):
        for name in ("marshalling", "system", "controller", "tech_room", "loc", "area5", "unit", "cabinet_seq", "ctrl_seq"):
            assert getattr(built, name) == getattr(known, name), name


def test_layout_reads_cables_back_exactly(mdb_path):
    rows = solve(mdb_path).rows
    layout = layout_from_rows(rows, load_config(), TQLog())
    assert layout.unmapped_ratio == 0 and layout.cabinets == [] and len(layout.cables) == 15
    assert layout.cables["320-ce-0001"].rows == 24 and layout.cables["320-ce-0035"].rows == 6
    assert all(c.start % (6 if c.rows <= 6 else 12) == 0 for c in layout.cables.values())
    assert sum(1 for r in rows if r["Tag Status"] == "Wired Spare") == len(layout.wired)


def test_layout_of_the_human_sample_is_fully_mappable(alloc_path):
    layout = layout_from_rows(read_allocation(alloc_path), load_config(), TQLog())
    assert layout.unmapped_ratio == 0 and len(layout.cables) == 15


# --------------------------------------------------------------- incremental re-solve
@pytest.fixture(scope="module")
def base(mdb_path):
    return solve(mdb_path)


def edited(mdb_path, change):
    return mutated(mdb_path, change)


def positions(rows):
    return {match_key(r["Tag Name"]): location(r) for r in rows if r["Tag Status"] in ("Field", "Cabinet Alarm")}


def test_no_edits_means_no_changes_and_identical_rows(mdb_path, base):
    res, rep = solve_incremental(mdb_path, base.rows)
    assert rep.changes == [] and rep.mode == "pinned" and rep.unchanged == 189
    assert res.rows == base.rows
    assert res.violations == [] and res.readiness.status == "ISSUE-READY"


def test_deleting_a_tag_leaves_a_reserved_pair_and_moves_nothing(mdb_path, base):
    def change(h, rows):
        rows.pop(row_of(h, rows, "320-LT   -80002"))
    res, rep = solve_incremental(edited(mdb_path, change), base.rows)
    assert rep.counts == {"Added": 0, "Deleted": 1, "Moved": 0, "Renamed": 0}
    gone = next(c for c in rep.changes if c.category == "Deleted")
    slot = next(r for r in res.rows if location(r) == gone.a_loc)
    assert slot["Tag Status"] in ("Spare Slot", "Wired Spare") and "Tag Deleted" in slot["Remarks"]
    assert slot["Field Cable Pair"] != "-" and slot["Change Type"] == "Deleted"       # the wired pair stays reserved
    assert positions(res.rows).items() >= {k: v for k, v in positions(base.rows).items() if k != "320-lt -80002"}.items()
    assert res.violations == []


def test_renaming_a_tag_keeps_its_slot_and_fills_old_tag(mdb_path, base):
    def change(h, rows):
        i = row_of(h, rows, "320-LT   -80002")
        rows[i][col(h, "Old Tag Number")] = rows[i][col(h, "Tag Number")]
        rows[i][col(h, "Tag Number")] = "320-LT   -80002-X"
        rows[i][col(h, "TagNumber")] = "320LT80002X"
    res, rep = solve_incremental(edited(mdb_path, change), base.rows)
    assert rep.counts == {"Added": 0, "Deleted": 0, "Moved": 0, "Renamed": 1}
    renamed = next(r for r in res.rows if r["Tag Name"] == "320-LT   -80002-X")
    assert renamed["Old Tag"] == "320-LT   -80002" and renamed["Change Type"] == "Renamed" and renamed["Revision No"] == "B"
    assert location(renamed) == positions(base.rows)["320-lt -80002"]


def test_adding_a_tag_on_a_free_pair_of_an_existing_cable(mdb_path, base):
    def change(h, rows):
        proto = list(rows[row_of(h, rows, "320-LT   -80002")])
        proto[col(h, "Tag Number")], proto[col(h, "TagNumber")] = "320-LT   -99999", "320LT99999"
        proto[col(h, "Pair Number")] = "Pair 24"
        rows.append(proto)
    res, rep = solve_incremental(edited(mdb_path, change), base.rows)
    assert rep.counts == {"Added": 1, "Deleted": 0, "Moved": 0, "Renamed": 0}
    new = next(r for r in res.rows if r["Tag Name"] == "320-LT   -99999")
    assert new["Field Cable No"] == "320-CE-0001" and new["Field Cable Pair"] == "Pair 24" and new["Change Type"] == "Added"
    assert res.violations == []
    assert all(s.shortfall == 0 for s in res.spare_lines)               # a consumed spare is replenished


def test_adding_a_tag_on_a_brand_new_cable(mdb_path, base):
    def change(h, rows):
        proto = list(rows[row_of(h, rows, "320-LT   -80002")])
        proto[col(h, "Tag Number")], proto[col(h, "TagNumber")] = "320-LT   -88888", "320LT88888"
        proto[col(h, "Multipair Cable No.")] = "320-CE-9999"
        proto[col(h, "Pair Number")] = "Pair 1"
        proto[col(h, "Logic Number")] = "-"
        rows.append(proto)
    res, rep = solve_incremental(edited(mdb_path, change), base.rows)
    assert rep.counts == {"Added": 1, "Deleted": 0, "Moved": 0, "Renamed": 0}
    assert res.violations == [] and res.readiness.status == "ISSUE-READY"
    mine = [r for r in res.rows if r["Field Cable No"] == "320-CE-9999"]
    assert len(mine) == 24                                             # the copied size text says 24 pairs: a whole 24-channel run
    assert verify(res.rows, res.cfg_used) == []


def test_changing_a_pair_moves_exactly_that_tag(mdb_path, base):
    def change(h, rows):
        rows[row_of(h, rows, "320-LT   -80002")][col(h, "Pair Number")] = "Pair 24"
    res, rep = solve_incremental(edited(mdb_path, change), base.rows)
    assert rep.counts == {"Added": 0, "Deleted": 0, "Moved": 1, "Renamed": 0}
    assert rep.changes[0].tag == "320-LT   -80002"
    assert res.violations == []


def test_a_cable_that_grows_with_its_neighbour_in_the_way_is_replaced_without_overlap(mdb_path, base):
    def change(h, rows):                                               # 12P cable becomes 24P
        c = col(h, "Multipair Cable No.")
        for r in rows:
            if r[c] == "320-CE-0045":
                r[col(h, "Multi-cable / Cable")] = "24PX1MM2/FR/IND&OS/ARM/NIS"
    res, rep = solve_incremental(edited(mdb_path, change), base.rows)
    assert res.violations == [] and verify(res.rows, res.cfg_used) == []
    assert rep.mode == "pinned"
    others = {k: v for k, v in positions(base.rows).items()}
    cable_rows = [r for r in res.rows if r["Field Cable No"] == "320-CE-0045"]
    assert len(cable_rows) == 24                                       # the cable now owns 24 channels
    moved = {c.tag for c in rep.changes if c.category == "Moved"}
    unrelated = {k for k, v in others.items()}
    assert all(match_key(t) in unrelated for t in moved)


def test_unchanged_tags_never_move_in_the_real_sample_scenario(mdb_path, alloc_path):
    rows_a = read_allocation(alloc_path)
    res, rep = solve_incremental(mdb_path, rows_a)
    print("\nSample Rev A (human) -> Rev B (MDB):", rep.counts, "unchanged:", rep.unchanged, "mode:", rep.mode)
    assert rep.mode == "pinned"
    a_by_key = {match_key(r["Tag Name"]): r for r in rows_a if r["Tag Status"] == "Field"}
    mdb_cable = {match_key(r["Tag Name"]): (r["Field Cable No"], r["Field Cable Pair"]) for r in res.rows if r["Tag Status"] == "Field"}
    moved = {match_key(c.tag) for c in rep.changes if c.category == "Moved"}
    for key, a_row in a_by_key.items():
        if key in mdb_cable and mdb_cable[key] == (a_row["Field Cable No"], a_row["Field Cable Pair"]):
            assert key not in moved, key
    assert res.violations == [] or all(v.severity == "warning" for v in res.violations)


def test_rev_a_with_an_unknown_cabinet_layout_falls_back_to_compare_only(mdb_path, base):
    rows_a = copy.deepcopy(base.rows)
    for r in rows_a[:600]:                                             # >1% of rows cannot be mapped
        r["Baseplate"] = "garbage"
    res, rep = solve_incremental(mdb_path, rows_a)
    assert rep.mode == "compare-only" and any(t.tq_id == "REV-A-UNPARSEABLE" for t in res.tqs)
    assert res.readiness.status == "DRAFT" and len(res.rows) == 1152


def test_empty_rev_a_does_not_crash(mdb_path):
    res, rep = solve_incremental(mdb_path, [])
    assert rep.mode == "compare-only" and rep.counts["Added"] == 189


def test_rev_a_with_a_cabinet_unknown_to_the_config_still_pins(mdb_path, base):
    rows_a = copy.deepcopy(base.rows)
    res, rep = solve_incremental(mdb_path, rows_a, cfg=None)
    cfg = load_config()
    cfg.cabinets = cfg.cabinets[:2]                                    # config forgets the P24 cabinet; Rev A still has it
    res2, rep2 = solve_incremental(mdb_path, rows_a, cfg=cfg)
    assert rep2.mode == "pinned" and rep2.changes == [] and res2.rows == base.rows


def test_two_step_solve_revision(mdb_path):
    def change(h, rows):
        rows.pop(row_of(h, rows, "320-LT   -80002"))
    a, b, rep = solve_revision(mdb_path, edited(mdb_path, change))
    assert rep.counts["Deleted"] == 1 and rep.counts["Moved"] == 0 and a.readiness.status == "ISSUE-READY"


def test_a_pending_wired_spare_is_kept_when_nothing_changes(mdb_path, base):
    res, _ = solve_incremental(mdb_path, base.rows)
    before = sorted(r["Tag Name"] for r in base.rows if r["Tag Status"] == "Wired Spare")
    after = sorted(r["Tag Name"] for r in res.rows if r["Tag Status"] == "Wired Spare")
    assert before == after and before


def test_incremental_is_deterministic(mdb_path, base):
    def change(h, rows):
        rows.pop(row_of(h, rows, "320-LT   -80002"))
    data = edited(mdb_path, change)
    r1, _ = solve_incremental(data, base.rows)
    r2, _ = solve_incremental(data, base.rows)
    assert r1.rows == r2.rows

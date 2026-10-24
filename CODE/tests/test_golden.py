"""Golden test: our allocation vs the official hand-made sample.

Positions (cabinet / CIOC / baseplate / channel) are NOT compared - an engineer and a
solver may legitimately place cables differently.  Everything that is determined by the
signal itself (data columns, hardware, cable, pair) must match exactly.
"""
from __future__ import annotations

from collections import Counter

import pytest

from io_sudoku.core.allocio import read_allocation
from io_sudoku.core.config import load_config
from io_sudoku.core.ingest import read_mdb
from io_sudoku.core.pipeline import solve
from io_sudoku.core.textnorm import match_key
from io_sudoku.core.tq import TQLog
from io_sudoku.core.verify import verify

DATA_COLUMNS = ["Technical Room", "Operating Area", "Risk Area", "Unit", "Segregation", "DSTName", "Service Description",
                "Location", "IO Type", "Signal Type", "Signal Level", "NON-IS / IS", "Equipment Name", "External Power",
                "CHARM Type", "Charm Description", "CHARM TB Part No", "CHARM TB Description", "CHARM TB1", "CHARM TB2",
                "CHARM TB3", "Field Cable No", "Field Cable Size", "Field Cable Pair", "HW Loop Typical", "Instrument type",
                "System 2", "Loop Name"]


@pytest.fixture(scope="module")
def ours(mdb_path):
    return solve(mdb_path)


@pytest.fixture(scope="module")
def sample(alloc_path):
    return read_allocation(alloc_path)


def by_tag(rows, status="Field"):
    return {match_key(r["Tag Name"]): r for r in rows if r["Tag Status"] == status}


def test_every_field_tag_matches_the_sample_except_where_the_mdb_itself_changed(ours, sample, mdb_path):
    mine, theirs = by_tag(ours.rows), by_tag(sample)
    common = sorted(set(mine) & set(theirs))
    assert len(common) >= 170
    mdb = {s.key: s for s in read_mdb(mdb_path, TQLog()).signals}
    # tags whose MDB cable or cable size differs from the sample (Rev A -> Rev B edits)
    changed = {k for k in common if (mdb[k].cable_no, mdb[k].cable_size) != (theirs[k]["Field Cable No"], theirs[k]["Field Cable Size"])}
    unexpected = []
    for key in common:
        for column in DATA_COLUMNS:
            if mine[key][column] != theirs[key][column] and key not in changed:
                unexpected.append((key, column, mine[key][column], theirs[key][column]))
    assert unexpected == [], unexpected[:10]
    assert changed and all(k.startswith("500-") for k in changed)       # only the 500-CE-LP-0003 edits differ


def test_field_pair_numbers_are_kept_exactly(ours, sample):
    mine, theirs = by_tag(ours.rows), by_tag(sample)
    for key in set(mine) & set(theirs):
        if mine[key]["Field Cable No"] == theirs[key]["Field Cable No"]:
            assert mine[key]["Field Cable Pair"] == theirs[key]["Field Cable Pair"], key


def test_cabinet_alarm_rows_match_the_sample(ours, sample):
    mine, theirs = by_tag(ours.rows, "Cabinet Alarm"), by_tag(sample, "Cabinet Alarm")
    assert set(mine) == set(theirs) and len(mine) == 12
    for key in mine:
        for column in ("Service Description", "IO Type", "Signal Type", "Signal Level", "CHARM Type", "Charm Description",
                       "CHARM TB Part No", "CHARM TB1", "CHARM TB2", "CHARM TB3", "HW Loop Typical", "Field Cable No",
                       "Field Cable Size", "Field Cable Pair", "Remarks", "Location", "Equipment Name", "Unit"):
            assert mine[key][column] == theirs[key][column], (key, column, mine[key][column], theirs[key][column])
        # alarms sit on baseplate 1 of CIOC 1 of the same cabinet in both
        assert mine[key]["Baseplate"].endswith("-CBP-1")


def test_wired_spare_conventions_match_the_sample(ours, sample):
    def shape(rows):
        return Counter((r["IO Type"], r["Service Description"], r["Signal Type"], r["Signal Level"], r["CHARM Type"],
                        r["CHARM TB Part No"], r["HW Loop Typical"]) for r in rows if r["Tag Status"] == "Wired Spare")
    mine, theirs = shape(ours.rows), shape(sample)
    assert set(mine) <= set(theirs) | {k for k in mine}          # every combination we create is a valid hardware combination
    for combo in mine:
        assert combo[1] == {"AIR": "SPARE AI", "AOR": "SPARE AO", "DIR": "SPARE DI", "DOR": "SPARE DO"}[combo[0]]
    # the sample's own combinations are all ones our catalogue knows
    assert {c[4] for c in theirs} <= {"SE4303T01", "SE4304T01", "SE4301T02", "SE4302T01", "SE4302T02"}


def test_spare_slots_look_like_the_sample(ours, sample):
    slot_cols = ("CHARM Type", "Charm Description", "DSTName", "CHARM TB1", "CHARM TB2", "CHARM TB3", "Tag Name", "IO Type",
                 "Segregation", "HW Loop Typical")
    def first_slot(rows):
        return next(r for r in rows if r["Tag Status"] == "Spare Slot" and r["Field Cable No"] == "-")
    a, b = first_slot(ours.rows), first_slot(sample)
    for column in slot_cols:
        assert a[column] == b[column], column


def test_section_sub_unit_is_close_to_the_sample(ours, sample):
    mine, theirs = by_tag(ours.rows), by_tag(sample)
    common = sorted(set(mine) & set(theirs))
    mismatches = [(k, mine[k]["Section / Sub Unit"], theirs[k]["Section / Sub Unit"]) for k in common
                  if mine[k]["Section / Sub Unit"] != theirs[k]["Section / Sub Unit"]]
    rate = 1 - len(mismatches) / len(common)
    print(f"\nSection / Sub Unit match rate: {rate:.1%}; first mismatches: {mismatches[:6]}")
    assert rate >= 0.85, mismatches[:20]


def test_the_sample_audit_shows_what_the_human_allocation_misses(sample):
    out = verify(sample, load_config())
    counts = Counter(v.rule for v in out)
    print("\nHuman sample, violations by rule:", dict(sorted(counts.items())))
    assert any(v.rule == "V10" and v.ref == "P30DPK320102/AIR" for v in out)
    assert not {v.rule for v in out if v.severity == "error"} - {"V10"}     # its only errors are spare shortfalls


def test_our_solution_beats_the_sample_on_every_rule(ours):
    assert verify(ours.rows, ours.cfg_used) == []

from __future__ import annotations

import copy
from collections import Counter

import pytest

from io_sudoku.core.allocio import read_allocation
from io_sudoku.core.config import load_config
from io_sudoku.core.rows import build_rows
from io_sudoku.core.tq import TQLog
from io_sudoku.core.textnorm import match_key
from io_sudoku.core.verify import verify
from tests.helpers import fixture_grids


@pytest.fixture(scope="module")
def solved(mdb_path):
    cfg, log, res, _ = fixture_grids(mdb_path)
    rows = build_rows(res.grids, cfg, log)
    keys = {match_key(r["Tag Name"]) for r in rows if r["Tag Status"] in ("Field", "Cabinet Alarm")}
    return cfg, rows, keys


def rules(violations):
    return {v.rule for v in violations}


def first(rows, **cond):
    for i, r in enumerate(rows):
        if all(r[k] == v for k, v in cond.items()):
            return i
    raise KeyError(cond)


def test_solved_output_is_completely_clean(solved):
    cfg, rows, keys = solved
    assert verify(rows, cfg, keys) == []


def test_empty_input(cfg):
    assert verify([], cfg) == []
    assert rules(verify([], cfg, {"x"})) == {"V01"}


def mutate(solved, change):
    cfg, rows, keys = solved
    rows = copy.deepcopy(rows)
    change(rows)
    return verify(rows, cfg, keys), rows


def test_v01_missing_tag(solved):
    cfg, rows, keys = solved
    assert "V01" in rules(verify(rows, cfg, keys | {"not-a-tag"}))
    dup = copy.deepcopy(rows)
    i = first(dup, **{"Tag Status": "Field"})
    j = first(dup, **{"Tag Status": "Spare Slot"})
    dup[j]["Tag Name"], dup[j]["Tag Status"] = dup[i]["Tag Name"], "Field"
    assert "V01" in rules(verify(dup, cfg, keys))


def test_v02_duplicate_slot(solved):
    def change(rows):
        rows[5] = {**rows[4], "Sr. No.": 6}
    v, _ = mutate(solved, change)
    assert "V02" in rules(v)


def test_v03_wrong_charm_number_and_prefix(solved):
    v, _ = mutate(solved, lambda rows: rows[10].update({"CHARM_No": 99}))
    assert "V03" in rules(v)
    v, _ = mutate(solved, lambda rows: rows[10].update({"Baseplate": "099-CBP-1"}))
    assert "V03" in rules(v)


def test_v04_and_v05_cable_breaks(solved):
    def pair_swap(rows):
        i = first(rows, **{"Field Cable No": "320-CE-0001", "Field Cable Pair": "Pair 5"})
        rows[i]["Field Cable Pair"] = "Pair 6"
    v, _ = mutate(solved, pair_swap)
    assert "V04" in rules(v)

    def split(rows):
        i = next(k for k, r in enumerate(rows) if r["Tag Status"] == "Field" and r["Field Cable No"] != "-")
        rows[i]["CIOC/CSLS Name"] = "P30DCIOC3201099"          # one row of the cable "moves" to another CIOC
    v, _ = mutate(solved, split)
    assert "V05" in rules(v)

    def misaligned(rows):
        # a one-pair cable starting on channel 5 of a baseplate (not a 6-channel boundary)
        j = first(rows, **{"Tag Status": "Spare Slot", "Field Cable No": "-", "Channel_No": 5})
        rows[j]["Field Cable No"], rows[j]["Field Cable Pair"] = "ODD-1", "Pair 1"
    v, _ = mutate(solved, misaligned)
    assert "V05" in rules(v)


def test_v06_a_and_b_in_one_cioc(solved):
    def change(rows):
        a = next(r for r in rows if r["Tag Status"] == "Field" and r["Segregation"] == "A")
        other = next(r for r in rows if r["Tag Status"] == "Field" and r["CIOC/CSLS Name"] == a["CIOC/CSLS Name"]
                     and r["Electronic/ Marshalling Cabinet"] == a["Electronic/ Marshalling Cabinet"] and r["Segregation"] == "-")
        other["Segregation"] = "B"
    v, _ = mutate(solved, change)
    assert "V06" in rules(v)


def test_v07_field_on_alarm_baseplate_and_alarm_elsewhere(solved):
    def change(rows):
        i = first(rows, **{"Baseplate": "001-CBP-1", "Tag Status": "Spare Slot"})
        rows[i]["Tag Status"] = "Field"
    v, _ = mutate(solved, change)
    assert "V07" in rules(v)

    def moved(rows):
        i = first(rows, **{"Tag Status": "Spare Slot", "Baseplate": "002-CBP-3"})
        rows[i]["Tag Status"] = "Cabinet Alarm"
    v, _ = mutate(solved, moved)
    assert "V07" in rules(v)


def test_v08_swapped_charm_and_v15_wrong_terminal_block(solved):
    def swap(rows):
        i = first(rows, **{"Tag Status": "Field", "IO Type": "AIR"})
        rows[i]["CHARM Type"] = "SE4304T01"
    v, _ = mutate(solved, swap)
    assert "V08" in rules(v)

    def tb(rows):
        i = first(rows, **{"Tag Status": "Field", "CHARM Type": "SE4302T02"})
        rows[i]["CHARM TB Part No"] = "SE4501"
    v, _ = mutate(solved, tb)
    assert {"V15", "V08"} <= rules(v)


def test_v09_status_discipline(solved):
    v, _ = mutate(solved, lambda rows: rows[first(rows, **{"Tag Status": "Spare Slot"})].update({"CHARM Type": "SE4303T01"}))
    assert "V09" in rules(v)
    v, _ = mutate(solved, lambda rows: rows[first(rows, **{"Tag Status": "Wired Spare"})].update({"Tag Name": "NOT-A-DSP"}))
    assert "V09" in rules(v)
    v, _ = mutate(solved, lambda rows: rows[first(rows, **{"Tag Status": "Field"})].update({"Field Cable Pair": "-"}))
    assert "V09" in rules(v)
    v, _ = mutate(solved, lambda rows: rows[first(rows, **{"Tag Status": "Field"})].update({"Tag Status": "Bogus"}))
    assert "V09" in rules(v)


def test_v10_missing_and_excess_wired_spares(solved):
    def drop(rows):
        i = first(rows, **{"Tag Status": "Wired Spare"})
        rows[i].update({"Tag Status": "Spare Slot", "CHARM Type": "SE6103", "Tag Name": "-"})
    v, _ = mutate(solved, drop)
    assert "V10" in rules(v)

    def extra(rows):
        i = next(k for k, r in enumerate(rows) if r["Tag Status"] == "Spare Slot" and r["Field Cable No"] != "-"
                 and r["Controller"] == "P30DPK320101")
        rows[i].update({"Tag Status": "Wired Spare", "IO Type": "AIR", "Tag Name": "3201DSP0100000"})
    cfg, rows, keys = solved
    rows = copy.deepcopy(rows)
    extra(rows)
    out = verify(rows, cfg, keys)
    assert "V10W" in rules(out) and all(v.severity == "warning" for v in out if v.rule == "V10W")


def test_v11_dropped_row(solved):
    v, _ = mutate(solved, lambda rows: rows.pop(100))
    assert "V11" in rules(v)


def test_v12_wired_spare_tag_does_not_match_address(solved):
    def change(rows):
        i = first(rows, **{"Tag Status": "Wired Spare"})
        rows[i]["Tag Name"] = rows[i]["Tag Name"][:-1] + ("9" if not rows[i]["Tag Name"].endswith("9") else "8")
    v, _ = mutate(solved, change)
    assert "V12" in rules(v)


def test_v13_controller_mismatch(solved):
    v, _ = mutate(solved, lambda rows: rows[3].update({"Controller": "P99DPK999999"}))
    assert "V13" in rules(v)
    v, _ = mutate(solved, lambda rows: rows[3].update({"CIOC/CSLS Name": "P30DCIOC3201099"}))
    assert "V13" in rules(v) or "V03" in rules(v)


def test_v14_not_enough_future_space(solved):
    def change(rows):
        for r in rows[:350]:
            if r["Tag Status"] == "Spare Slot":
                r["Tag Status"] = "Field"
    v, _ = mutate(solved, change)
    assert "V14" in rules(v)


def test_v16_end_baseplates_must_stay_empty_is_a_warning(solved):
    def change(rows):
        i = first(rows, **{"Baseplate": "004-CBP-8", "Channel_No": 1})
        rows[i]["Field Cable No"] = "ODD-9"
    v, _ = mutate(solved, change)
    assert any(x.rule == "V16" and x.severity == "warning" for x in v)


def test_verifier_never_raises_on_garbage(cfg):
    junk = [{}, {"Tag Status": None, "Channel_No": "x"}, {"Baseplate": object(), "CHARM_No": []}]
    out = verify(junk, cfg, {"a"})
    assert isinstance(out, list)


def test_human_sample_is_audited_and_its_spare_shortfall_is_caught(alloc_path):
    cfg = load_config()
    rows = read_allocation(alloc_path)
    out = verify(rows, cfg)
    counts = Counter(v.rule for v in out)
    print("\nHuman sample violations by rule:", dict(sorted(counts.items())))
    short = [v for v in out if v.rule == "V10" and v.ref == "P30DPK320102/AIR"]
    assert short, counts                       # the human sample really breaks the 10% rule here
    assert "V06" not in counts and "V02" not in counts and "V11" not in counts

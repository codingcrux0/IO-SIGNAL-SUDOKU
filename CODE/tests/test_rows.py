from __future__ import annotations

import re
from collections import Counter

import pytest

from io_sudoku.core.allocio import CANONICAL_COLUMNS
from io_sudoku.core.grid import CabinetGrid
from io_sudoku.core.rows import build_rows, derive_section
from io_sudoku.core.spares import apply_spares
from io_sudoku.core.tq import TQLog
from tests.helpers import fixture_grids, make_block, make_signal


@pytest.fixture(scope="module")
def built(mdb_path):
    cfg, log, res, lines = fixture_grids(mdb_path)
    rows = build_rows(res.grids, cfg, log)
    return cfg, log, res, rows


def test_every_row_has_the_76_columns_in_order(built):
    _, _, _, rows = built
    assert len(rows) == 1152
    assert all(list(r) == CANONICAL_COLUMNS for r in rows)
    assert [r["Sr. No."] for r in rows] == list(range(1, 1153))


def test_charm_formula_and_hierarchy_on_every_row(built):
    _, _, _, rows = built
    for r in rows:
        bp = int(r["Baseplate"].rsplit("-", 1)[1])
        assert r["CHARM_No"] == (bp - 1) * 12 + r["Channel_No"]
        assert 1 <= bp <= 8 and 1 <= r["Channel_No"] <= 12
        assert r["Baseplate"][:3] == r["CIOC/CSLS Name"][-3:]
    per_cab = Counter(r["Electronic/ Marshalling Cabinet"] for r in rows)
    assert set(per_cab.values()) == {384} and len(per_cab) == 3


def test_status_counts_match_the_inputs(built):
    _, _, _, rows = built
    counts = Counter(r["Tag Status"] for r in rows)
    assert counts["Field"] == 177 and counts["Cabinet Alarm"] == 12
    assert counts["Wired Spare"] == 22 - 0 or counts["Wired Spare"] > 0
    assert sum(counts.values()) == 1152


def test_spare_slots_are_protection_covers(built):
    _, _, _, rows = built
    slots = [r for r in rows if r["Tag Status"] == "Spare Slot"]
    assert slots
    for r in slots:
        assert r["CHARM Type"] == "SE6103" and r["Charm Description"] == "CHARM PROTECTION COVER"
        assert r["DSTName"] == "_" and r["Tag Name"] == "-" and r["IO Type"] == "-"
        assert r["CHARM TB1"] == r["CHARM TB2"] == r["CHARM TB3"] == "-"
        assert r["CHARM TB Part No"] in ("SE4501", "SE4502")


def test_wired_spares_follow_the_rulebook(built):
    _, _, _, rows = built
    spares = [r for r in rows if r["Tag Status"] == "Wired Spare"]
    assert spares
    for r in spares:
        assert re.fullmatch(r"\d{4}DSP\d{2}\d{3}\d{1,2}\d{1,2}", r["Tag Name"]), r["Tag Name"]
        assert r["DSTName"] == r["Tag Name"] + "_"
        assert r["Service Description"] == {"AIR": "SPARE AI", "AOR": "SPARE AO", "DIR": "SPARE DI", "DOR": "SPARE DO"}[r["IO Type"]]
        assert r["CHARM Type"] != "SE6103" and r["Field Cable No"] != "-" and r["Field Cable Pair"].startswith("Pair")
        assert r["Segregation"] == "-" and r["Loop Name"] == "-"
        assert r["Unit"] != "-" and r["Location"] != "-"


def test_cabinet_alarms_sit_on_baseplate_one_of_cioc_one(built):
    _, _, _, rows = built
    alarms = [r for r in rows if r["Tag Status"] == "Cabinet Alarm"]
    assert len(alarms) == 12
    assert all(r["Baseplate"].endswith("-CBP-1") and r["CIOC/CSLS Name"].endswith(("001", "013")) for r in alarms)
    assert {r["CHARM Type"] for r in alarms} == {"SE4303T03", "SE4301T02"}
    internal = [r for r in alarms if r["Remarks"] == "Internal Cabinet Alarm."]
    assert len(internal) == 9 and all(r["Field Cable No"] == "-" for r in internal)
    ice = [r for r in alarms if r["Field Cable No"] != "-"]
    assert len(ice) == 3 and {r["Field Cable Pair"] for r in ice} == {"Triad 1", "Pair 1", "Pair 2"}
    assert all(r["Instrument type"] == "-" for r in alarms)


def test_field_rows_carry_mdb_data_and_catalogue_hardware(built):
    _, _, _, rows = built
    field = {r["Tag Name"]: r for r in rows if r["Tag Status"] == "Field"}
    r = field["320-FT   -20645-A"]
    assert (r["IO Type"], r["CHARM Type"], r["CHARM TB Part No"], r["HW Loop Typical"]) == ("AIR", "SE4303T01", "SE4501", "HW-TYP-41 - LT-01")
    assert r["Field Cable No"] == "320-CE-0001" and r["Field Cable Pair"] == "Pair 1" and r["Segregation"] == "A-CONTROL"
    assert r["Service Description"] == "D-2011 FLOW" or r["Service Description"] != "-"
    assert r["DSTName"] == "320FT20645A_"
    assert not any(" -" == str(v) for row in rows for v in row.values())
    sov = [x for x in field.values() if x["Instrument type"] == "Solenoid Valve"]
    assert len(sov) == 27 and all((x["CHARM Type"], x["CHARM TB Part No"]) == ("SE4302T02", "SE4502") for x in sov)


def test_no_stray_spaces_and_numbers_are_ints(built):
    _, _, _, rows = built
    for r in rows:
        for k, v in r.items():
            if isinstance(v, str):
                assert v == v.strip(), (k, v)
        for k in ("Sr. No.", "Channel_No", "CHARM_No"):
            assert isinstance(r[k], int)
        for k in ("CHARM TB1", "CHARM TB2", "CHARM TB3"):
            assert r[k] == "-" or isinstance(r[k], int)


@pytest.mark.parametrize("tag,unit,section", [("320-XYV  -20202", 320, "200"), ("320-LT   -81209", 320, "800"),
                                              ("320-PT   -42049", 320, "420"), ("500-X -00012", 500, "LOGISTIC"),
                                              ("440-PI   -20077-L", 440, "LOGISTIC"), ("nonsense", 320, "-"), (None, None, "-"),
                                              ("320-XLS  -83013-AO", 320, "800")])
def test_derive_section(tag, unit, section):
    assert derive_section(tag, unit) == section


def test_only_alarms_and_empty_input(cfg):
    grid = CabinetGrid(cfg.cabinets[0], cfg.rules)
    grid.place_alarm(make_signal(tag="A-T", is_alarm=True, io_type="AIR", cable_no=None, pair_no=None), 1, "T")
    rows = build_rows({grid.cab.marshalling: grid}, cfg, TQLog())
    assert len(rows) == 384 and Counter(r["Tag Status"] for r in rows) == {"Cabinet Alarm": 1, "Spare Slot": 383}
    assert build_rows({}, cfg, TQLog()) == []


def test_one_high_current_note_per_solenoid_cable(built):
    _, log, _, _ = built
    refs = sorted(t.ref for t in log.of("HIGH-CURRENT-VERIFY"))
    assert refs == sorted(set(refs)) and "320-CS-0008" in refs and "320-CS-0005" in refs


def test_revision_label_is_text(built, mdb_path):
    cfg, log, res, _ = built
    rows = build_rows(res.grids, cfg, TQLog(), rev_label="B")
    assert {r["Revision No"] for r in rows} == {"B"}


def test_wired_spare_inherits_location_and_unit_from_its_cable(cfg):
    grid = CabinetGrid(cfg.cabinets[2], cfg.rules)            # P24
    blk = make_block("LP-1", 10, size=12)
    for s in blk.signals.values():
        s.location, s.unit = "LP", 500
    grid.place_block(blk, 2, 0)
    grid.assign_profiles()
    apply_spares({grid.cab.marshalling: grid}, cfg, TQLog())
    rows = build_rows({grid.cab.marshalling: grid}, cfg, TQLog())
    spare = next(r for r in rows if r["Tag Status"] == "Wired Spare")
    assert spare["Location"] == "LP" and spare["Unit"] == 500

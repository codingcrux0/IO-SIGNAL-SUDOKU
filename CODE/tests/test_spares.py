from __future__ import annotations

import re

import pytest

from io_sudoku.core.cables import build_blocks, link_groups
from io_sudoku.core.config import load_config
from io_sudoku.core.grid import CabinetGrid
from io_sudoku.core.ingest import read_mdb
from io_sudoku.core.place import plan_and_place
from io_sudoku.core.spares import apply_spares, quota
from io_sudoku.core.tq import TQLog
from io_sudoku.core.validate import validate
from tests.helpers import make_block


@pytest.fixture()
def setup(cfg):
    grid = CabinetGrid(cfg.cabinets[0], cfg.rules)
    return grid, cfg, TQLog()


def finish(grid, cfg, log):
    grid.assign_profiles(log)
    return apply_spares({grid.cab.marshalling: grid}, cfg, log, {})


def wired_cells(grid, io=None):
    return [c for c in grid.cells.values() if c.status == "Wired Spare" and (io is None or c.io_type == io)]


@pytest.mark.parametrize("n,expected", [(42, 5), (5, 1), (0, 0), (11, 2), (10, 1), (1, 1), (20, 2), (24, 3), (7, 1), (100, 10), (101, 11)])
def test_quota_is_ceil_ten_percent(n, expected):
    assert quota(n) == expected
    assert quota(n, 15) == -(-n * 15 // 100)


def test_exactly_the_quota_is_converted_from_the_lowest_free_pairs(setup):
    grid, cfg, log = setup
    grid.place_block(make_block("C1", 20, size=24), 2, 0)                 # 20 AIR signals, pairs 21-24 free
    lines = finish(grid, cfg, log)
    air = next(l for l in lines if l.io_type == "AIR")
    assert (air.field, air.quota, air.wired, air.shortfall, air.excess) == (20, 2, 2, 0, 0)
    assert sorted(c.pair_no for c in wired_cells(grid, "AIR")) == [21, 22]
    assert len(wired_cells(grid)) == 2                                     # nothing else was converted
    assert not log.has("SPARE-SHORTFALL")
    spare = grid.cells[(2, 2, 9)]                                          # pair 21 = channel 21 -> bp 2, ch 9
    assert spare.status == "Wired Spare" and spare.profile == "AIR_2W"
    assert re.fullmatch(r"3201DSP0100229", spare.dsp)                      # 3201 DSP 01 002 2 9


def test_dsp_tag_matches_the_official_pattern(setup):
    grid, cfg, log = setup
    grid.place_block(make_block("C1", 20, size=24), 3, 0)
    finish(grid, cfg, log)
    assert {c.dsp for c in wired_cells(grid)} == {"3201DSP0100329", "3201DSP01003210"}


def test_existing_wired_spares_count_toward_the_quota(setup):
    grid, cfg, log = setup
    grid.place_block(make_block("C1", 20, size=24), 2, 0)
    for cell in [grid.cells[(2, 2, 9)], grid.cells[(2, 2, 10)]]:
        cell.status, cell.io_type, cell.profile, cell.dsp = "Wired Spare", "AIR", "AIR_2W", "OLD"
    lines = finish(grid, cfg, log)
    assert len(wired_cells(grid)) == 2 and next(l for l in lines if l.io_type == "AIR").shortfall == 0


def test_excess_spares_are_reported_not_removed(setup):
    grid, cfg, log = setup
    grid.place_block(make_block("C1", 10, size=24), 2, 0)               # quota 1
    for ch in (11, 12):
        c = grid.cells[(2, 1, ch)]
        c.status, c.io_type, c.profile, c.dsp = "Wired Spare", "AIR", "AIR_2W", f"OLD{ch}"
    air = next(l for l in finish(grid, cfg, log) if l.io_type == "AIR")
    assert (air.wired, air.excess, air.shortfall) == (2, 1, 0)


def test_dor_spare_in_a_solenoid_cable_is_high_current(setup):
    grid, cfg, log = setup
    grid.place_block(make_block("S1", 10, size=12, io="DOR", instrument="Solenoid Valve", code="XYV"), 2, 0)
    finish(grid, cfg, log)
    spare = wired_cells(grid, "DOR")[0]
    assert spare.profile == "DOR_T02"


def test_a_spare_of_another_type_in_a_solenoid_cable_still_gets_the_right_hardware(setup):
    grid, cfg, log = setup
    grid.place_block(make_block("S1", 10, size=12, io="DOR", instrument="Solenoid Valve", code="XYV"), 2, 0)
    grid.place_block(make_block("I1", 10, size=12, io="DIR"), 2, 12)
    finish(grid, cfg, log)
    assert {c.profile for c in wired_cells(grid, "DIR")} == {"DIR"}


def test_no_free_pairs_gives_a_shortfall_tq_and_no_crash(setup):
    grid, cfg, log = setup
    grid.place_block(make_block("C1", 12, size=12), 2, 0)               # cable completely full
    lines = finish(grid, cfg, log)
    assert log.has("SPARE-SHORTFALL") and wired_cells(grid) == []
    air = next(l for l in lines if l.io_type == "AIR")
    assert (air.quota, air.wired, air.shortfall) == (2, 0, 2)
    assert [t.ref for t in log.of("SPARE-SHORTFALL")] == ["P30DPK320101/AIR"]


def test_freed_pair_of_same_io_type_is_preferred(setup):
    grid, cfg, log = setup
    grid.place_block(make_block("A1", 12, size=24), 2, 0)               # pairs 13-24 free
    grid.cells[(2, 2, 6)].former_io = "AIR"                              # pair 18 used to hold an AIR tag
    finish(grid, cfg, log)
    assert 18 in {c.pair_no for c in wired_cells(grid, "AIR")}


def test_pair_in_a_cable_that_already_carries_the_type_is_preferred(setup):
    grid, cfg, log = setup
    grid.place_block(make_block("A1", 10, size=12, io="AIR"), 2, 0)       # AIR cable, 2 free pairs
    grid.place_block(make_block("D1", 4, size=12, io="DIR"), 2, 12)       # DIR cable, 8 free pairs
    finish(grid, cfg, log)
    assert {c.cable_no for c in wired_cells(grid, "AIR")} == {"A1"}


def test_alarms_do_not_count_as_field_signals(setup):
    from tests.helpers import make_signal
    grid, cfg, log = setup
    grid.place_alarm(make_signal(tag="X-T", is_alarm=True, io_type="AIR", cable_no=None, pair_no=None), 1, "T")
    lines = finish(grid, cfg, log)
    assert all(l.field == 0 and l.quota == 0 for l in lines)


def test_end_reserve_and_alarm_baseplate_are_never_converted(cfg):
    cfg.rules.auto_expand = False
    cfg.cabinets = [cfg.cabinets[0]]
    log = TQLog()
    blocks = [make_block(f"G{i:02d}", 20, size=24, group=0, logic="L") for i in range(14)]    # forces the end reserve
    res = plan_and_place(blocks, [], cfg, log)
    grid = next(iter(res.grids.values()))
    assert log.has("FUTURE-SPACE-MISS")
    apply_spares(res.grids, cfg, log)
    for (cioc, bp, ch), cell in grid.cells.items():
        if cell.status == "Wired Spare":
            assert not (cioc == 1 and bp == 1) and not (cioc == 4 and bp >= 5)


def test_spare_percentage_comes_from_the_rules(setup):
    grid, cfg, log = setup
    cfg.rules.spare_pct = 20
    grid.place_block(make_block("C1", 20, size=24), 2, 0)
    finish(grid, cfg, log)
    assert len(wired_cells(grid)) == 4


def test_traces_explain_each_spare(setup):
    grid, cfg, log = setup
    grid.place_block(make_block("C1", 20, size=24), 2, 0)
    traces: dict = {}
    grid.assign_profiles(log)
    apply_spares({grid.cab.marshalling: grid}, cfg, log, traces)
    lines = traces["3201dsp0100229"]
    assert "Wired spare AIR: quota 2, had 0" in lines[0] and "C1 pair 21" in lines[0]


def test_fixture_meets_every_quota_exactly(mdb_path):
    cfg, log = load_config(), TQLog()
    ing = read_mdb(mdb_path, log)
    v = validate(ing, cfg, log)
    blocks, _ = build_blocks(v.accepted, v.size_by_cable, cfg, log)
    link_groups(blocks)
    res = plan_and_place(blocks, v.alarms, cfg, log)
    lines = apply_spares(res.grids, cfg, log)
    assert len(lines) == 12 and all(l.shortfall == 0 and l.wired == l.quota and l.excess == 0 for l in lines)
    assert not log.has("SPARE-SHORTFALL")
    total_field = sum(l.field for l in lines)
    assert total_field == 177

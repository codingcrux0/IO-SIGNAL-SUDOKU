from __future__ import annotations

import pytest

from io_sudoku.core.cables import block_length, build_blocks, family_of, link_groups
from io_sudoku.core.config import RulesCfg, load_config
from io_sudoku.core.grid import CabinetGrid
from io_sudoku.core.ingest import read_mdb
from io_sudoku.core.tq import TQLog
from io_sudoku.core.validate import validate
from tests.helpers import make_block, make_signal


# ----------------------------------------------------------------------------- cables
@pytest.mark.parametrize("declared,length", [(1, 6), (4, 6), (6, 6), (7, 12), (12, 12), (13, 24), (18, 24), (24, 24), (36, 36), (96, 96)])
def test_block_length(declared, length):
    assert block_length(declared) == length


def test_family_mapping():
    r = RulesCfg()
    assert [family_of(c, r) for c in ("A", "a", "A-CONTROL", "B", "B-ALARM", "C", "D", "E", "-", None, "")] == \
        ["A", "A", "A", "B", "B", None, None, None, None, None, None]


def test_mixed_a_and_b_cable_is_quarantined():
    cfg, log = load_config(), TQLog()
    sigs = [make_signal(tag="A1", segregation="A", pair_no=1), make_signal(tag="B1", segregation="B", pair_no=2)]
    blocks, bad = build_blocks(sigs, {"c-1": 12}, cfg, log)
    assert blocks == [] and {q.tq_id for q in bad} == {"MIXED-SEGREGATION"} and len(bad) == 2


def test_cable_too_large_and_two_rooms_and_rounding():
    cfg, log = load_config(), TQLog()
    blocks, bad = build_blocks([make_signal(pair_no=1)], {"c-1": 120}, cfg, log)
    assert blocks == [] and bad[0].tq_id == "CABLE-TOO-LARGE"
    sigs = [make_signal(tag="A", pair_no=1, tech_room="PIB-30"), make_signal(tag="B", pair_no=2, tech_room="PIB-24")]
    blocks, bad = build_blocks(sigs, {"c-1": 12}, cfg, log)
    assert blocks == [] and bad[0].tq_id == "GROUP-SPANS-ROOMS"
    log2 = TQLog()
    blocks, _ = build_blocks([make_signal(pair_no=1)], {"c-1": 18}, cfg, log2)
    assert blocks[0].length == 24 and log2.has("CABLE-SIZE-ROUNDED")


def test_union_find_groups_by_shared_logic_number():
    blocks = [make_block("C-A", 3, group=-1, logic="L1"), make_block("C-B", 3, logic="L2"),
              make_block("C-C", 3, logic="L1"), make_block("C-D", 3), make_block("C-E", 3, logic="L2")]
    blocks.sort(key=lambda b: b.key)
    link_groups(blocks)
    groups = {}
    for b in blocks:
        groups.setdefault(b.group_id, set()).add(b.cable_no)
    assert sorted(map(sorted, groups.values())) == [["C-A", "C-C"], ["C-B", "C-E"], ["C-D"]]
    assert sorted(groups) == [0, 1, 2]
    assert blocks[0].group_id == 0 and blocks[1].group_id == 1      # ranked by smallest cable key


def test_group_spanning_rooms_is_marked():
    a, b = make_block("C-A", 3, logic="L1", room="PIB-30"), make_block("C-B", 3, logic="L1", room="PIB-24")
    log = TQLog()
    link_groups([a, b], log)
    assert a.group_id == b.group_id == -2 and log.has("GROUP-SPANS-ROOMS")


def test_fixture_has_exactly_the_ten_expected_groups(mdb_path):
    cfg, log = load_config(), TQLog()
    ing = read_mdb(mdb_path, log)
    v = validate(ing, cfg, log)
    blocks, bad = build_blocks(v.accepted, v.size_by_cable, cfg, log)
    assert bad == [] and len(blocks) == 15
    link_groups(blocks)
    groups = {}
    for b in blocks:
        groups.setdefault(b.group_id, set()).add(b.cable_no)
    got = {frozenset(g) for g in groups.values()}
    expected = {frozenset(x) for x in (
        {"320-CE-0001", "320-CE-0004"}, {"320-CE-0035"}, {"320-CE-0040"}, {"320-CE-0045", "320-CS-0005"},
        {"320-CE-0083", "320-CE-0087"}, {"320-CS-0008"}, {"320-CS-0022"}, {"500-CE-0013"},
        {"500-CE-0015", "500-CE-LP-0003-A", "500-CE-LP-0003-B"}, {"OS02-ICE-6001"})}
    assert got == expected and len(groups) == 10
    by = {b.cable_no: b for b in blocks}
    assert by["320-CE-0001"].declared_pairs == 24 and by["320-CE-0001"].length == 24
    assert by["320-CE-0035"].length == 6
    again = build_blocks(v.accepted, v.size_by_cable, cfg, TQLog())[0]
    link_groups(again)
    assert [b.group_id for b in again] == [b.group_id for b in blocks]


# ------------------------------------------------------------------------------- grid
@pytest.fixture()
def grid(cfg):
    return CabinetGrid(cfg.cabinets[0], cfg.rules)


def test_geometry(grid):
    assert CabinetGrid.pos_to_bp_ch(0) == (1, 1)
    assert CabinetGrid.pos_to_bp_ch(11) == (1, 12)
    assert CabinetGrid.pos_to_bp_ch(12) == (2, 1)
    assert CabinetGrid.pos_to_bp_ch(95) == (8, 12)
    assert grid.is_alarm_pos(1, 11) and not grid.is_alarm_pos(1, 12) and not grid.is_alarm_pos(2, 0)
    assert grid.is_end_reserved(4, 48) and not grid.is_end_reserved(4, 47) and not grid.is_end_reserved(3, 90)


def test_field_cables_never_use_the_alarm_baseplate(grid):
    b = make_block("C1", 12)
    assert grid.find_run(b, 1) == 12            # CIOC 1 starts after baseplate 1
    assert grid.find_run(b, 2) == 0
    with pytest.raises(ValueError):
        grid.place_block(b, 1, 0)


def test_alignment_of_runs(grid):
    six, twelve, twentyfour = make_block("S", 6), make_block("T", 12), make_block("U", 24)
    assert grid.find_run(six, 2) == 0
    grid.place_block(six, 2, 0)
    assert grid.find_run(make_block("S2", 6), 2) == 6        # second half of the same baseplate
    grid.place_block(make_block("S2", 6), 2, 6)
    assert grid.find_run(twelve, 2) == 12                     # next whole baseplate
    assert grid.find_run(twentyfour, 2) == 12
    start = grid.find_run(twentyfour, 2)
    grid.place_block(twentyfour, 2, start)
    assert start % 12 == 0
    bp, ch = grid.pos_to_bp_ch(start + 12)                    # pair 13 -> next baseplate, channel 1
    assert (bp, ch) == (3, 1)
    assert grid.cells[(2, bp, ch)].pair_no == 13


def test_pair_maps_to_channel_and_unused_pairs_are_reserved(grid):
    b = make_block("C1", [1, 2, 5], size=12)
    grid.place_block(b, 2, 0)
    assert grid.cells[(2, 1, 1)].status == "Field" and grid.cells[(2, 1, 1)].pair_no == 1
    assert grid.cells[(2, 1, 5)].signal.tag == "C1-5"
    unused = grid.cells[(2, 1, 3)]
    assert unused.status == "Spare Slot" and unused.pair_no == 3 and unused.cable_no == "C1"
    assert unused.pair_text == "Pair 3"
    assert grid.used_channels() == 12


def test_a_24_pair_cable_never_fits_in_scattered_slots(grid):
    # CIOC 2: occupy baseplates 1, 3, 4, 6 and 8, leaving only baseplates 2, 5 and 7 free.
    # That is 36 free slots, but never two whole baseplates in a row.
    for i, start in enumerate((0, 24, 36, 60, 84)):
        grid.place_block(make_block(f"X{i}", 12), 2, start)
    assert grid.find_run(make_block("BIG", 24), 2) is None      # a 24-pair cable is never split
    assert grid.find_run(make_block("MID", 12), 2) == 12        # a 12-pair cable still fits
    assert grid.find_run(make_block("LOW", 6), 2) == 12


def test_end_reserve_is_kept_empty_unless_allowed(grid):
    big = make_block("B", 12)
    # fill CIOC 4 baseplates 1-4
    for i in range(4):
        grid.place_block(make_block(f"Z{i}", 12), 4, i * 12)
    assert grid.find_run(big, 4) is None                       # only the reserve is left
    assert grid.find_run(big, 4, allow_reserved=True) == 48    # forced use of the reserve


def test_family_is_derived_and_follows_removal(grid):
    a = make_block("A1", 12, family="A")
    grid.place_block(a, 2, 0)
    assert grid.cioc_family(2) == "A" and grid.cioc_family(3) is None
    grid.place_block(make_block("N1", 12), 2, 12)               # neutral does not change it
    assert grid.cioc_family(2) == "A"
    grid.remove_block("a1")
    assert grid.cioc_family(2) is None
    assert grid.used_channels() == 12


def test_remove_block_clears_cells_and_occupancy(grid):
    b = make_block("C1", 12)
    grid.place_block(b, 3, 0)
    grid.remove_block("c1")
    assert grid.cells == {} and not any(grid.occ[3]) and grid.placements == {}
    grid.remove_block("nope")        # harmless
    grid.place_block(b, 3, 0)        # can be placed again


def test_place_errors(grid):
    b = make_block("C1", 12)
    grid.place_block(b, 2, 0)
    for args in ((b, 2, 0), (make_block("C2", 12), 2, 0), (make_block("C3", 12), 2, 90), (make_block("C4", 12), 9, 0)):
        with pytest.raises(ValueError):
            grid.place_block(*args)


def test_alarm_cells_and_counts(grid):
    alarm = make_signal(tag="ALM-T", is_alarm=True, cable_no=None, pair_no=None, pair_text=None)
    grid.place_alarm(alarm, 1, "T")
    assert grid.cells[(1, 1, 1)].status == "Cabinet Alarm" and grid.cells[(1, 1, 1)].alarm_kind == "T"
    assert grid.used_channels() == 0          # alarms do not count as field channels
    with pytest.raises(ValueError):
        grid.place_alarm(alarm, 13, "T")
    assert grid.has_content()


def test_clone_is_independent(grid):
    grid.place_block(make_block("C1", 12), 2, 0)
    other = grid.clone()
    other.remove_block("c1")
    other.cells.clear()
    assert "c1" in grid.placements and len(grid.cells) == 12 and any(grid.occ[2])


def test_free_non_reserved_counts(grid):
    assert grid.free_non_reserved() == 324
    grid.place_block(make_block("C1", 24), 2, 0)
    assert grid.free_non_reserved() == 300


def test_triad_pair_labels(grid):
    b = make_block("ICE", [1], size=1)
    b.size_text = "1TX1.3MM2/FR/OS/NIS"
    b.signals[1] = make_signal(tag="ICE-1", pair_text=None, pair_no=1)
    grid.place_block(b, 2, 0)
    assert grid.cells[(2, 1, 1)].pair_text == "Triad 1"

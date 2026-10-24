from __future__ import annotations

import pytest

from io_sudoku.core.cables import build_blocks, link_groups
from io_sudoku.core.config import load_config
from io_sudoku.core.grid import CabinetGrid
from io_sudoku.core.ingest import read_mdb
from io_sudoku.core.place import alarm_kind, cioc_order, plan_and_place
from io_sudoku.core.tq import TQLog
from io_sudoku.core.validate import validate
from tests.helpers import make_block, make_signal


def plan(blocks, alarms=(), cfg=None, **kw):
    cfg = cfg or load_config()
    log = TQLog()
    res = plan_and_place(list(blocks), list(alarms), cfg, log, **kw)
    return res, log, cfg


def alarm(tag, equipment, cable=None, pair=None, row=2):
    return make_signal(tag=tag, equipment=equipment, is_alarm=True, cable_no=cable, pair_no=pair,
                       pair_text=None if pair is None else f"Pair {pair}", row_ref=row, io_type="DIR")


def placements(res):
    out = {}
    for cab, grid in res.grids.items():
        for key, (blk, cioc, start) in grid.placements.items():
            out[key] = (cab, cioc, start)
    return out


def one_cab_cfg(**rules):
    cfg = load_config()
    cfg.cabinets = [cfg.cabinets[0]]
    for k, v in rules.items():
        setattr(cfg.rules, k, v)
    return cfg


# ------------------------------------------------------------------ basic placement
def test_24_pair_cable_is_aligned_and_pair_13_starts_the_next_baseplate():
    res, _, _ = plan([make_block("C1", 24)])
    cab, cioc, start = placements(res)["c1"]
    grid = res.grids[cab]
    assert start % 12 == 0
    bp, ch = grid.pos_to_bp_ch(start + 12)
    assert grid.cells[(cioc, bp, ch)].pair_no == 13 and ch == 1


def test_two_six_pair_cables_share_one_baseplate():
    res, _, _ = plan([make_block("S1", 6, group=0), make_block("S2", 6, group=0)])
    p = placements(res)
    (c1, i1, s1), (c2, i2, s2) = p["s1"], p["s2"]
    assert c1 == c2 and i1 == i2 and abs(s1 - s2) == 6 and s1 // 12 == s2 // 12


def test_field_never_uses_the_alarm_baseplate_or_the_end_reserve():
    blocks = [make_block(f"C{i:02d}", 24, group=i) for i in range(5)] + [make_block(f"D{i}", 12, group=9 + i) for i in range(6)]
    res, _, _ = plan(blocks)
    for grid in res.grids.values():
        for (cioc, bp, ch), cell in grid.cells.items():
            if cell.status != "Cabinet Alarm":
                assert not (cioc == 1 and bp == 1)
            assert not (cioc == 4 and bp >= 5)      # end reserve empty in a normal run


def test_a_and_b_never_share_a_ciocand_prefer_1_2_and_3_4():
    blocks = []
    for i in range(5):
        blocks.append(make_block(f"A{i}", 12, family="A", group=i))
        blocks.append(make_block(f"B{i}", 12, family="B", group=10 + i))
    res, log, _ = plan(blocks)
    for grid in res.grids.values():
        for cioc in range(1, 5):
            fams = {b.family for b, c, _ in grid.placements.values() if c == cioc and b.family}
            assert len(fams) <= 1
    p = placements(res)
    assert all(p[f"a{i}"][1] in (1, 2) for i in range(5))
    assert all(p[f"b{i}"][1] in (3, 4) for i in range(5))
    assert not log.has("SEGREGATION-PREFERENCE-RELAXED")


def test_neutral_cables_do_not_push_a_cables_out_of_ciocs_1_and_2():
    blocks = [make_block(f"N{i}", 24, group=20 + i) for i in range(3)] + [make_block(f"A{i}", 24, family="A", group=i) for i in range(3)]
    res, _, _ = plan(blocks)
    p = placements(res)
    assert all(p[f"a{i}"][1] in (1, 2) for i in range(3))


def test_relaxed_preference_is_logged_but_hard_rule_still_holds():
    # CIOC 1 holds 84 free channels and CIOC 2 holds 96: seven 24-pair A cables need CIOC 3 as well.
    blocks = [make_block(f"A{i}", 24, family="A", group=i) for i in range(8)]
    blocks.append(make_block("B0", 12, family="B", group=50))
    res, log, _ = plan(blocks, cfg=one_cab_cfg())
    grid = next(iter(res.grids.values()))
    assert log.has("SEGREGATION-PREFERENCE-RELAXED")
    assert {c for b, c, _ in grid.placements.values() if b.family == "A"} & {3, 4}
    for cioc in range(1, 5):
        assert len({b.family for b, c, _ in grid.placements.values() if c == cioc and b.family}) <= 1


def test_a_logic_group_stays_in_one_cabinet():
    blocks = [make_block("G1", 24, group=0, logic="L"), make_block("G2", 24, group=0, logic="L"),
              make_block("X1", 24, group=1), make_block("X2", 24, group=2)]
    res, _, _ = plan(blocks)
    p = placements(res)
    assert p["g1"][0] == p["g2"][0]
    assert len({v[0] for v in p.values()}) == 2        # worst-fit decreasing spreads load


def test_worst_fit_balances_two_cabinets():
    blocks = [make_block(f"C{i}", 24, group=i) for i in range(4)]
    res, _, _ = plan(blocks)
    counts = [len(g.placements) for g in res.grids.values()]
    assert counts == [2, 2]


def test_group_hint_keeps_a_group_in_its_old_cabinet(cfg):
    blocks = [make_block("C1", 24, group=0)]
    res, _, _ = plan(blocks, cfg=cfg, group_cabinet_hint={0: "P30-DCM-32001-04"})
    assert list(res.grids) == ["P30-DCM-32001-04"]


# ---------------------------------------------------------------------------- alarms
def test_alarm_kind():
    assert alarm_kind("320-EJA  -01001-T") == "T" and alarm_kind("x-ac") == "AC" and alarm_kind("x-DC") == "DC"
    assert alarm_kind("320-EJA  -01001") is None and alarm_kind(None) is None


def test_six_alarms_fill_channels_1_to_6_in_order():
    alarms = [alarm("S-DC", "P30-DCS-32001-01", row=2), alarm("S-T", "P30-DCS-32001-01", row=3),
              alarm("M-AC", "P30-DCM-32001-01", row=4), alarm("M-DC", "P30-DCM-32001-01", row=5),
              alarm("M-T", "P30-DCM-32001-01", row=6), alarm("S-AC", "P30-DCS-32001-01", row=7)]
    res, log, _ = plan([], alarms)
    grid = res.grids["P30-DCM-32001-01"]
    order = [grid.cells[(1, 1, ch)].signal.tag for ch in range(1, 7)]
    assert order == ["M-T", "M-AC", "M-DC", "S-T", "S-AC", "S-DC"]       # marshalling first, then system; T, AC, DC
    assert res.alarms_unplaced == [] and grid.used_channels() == 0


def test_thirteen_alarms_overflow():
    alarms = [alarm(f"A{i:02d}-T", "P30-DCM-32001-01", row=i + 2) for i in range(13)]
    res, log, _ = plan([], alarms)
    assert log.has("ALARM-OVERFLOW") and len(res.alarms_unplaced) == 1
    assert sum(1 for c in res.grids["P30-DCM-32001-01"].cells.values() if c.status == "Cabinet Alarm") == 12


def test_alarm_problems_become_tqs():
    res, log, _ = plan([], [alarm("X-T", "NO-SUCH-CABINET"), alarm("Y", "P30-DCM-32001-01")])
    assert log.has("NO-CABINET-FOR-ALARM") and log.has("ALARM-UNKNOWN-KIND") and len(res.alarms_unplaced) == 2
    assert res.grids == {}


def test_missing_system_cabinet_alarms_are_reported():
    alarms = [alarm("M-T", "P30-DCM-32001-01")]
    res, log, _ = plan([], alarms)
    assert [t.ref for t in log.of("ALARMS-MISSING-FOR-CABINET")] == ["P30-DCS-32001-01"]


# ----------------------------------------------------------------------- the ladder
def _prefill(cfg, per_cab_channels=48):
    """Grids that already hold some cables, so cabinets look partly full."""
    grids = {}
    for cab in cfg.cabinets_in_room("PIB-30"):
        grid = CabinetGrid(cab, cfg.rules)
        for i in range(per_cab_channels // 24):
            blk = make_block(f"PRE-{cab.cabinet_seq}-{i}", 24, group=100 + i)
            grid.place_block(blk, 2, i * 24)
        grids[cab.marshalling] = grid
    return grids


def test_group_that_fits_no_existing_cabinet_goes_to_a_new_one():
    cfg = load_config()
    grids = _prefill(cfg)
    group = [make_block(f"G{i:02d}", 24, group=0, logic="L") for i in range(12)] + [make_block("G12", 12, group=0, logic="L")]
    assert sum(b.length for b in group) == 300
    res, log, cfg = plan(group, cfg=cfg, prebuilt=grids)
    assert res.unplaced == [] and log.has("CABINET-AUTO-ADDED") and not log.has("FUTURE-SPACE-MISS")
    assert "P30-DCM-32001-05" in res.grids
    assert {v[0] for k, v in placements(res).items() if k.startswith("g")} == {"P30-DCM-32001-05"}


def test_group_bigger_than_a_cabinet_is_split_across_cabinets():
    group = [make_block(f"G{i:02d}", 24, group=0, logic="L") for i in range(14)]       # 336 > 324 usable
    res, log, _ = plan(group)
    assert res.unplaced == [] and log.has("AFFINITY-SPLIT") and not log.has("FUTURE-SPACE-MISS")
    assert len(placements(res)) == 14
    for grid in res.grids.values():
        for blk, cioc, start in grid.placements.values():
            assert all(grid.cells[(cioc, *grid.pos_to_bp_ch(start + p - 1))].pair_no == p for p in range(1, blk.declared_pairs + 1))


def test_five_hundred_channels_split_and_every_block_stays_whole():
    group = [make_block(f"G{i:02d}", 24, group=0, logic="L") for i in range(21)]       # 504 channels
    res, log, _ = plan(group)
    assert res.unplaced == [] and log.has("AFFINITY-SPLIT") and len(placements(res)) == 21


def test_without_auto_expand_the_end_reserve_is_used_and_flagged():
    cfg = one_cab_cfg(auto_expand=False)
    group = [make_block(f"G{i:02d}", 24, group=0, logic="L") for i in range(14)]
    res, log, _ = plan(group, cfg=cfg)
    assert res.unplaced == [] and log.has("FUTURE-SPACE-MISS")
    grid = next(iter(res.grids.values()))
    reserve_used = [k for k in grid.cells if k[0] == 4 and k[1] >= 5]
    assert reserve_used                                             # the reserve really was used


def test_no_room_anywhere_is_an_overflow_not_a_crash():
    cfg = one_cab_cfg(auto_expand=False)
    blocks = [make_block(f"G{i:02d}", 24, group=i) for i in range(20)]
    res, log, _ = plan(blocks, cfg=cfg)
    assert log.has("CAPACITY-OVERFLOW") and len(res.unplaced) == 5
    assert len(placements(res)) == 15


# ---------------------------------------------------------------------------- pins
def test_pin_is_honoured_for_a_neutral_cable():
    res, log, _ = plan([make_block("P1", 12)], pins={"p1": ("P30-DCM-32001-04", 4)})
    assert placements(res)["p1"][:2] == ("P30-DCM-32001-04", 4) and not log.has("PIN-UNSATISFIABLE")


def test_pin_that_would_mix_a_and_b_is_ignored_and_explained():
    blocks = [make_block("B1", 12, family="B", group=0), make_block("A1", 12, family="A", group=1)]
    res, log, _ = plan(blocks, pins={"b1": ("P30-DCM-32001-01", 3), "a1": ("P30-DCM-32001-01", 3)})
    p = placements(res)
    assert log.has("PIN-UNSATISFIABLE")
    assert p["a1"][1] == 3 and p["b1"][1] != 3          # pinned cables are placed A before B, so A wins CIOC 3
    grid = res.grids[p["a1"][0]]
    for cioc in range(1, 5):
        assert len({b.family for b, c, _ in grid.placements.values() if c == cioc and b.family}) <= 1


def test_pin_to_unknown_cabinet_is_ignored():
    res, log, _ = plan([make_block("P1", 12)], pins={"p1": ("NOPE", 2)})
    assert log.has("PIN-UNSATISFIABLE") and "p1" in placements(res)


# ------------------------------------------------------------------------- misc
def test_cioc_order_respects_the_hard_rule():
    cfg = load_config()
    grid = CabinetGrid(cfg.cabinets[0], cfg.rules)
    grid.place_block(make_block("B1", 12, family="B"), 1, 12)           # CIOC 1 now belongs to B
    a_order = [c for c, _ in cioc_order(make_block("A", 12, family="A"), grid)]
    assert 1 not in a_order and a_order == [2, 3, 4]
    b_order = [c for c, _ in cioc_order(make_block("B", 12, family="B"), grid)]
    assert b_order == [3, 4, 1, 2]


def test_unknown_room_is_reported_not_crashed():
    res, log, _ = plan([make_block("C1", 12, room="PIB-99")])
    assert log.has("NO-CABINET-FOR-ROOM") and len(res.unplaced) == 1


def test_every_placed_cable_has_a_why_trace():
    res, _, _ = plan([make_block("C1", 24, family="A", group=0, logic="L7")])
    lines = res.traces["c1"]
    assert len(lines) >= 4
    assert any("logic group 0" in l and "L7" in l for l in lines)
    assert any("A-family cable -> CIOC" in l for l in lines)
    assert any(l.startswith("Placed at baseplate") for l in lines)
    assert res.traces["c1-1"] is res.traces["c1"]          # each tag points at its cable's trace


# ----------------------------------------------------------------------- the sample
def _fixture_plan(mdb_path):
    cfg, log = load_config(), TQLog()
    ing = read_mdb(mdb_path, log)
    v = validate(ing, cfg, log)
    blocks, _ = build_blocks(v.accepted, v.size_by_cable, cfg, log)
    link_groups(blocks)
    res = plan_and_place(blocks, v.alarms, cfg, log)
    return res, log, cfg


def test_fixture_is_fully_placed(mdb_path):
    res, log, _ = _fixture_plan(mdb_path)
    assert res.unplaced == [] and res.alarms_unplaced == []
    assert set(res.grids) == {"P30-DCM-32001-01", "P30-DCM-32001-04", "P24-DCM-50002-01"}
    field = sum(1 for g in res.grids.values() for c in g.cells.values() if c.status == "Field")
    alarms = sum(1 for g in res.grids.values() for c in g.cells.values() if c.status == "Cabinet Alarm")
    assert (field, alarms) == (177, 12)
    refs = sorted(t.ref for t in log.of("ALARMS-MISSING-FOR-CABINET"))
    assert refs == ["P24-DCS-50002-01", "P30-DCS-32001-02"]
    assert not [t for t in log if t.severity == "error"]
    for grid in res.grids.values():
        assert len(grid.cells) <= 384
        for (cioc, bp, ch), cell in grid.cells.items():
            if cell.status != "Cabinet Alarm":
                assert not (cioc == 1 and bp == 1) and not (cioc == 4 and bp >= 5)
        for cioc in range(1, 5):
            assert len({b.family for b, c, _ in grid.placements.values() if c == cioc and b.family}) <= 1


def test_fixture_groups_land_in_one_cabinet_each_and_both_p30_cabinets_are_used(mdb_path):
    res, _, _ = _fixture_plan(mdb_path)
    p = placements(res)
    for group in ({"320-ce-0001", "320-ce-0004"}, {"320-ce-0045", "320-cs-0005"}, {"320-ce-0083", "320-ce-0087"},
                  {"500-ce-0015", "500-ce-lp-0003-a", "500-ce-lp-0003-b"}):
        assert len({p[k][0] for k in group}) == 1
    assert {v[0] for k, v in p.items() if k.startswith("320-")} == {"P30-DCM-32001-01", "P30-DCM-32001-04"}


def test_fixture_placement_is_deterministic(mdb_path):
    a, b = _fixture_plan(mdb_path)[0], _fixture_plan(mdb_path)[0]
    assert placements(a) == placements(b)
    assert {k: [(x, y.status, y.pair_no) for x, y in sorted(g.cells.items())] for k, g in a.grids.items()} == \
           {k: [(x, y.status, y.pair_no) for x, y in sorted(g.cells.items())] for k, g in b.grids.items()}


def test_a_neutral_cable_may_be_pinned_into_a_ciocthat_already_holds_a_family():
    blocks = [make_block("A1", 12, family="A", group=0), make_block("N1", 12, group=1)]
    res, log, _ = plan(blocks, cfg=one_cab_cfg(), pins={"n1": ("P30-DCM-32001-01", 1)})
    p = placements(res)
    assert p["a1"][1] == 1 and p["n1"][1] == 1 and not log.has("PIN-UNSATISFIABLE")
    from io_sudoku.core.place import family_fits
    assert family_fits("A", None) and family_fits(None, "B") and family_fits("A", "A") and not family_fits("A", "B")

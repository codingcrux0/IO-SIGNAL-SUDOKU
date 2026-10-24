from __future__ import annotations

import pytest

from io_sudoku.core.config import RulesCfg, load_config
from io_sudoku.core.ingest import IngestResult, read_mdb, empty_result
from io_sudoku.core.overrides import (
    Override, apply_overrides, overrides_from_json, overrides_to_json, suggest_resolution, validate_override,
)
from io_sudoku.core.topology_infer import NAME_RE, infer_cabinets
from io_sudoku.core.tq import TQLog
from io_sudoku.core.validate import parse_cable_size, validate
from tests.helpers import make_signal
from tests.mutate import col, mutated, read_table, row_of


def run(signals, alarms=None, cfg=None):
    ing = empty_result()
    ing.signals, ing.alarms = list(signals), list(alarms or [])
    log = TQLog()
    return validate(ing, cfg or load_config(), log), log


def tq_of(v, tag):
    return [q.tq_id for q in v.quarantined if q.signal.tag == tag]


# --------------------------------------------------------------------- validate
def test_parse_cable_size():
    assert parse_cable_size("24PX1MM2/FR/IND&OS/ARM/NIS") == 24
    assert parse_cable_size("06PX1MM2/FR") == 6
    assert parse_cable_size("1TX1.3MM2/FR/OS/NIS") == 1
    assert parse_cable_size("2PX1.3MM2/FR") == 2
    assert parse_cable_size("-") is None and parse_cable_size(None) is None and parse_cable_size("garbage") is None
    assert parse_cable_size("0PX") is None


@pytest.mark.parametrize("overrides,tq_id", [
    (dict(tag=""), "BLANK-TAG"),
    (dict(io_type=None), "MISSING-IO-TYPE"),
    (dict(io_type="XYZ"), "UNKNOWN-IO-TYPE"),
    (dict(tech_room="PIB-99"), "NO-CABINET-FOR-ROOM"),
    (dict(tech_room=None), "NO-CABINET-FOR-ROOM"),
    (dict(segregation="A-B"), "UNSUPPORTED-SEGREGATION"),
    (dict(cable_no=None), "MISSING-CABLE"),
    (dict(pair_no=None), "MISSING-PAIR"),
    (dict(pair_no=13), "PAIR-BEYOND-CABLE"),
    (dict(pair_no=0), "PAIR-BEYOND-CABLE"),
    (dict(execution="IS"), "IS-SIGNAL-UNSUPPORTED"),
    (dict(instrument_type="IRC interface"), "OUT-OF-SCOPE-SIGNAL"),
    (dict(equipment="MCC panel"), "OUT-OF-SCOPE-SIGNAL"),
])
def test_each_rule_quarantines_with_its_tq(overrides, tq_id):
    sig = make_signal(tag=overrides.pop("tag", "T-1"), **overrides) if "tag" in overrides else make_signal(**overrides)
    if tq_id == "BLANK-TAG":
        sig = make_signal(tag="", key="")
    v, log = run([sig])
    assert v.accepted == []
    assert [q.tq_id for q in v.quarantined] == [tq_id]
    assert log.has(tq_id)


def test_circuit_is_not_irc():
    v, _ = run([make_signal(instrument_type="Circuit breaker")])
    assert len(v.accepted) == 1


def test_duplicate_tag_by_spacing_and_case_quarantines_both():      # Review Focus 4
    a = make_signal(tag="320-FT   -1", pair_no=1)
    b = make_signal(tag="320-ft -1", pair_no=2)
    v, log = run([a, b])
    assert v.accepted == [] and {q.tq_id for q in v.quarantined} == {"DUPLICATE-TAG"}
    assert len(v.quarantined) == 2


def test_duplicate_tag_between_signal_and_alarm():
    a = make_signal(tag="X-1")
    alarm = make_signal(tag="x-1", is_alarm=True, cable_no=None, pair_no=None)
    v, _ = run([a], [alarm])
    assert v.accepted == [] and v.alarms == []
    assert len(v.quarantined) == 2


def test_duplicate_pair_quarantines_all_members():
    v, log = run([make_signal(tag="A", pair_no=3), make_signal(tag="B", pair_no=3), make_signal(tag="C", pair_no=4)])
    assert [s.tag for s in v.accepted] == ["C"]
    assert sorted(q.signal.tag for q in v.quarantined) == ["A", "B"]
    assert log.has("DUPLICATE-PAIR")


def test_cable_size_conflict_and_inference():
    v, log = run([make_signal(tag="A", cable_size="12PX1MM2", pair_no=1), make_signal(tag="B", cable_size="24PX1MM2", pair_no=2)])
    assert v.accepted == [] and log.has("CABLE-SIZE-CONFLICT")
    sigs = [make_signal(tag=f"S{i}", cable_size=None, pair_no=i) for i in range(1, 10)]
    v, log = run(sigs)
    assert len(v.accepted) == 9 and v.size_by_cable["c-1"] == 12 and log.has("CABLE-SIZE-INFERRED")
    v, log = run([make_signal(cable_size=None, pair_no=200)])
    assert v.accepted == [] and log.has("BAD-CABLE-SIZE")


def test_one_bad_pair_does_not_sink_the_cable():
    v, _ = run([make_signal(tag="A", cable_size=None, pair_no=0), make_signal(tag="B", cable_size=None, pair_no=2)])
    assert [s.tag for s in v.accepted] == ["B"] and tq_of(v, "A") == ["PAIR-BEYOND-CABLE"]


def test_io_type_conflict_is_a_warning_only():
    ok = make_signal(tag="OK", io_type="DIR", io_type2="DOR", pair_no=1)
    bad = make_signal(tag="BAD", io_type="AIR", io_type2="DIR", pair_no=2)
    v, log = run([ok, bad])
    assert len(v.accepted) == 2
    assert [t.ref for t in log.of("IO-TYPE-CONFLICT")] == ["BAD"]
    assert len(log.of("IO-TYPE2-NOTED")) == 1


def test_fixture_validates_clean(mdb_path):
    log = TQLog()
    ing = read_mdb(mdb_path, log)
    v = validate(ing, load_config(), log)
    assert v.quarantined == []
    assert len(v.accepted) == 177 and len(v.alarms) == 12
    assert not [t for t in log if t.severity == "error"]
    assert len(log.of("IO-TYPE2-NOTED")) == 1
    assert len(v.size_by_cable) == 15          # the 15 field cables


# --------------------------------------------------------------------- topology
def test_inference_reproduces_p24_cabinet(mdb_path):
    cfg = load_config()
    original = cfg.cabinets[2]
    cfg.cabinets = cfg.cabinets[:2]            # forget PIB-24
    log = TQLog()
    ing = read_mdb(mdb_path, log)
    assert infer_cabinets(ing, cfg, log) == 1
    new = cfg.cabinets[-1]
    for name in ("marshalling", "system", "controller", "tech_room", "loc", "area5", "unit", "cabinet_seq", "ctrl_seq"):
        assert getattr(new, name) == getattr(original, name), name
    assert new.inferred is True and log.has("TOPOLOGY-INFERRED")


def test_inference_pairs_p30_cabinets_like_the_real_topology(mdb_path):
    cfg = load_config()
    cfg.cabinets = [cfg.cabinets[2]]           # forget PIB-30
    ing = read_mdb(mdb_path, TQLog())
    assert infer_cabinets(ing, cfg, TQLog()) == 2
    p30 = [c for c in cfg.cabinets if c.tech_room == "PIB-30"]
    assert [(c.marshalling, c.system, c.controller) for c in p30] == [
        ("P30-DCM-32001-01", "P30-DCS-32001-01", "P30DPK320101"),
        ("P30-DCM-32001-04", "P30-DCS-32001-02", "P30DPK320102")]


def test_inference_from_room_name_when_no_alarms():
    sigs = [make_signal(tag=f"T{i}", tech_room="PIB-31", risk_area="RA 330-01", unit=330, pair_no=i) for i in range(1, 4)]
    ing = IngestResult(signals=sigs)
    cfg = load_config()
    log = TQLog()
    assert infer_cabinets(ing, cfg, log) == 1
    c = cfg.cabinets[-1]
    assert (c.marshalling, c.system, c.controller, c.unit) == ("P31-DCM-33001-01", "P31-DCS-33001-01", "P31DPK330101", 330)


def test_unparseable_room_adds_nothing():
    ing = IngestResult(signals=[make_signal(tech_room="LAB")])
    cfg = load_config()
    assert infer_cabinets(ing, cfg, TQLog()) == 0 and len(cfg.cabinets) == 3
    v = validate(ing, cfg, TQLog())
    assert [q.tq_id for q in v.quarantined] == ["NO-CABINET-FOR-ROOM"]


def test_name_regex_and_determinism():
    m = NAME_RE.match("Q07-DCM-12345-02")
    assert m and (m["loc"], m["kind"], m["area5"], m["seq"]) == ("Q07", "M", "12345", "02")
    assert NAME_RE.match("Q07-DCS-12345-01")["kind"] == "S"
    sigs = [make_signal(tech_room="PIB-31", risk_area="RA 330-01")]
    cfg1, cfg2 = load_config(), load_config()
    infer_cabinets(IngestResult(signals=sigs), cfg1, TQLog())
    infer_cabinets(IngestResult(signals=sigs), cfg2, TQLog())
    assert cfg1.cabinets == cfg2.cabinets


def test_known_rooms_are_left_alone(mdb_path):
    cfg = load_config()
    assert infer_cabinets(read_mdb(mdb_path, TQLog()), cfg, TQLog()) == 0 and len(cfg.cabinets) == 3


# --------------------------------------------------------------------- overrides
def test_override_fixes_a_quarantined_signal(mdb_path):
    def change(h, rows):
        i = row_of(h, rows, "320-FT   -20645-A")
        rows[i][col(h, "I/O Type Name")] = None
    data = mutated(mdb_path, change)
    cfg, log = load_config(), TQLog()
    ing = read_mdb(data, log)
    assert any(q.tq_id == "MISSING-IO-TYPE" for q in validate(ing, cfg, TQLog()).quarantined)

    ing.signals = apply_overrides(ing.signals, [Override("320-ft -20645-a", "io_type", "AIR", "eng1")], cfg, log)
    v = validate(ing, cfg, log)
    assert v.quarantined == [] and log.has("OVERRIDE-APPLIED")


def test_invalid_overrides_are_rejected():
    cfg = load_config()
    for o in (Override("t", "io_type", "XYZ", "eng"), Override("t", "pair_no", 0, "eng"),
              Override("t", "unit", 5, "eng"), Override("t", "segregation", "Q", "eng"),
              Override("t", "cable_no", "", "eng"), Override("t", "cable_no", "x" * 61, "eng"),
              Override("", "io_type", "AIR", "eng"), Override("t", "io_type", "AIR", "")):
        assert validate_override(o, cfg), o
    assert validate_override(Override("t", "io_type", "ai", "eng"), cfg) == []
    assert validate_override(Override("t", "segregation", "-", "eng"), cfg) == []
    log = TQLog()
    out = apply_overrides([make_signal(tag="t")], [Override("t", "io_type", "XYZ", "eng")], cfg, log)
    assert out[0].io_type == "AIR" and log.has("OVERRIDE-INVALID")


def test_override_for_unknown_tag_and_last_answer_wins():
    cfg, log = load_config(), TQLog()
    s = make_signal(tag="t", io_type=None)
    out = apply_overrides([s], [Override("t", "io_type", "AOR", "a"), Override("T", "io_type", "DIR", "b"),
                                Override("nope", "io_type", "AIR", "a")], cfg, log)
    assert out[0].io_type == "DIR" and log.has("OVERRIDE-NO-MATCH")
    assert s.io_type is None                         # input signal untouched


def test_pair_override_sets_pair_text_and_order_of_other_fields_is_irrelevant():
    cfg = load_config()
    s = make_signal(tag="t", pair_no=None, pair_text=None, io_type=None)
    a = [Override("t", "pair_no", 4, "e"), Override("t", "io_type", "AIR", "e")]
    r1 = apply_overrides([s], a, cfg, TQLog())[0]
    r2 = apply_overrides([s], a[::-1], cfg, TQLog())[0]
    assert r1 == r2 and r1.pair_no == 4 and r1.pair_text == "Pair 4"


def test_overrides_json_round_trip_and_tolerance():
    items = [Override("t", "io_type", "AIR", "eng", "note"), Override("u", "pair_no", 3, "eng")]
    assert overrides_from_json(overrides_to_json(items)) == items
    assert overrides_from_json("not json") == [] and overrides_from_json(None) == []
    assert overrides_from_json('[{"bad": 1}, 5]') == []


def test_suggestions():
    cfg = load_config()
    log = TQLog()
    members = [make_signal(tag=f"S{i}", pair_no=i, cable_size="12PX1MM2") for i in range(1, 6)]
    missing = make_signal(tag="M", pair_no=None, cable_size="12PX1MM2")
    tq = log.add("MISSING-PAIR", "M")
    assert [s["value"] for s in suggest_resolution(tq, missing, members, cfg)] == list(range(6, 13))
    tq = log.add("MISSING-IO-TYPE", "x")
    assert [s["value"] for s in suggest_resolution(tq, make_signal(signal_type="4-20 ma"), [], cfg)] == ["AIR", "AOR"]
    assert [s["value"] for s in suggest_resolution(tq, make_signal(signal_type="-", signal_level="Voltfree-contact"), [], cfg)] == ["DIR"]
    assert [s["value"] for s in suggest_resolution(tq, make_signal(signal_type=None, signal_level=None), [], cfg)] == ["AIR", "AOR", "DIR", "DOR"]
    tq = log.add("MISSING-CABLE", "x")
    got = [s["value"] for s in suggest_resolution(tq, make_signal(cable_no=None), members, cfg)]
    assert got == ["C-1"]
    tq = log.add("UNSUPPORTED-SEGREGATION", "x")
    assert [s["value"] for s in suggest_resolution(tq, None, [], cfg)] == ["A", "B", "-"]
    assert suggest_resolution(log.add("BLANK-TAG", "x"), None, [], cfg) == []

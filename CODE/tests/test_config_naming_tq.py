from __future__ import annotations

import json

import pytest

from io_sudoku.core import naming as nm
from io_sudoku.core.config import (
    Config, RulesCfg, config_from_dict, config_to_dict, load_config,
)
from io_sudoku.core.models import Signal
from io_sudoku.core.tq import CATALOGUE, MESSAGES, TQLog
from tests.helpers import make_signal


# ----------------------------------------------------------------------- config
def test_default_topology_has_three_cabinets(cfg):
    assert len(cfg.cabinets) == 3
    assert [c.cabinet_seq for c in cfg.cabinets] == [1, 4, 1]


def test_cabinet_for_equipment_matches_system_or_marshalling_any_case(cfg):
    assert cfg.cabinet_for_equipment("P30-DCS-32001-02").marshalling == "P30-DCM-32001-04"
    assert cfg.cabinet_for_equipment("  p30-dcs-32001-02 ").marshalling == "P30-DCM-32001-04"
    assert cfg.cabinet_for_equipment("P30-DCM-32001-01").system == "P30-DCS-32001-01"
    assert cfg.cabinet_for_equipment("NOPE") is None
    assert cfg.cabinet_for_equipment(None) is None


def test_rooms(cfg):
    assert len(cfg.cabinets_in_room("PIB-30")) == 2
    assert len(cfg.cabinets_in_room(" pib-30 ")) == 2
    assert cfg.cabinets_in_room("NOPE") == []
    assert cfg.cabinets_in_room(None) == []
    assert cfg.known_rooms() == ["PIB-30", "PIB-24"]


def test_new_cabinet_for_room(cfg):
    new = cfg.new_cabinet_for_room("PIB-30")
    assert new is not None
    assert (new.cabinet_seq, new.ctrl_seq) == (5, 3)
    assert new.marshalling == "P30-DCM-32001-05"
    assert new.system == "P30-DCS-32001-03"
    assert new.controller == "P30DPK320103"
    assert new.inferred is True
    assert len(cfg.cabinets) == 4          # appended
    assert cfg.new_cabinet_for_room("NOPE") is None


def test_rules_numbers():
    rules = RulesCfg()
    assert rules.usable_channels() == 324
    assert rules.future_slots_required() == 39


def test_load_config_survives_corrupt_and_missing_files(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert len(load_config(bad).cabinets) == 3
    assert len(load_config(tmp_path / "missing.json").cabinets) == 3
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"cabinets": []}), encoding="utf-8")
    assert len(load_config(empty).cabinets) == 3


def test_config_round_trip(cfg):
    cfg.rules.spare_pct = 15
    again = config_from_dict(config_to_dict(cfg))
    assert again.rules.spare_pct == 15
    assert [c.marshalling for c in again.cabinets] == [c.marshalling for c in cfg.cabinets]
    assert len(config_from_dict("junk").cabinets) == 3


# ----------------------------------------------------------------------- naming
def test_charm_formula():
    assert nm.charm_no(6, 9) == 69
    assert nm.charm_no(1, 1) == 1
    assert nm.charm_no(8, 12) == 96


def test_naming_cabinet_4(cfg):
    c = cfg.cabinets[1]
    assert nm.cioc_seq(c, 1) == 13
    assert nm.cioc_name(c, 1) == "P30DCIOC3201013"
    assert nm.baseplate_name(c, 1, 6) == "013-CBP-6"
    assert nm.dsp_tag(c, 1, 6, 9) == "3201DSP0201369"
    assert nm.viz_name(c, 3) == "P30-DCM-32001-04(R)"
    assert nm.viz_name(c, 2) == "P30-DCM-32001-04(F)"


def test_naming_other_cabinets(cfg):
    c1, p24 = cfg.cabinets[0], cfg.cabinets[2]
    assert nm.dsp_tag(c1, 1, 3, 5) == "3201DSP0100135"
    assert nm.dsp_tag(c1, 2, 2, 10) == "3201DSP01002210"
    assert nm.dsp_tag(p24, 2, 1, 6) == "5002DSP0100216"
    assert nm.cioc_name(p24, 1) == "P24DCIOC5002001"


def test_area4_dst_side():
    assert nm.area4("32001") == "3201"
    assert nm.area4("50002") == "5002"
    assert nm.dst_name("320-EJA  -01001-T") == "320EJA01001T_"
    assert nm.dst_name(None) == "_"
    assert nm.dst_name("") == "_"
    assert [nm.side(i) for i in (1, 2, 3, 4)] == ["F", "F", "R", "R"]


def test_parse_inverse(cfg):
    c = cfg.cabinets[1]
    assert nm.parse_cioc_index(c, "P30DCIOC3201013") == 1
    assert nm.parse_cioc_index(c, "P30DCIOC3201016") == 4
    assert nm.parse_cioc_index(c, "P30DCIOC3201001") is None   # belongs to cabinet 1
    assert nm.parse_cioc_index(c, None) is None
    assert nm.parse_bp("013-CBP-6") == 6
    assert nm.parse_bp("013-CBP-9") is None
    assert nm.parse_bp("junk") is None


# --------------------------------------------------------------------------- TQ
def test_tq_basics():
    log = TQLog()
    tq = log.add("MISSING-PAIR", "320-FT")
    assert tq.severity == "error" and tq.ref == "320-FT"
    assert "320-FT" in tq.message
    assert log.has("MISSING-PAIR") and len(log) == 1
    assert log.of("MISSING-PAIR") == [tq]
    assert log.has_once("MISSING-PAIR", "320-FT") and not log.has_once("MISSING-PAIR", "x")


def test_unknown_tq_id_becomes_internal_and_never_raises():
    log = TQLog()
    tq = log.add("NOT-A-REAL-ID", "x")
    assert tq.tq_id == "INTERNAL"
    assert "NOT-A-REAL-ID" in tq.message


def test_tq_order_and_no_dedupe_and_counts():
    log = TQLog()
    log.add("MISSING-PAIR", "a")
    log.add("MISSING-PAIR", "a")
    log.add("DELETED-IN-MDB", "b")
    assert [t.tq_id for t in log] == ["MISSING-PAIR", "MISSING-PAIR", "DELETED-IN-MDB"]
    assert log.count_by_severity() == {"error": 2, "warning": 0, "info": 1}


def test_ref_with_braces_is_safe():
    assert "{x}" in TQLog().add("MISSING-PAIR", "{x}").message


def test_catalogue_is_complete_and_consistent():
    assert len(CATALOGUE) == 62                    # + PROJECT-RULE-BROKEN, ANSWER-UNRESOLVED, PROJECT-CHECK-ERROR
    for tq_id, spec in CATALOGUE.items():
        assert spec.severity in ("error", "warning", "info"), tq_id
        assert spec.owner and spec.category and spec.resolution, tq_id
    assert set(MESSAGES) <= set(CATALOGUE)
    assert set(CATALOGUE) <= set(MESSAGES)   # every id has a question text


def test_make_signal_helper():
    s = make_signal(tag="320-FT   -1")
    assert isinstance(s, Signal)
    assert s.key == "320-ft -1"
    assert s.pair_text == "Pair 1"

from __future__ import annotations

import json
from pathlib import Path

import pytest

from io_sudoku.core.cables import family_of
from io_sudoku.core.catalog import is_high_current, profile_for
from io_sudoku.core.config import load_config
from io_sudoku.core.constants import IO_TYPES
from io_sudoku.core.pipeline import output_hash, solve
from io_sudoku.core.rulepack import (
    LOCKED_RULES, OVERRIDE_KEYS, PARAM_RANGES, RulePack, apply_pack, default_pack, derive, pack_from_dict, pack_hash,
    pack_to_dict, validate_pack,
)
from io_sudoku.core.textnorm import normalise_io_type
from tests.helpers import make_signal


def with_overrides(**ov):
    return RulePack("custom", 2, "VIT-2026 v1", {}, ov, False)


def test_default_pack_holds_the_claude_rules_values():
    p = default_pack()
    assert (p.name, p.version, p.read_only) == ("VIT-2026", 1, True)
    assert p.params == {"spare_pct": 10, "future_pct": 10, "end_reserve_bps": 4, "empty_bp_min": 3} and p.overrides == {}
    assert validate_pack(p) == []
    on_disk = json.loads((Path(__file__).resolve().parents[1] / "io_sudoku" / "data" / "packs" / "VIT-2026.json").read_text())
    assert pack_from_dict(on_disk) == p


def test_applying_the_default_pack_changes_nothing(mdb_path):
    cfg = load_config()
    assert solve(mdb_path, apply_pack(default_pack(), cfg)).rows == solve(mdb_path, cfg).rows


def test_a_higher_spare_percentage_gives_more_spares_and_leaves_the_input_untouched(mdb_path):
    cfg = load_config()
    pack = derive(default_pack())
    pack = RulePack(pack.name, pack.version, pack.parent, {"spare_pct": 15}, {}, False)
    new_cfg = apply_pack(pack, cfg)
    assert cfg.rules.spare_pct == 10 and new_cfg.rules.spare_pct == 15 and new_cfg is not cfg
    base, more = solve(mdb_path, cfg), solve(mdb_path, new_cfg)
    assert more.kpis["wired_spare"] > base.kpis["wired_spare"]
    assert more.violations == [] and more.readiness.status == "ISSUE-READY"


def test_derive_makes_an_editable_child_of_the_default():
    child = derive(default_pack(), "my project")
    assert (child.name, child.version, child.read_only, child.parent) == ("my project", 2, False, "VIT-2026 v1")


@pytest.mark.parametrize("pack", [
    RulePack("x", 1, None, {"spare_pct": 31}), RulePack("x", 1, None, {"spare_pct": -1}), RulePack("x", 1, None, {"nope": 1}),
    RulePack("x", 1, None, {"spare_pct": True}), RulePack("", 1, None), RulePack("x", 0, None),
    RulePack("x", 1, None, {}, {"unknown_key": 1}),
    RulePack("x", 1, None, {}, {"io_aliases": {"DOX": "XYZ"}}), RulePack("x", 1, None, {}, {"io_aliases": {"A" * 21: "AIR"}}),
    RulePack("x", 1, None, {}, {"instrument_profiles": {"Pump": "BOGUS"}}),
    RulePack("x", 1, None, {}, {"instrument_profiles": {"Pump": "AIR_RTD"}}),
    RulePack("x", 1, None, {}, {"segregation_families": {"C": "Z"}}),
    RulePack("x", 1, None, {}, {"high_current_keywords": [""]}), RulePack("x", 1, None, {}, {"high_current_codes": ["no good"]}),
    RulePack("x", 1, None, {}, {"extra_cabinets": [{"marshalling": "bad"}]}),
    RulePack("x", 1, None, {}, {"io_aliases": 5}),
])
def test_validation_rejects(pack):
    assert validate_pack(pack)


def test_invalid_pack_changes_nothing():
    cfg = load_config()
    out = apply_pack(RulePack("x", 1, None, {"spare_pct": 99}), cfg)
    assert out.rules == cfg.rules and out is not cfg


def test_alias_keyword_profile_and_segregation_overrides_take_effect():
    cfg = load_config()
    out = apply_pack(with_overrides(io_aliases={"dox": "dor"}, high_current_keywords=["Siren Horn", "pump"],
                                    high_current_codes=["abc"], instrument_profiles={"Motor Fault Alarm": "DOR_T02"},
                                    segregation_families={"C": "A", "A-CONTROL": "neutral"}), cfg)
    assert normalise_io_type("dox", out.rules.io_aliases) == "DOR"
    sig = make_signal(io_type="DOR", instrument_type="Big pump", instrument_code=None)
    assert is_high_current(sig, out.rules) and not is_high_current(sig, cfg.rules)
    assert is_high_current(make_signal(io_type="DOR", instrument_type="x", instrument_code="ABC"), out.rules)
    assert profile_for(make_signal(io_type="DOR", instrument_type="motor fault alarm"), out.rules) == "DOR_T02"
    assert family_of("C", out.rules) == "A" and family_of("A-CONTROL", out.rules) is None
    assert "C" not in out.rules.neutral_codes and "A-CONTROL" in out.rules.neutral_codes


def test_extra_cabinets_are_added_once():
    cab = {"marshalling": "P31-DCM-33001-01", "system": "P31-DCS-33001-01", "controller": "P31DPK330101",
           "tech_room": "PIB-31", "loc": "P31", "area5": "33001", "unit": 330, "cabinet_seq": 1, "ctrl_seq": 1}
    pack = with_overrides(extra_cabinets=[cab])
    out = apply_pack(pack, apply_pack(pack, load_config()))
    assert [c.marshalling for c in out.cabinets].count("P31-DCM-33001-01") == 1 and len(out.cabinets) == 4


def test_no_locked_rule_can_be_expressed():
    assert len(LOCKED_RULES) == 6 and not any("alarm" in r.lower() for r in LOCKED_RULES)
    assert set(PARAM_RANGES) == {"spare_pct", "future_pct", "end_reserve_bps", "empty_bp_min", "alarm_cioc", "alarm_bp"}
    assert OVERRIDE_KEYS == ("io_aliases", "high_current_keywords", "high_current_codes", "instrument_profiles",
                             "segregation_families", "extra_cabinets", "project_rules")
    # A and B can still never share a CIOC whatever a pack says: families may be re-mapped, never merged.
    out = apply_pack(with_overrides(segregation_families={"C": "B"}), load_config())
    assert set(out.rules.a_codes).isdisjoint(out.rules.b_codes)


def test_hash_is_stable_and_round_trip_works():
    a = RulePack("x", 2, "p", {"spare_pct": 12, "future_pct": 10}, {"io_aliases": {"Q": "AIR"}, "high_current_keywords": ["w"]})
    b = RulePack("x", 2, "p", {"future_pct": 10, "spare_pct": 12}, {"high_current_keywords": ["w"], "io_aliases": {"Q": "AIR"}})
    assert pack_hash(a) == pack_hash(b) and pack_hash(a) != pack_hash(default_pack())
    assert pack_from_dict(pack_to_dict(a)) == a


def test_junk_becomes_the_default_pack():
    for junk in ("junk", None, 5, {"junk": 1}, {"name": "x"}, {"name": "x", "version": "NaN"},
                 {"name": "x", "version": 1, "params": {"spare_pct": 99}}):
        assert pack_from_dict(junk) == default_pack()

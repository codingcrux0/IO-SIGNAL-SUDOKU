"""The VIT allocation guide's customer-specific items are project choices, not locked rules: the cabinet-alarm
baseplate can be moved (default CIOC 1, baseplate 1, results unchanged), and a digital input that is not a dry contact
is questioned instead of silently getting the dry-contact CHARM."""
from __future__ import annotations

from collections import Counter

from io_sudoku.core import rulechange as rc
from io_sudoku.core.cellcheck import check_cell
from io_sudoku.core.config import RulesCfg, load_config
from io_sudoku.core.naming import parse_bp
from io_sudoku.core.pipeline import solve
from io_sudoku.core.revision import solve_incremental
from io_sudoku.core.ruleimpact import SETTINGS, group_of
from io_sudoku.core.rulepack import (LOCKED_RULES, RulePack, apply_pack, default_pack, pack_hash, project_choices,
                                     validate_pack)
from io_sudoku.samples import sample_mdb_bytes


def _pack(**params) -> RulePack:
    return RulePack("T", 2, None, {**default_pack().params, **params}, {}, False)


def _where(rows, status):
    return Counter((((int(r["CIOC/CSLS Name"][-3:]) - 1) % 4) + 1, parse_bp(r["Baseplate"])) for r in rows
                   if r["Tag Status"] == status)


def test_the_alarm_baseplate_is_a_project_choice_not_a_locked_rule():
    assert not any("alarm" in r.lower() for r in LOCKED_RULES) and "alarm_baseplate" in rc.TEMPLATES
    rules = load_config().rules
    assert (rules.alarm_cioc, rules.alarm_bp) == (1, 1)                      # this project's default
    assert any("CIOC 1, baseplate 1" in c for c in project_choices(rules))
    assert pack_hash(default_pack()) == pack_hash(default_pack())            # the default pack itself is unchanged
    assert "alarm_cioc" not in default_pack().params


def test_moving_the_alarm_baseplate_keeps_every_rule():
    data = sample_mdb_bytes()
    default = solve(data)
    assert set(_where(default.rows, "Cabinet Alarm")) == {(1, 1)}
    for cioc, bp in ((2, 1), (1, 8), (3, 4), (4, 4)):
        result = solve(data, apply_pack(_pack(alarm_cioc=cioc, alarm_bp=bp), load_config()))
        assert set(_where(result.rows, "Cabinet Alarm")) == {(cioc, bp)} and not result.violations
        assert result.kpis["field"] == default.kpis["field"] and not result.quarantined
        on_bp = {r["Tag Status"] for r in result.rows if (((int(r["CIOC/CSLS Name"][-3:]) - 1) % 4) + 1,
                                                           parse_bp(r["Baseplate"])) == (cioc, bp)}
        assert on_bp <= {"Cabinet Alarm", "Spare Slot"}                    # no field cable on the alarm baseplate


def test_an_alarm_baseplate_inside_the_empty_end_is_refused():
    assert validate_pack(_pack(alarm_cioc=4, alarm_bp=5))
    assert RulesCfg(alarm_cioc=4, alarm_bp=8).alarm_problem() and not RulesCfg(alarm_cioc=4, alarm_bp=4).alarm_problem()
    p, errors = rc.build_proposal("alarm_baseplate", {"alarm_cioc": 4, "alarm_bp": 6}, "alice", known_rooms=["PIB-30"])
    assert p is None and "kept empty" in errors[0]


def test_the_alarm_baseplate_rule_goes_through_the_review_queue():
    p, errors = rc.build_proposal("alarm_baseplate", {"alarm_cioc": 2, "alarm_bp": 1}, "alice", known_rooms=["PIB-30"])
    assert not errors and "CIOC 2, baseplate 1" in p.statement
    rc.verify(p, "now")
    pack = rc.apply_approved(default_pack(), [p], load_config())
    assert pack.params["alarm_cioc"] == 2 and pack.params["alarm_bp"] == 1 and not validate_pack(pack)
    cfg = apply_pack(pack, load_config())
    assert (cfg.rules.alarm_cioc, cfg.rules.alarm_bp) == (2, 1)


def test_the_alarm_check_follows_the_setting_and_is_listed_with_the_settings():
    result = solve(sample_mdb_bytes(), apply_pack(_pack(alarm_cioc=2, alarm_bp=1), load_config()))
    alarm = next(r for r in result.rows if r["Tag Status"] == "Cabinet Alarm")
    check = next(c for c in check_cell(result, alarm) if c.rule == "V07")
    assert check.status == "pass" and "CIOC 2, baseplate 1" in check.title
    assert group_of("V07", check.title) == SETTINGS


def test_a_revision_that_moves_the_alarm_baseplate_moves_only_the_alarms():
    data = sample_mdb_bytes()
    rev_a = solve(data)
    result, report = solve_incremental(data, rev_a.rows, apply_pack(_pack(alarm_cioc=2, alarm_bp=1), load_config()), "B")
    assert not result.violations and report.counts["Moved"] == 12 and report.counts["Added"] == 0


def test_a_digital_input_that_is_not_a_dry_contact_is_questioned():
    from io_sudoku.core.catalog import profile_for
    from io_sudoku.core.models import Signal
    from io_sudoku.core.tq import TQLog, CATALOGUE

    def sig(level):
        return Signal(row_ref=2, sheet="s", tag="T-1", key="t-1", io_type="DIR", signal_level=level)
    rules = load_config().rules
    for level, asked in (("Voltfree-contact", False), ("Dry contact", False), (None, False), ("Volt-contact", True),
                         ("24VDC powered", True)):
        log = TQLog()
        assert profile_for(sig(level), rules, log) == "DIR"                  # the hardware is not changed
        assert log.has("DIR-CONTACT-CHECK") is asked, level
    assert CATALOGUE["DIR-CONTACT-CHECK"].severity == "warning"


def test_placement_keeps_the_future_space_whatever_the_settings():
    """Placement keeps free the larger of the empty end baseplates and the future space, so a higher future-space
    percentage opens another cabinet instead of breaking V14 (the defaults keep 48 channels, as before)."""
    rules = load_config().rules
    assert rules.usable_channels() == 384 - 12 - 48
    pack = _pack(future_pct=25)
    cfg = apply_pack(pack, load_config())
    assert cfg.rules.usable_channels() == 384 - 12 - 96
    result = solve((__import__("pathlib").Path(__file__).resolve().parents[1] / "test_cases" /
                    "16_big_project_1600_signals.xlsx").read_bytes(), cfg)
    assert not [v for v in result.violations if v.rule == "V14"]


def test_fewer_empty_end_baseplates_lowers_the_empty_end_warning_too():
    p, _ = rc.build_proposal("end_reserve_bps", {"value": 2}, "alice", known_rooms=["PIB-30"])
    rc.verify(p, "now")
    pack = rc.apply_approved(default_pack(), [p], load_config())
    assert pack.params["end_reserve_bps"] == 2 and pack.params["empty_bp_min"] == 2
    p, _ = rc.build_proposal("end_reserve_bps", {"value": 6}, "alice", known_rooms=["PIB-30"])
    rc.verify(p, "now")
    assert rc.apply_approved(default_pack(), [p], load_config()).params["empty_bp_min"] == 3

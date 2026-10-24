from __future__ import annotations

import json

import pytest

from io_sudoku.core import catalog
from io_sudoku.core.catalog import (
    _BUILTIN, alarm_hardware, charm_matches_io, default_profile_for_io, hardware,
    is_high_current, profile_for, spare_slot_hardware,
)
from io_sudoku.core.config import RulesCfg
from io_sudoku.core.constants import PROFILES
from io_sudoku.core.ingest import read_mdb
from io_sudoku.core.textnorm import match_key
from io_sudoku.core.tq import TQLog
from tests.helpers import make_signal
from tests.mutate import read_table

RULES = RulesCfg()

EXPECTED = {   # profile: (charm, tb, tb1, tb2, tb3, loop)
    "AIR_2W": ("SE4303T01", "SE4501", 1, 2, None, "HW-TYP-41 - LT-01"),
    "AIR_4W": ("SE4303T01", "SE4501", None, 2, 4, "HW-TYP-41 - LT-02B"),
    "AIR_RTD": ("SE4303T03", "SE4501", 1, 2, 4, "SA-AMI-530-4EME-000041 - LT-03"),
    "AOR": ("SE4304T01", "SE4501", 1, 2, None, "HW-TYP-41 - LT-04"),
    "DIR": ("SE4301T02", "SE4501", 1, 2, None, "HW-TYP-41 - LT-05"),
    "DOR_T01": ("SE4302T01", "SE4501", 1, 2, None, "HW-TYP-41 - LT-07"),
    "DOR_T02": ("SE4302T02", "SE4502", None, 2, 4, "HW-TYP-41 - LT-08A"),
}


@pytest.mark.parametrize("profile", PROFILES)
def test_every_profile_matches_the_rulebook(profile):
    h = hardware(profile)
    assert (h.charm_type, h.tb_part, h.tb1, h.tb2, h.tb3, h.hw_loop) == EXPECTED[profile]


def test_claude_rules_hardware_mapping_literally():
    assert (hardware("AIR_2W").charm_type, hardware("AIR_2W").tb_part) == ("SE4303T01", "SE4501")
    assert (hardware("AOR").charm_type, hardware("AOR").tb_part) == ("SE4304T01", "SE4501")
    assert (hardware("DIR").charm_type, hardware("DIR").tb_part) == ("SE4301T02", "SE4501")
    assert (hardware("DOR_T02").charm_type, hardware("DOR_T02").tb_part) == ("SE4302T02", "SE4502")
    assert (hardware("DOR_T01").charm_type, hardware("DOR_T01").tb_part) == ("SE4302T01", "SE4501")


def test_unknown_profile_is_safe():
    assert hardware("NOPE").profile == "AIR_2W"


def test_builtin_copy_equals_json_file():
    data = json.loads((catalog.DATA_DIR / "catalog.json").read_text(encoding="utf-8"))
    assert data == _BUILTIN


def test_alarm_hardware():
    assert alarm_hardware("AC", ice=False).hw_loop == "SA-AMI-530-4EME-000029 SH.16"
    assert alarm_hardware("DC", ice=True).hw_loop == "SA-AMI-530-4EME-000041 - LT-05"
    assert alarm_hardware("T", True).charm_type == "SE4303T03"
    assert alarm_hardware("T", False).hw_loop == "SA-AMI-530-4EME-000041 - LT-03"
    assert alarm_hardware("??", False).charm_type == "SE4301T02"


def test_spare_slot_is_a_protection_cover():
    h = spare_slot_hardware()
    assert h.charm_type == "SE6103" and h.charm_desc == "CHARM PROTECTION COVER"
    assert (h.tb1, h.tb2, h.tb3) == (None, None, None)
    assert spare_slot_hardware("SE4502").tb_part == "SE4502"
    assert spare_slot_hardware("garbage").tb_part == "SE4501"


@pytest.mark.parametrize("instrument,code,service,expected", [
    ("Solenoid Valve", None, None, True), ("Horn", None, None, True), (None, None, "BEACON ON", True),
    (None, "XYV", None, True), (None, "zyv", None, True), ("Motor Fault Alarm", "MXA", None, False),
    ("Solenoidal gizmo", None, None, False),   # whole words only
    ("Solenoid valves", None, None, True),
    ("Sounder", None, None, True), ("Position Indication Open", "ZLO", None, False),
])
def test_high_current_detection(instrument, code, service, expected):
    sig = make_signal(io_type="DOR", instrument_type=instrument, instrument_code=code, service=service)
    assert is_high_current(sig, RULES) is expected


def test_profile_for_cases():
    log = TQLog()
    assert profile_for(make_signal(io_type="AIR", signal_level="2-Wire"), RULES, log) == "AIR_2W"
    assert profile_for(make_signal(io_type="AIR", signal_level="4-Wire"), RULES, log) == "AIR_4W"
    assert not len(log)
    assert profile_for(make_signal(tag="A", io_type="AIR", signal_level=None), RULES, log) == "AIR_2W"
    assert log.has("MISSING-SIGNAL-LEVEL")
    # field RTD stays SE4303T01 (CLAUDE_RULES) and raises a TQ
    assert profile_for(make_signal(tag="R", io_type="AIR", signal_type="RTD"), RULES, log) == "AIR_2W"
    assert log.has("RTD-FIELD-SIGNAL")
    assert profile_for(make_signal(io_type="AOR"), RULES) == "AOR"
    assert profile_for(make_signal(io_type="DIR"), RULES) == "DIR"
    assert profile_for(make_signal(io_type="DOR", instrument_type="Solenoid Valve"), RULES) == "DOR_T02"
    assert profile_for(make_signal(io_type="DOR", instrument_type="Alarm"), RULES) == "DOR_T01"
    log2 = TQLog()
    assert profile_for(make_signal(tag="D", io_type="DOR", instrument_type=None, instrument_code=None), RULES, log2) == "DOR_T01"
    assert log2.has("UNKNOWN-DOR-DUTY")


def test_profile_tqs_are_logged_once_per_signal():
    log = TQLog()
    sig = make_signal(tag="X", io_type="AIR", signal_level=None)
    for _ in range(3):
        profile_for(sig, RULES, log)
    assert len(log.of("MISSING-SIGNAL-LEVEL")) == 1


def test_instrument_override_wins_but_never_rtd():
    rules = RulesCfg(instrument_profiles={"Motor Fault Alarm": "DOR_T02", "Pressure Transmitter": "AIR_RTD"})
    assert profile_for(make_signal(io_type="DOR", instrument_type="motor  fault alarm"), rules) == "DOR_T02"
    assert profile_for(make_signal(io_type="AIR", instrument_type="Pressure Transmitter"), rules) == "AIR_2W"


def test_charm_matches_io():
    assert charm_matches_io("AIR", "SE4303T01", "Field")
    assert not charm_matches_io("AIR", "SE4303T03", "Field")
    assert charm_matches_io("AIR", "SE4303T03", "Cabinet Alarm")
    assert charm_matches_io("DOR", "SE4302T02", "Wired Spare")
    assert not charm_matches_io("DIR", "SE4304T01", "Field")
    assert not charm_matches_io(None, "SE4301T02", "Field")
    assert default_profile_for_io("DOR") == "DOR_T01" and default_profile_for_io("??") == "AIR_2W"


# ------------------------------------------------------------- golden vs the sample
@pytest.fixture(scope="module")
def sample_rows(alloc_path):
    headers, rows = read_table(alloc_path)
    return [dict(zip(headers, r)) for r in rows]


def _tb(v):
    return None if v in (None, "-") else int(v)


def _hardware_cells(row):
    return (row["CHARM Type"], row["Charm Description"], row["CHARM TB Part No"], row["CHARM TB Description"],
            _tb(row["CHARM TB1"]), _tb(row["CHARM TB2"]), _tb(row["CHARM TB3"]), str(row["HW Loop Typical"]).strip())


def _cells(h):
    return (h.charm_type, h.charm_desc, h.tb_part, h.tb_desc, h.tb1, h.tb2, h.tb3, h.hw_loop)


def test_golden_field_hardware_matches_every_sample_row(mdb_path, sample_rows):
    signals = {s.key: s for s in read_mdb(mdb_path, TQLog()).signals}
    checked = 0
    for row in sample_rows:
        if row["Tag Status"] != "Field":
            continue
        sig = signals.get(match_key(row["Tag Name"]))
        if sig is None:                      # tag renamed between sample and MDB
            continue
        assert _cells(hardware(profile_for(sig, RULES))) == _hardware_cells(row), row["Tag Name"]
        checked += 1
    assert checked >= 170


def test_golden_wired_spare_hardware(sample_rows):
    checked = 0
    for row in sample_rows:
        if row["Tag Status"] != "Wired Spare":
            continue
        io, charm, tb1 = row["IO Type"], row["CHARM Type"], _tb(row["CHARM TB1"])
        profile = {"AIR": "AIR_4W" if tb1 is None else "AIR_2W", "AOR": "AOR", "DIR": "DIR",
                   "DOR": "DOR_T02" if charm == "SE4302T02" else "DOR_T01"}[io]
        assert _cells(hardware(profile)) == _hardware_cells(row), row["Tag Name"]
        checked += 1
    assert checked == 22


def test_golden_cabinet_alarm_hardware(sample_rows):
    checked = 0
    for row in sample_rows:
        if row["Tag Status"] != "Cabinet Alarm":
            continue
        kind = str(row["Tag Name"]).strip().rsplit("-", 1)[-1].upper()
        ice = row["Field Cable No"] not in (None, "-")
        assert _cells(alarm_hardware(kind, ice)) == _hardware_cells(row), row["Tag Name"]
        checked += 1
    assert checked == 12


def test_golden_spare_slots_are_covers(sample_rows):
    for row in sample_rows:
        if row["Tag Status"] == "Spare Slot":
            h = spare_slot_hardware(row["CHARM TB Part No"])
            assert (h.charm_type, h.charm_desc, h.tb_part, h.tb_desc) == (
                row["CHARM Type"], row["Charm Description"], row["CHARM TB Part No"], row["CHARM TB Description"])

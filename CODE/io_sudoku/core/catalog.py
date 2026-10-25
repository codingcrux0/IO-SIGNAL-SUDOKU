"""Hardware catalogue: which CHARM, terminal block and loop typical each signal gets.

The numbers live in data/catalog.json (derived from CLAUDE_RULES section 3C and the
official sample).  This module only LOOKS THINGS UP - there is no hard-coded
engineering table in the code.  If the JSON file is missing or damaged, a built-in
copy of the same table is used so the tool still runs.

Profiles (see constants.PROFILES):
  AIR_2W / AIR_4W   analog input  SE4303T01 + SE4501
  AIR_RTD           RTD input     SE4303T03 + SE4501  (cabinet temperature alarms ONLY)
  AOR               analog output SE4304T01 + SE4501
  DIR               discrete in   SE4301T02 + SE4501
  DOR_T01           standard DO   SE4302T01 + SE4501
  DOR_T02           high-current  SE4302T02 + SE4502 (fused, injected power)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from io_sudoku.core.config import RulesCfg
from io_sudoku.core.constants import PROFILES
from io_sudoku.core.models import Signal
from io_sudoku.core.textnorm import match_key, text_key
from io_sudoku.core.tq import TQLog

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

_STD_TB = "Standard CHARM Terminal Block"
_FUSED_TB = "Fused-Injected-Power Terminal Block"
_BUILTIN: dict[str, Any] = {
    "profiles": {
        "AIR_2W": {"charm_type": "SE4303T01", "charm_desc": "AI 4-20 MA HART CHARM", "tb_part": "SE4501", "tb_desc": _STD_TB,
                   "tb": [1, 2, None], "hw_loop": "HW-TYP-41 - LT-01", "signal_type": "4-20 ma HART", "signal_level": "2-Wire"},
        "AIR_4W": {"charm_type": "SE4303T01", "charm_desc": "AI 4-20 MA HART CHARM", "tb_part": "SE4501", "tb_desc": _STD_TB,
                   "tb": [None, 2, 4], "hw_loop": "HW-TYP-41 - LT-02B", "signal_type": "4-20 ma HART", "signal_level": "4-Wire"},
        "AIR_RTD": {"charm_type": "SE4303T03", "charm_desc": "RTD Input Charm", "tb_part": "SE4501", "tb_desc": _STD_TB,
                    "tb": [1, 2, 4], "hw_loop": "SA-AMI-530-4EME-000041 - LT-03", "signal_type": "RTD", "signal_level": "3-Wire"},
        "AOR": {"charm_type": "SE4304T01", "charm_desc": "AO 4-20 MA HART CHARM", "tb_part": "SE4501", "tb_desc": _STD_TB,
                "tb": [1, 2, None], "hw_loop": "HW-TYP-41 - LT-04", "signal_type": "4-20 ma HART", "signal_level": "2-Wire"},
        "DIR": {"charm_type": "SE4301T02", "charm_desc": "DISCRETE INPUT CHARM; 24 VDC DRY CONTACT: LOW SIDE SENSE",
                "tb_part": "SE4501", "tb_desc": _STD_TB, "tb": [1, 2, None], "hw_loop": "HW-TYP-41 - LT-05",
                "signal_type": "-", "signal_level": "Voltfree-contact"},
        "DOR_T01": {"charm_type": "SE4302T01", "charm_desc": "DISCRETE OUTPUT CHARM; 24 VDC; HIGH SIDE", "tb_part": "SE4501",
                    "tb_desc": _STD_TB, "tb": [1, 2, None], "hw_loop": "HW-TYP-41 - LT-07", "signal_type": "-",
                    "signal_level": "Volt-contact"},
        "DOR_T02": {"charm_type": "SE4302T02", "charm_desc": "DO 24V DC Isolated", "tb_part": "SE4502", "tb_desc": _FUSED_TB,
                    "tb": [None, 2, 4], "hw_loop": "HW-TYP-41 - LT-08A", "signal_type": "-", "signal_level": "Volt-contact"},
    },
    "alarm": {
        "T": {"profile": "AIR_RTD"},
        "AC": {"profile": "DIR", "hw_loop_internal": "SA-AMI-530-4EME-000029 SH.16", "hw_loop_ice": "SA-AMI-530-4EME-000041 - LT-05"},
        "DC": {"profile": "DIR", "hw_loop_internal": "SA-AMI-530-4EME-000029 SH.16", "hw_loop_ice": "SA-AMI-530-4EME-000041 - LT-05"},
    },
    "spare_slot": {"charm_type": "SE6103", "charm_desc": "CHARM PROTECTION COVER"},
    "terminal_blocks": {"SE4501": _STD_TB, "SE4502": _FUSED_TB},
}


@dataclass(frozen=True)
class Hardware:
    profile: str
    charm_type: str
    charm_desc: str
    tb_part: str
    tb_desc: str
    tb1: int | None
    tb2: int | None
    tb3: int | None
    hw_loop: str
    signal_type: str
    signal_level: str


@lru_cache(maxsize=1)
def _table() -> dict[str, Any]:
    """The catalogue data: catalog.json if valid, otherwise the built-in copy."""
    try:
        data = json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))
        if set(PROFILES) <= set(data["profiles"]) and "alarm" in data and "spare_slot" in data:
            return data
    except Exception:
        pass
    return _BUILTIN


def _make(profile: str, spec: dict[str, Any]) -> Hardware:
    tb = list(spec.get("tb", [None, None, None])) + [None, None, None]
    return Hardware(profile, spec["charm_type"], spec["charm_desc"], spec["tb_part"], spec["tb_desc"],
                    tb[0], tb[1], tb[2], spec["hw_loop"], spec["signal_type"], spec["signal_level"])


def hardware(profile: str) -> Hardware:
    """Hardware for a profile. Unknown profile -> AIR_2W (never raises)."""
    profiles = _table()["profiles"]
    key = profile if profile in profiles else "AIR_2W"
    return _make(key, profiles[key])


def alarm_hardware(kind: str, ice: bool) -> Hardware:
    """Cabinet alarm hardware: T = RTD temperature, AC/DC = discrete power-fail alarms.

    `ice` is True when the alarm arrives on an ICE cable (system cabinets), False for
    internal wiring.  Unknown kinds fall back to the discrete-input hardware.
    """
    alarms = _table()["alarm"]
    spec = alarms.get(str(kind).upper(), alarms["AC"])
    base = hardware(spec["profile"])
    loop_key = "hw_loop_ice" if ice else "hw_loop_internal"
    loop = spec.get(loop_key)
    if loop:
        return Hardware(base.profile, base.charm_type, base.charm_desc, base.tb_part, base.tb_desc,
                        base.tb1, base.tb2, base.tb3, loop, base.signal_type, base.signal_level)
    return base


def spare_slot_hardware(tb_part: str = "SE4501") -> Hardware:
    """A Spare Slot has NO functional CHARM: just the SE6103 protection cover."""
    table = _table()
    spec = table["spare_slot"]
    tbs = table.get("terminal_blocks", _BUILTIN["terminal_blocks"])
    part = tb_part if tb_part in tbs else "SE4501"
    return Hardware("SPARE_SLOT", spec["charm_type"], spec["charm_desc"], part, tbs.get(part, _STD_TB),
                    None, None, None, "-", "-", "-")


def default_profile_for_io(io_type: str) -> str:
    return {"AIR": "AIR_2W", "AOR": "AOR", "DIR": "DIR", "DOR": "DOR_T01"}.get(str(io_type).upper(), "AIR_2W")


def is_high_current(sig: Signal, rules: RulesCfg) -> bool:
    """Solenoid / horn / beacon / sounder loads need the fused, isolated DO (CLAUDE_RULES 3C).

    True when a keyword appears as a WHOLE WORD in the instrument description or the
    service text, or when the instrument code (XYV, ZYV, SOV ...) is on the list.
    """
    texts = " ".join(t for t in (sig.instrument_type, sig.service) if t).casefold()
    for keyword in rules.high_current_keywords:
        kw = str(keyword).casefold().strip()
        if kw and re.search(rf"\b{re.escape(kw)}\b", texts):
            return True
    code = (sig.instrument_code or "").strip().upper()
    return bool(code) and code in {str(c).upper() for c in rules.high_current_codes}


_DRY_WORDS = ("voltfree", "dry", "potentialfree", "drycontact")      # signal levels that ARE a dry contact


def profile_for(sig: Signal, rules: RulesCfg, log: TQLog | None = None) -> str:
    """Pick the hardware profile of a FIELD signal (alarms use alarm_hardware instead)."""
    def note(tq_id: str) -> None:
        if log is not None and not log.has_once(tq_id, sig.tag):
            log.add(tq_id, sig.tag)

    override_key = match_key(sig.instrument_type)
    if override_key:
        wanted = {match_key(k): v for k, v in rules.instrument_profiles.items()}
        profile = wanted.get(override_key)
        if profile in PROFILES and profile != "AIR_RTD":
            return profile  # type: ignore[return-value]

    io = (sig.io_type or "").upper()
    if io == "AIR":
        level = text_key(sig.signal_level)
        if not level:
            note("MISSING-SIGNAL-LEVEL")
        if text_key(sig.signal_type) == "rtd":
            note("RTD-FIELD-SIGNAL")           # project rule: still SE4303T01, human confirms
        return "AIR_4W" if level == "4-wire" else "AIR_2W"
    if io == "AOR":
        return "AOR"
    if io == "DIR":
        level = text_key(sig.signal_level)
        if level and not any(w in level.replace(" ", "").replace("-", "") for w in _DRY_WORDS):
            note("DIR-CONTACT-CHECK")         # the VIT guide: start from the real electrical signal (contact type)
        return "DIR"
    if io == "DOR":
        if not sig.instrument_type and not sig.instrument_code:
            note("UNKNOWN-DOR-DUTY")
        return "DOR_T02" if is_high_current(sig, rules) else "DOR_T01"
    return default_profile_for_io(io)


def charm_matches_io(io_type: str | None, charm_type: str | None, status: str) -> bool:
    """Is this CHARM an allowed one for this IO type and tag status? (used by the verifier)"""
    io = (io_type or "").upper()
    charm = (charm_type or "").upper()
    if status == "Cabinet Alarm":
        allowed = {"AIR": {"SE4303T03", "SE4303T01"}, "DIR": {"SE4301T02"}}
    else:
        allowed = {"AIR": {"SE4303T01"}, "AOR": {"SE4304T01"}, "DIR": {"SE4301T02"},
                   "DOR": {"SE4302T01", "SE4302T02"}}
    return charm in allowed.get(io, set())
